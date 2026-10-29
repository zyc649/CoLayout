"""Optional compact member projections of the full authorized physical graph."""

from collections import defaultdict
from ..editor import projected
from ..model import LiteError
from .component_selection import referenced_component, object_components, validate_target


def extent(figures, scale):
    boxes = [g.bounds for _, g in figures if not g.is_empty]
    return (
        [
            min(b[0] for b in boxes) / scale,
            min(b[1] for b in boxes) / scale,
            max(b[2] for b in boxes) / scale,
            max(b[3] for b in boxes) / scale,
        ]
        if boxes
        else None
    )


def select(workspace, profile, rid, graph, target):
    from .inspection import direct_ids

    validate_target(target)
    all_ids = {n['component_id'] for n in graph['nodes']}
    pins = {pin['id']: pin for pin in graph['pins'] + graph.get('directional_markers', [])}
    if target is None:
        return all_ids, None
    if target.kind == 'component':
        ids = referenced_component(graph, target.id, target.query_ref)
    elif target.kind == 'pin':
        if target.id not in pins:
            raise LiteError('PIN_UNKNOWN_OR_OUTSIDE_REGION')
        ids = set(graph['pin_components'].get(target.id, ()))
    elif target.kind == 'net':
        if target.id not in {p['net'] for p in pins.values()}:
            raise LiteError('NET_OUTSIDE_REGION')
        ids = set().union(
            *(
                graph['pin_components'].get(pin['id'], set())
                for pin in pins.values()
                if pin['net'] == target.id
            )
        )
    else:
        if target.id not in direct_ids(workspace, rid):
            raise LiteError(
                'OBJECT_UNKNOWN_OR_OUTSIDE_REGION', '仅查询本层对象；子模块请按公开 PIN 查询。'
            )
        if target.layer is not None and target.layer not in {r['layer'] for r in profile.layers}:
            raise LiteError('QUERY_LAYER_UNKNOWN', layers=[target.layer])
        ids = object_components(
            graph,
            target.id,
            point_um=target.point_um,
            layer=target.layer,
            scale=profile.dbu_per_micron,
            bounds=workspace.local_data.regions[rid].bbox,
        )
    return ids, {
        'target': target.model_dump(exclude_none=True),
        'component_ids': sorted(ids),
        'ambiguous': len(ids) > 1 and target.kind in ('object', 'pin'),
        'message': (
            '对象/接口涉及多个真实分量；没有合并。可用对象+层+点或当前分量引用定位。'
            if len(ids) > 1 and target.kind in ('object', 'pin')
            else '此处没有可确认的物理分量；不会按 net_intent 或名称猜测。'
            if not ids
            else '按全接入区物理图选择；局部过滤不重建连通。'
        ),
    }


def members(workspace, profile, rid, graph, ids, query, *, keep_empty=False):
    from .inspection import direct_ids, editable_actions

    objects = projected(workspace)
    allowed = direct_ids(workspace, rid)
    pins = {pin['id']: pin for pin in graph['pins']}
    nodes = defaultdict(list)
    by_node = {}
    for node in graph['nodes']:
        nodes[node['component_id']].append(node)
        by_node[node['id']] = node['component_id']
    edges = defaultdict(list)
    for edge in graph['edges']:
        if edge['kind'] != 'via':
            continue
        components = {by_node[ident] for ident in edge['node_ids']}
        if len(components) == 1:
            edges[next(iter(components))].append(edge)
    result = []
    for cid in sorted(ids):
        grouped = defaultdict(list)
        for node in nodes[cid]:
            grouped[node['owner_uid']].append((node['layer'], node['geometry']))
        for edge in edges[cid]:
            owner = edge.get('via_owner_uid')
            if owner is not None:
                grouped[owner].append((edge['cut_layer'], edge['geometry']))
        all_figures = [(n['layer'], n['geometry']) for n in nodes[cid]] + [
            (e['cut_layer'], e['geometry']) for e in edges[cid]
        ]
        member_rows = []
        for uid, figures in sorted(grouped.items(), key=lambda row: str(row[0])):
            if uid not in allowed:
                continue
            matched = [(layer, g) for layer, g in figures if query.matches(layer, g)]
            if not matched:
                continue
            obj = objects[uid]
            member_rows.append(
                {
                    'uid': uid,
                    'kind': obj.kind,
                    'name': obj.attributes.get('name'),
                    'layers': sorted({layer for layer, g in figures}),
                    'bounds_um': extent(figures, query.scale),
                    'matched_layers': sorted({layer for layer, g in matched}),
                    'extent_basis': 'component material of this owner; not an editable fragment',
                    'edit_scope': 'whole_instance_only'
                    if obj.kind in ('inst', 'mosaic')
                    else 'whole_mpp_only'
                    if obj.mpp
                    else 'direct_object',
                    'actions': editable_actions(obj),
                    'read_only_reason': obj.read_only_reason,
                }
            )
        pin_ids = sorted(graph['component_pins'].get(cid, ()))
        pin_rows = [
            {
                'id': pid,
                'owner': pins[pid]['owner'],
                'name': pins[pid]['label'],
                'net': pins[pid]['net'],
                'layers': query.figures_match(pins[pid]['figures']),
                'bounds_um': extent(pins[pid]['figures'], query.scale),
                'edit_scope': 'human_interface_only'
                if pins[pid]['local']
                else 'read_only_native_pin',
            }
            for pid in pin_ids
            if query.figures_match(pins[pid]['figures'])
        ]
        if query.active and not keep_empty and not member_rows and not pin_rows:
            continue
        nets = sorted({pins[pid]['net'] for pid in pin_ids if pins[pid]['net'] is not None})
        result.append(
            {
                'id': cid,
                'nets': nets,
                'net_status': 'shorted' if len(nets) > 1 else 'assigned' if nets else 'unassigned',
                'unknown_pin_ids': [pid for pid in pin_ids if pins[pid]['net'] is None],
                'pin_ids': pin_ids,
                'layers': sorted({layer for layer, g in all_figures}),
                'bounds_um': extent(all_figures, query.scale),
                'objects': member_rows,
                'pins': pin_rows,
                'total_object_count': sum(uid in allowed for uid in grouped),
                'returned_object_count': len(member_rows),
                'unexposed_owner_count': sum(uid not in allowed for uid in grouped),
                'members_filtered': query.active,
                'members_complete': not query.active,
                'connectivity_scope': 'whole claimed region; pin_ids/nets/bounds are not clipped by member filters',
            }
        )
    return result

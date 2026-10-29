"""Authorized screenshot targets over the same versioned physical graph as net."""

from math import isfinite
from shapely.geometry import box
from shapely.ops import unary_union
from ..editor import projected
from ..inspection_data import scope_pins
from ..region_analysis import scope_graph, connectivity
from ..regions.query import children, object_bounds
from ..model import LiteError
from .inspection import direct_ids


def prepare(w, p, rid, args):
    location=None
    if args.markup_id:
        from .markup_query import resolve
        location=resolve(w,p,rid,args.markup_id,args.padding_um,args.clip_to_region)
        args=args.model_copy(update={'bounds_um':tuple(location['bounds_um'])})
    region = w.local_data.regions[rid]
    scale = p.dbu_per_micron
    layers = set(args.layers) if args.layers is not None else None
    known = {row['layer'] for row in p.layers}
    if layers is not None and layers - known:
        raise LiteError('CAPTURE_LAYER_UNKNOWN', layers=sorted(layers - known))
    target = args.target
    from .component_selection import referenced_component,object_components,validate_target
    validate_target(target)
    mode = args.highlight
    if target is None and mode not in ('auto', 'none'):
        raise LiteError('CAPTURE_TARGET_REQUIRED')
    mode = (
        (
            'net'
            if target and target.kind == 'net'
            else 'component'
            if target and target.kind in ('pin', 'component')
            else 'none'
        )
        if mode == 'auto'
        else mode
    )
    if args.job_id and (mode != 'none' or target and target.kind == 'component'):
        raise LiteError(
            'CANDIDATE_HIGHLIGHT_UNSUPPORTED', '候选可普通截图；不将正式版图的物理分量套到候选。'
        )
    pins, _ = scope_pins(w, p, rid, False)
    by_pin = {pin['id']: pin for pin in pins}
    graph = (
        scope_graph(w, p, rid)
        if mode != 'none' or target and target.kind in ('net', 'component')
        else None
    )
    report = connectivity(graph) if graph else None
    components = set()
    pin_ids = set()
    context_pin_ids = set()
    geometries = []
    nets = set()
    if target:
        if target.kind == 'pin':
            if target.id not in by_pin:
                raise LiteError('PIN_UNKNOWN_OR_OUTSIDE_REGION')
            pin = by_pin[target.id]
            pin_ids.add(target.id)
            geometries += [g for _, g in pin['figures']]
            if pin['net'] is not None:
                nets.add(pin['net'])
            if graph:
                components.update(graph['pin_components'].get(target.id, ()))
        elif target.kind == 'net':
            rows = [row for row in report['nets'] if row['net'] == target.id]
            if not rows:
                raise LiteError('NET_OUTSIDE_REGION')
            nets.add(target.id)
            components.update(rows[0]['components'])
            pin_ids.update(pin['id'] for pin in pins if pin['net'] == target.id)
        elif target.kind == 'component':
            components.update(referenced_component(graph,target.id,target.query_ref))
        else:
            objects = projected(w)
            allowed = direct_ids(w, rid)
            child = {r.id: r for r in children(w, rid)}
            markups = {m.id: m for m in (*w.local_data.markups.values(),*w.local_data.keepouts.values()) if m.scope_id == rid}
            if target.id in allowed:
                bounds = object_bounds(w, objects[target.id], p)
            elif target.id in child or target.id in markups:
                bounds = (child.get(target.id) or markups.get(target.id)).bbox
            else:
                raise LiteError('OBJECT_UNKNOWN_OR_OUTSIDE_REGION')
            if bounds:
                geometries.append(box(*bounds[0], *bounds[1]))
            context_pin_ids.update(pin['id'] for pin in pins if pin['owner'] == target.id)
            if mode=='none':pin_ids.update(context_pin_ids)
            if mode != 'none':
                if (
                    target.point_um is None
                    or not all(isfinite(v) for v in target.point_um)
                    or not target.layer
                ):
                    raise LiteError(
                        'CAPTURE_SEED_POINT_REQUIRED', '导电对象种子需提供 point_um 和 layer。'
                    )
                if target.layer not in known:raise LiteError('CAPTURE_LAYER_UNKNOWN',layers=[target.layer])
                components.update(object_components(graph,target.id,point_um=target.point_um,layer=target.layer,scale=scale,bounds=region.bbox))
                selected_ids=set().union(*(graph['component_pins'].get(cid,set()) for cid in components))
                nets.update(pin['net'] for pin in graph['pins'] if pin['id'] in selected_ids and pin['net'] is not None)
    if graph:
        if mode == 'net':
            if not nets:
                raise LiteError('CAPTURE_NET_UNRESOLVED', '此处尚无可确认的目标网络。')
            for row in report['nets']:
                if row['net'] in nets:
                    components.update(row['components'])
                    pin_ids.update(row['pins'])
        for cid in components:
            pin_ids.update(graph['component_pins'].get(cid, ()))
        nets.update(by_pin[pid]['net'] for pid in pin_ids if pid in by_pin and by_pin[pid]['net'] is not None)
    nodes = [node for node in (graph or {}).get('nodes', []) if node['component_id'] in components]
    geometries += [node['geometry'] for node in nodes]
    geometries += [g for pid in pin_ids for _, g in by_pin.get(pid, {}).get('figures', [])]
    (a, b), (c, d) = region.bbox
    bounds = args.bounds_um
    if (
        bounds is None
        and target
        and args.fit == 'target'
        and not any(not g.is_empty for g in geometries)
    ):
        raise LiteError(
            'CAPTURE_TARGET_GEOMETRY_MISSING',
            '目标缺少可用几何，无法自动取景；请先检查布局或端口诊断。',
        )
    if bounds is None and target and args.fit == 'target' and geometries:
        x, y, xx, yy = unary_union(geometries).bounds
        pad = max((xx - x) * 0.08, (yy - y) * 0.08, 10 * p.grid)
        bounds = (
            max(a, x - pad) / scale,
            max(b, y - pad) / scale,
            min(c, xx + pad) / scale,
            min(d, yy + pad) / scale,
        )
    bounds = bounds or (a / scale, b / scale, c / scale, d / scale)
    if not all(isfinite(v) for v in bounds):
        raise LiteError('INVALID_CAPTURE_BOUNDS','截图坐标必须为有限数。',bounds_um=list(bounds))
    x, y, xx, yy = (v * scale for v in bounds)
    if x>=xx or y>=yy:
        raise LiteError('INVALID_CAPTURE_BOUNDS','截图范围必须满足 xmin < xmax 且 ymin < ymax；宽高必须为正。',
                        bounds_um=list(bounds),invalid_axes=[name for name,lo,hi in (('x',x,xx),('y',y,yy)) if lo>=hi])
    if not (a <= x < xx <= c and b <= y < yy <= d):
        raise LiteError('CAPTURE_OUTSIDE_REGION','截图范围超出已接入操作区。',bounds_um=list(bounds),region_bounds_um=[a/scale,b/scale,c/scale,d/scale])
    node_ids = {node['id'] for node in nodes}
    vias = [
        edge
        for edge in (graph or {}).get('edges', [])
        if edge['kind'] == 'via' and set(edge['node_ids']) <= node_ids
    ]
    involved = {node['layer'] for node in nodes} | {edge['cut_layer'] for edge in vias}
    shorts = [row for row in (report or {}).get('shorts', []) if row['component'] in components]
    issues = [
        {'pin_id': row['pin_id'], 'pin_name':row['pin_name'],'reason': row['reason']}
        for row in (report or {}).get('pin_issues', [])
        if row['pin_id'] in pin_ids
    ]
    summary = {
        'mode': mode,
        'target': target.model_dump() if target else None,
        'query_ref': (graph or {}).get('query_ref'),
        'components': sorted(components),
        'pin_ids': sorted(pin_ids),
        'context_pin_ids':sorted(context_pin_ids-pin_ids),
        'nets': sorted(nets),
        'shorts': shorts,
        'pin_issues': issues,
        'hidden_connection_layers': sorted(involved - layers) if layers is not None else [],
        'coverage_warnings': (report or {}).get('warnings', []),
        'diagnostics_truncated': (report or {}).get('diagnostics_truncated', False),
        'meaning': '颜色区分真实物理分量；同一目标网络不代表已接通。',
    }
    return {
        'bounds': bounds,
        'location':location,
        'pins': pins,
        'nodes': nodes,
        'vias': vias,
        'components': components,
        'pin_ids': pin_ids,
        'summary': summary,
        'layers': layers,
        'mode': mode,
    }

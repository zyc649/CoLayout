"""Explicit local access reference and truthful enclosure-extension feedback."""

from shapely.geometry import box, Polygon
from shapely.ops import unary_union
from ..model import LiteError, Shape
from .via_candidates import footprints


def bases(access):
    args = access.args
    rows = {}
    for pin in access.pins.values():
        if (
            pin['net'] != args.net_intent
            or args.targets
            and pin['id'] not in args.targets
            and pin['owner'] not in args.targets
        ):
            continue
        for layer, g in pin['figures']:
            if layer not in access.access or not g.intersects(access.roi):
                continue
            key = (pin['id'], layer)
            row = rows.setdefault(
                key,
                {
                    'target_id': pin['id'],
                    'owner': pin['owner'],
                    'label': pin.get('display_name', pin['label']),
                    'layer': layer,
                    'basis': 'virtual_interface' if pin['local'] else 'native_pin',
                    'parts': [],
                },
            )
            row['parts'].append(g)
    for layer, nodes in access.by_layer.items():
        if layer not in access.access:
            continue
        for node in nodes:
            uid = node['owner_uid']
            g = node['geometry']
            if args.targets and uid not in args.targets or not g.intersects(access.roi):
                continue
            if (
                access.nets[node['component_id']] != {args.net_intent}
                and uid not in access.intent_targets | access.generated
            ):
                continue
            # Instance access is identified by exact PIN ID, not its whole net.
            if any(pin['owner'] == uid for pin in access.pins.values()):
                continue
            row = rows.setdefault(
                (uid, layer),
                {
                    'target_id': uid,
                    'owner': uid,
                    'label': uid,
                    'layer': layer,
                    'basis': 'conductor',
                    'parts': [],
                },
            )
            row['parts'].append(g)
    return [
        {**{k: v for k, v in row.items() if k != 'parts'}, 'geometry': unary_union(row['parts'])}
        for row in rows.values()
    ]


def reference(access):
    if not access.args.allow_landing or access.args.landing_policy == 'expand_window':
        return None
    candidates = access.bases
    ident = access.args.landing_reference
    if ident is not None:
        candidates = [row for row in candidates if row['target_id'] == ident]
    else:
        native = [row for row in candidates if row['basis'] == 'native_pin']
        if native:
            candidates = native
        else:
            physical = [row for row in candidates if row['basis'] == 'conductor']
            if physical:
                candidates = physical
    preferred = [row for row in candidates if row['layer'] == access.args.start_layer]
    candidates = preferred or [row for row in candidates if row['layer'] == access.args.end_layer]
    if len(candidates) != 1:
        raise LiteError(
            'AUTOVIA_REFERENCE_REQUIRED',
            '贴合模式需要一个明确的接入参考；请设置 landing_reference 为本次目标 PIN 或导体 ID。',
            candidates=[{k: v for k, v in row.items() if k != 'geometry'} for row in candidates],
        )
    return candidates[0]


def search_window(access, name, roi):
    ref = access.reference
    if ref is None:
        return roi
    p = access.editor.profile
    one = footprints(
        Shape(
            kind='stdVia',
            origin=(0, 0),
            via_definition=name,
            via_parameters={'cutRows': 1, 'cutColumns': 1},
        ),
        p,
    )
    base = one.get(ref['layer']) or unary_union(list(one.values()))
    minw, minh = base.bounds[2] - base.bounds[0], base.bounds[3] - base.bounds[1]
    geometry = ref['geometry']
    pieces = list(geometry.geoms) if hasattr(geometry, 'geoms') else [geometry]
    allowed = []
    for piece in pieces:
        if piece.is_empty or not piece.intersects(roi):
            continue
        x, y, xx, yy = piece.bounds
        if piece.equals(box(x, y, xx, yy)):
            dx = max(0, minw - (xx - x)) / 2
            dy = max(0, minh - (yy - y)) / 2
            allowed.append(box(x - dx, y - dy, xx + dx, yy + dy))
        else:
            allowed.append(piece)  # Nonrectangular access: no guessed rectangular expansion.
    limit = unary_union(allowed)
    access.reference_limit = limit
    # Larger opposite-layer enclosure is permitted; the reference-layer check
    # below remains exact. All layers still must fit the caller's original ROI.
    all_bounds = unary_union(list(one.values())).bounds
    margin = max(
        0,
        base.bounds[0] - all_bounds[0],
        base.bounds[1] - all_bounds[1],
        all_bounds[2] - base.bounds[2],
        all_bounds[3] - base.bounds[3],
    )
    return roi.intersection(limit.buffer(margin, join_style='mitre') if margin else limit)


def permits(access, figures):
    ref = access.reference
    return (
        ref is None
        or ref['layer'] not in figures
        or access.reference_limit.covers(figures[ref['layer']])
    )


def report(access, editor, created, reused):
    scale = editor.profile.dbu_per_micron
    new = {}
    for uid in created:
        for layer, g in footprints(editor.object(uid).shape, editor.profile).items():
            new.setdefault(layer, []).append(g)
    new = {layer: unary_union(parts) for layer, parts in new.items()}
    metals = {row['layer'] for row in editor.profile.layers if row.get('material') == 'metal'}
    additions = []
    for layer, g in new.items():
        if layer not in metals:
            continue
        known = unary_union([node['geometry'] for node in access.by_layer[layer]])
        extra = g.difference(known)
        additions.append(
            {
                'layer': layer,
                'role': 'outer_target_layer'
                if layer in access.access
                else 'intermediate_via_metal',
                'added_outside_visible_metal_um2': extra.area / scale**2,
                'added_bounds_um': [v / scale for v in extra.bounds]
                if not extra.is_empty
                else None,
                'basis': 'current-level physical geometry and native public PIN access; virtual interface markers are not metal',
            }
        )
    changes = []
    for row in access.bases:
        original = row['geometry']
        added = new.get(row['layer'], Polygon())
        if added.is_empty or not added.intersects(original):
            continue
        parts = list(added.geoms) if hasattr(added, 'geoms') else [added]
        relevant = unary_union([g for g in parts if g.intersects(original)])
        extension = relevant.difference(original)
        x, y, xx, yy = original.bounds
        a, b, c, d = relevant.bounds
        rectangular = original.equals(box(x, y, xx, yy))
        changes.append(
            {
                **{k: v for k, v in row.items() if k != 'geometry'},
                'basis_bounds_um': [v / scale for v in original.bounds],
                'added_outside_basis_um2': extension.area / scale**2,
                'extension_um': {
                    'left': max(0, x - a) / scale,
                    'bottom': max(0, y - b) / scale,
                    'right': max(0, c - xx) / scale,
                    'top': max(0, d - yy) / scale,
                }
                if rectangular
                else None,
                'added_bounds_um': [v / scale for v in extension.bounds]
                if not extension.is_empty
                else None,
                'geometry_note': 'axis-aligned rectangle reference'
                if rectangular
                else 'exact shape difference; directional extension not inferred',
                'physical_metal_basis': row['basis'] != 'virtual_interface',
            }
        )
    ref = access.reference
    return {
        'landing_policy': access.args.landing_policy
        if access.args.allow_landing
        else 'existing_metal_only',
        'landing_reference': {k: v for k, v in ref.items() if k != 'geometry'} if ref else None,
        'landing_changes': changes,
        'used_landing': any(row['added_outside_visible_metal_um2'] > 0 for row in additions),
        'added_metal_by_layer': additions,
        'reused_only': bool(reused and not created),
        'landing_note': (
            '起止层仅使用已知已有金属；多级过孔仍可生成必要的中间层包围。'
            if not access.args.allow_landing
            else '贴合参考目标只补单孔最低包围所需的窄轴扩展，不为增加孔数拉长参考；其他层仍可补该阵列所需包围。'
            if access.args.landing_policy == 'fit_target'
            else '按明确授权在 bounds_um 内扩大接入，以寻找更多合法切孔。'
        )
        + ' 扩展量为设计信息，不是 DRC 违规；虚拟接口标记不算已有金属。',
    }

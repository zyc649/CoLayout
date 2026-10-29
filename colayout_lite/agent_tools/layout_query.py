"""Bounded layout projection options, including human markup boxes."""

from shapely.geometry import mapping
from ..model import LiteError


def markup_rows(w, region_id, scale):
    return [
        {
            'uid': m.id,
            'kind': 'markup',
            'text': m.text,
            'scope_id': m.scope_id,
            'bounds_um': [v / scale for point in m.bbox for v in point],
            'coordinates': 'workspace_um',
            'read_only': True,
            'role': 'layout_intent_only',
        }
        for m in w.local_data.markups.values()
        if m.scope_id == region_id
    ]


def selection(ids, children, markups, pins, uids, pin_ids):
    allowed = ids | {r.id for r in children} | {row['uid'] for row in markups}
    allowed_pins = {pin['id'] for pin in pins}
    if uids is not None and set(uids) - allowed:
        raise LiteError(
            'OBJECT_UNKNOWN_OR_OUTSIDE_REGION',
            'ID 不存在、已失效或不在当前操作区直属查询范围内。',
            ids=sorted(set(uids) - allowed),
        )
    if pin_ids is not None and set(pin_ids) - allowed_pins:
        raise LiteError(
            'PIN_UNKNOWN_OR_OUTSIDE_REGION',
            'PIN 不存在、已失效或不在当前操作区接口范围内。',
            ids=sorted(set(pin_ids) - allowed_pins),
        )
    if uids is None and pin_ids is None:
        return allowed, allowed_pins
    selected = set(uids or [])
    return selected, set(pin_ids or []) | {pin['id'] for pin in pins if pin['owner'] in selected}


def pin_row(pin, scale, detail):
    result = {
        'id': pin['id'],
        'owner': pin['owner'],
        'name': pin['label'],
        'pin_name':pin['name'],
        'display_name':pin.get('display_name',pin['label']),
        'owner_name':pin.get('owner_name'),
        'net': pin['net'],
        'signal': pin.get('signal'),
        'local': pin['local'],
        'layer_mode':pin.get('layer_mode','single'),
        'coverage_mode':'any_layer' if pin.get('layer_mode')=='any_metal' else 'all_figures',
        'allowed_layers':sorted({layer for layer,g in pin['figures']}),
        'physical_required': pin.get('physical_required', True),
        'connection_requirement':'alternative_child_landing' if pin.get('interface_group') else 'fixed_landing' if pin.get('physical_required',True) else 'directional_marker',
        'copied_port_group':pin.get('copied_port_group'),
        'alternative_pin_ids':pin.get('alternative_pin_ids',[]),
        'directional': pin.get('directional', False),
        'side': pin.get('side'),
        'figures': [
            {
                'layer': layer,
                'bbox_um': [v / scale for v in g.bounds],
                **({'geometry_dbu': mapping(g)} if detail == 'full' else {}),
            }
            for layer, g in pin['figures']
        ],
    }
    if detail == 'summary':
        figures = result.pop('figures')
        bounds = [row['bbox_um'] for row in figures]
        result.update(
            figure_count=len(figures),
            layers=sorted({row['layer'] for row in figures}),
            bounds_um=[
                min(b[0] for b in bounds),
                min(b[1] for b in bounds),
                max(b[2] for b in bounds),
                max(b[3] for b in bounds),
            ]
            if bounds
            else None,
        )
    return result

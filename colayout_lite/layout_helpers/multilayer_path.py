"""One orthogonal path with configured layer directions and checked via stacks."""

from math import ceil
from shapely.geometry import box
from shapely.ops import unary_union
from ..actions import Actions, dbu
from ..model import LiteError, Shape, MAX_DBU
from ..wire_defaults import default_width, metal_stack
from ..regions.query import metals, object_bounds
from ..region_analysis import scope_graph
from .contracts import AutoVias
from .auto_vias import create as fill_vias
from .via_candidates import chain, footprints
from .common import report_bounds


def automatic_layers(profile, rules):
    allowed = set(metals(profile))
    result = {}
    for direction in ('horizontal', 'vertical'):
        candidates = [
            name
            for name, value in rules.design_warnings.directions.items()
            if value.preferred == direction and name in allowed
        ]
        if not candidates:
            continue
        if len(candidates) > 1:
            try:
                order = metal_stack(profile, profile.editor_defaults.get('metal_stack'))
            except LiteError:
                continue
            candidates = sorted(
                candidates, key=lambda name: order.index(name) if name in order else len(order)
            )
        result[direction] = candidates[0]
    return result


def create(editor, args, rules, *, cancelled=None):
    if rules is None:
        raise LiteError('LOCAL_DRC_REQUIRED')
    p = editor.profile
    scale = p.dbu_per_micron
    grid = p.grid
    points = [tuple(dbu(v, p) for v in point) for point in args.points]
    preferred = automatic_layers(p, rules)
    layers = []
    for index, (a, b) in enumerate(zip(points, points[1:])):
        if a == b or (a[0] != b[0] and a[1] != b[1]):
            raise LiteError(
                'MULTILAYER_ORTHOGONAL_REQUIRED', '组合路径首版只接受非零正交线段；不会改写斜线。'
            )
        direction = 'horizontal' if a[1] == b[1] else 'vertical'
        layer = args.layers[index] if args.layers is not None else preferred.get(direction)
        if layer is None:
            raise LiteError(
                'PREFERRED_LAYER_REQUIRED',
                '请由人在 DRC 工艺设置中配置首选方向，或显式给出每段 layers。',
                direction=direction,
            )
        if layer not in metals(p):
            raise LiteError('LAYER_NOT_WRITABLE', layer=layer)
        layers.append(layer)
    if set(args.widths_um) - set(layers):
        raise LiteError('UNUSED_WIDTH_LAYER')
    widths = {layer: args.widths_um.get(layer, default_width(p, layer)) for layer in set(layers)}
    original = scope_graph(editor.w, p, editor.scope_id)
    by_pin = {pin['id']: pin for pin in original['pins']}

    def endpoint_layer(pin_id, explicit, fallback):
        if pin_id is None:
            return explicit or fallback
        pin = by_pin.get(pin_id)
        if pin is None:
            raise LiteError('PIN_UNKNOWN_OR_OUTSIDE_REGION')
        if pin['net'] != args.net_intent:
            raise LiteError('ENDPOINT_NET_MISMATCH')
        components = original['pin_components'].get(pin_id, set())
        accessible = {
            node['layer']
            for node in original['nodes']
            if node['component_id'] in components and node['layer'] in metals(p)
        }
        accessible.update(
            layer for layer, g in pin['figures'] if pin['local'] and layer in metals(p)
        )
        if explicit:
            if explicit not in accessible:
                raise LiteError('ENDPOINT_METAL_ACCESS_REQUIRED', pin_id=pin_id, layer=explicit)
            return explicit
        if fallback in accessible:
            return fallback
        if len(accessible) == 1:
            return next(iter(accessible))
        raise LiteError(
            'ENDPOINT_METAL_ACCESS_REQUIRED',
            '请指定有真实金属接入的端点层。',
            pin_id=pin_id,
            available_layers=sorted(accessible),
        )

    start = endpoint_layer(args.start_pin_id, args.start_layer, layers[0])
    end = endpoint_layer(args.end_pin_id, args.end_layer, layers[-1])
    allowed = box(-MAX_DBU, -MAX_DBU, MAX_DBU, MAX_DBU)
    if editor.scope_id:
        region = editor.w.local_data.regions[editor.scope_id]
        allowed = box(*region.bbox[0], *region.bbox[1])
    if args.bounds_um is not None:
        a, b, c, d = [dbu(v, p) for v in args.bounds_um]
        if a >= c or b >= d or not allowed.covers(box(a, b, c, d)):
            raise LiteError('HELPER_BOUNDS_OUTSIDE_REGION')
        allowed = box(a, b, c, d)
    created = []
    segments = []
    transitions = []
    with editor.transaction() as staged:
        for layer, a, b in zip(layers, points, points[1:]):
            if cancelled is not None and cancelled.is_set():
                raise LiteError('EDIT_CANCELLED')
            uid = (
                Actions(staged)
                .execute(
                    'create_path90',
                    {
                        'lpp': [layer, 'drawing'],
                        'points': [[v / scale for v in pt] for pt in (a, b)],
                        'width': widths[layer],
                        'style': 'truncateExtend',
                        'net_intent': args.net_intent,
                    },
                )
                .uid
            )
            created.append(uid)
            segments.append(
                {
                    'uid': uid,
                    'layer': layer,
                    'width_um': widths[layer],
                    'points_um': [[v / scale for v in pt] for pt in (a, b)],
                }
            )
        junctions = [
            (points[i], layers[i - 1], layers[i])
            for i in range(1, len(points) - 1)
            if layers[i - 1] != layers[i]
        ]
        if start != layers[0]:
            junctions.insert(0, (points[0], start, layers[0]))
        if end != layers[-1]:
            junctions.append((points[-1], layers[-1], end))
        generated = set(created)
        for point, lower, upper in junctions:
            route = chain(p, rules, lower, upper)
            minimum = max(
                2, rules.design_warnings.minimum_cuts if rules.design_warnings.via_enabled else 2
            )
            extents = []
            for name, _, _ in route:
                shape = Shape(
                    kind='stdVia',
                    origin=(0, 0),
                    via_definition=name,
                    via_parameters={'cutRows': 1, 'cutColumns': minimum},
                )
                extents.append(unary_union(list(footprints(shape, p).values())).bounds)
            needed = max(max(abs(v) for v in extent) * 2 for extent in extents)
            size = (
                dbu(args.landing_size_um, p)
                if args.landing_size_um is not None
                else max(needed, *(dbu(w, p) for w in widths.values()))
            )
            half = ceil(size / (2 * grid)) * grid
            roi = box(
                point[0] - half, point[1] - half, point[0] + half, point[1] + half
            ).intersection(allowed)
            if roi.is_empty:
                raise LiteError('VIA_LANDING_OUTSIDE_BOUNDS')
            bounds = [v / scale for v in roi.bounds]
            result = fill_vias(
                staged,
                AutoVias(
                    bounds_um=bounds,
                    start_layer=lower,
                    end_layer=upper,
                    net_intent=args.net_intent,
                    allow_landing=True,
                    landing_policy='expand_window',
                ),
                rules,
                cancelled=cancelled,
                generated=generated,
            )
            generated.update(result['created_uids'])
            created.extend(result['created_uids'])
            transitions.append(
                {
                    'point_um': [v / scale for v in point],
                    'from': lower,
                    'to': upper,
                    'levels': result['levels'],
                    'bounds_um': result['bounds_um'],
                }
            )
        for uid in created:
            bounds = object_bounds(staged.w, staged.object(uid), p)
            if not allowed.covers(box(*bounds[0], *bounds[1])):
                raise LiteError('HELPER_BOUNDS_VIOLATION', uid=uid, edit_applied=False)
        graph = scope_graph(staged.w, p, staged.scope_id)
        components = {n['component_id'] for n in graph['nodes'] if n['owner_uid'] in created}
        if len(components) != 1:
            raise LiteError(
                'PATH_NOT_CONNECTED', '生成路径没有组成一个物理分量，未采用。', edit_applied=False
            )
        cid = next(iter(components))
        pins = {pin['id']: pin for pin in graph['pins']}
        contacts = graph['component_pins'].get(cid, set())
        nets = {pins[pid]['net'] for pid in contacts if pins[pid]['net'] is not None}
        if nets - {args.net_intent}:
            raise LiteError('PATH_SHORT_DETECTED', nets=sorted(nets), edit_applied=False)
        for pid in (args.start_pin_id, args.end_pin_id):
            if pid and pid not in contacts:
                raise LiteError('PATH_ENDPOINT_NOT_CONNECTED', pin_id=pid, edit_applied=False)
    return {
        'created_uids': created,
        'segments': segments,
        'transitions': transitions,
        'internal_connected': True,
        'net_intent': args.net_intent,
        'external_net_confirmed': nets == {args.net_intent},
        'connection_scope': 'generated path and its actual contacts; does not declare the whole target net complete',
        **report_bounds(editor, created),
    }

"""Advisory for touching unexposed device metal; no device/net extraction.

Only native, same-owner, same-layer metal can establish a PIN extension.
External wires must never make an internal component appear to be an access.
"""
from collections import defaultdict
from shapely.geometry import box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from ..hierarchy import is_hierarchical_instance
from ..materials import extract
from ..model import digest
from ..physical_connectivity import _touches_conductively
from ..pin_geometry import cached_pin_geometry
from ..regions.query import object_bounds
from .models import Marker, Region

RULE_ID = 'design.internal_metal_contact'
PURPOSES = {'drawing', 'pin'}


def polygons(geometry):
    if geometry.geom_type == 'Polygon':
        if not geometry.is_empty:
            yield geometry
    elif hasattr(geometry, 'geoms'):
        for part in geometry.geoms:
            yield from polygons(part)


def edges(geometry):
    if geometry.geom_type == 'Polygon':
        for ring in (geometry.exterior, *geometry.interiors):
            yield from edges(ring)
    elif geometry.geom_type in ('LineString', 'LinearRing'):
        points = list(geometry.coords)
        for a, b in zip(points, points[1:]):
            if a != b:
                yield (*a, *b)
    elif hasattr(geometry, 'geoms'):
        for part in geometry.geoms:
            yield from edges(part)


def run(w, technology, physical, objects, allowed, roi, context, *, checkpoint=lambda: None, limit=10000):
    from .local import bounds

    metals = {row['layer'] for row in technology.layers
              if row['purpose'] == 'drawing' and row.get('material') == 'metal'}
    devices = {uid for uid in allowed if objects[uid].kind in ('inst', 'mosaic')
               and not is_hierarchical_instance(w, objects[uid])}
    coverage = {'warning_count': 0, 'reported_count': 0, 'omitted_count': 0,
                'scope': 'current-level standalone metal against ordinary native device metal; same-layer PIN extension only'}
    if not devices or not metals:
        return [], coverage

    native = defaultdict(list)
    wire_rows = defaultdict(list)
    for row in physical:
        checkpoint()
        if row.layer not in metals or row.purpose not in PURPOSES or row.owner not in allowed:
            continue
        if row.owner in devices:
            native[(row.owner, row.layer)].append(row.geometry)
        elif not row.inside_instance and objects[row.owner].kind not in ('inst', 'mosaic'):
            wire_rows[(row.owner, row.layer)].append(row.geometry)
    wires = {key: unary_union(rows) for key, rows in wire_rows.items()}
    layers = defaultdict(list)
    for (uid, layer), geometry in sorted(wires.items()):
        layers[layer].append((uid, geometry))
    trees = {layer: STRtree([geometry for _, geometry in rows]) for layer, rows in layers.items()}

    # Broad phase uses the already extracted ROI material. Do not build all
    # device components when no independent wire even touches their metal.
    candidates = set()
    for key, rows in native.items():
        uid, layer = key
        if layer not in trees:
            continue
        for geometry in rows:
            checkpoint()
            clipped = geometry.intersection(roi)
            if not clipped.is_empty and len(trees[layer].query(clipped, predicate='intersects')):
                candidates.add(key)
                break
    if not candidates:
        return [], coverage

    candidate_owners = {uid for uid, _ in candidates}
    public = defaultdict(list)
    available = set()
    unavailable = set()
    for pin in w.baseline.pins:
        uid = pin.get('instance_uid')
        if uid not in candidate_owners:
            continue
        checkpoint()
        try:
            layer = pin['lpp'][0]
            geometry = cached_pin_geometry(w.baseline, pin, w.baseline.objects[uid].placement, objects[uid].placement)
        except (KeyError, ValueError, TypeError):
            unavailable.add(uid)
            continue
        available.add(uid)
        if layer in metals:
            public[(uid, layer)].append(geometry)
    unavailable.update(candidate_owners - available)

    # A small ROI can omit the PIN or an intermediate native metal strip.
    # Classify with the complete device; clip only the emitted contact witness.
    extra = set()
    boxes = []
    for uid in sorted(candidate_owners - unavailable):
        checkpoint()
        extent = object_bounds(w, objects[uid], technology)
        if extent is None:
            unavailable.add(uid)
        elif not context.covers(box(*extent[0], *extent[1])):
            extra.add(uid)
            boxes.append(box(*extent[0], *extent[1]))
    if extra:
        complete, _, warnings, _, _ = extract(w, technology, Region(bbox=bounds(unary_union(boxes))),
                                             0, checkpoint, owner_filter=extra)
        unavailable.update(row['uid'] for row in warnings if row.get('uid') in extra)
        if any('uid' not in row for row in warnings):
            unavailable.update(extra)
        for key in list(native):
            if key[0] in extra:
                native.pop(key)
        for row in complete:
            if row.owner in extra and row.layer in metals and row.purpose in PURPOSES:
                native[(row.owner, row.layer)].append(row.geometry)

    contacts = defaultdict(list)
    for key in sorted(candidates):
        uid, layer = key
        checkpoint()
        if uid in unavailable:
            continue
        pin_shapes = public.get(key, [])
        pin_tree = STRtree(pin_shapes)
        for component in polygons(unary_union(native.get(key, []))):
            checkpoint()
            if any(_touches_conductively(component, pin_shapes[int(i)])
                   for i in pin_tree.query(component, predicate='intersects')):
                continue
            for i in trees[layer].query(component, predicate='intersects'):
                checkpoint()
                wire, geometry = layers[layer][int(i)]
                witness = component.intersection(geometry).intersection(roi)
                # A single corner does not establish a physical metal contact.
                if witness.area > 0 or witness.length > 0:
                    contacts[(wire, uid, layer)].append(witness)

    markers = []
    for (wire, device, layer), pieces in sorted(contacts.items()):
        checkpoint()
        coverage['warning_count'] += 1
        if len(markers) >= limit:
            coverage['omitted_count'] += 1
            continue
        contact = unary_union(pieces).normalize()
        wire_obj, device_obj = objects[wire], objects[device]
        refs = tuple({'uid': uid, 'kind': obj.kind, 'name': obj.attributes.get('name'),
                      'inside_instance': inside}
                     for uid, obj, inside in ((wire, wire_obj, False), (device, device_obj, True)))
        scale = technology.dbu_per_micron
        name = device_obj.attributes.get('name') or device
        markers.append(Marker(id=digest([RULE_ID, wire, device, layer, contact.wkb_hex])[:24],
            rule_id=RULE_ID, message=f'可能误接 {name} 内部的 {layer} 金属，请检查走线路径。',
            severity='warning', kind='edges', edges=tuple(edges(contact)), bbox=bounds(contact),
            layers=(layer,), objects=refs, association='local_geometry',
            details={'category': 'design_warning', 'advice': 'device_internal_metal_contact',
                     'wire_uid': wire, 'device_uid': device, 'layer': layer,
                     'contact_area_um2': contact.area / scale**2,
                     'contact_bounds_um': [v/scale for v in contact.bounds],
                     'method': 'native_same_layer_components_excluding_public_pin_access',
                     'limitation': '仅为误接风险提示；不抽取器件内部电路，不代表短路或 LVS 结论。'}))
    coverage['reported_count'] = len(markers)
    if unavailable:
        coverage['skipped_devices_without_complete_pin_geometry'] = len(unavailable)
    return markers, coverage

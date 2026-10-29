"""Local conductor connectivity; never LVS or transistor channel extraction.

Coordinates are database units throughout. Native Layout net targets label components
*after* the physical graph is built; net names never join disconnected shapes.
Technology-declared metals, poly and N-wells participate. Contacts require
actual material coverage; diffusion and implants are evidence, not conductors.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import replace
from itertools import combinations
from math import isfinite

from shapely.geometry import box, mapping
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .materials import apply_delta, extract, placement_delta, polygon_from_figure
from .drc.models import Region
from .editor import projected
from .hierarchy import node_info
from .model import LiteError, MAX_DBU
from .conduction_rules import ConductionRules


def _number(value):
    number = float(value)
    if not isfinite(number):
        raise ValueError('Non-finite pin coordinate')
    return int(number) if number.is_integer() else number


def _points(values):
    return [[_number(v) for v in p] for p in values]


def _bbox(geometry):
    a, b, c, d = geometry.bounds
    return [[_number(a), _number(b)], [_number(c), _number(d)]]


def _polygons(geometry):
    polygons = [geometry] if geometry.geom_type == 'Polygon' else list(geometry.geoms)
    return [
        dict(exterior=_points(p.exterior.coords), holes=[_points(r.coords) for r in p.interiors])
        for p in polygons
        if p.geom_type == 'Polygon'
    ]


def _metal_layers(technology):
    return {row['layer'] for row in technology.layers if row.get('material') == 'metal'}


def _cache_warnings(workspace):
    """Check cache ownership even for an instance missing a usable bounding box."""
    nodes = workspace.baseline.display.get('nodes', {})
    root = nodes.get(workspace.baseline.display.get('root'))
    root_children = {child[0] for child in root[10] or []} if root and len(root) > 10 else set()
    warnings = []
    for uid, obj in projected(workspace).items():
        if obj.kind not in ('inst', 'mosaic'):
            continue
        missing = obj.native_id not in root_children
        visited = set()

        def check_node(key):
            if key in visited:
                return False
            visited.add(key)
            node = nodes.get(key)
            if not node or len(node) < 11 or node_info(node).get('collapsed'):
                return True
            return any(check_node(c[1]) for c in node[10] or [])

        if check_node(obj.attributes.get('master_key')) or missing:
            warnings.append(dict(kind='incomplete_instance_cache', uid=uid))
    return warnings


def _intent_endpoints(intent):
    if not isinstance(intent, dict) or intent.get('schema_version') != 'colayout-agent-intent-1':
        raise LiteError('INVALID_AGENT_INTENT', 'Expected colayout-agent-intent-1')
    nets = intent.get('nets')
    if not isinstance(nets, dict) or not isinstance(intent.get('instance_map', {}), dict):
        raise LiteError('INVALID_AGENT_INTENT', 'nets and instance_map must be objects')
    for name, endpoints in nets.items():
        if not isinstance(name, str) or not name or not isinstance(endpoints, list):
            raise LiteError('INVALID_AGENT_INTENT', 'Each net needs a name and endpoint list')
        if any(not isinstance(e, str) or not e for e in endpoints):
            raise LiteError('INVALID_AGENT_INTENT', 'Endpoint names must be nonempty strings')
    return list(dict.fromkeys(e for endpoints in nets.values() for e in endpoints))


from .pin_geometry import pin_geometry as _pin_geometry


def _resolve_endpoints(workspace, technology, intent, local_pins):
    objects = projected(workspace)
    metals = ConductionRules(technology).conductors
    endpoints = {}
    unresolved = []
    pins_by_terminal = defaultdict(list)
    for pin in workspace.baseline.pins:
        pins_by_terminal[(pin.get('instance_uid'), pin.get('terminal'))].append(pin)
    for endpoint in _intent_endpoints(intent):
        endpoints[endpoint] = []

        def problem(reason, **details):
            unresolved.append(dict(endpoint=endpoint, reason=reason, **details))

        if endpoint.startswith('$'):
            native_ports = (
                workspace.layout_connectivity.ports if workspace.layout_connectivity else {}
            )
            name = endpoint[1:]
            if any(name == t.name or name in t.members for t in native_ports.values()):
                # Native top-level pins stay real geometry, never local markers.
                from .geometry import shape_figure

                rows = [t for t in workspace.baseline.terminals if t[0] == name]
                for term in rows:
                    for pi, pin_row in enumerate(term[3] or []):
                        for fi, uid in enumerate(pin_row[2] or []):
                            obj = objects.get(uid)
                            if obj and obj.shape and obj.shape.lpp and obj.shape.lpp[0] in metals:
                                endpoints[endpoint].append(
                                    dict(
                                        lpp=obj.shape.lpp,
                                        geometry=polygon_from_figure(shape_figure(obj.shape)),
                                        owner_uid=uid,
                                        local=False,
                                        pin_index=pi,
                                        figure_index=fi,
                                    )
                                )
                if not endpoints[endpoint]:
                    problem('native_top_pin_geometry_unavailable')
                continue
            pin = local_pins.get(endpoint[1:])
            if not pin:
                problem('local_pin_missing')
                continue
            try:
                lpp = tuple(pin['lpp'])
                bounds = pin['bbox']
                if len(lpp) != 2 or len(bounds) != 2 or any(len(p) != 2 for p in bounds):
                    raise ValueError('Invalid pin layer/bounds')
                if any(type(v) is not int or abs(v) > MAX_DBU for p in bounds for v in p):
                    raise ValueError('Local pin coordinates must be integer DBU')
                if any(a >= b for a, b in zip(*bounds)):
                    raise ValueError('Local pin must have positive area')
                g = box(*bounds[0], *bounds[1])
                if lpp[0] not in metals:
                    problem('nonmetal_endpoint', lpp=list(lpp))
                    continue
                endpoints[endpoint].append(
                    dict(
                        lpp=lpp, geometry=g, owner_uid=None, local=True, pin_index=0, figure_index=0
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                problem('invalid_local_pin', message=str(error))
            continue
        if '.' not in endpoint:
            problem('invalid_endpoint_name')
            continue
        name, terminal = endpoint.rsplit('.', 1)
        uid = intent.get('instance_map', {}).get(name)
        obj = objects.get(uid)
        if obj is None or obj.kind not in ('inst', 'mosaic'):
            problem('instance_missing', instance=name, uid=uid)
            continue
        if obj.kind == 'mosaic':
            problem('mosaic_endpoint_requires_occurrence_identity', uid=uid)
            continue
        pins = pins_by_terminal.get((uid, terminal), [])
        if not pins:
            problem('terminal_missing', uid=uid, terminal=terminal)
            continue
        before = workspace.baseline.objects[uid].placement
        nonmetals = []
        for pin in pins:
            lpp = pin.get('lpp') or []
            if len(lpp) != 2 or lpp[0] not in metals:
                nonmetals.append(lpp)
                continue
            try:
                g = _pin_geometry(pin, before, obj.placement)
                endpoints[endpoint].append(
                    dict(
                        lpp=tuple(lpp),
                        geometry=g,
                        owner_uid=uid,
                        local=False,
                        pin_index=pin.get('pin_index'),
                        figure_index=pin.get('figure_index'),
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                problem('pin_geometry_unavailable', uid=uid, message=str(error))
        if not endpoints[endpoint] and nonmetals:
            problem('nonmetal_endpoint', uid=uid, lpps=nonmetals)
    return endpoints, unresolved


def endpoint_geometries(workspace, technology, intent: dict, local_pins: dict) -> dict:
    """Return exact, currently placed routing targets, keyed by Layout endpoint.

    Missing/unsupported endpoints map to an empty list; check_connectivity reports
    their reasons. Each row contains lpp, bbox and polygons in DBU. Multiple rows
    are physical figures, not an implicit electrical connection between them.
    """
    endpoints, _ = _resolve_endpoints(workspace, technology, intent, local_pins)
    return {
        name: [
            dict(
                lpp=list(row['lpp']),
                bbox=_bbox(row['geometry']),
                polygons=_polygons(row['geometry']),
                owner_uid=row['owner_uid'],
                pin_index=row['pin_index'],
                figure_index=row['figure_index'],
                local=row['local'],
            )
            for row in rows
        ]
        for name, rows in endpoints.items()
    }


class _UnionFind:
    def __init__(self, size):
        self.parent = list(range(size))

    def find(self, n):
        while self.parent[n] != n:
            self.parent[n] = self.parent[self.parent[n]]
            n = self.parent[n]
        return n

    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def _touches_conductively(a, b):
    intersection = a.intersection(b)
    # A shared edge is conductive. A single corner is not a manufacturable
    # connection, and must not make a net pass.
    return intersection.area > 0 or intersection.length > 0


def _physical_materials(workspace, technology, intent, physical_override):
    """Extract and split conductor polygons, retaining all coverage warnings."""
    rules = ConductionRules(technology)
    metals = rules.metals
    warnings = (
        _cache_warnings(workspace) if physical_override is None else list(physical_override[1])
    )
    if workspace.baseline.technology_fingerprint != technology.native_fingerprint:
        warnings.append(dict(kind='technology_mismatch'))
    if workspace.baseline.dbu_per_micron != technology.dbu_per_micron:
        warnings.append(dict(kind='unit_mismatch'))
    if not metals:
        warnings.append(dict(kind='no_declared_metal_layers'))
    if not intent['nets'] or any(not e for e in intent['nets'].values()):
        warnings.append(dict(kind='empty_intent_net'))
    if workspace.baseline.display.get('unsupported'):
        warnings.append(
            dict(
                kind='unsupported_display_geometry',
                details=workspace.baseline.display['unsupported'],
            )
        )
    all_physical = []
    if physical_override is not None:
        all_physical = physical_override[0]
    else:
        try:
            region = Region(bbox=((-MAX_DBU, -MAX_DBU), (MAX_DBU, MAX_DBU)))
            all_physical, _, extraction_warnings, _, _ = extract(workspace, technology, region, 0)
            warnings.extend(extraction_warnings)
            from .conduction_access import default_access_projection

            all_physical, access_warnings = default_access_projection(
                workspace, technology, all_physical
            )
            warnings.extend(access_warnings)
        except (ValueError, KeyError, TypeError, LiteError) as error:
            warnings.append(dict(kind='physical_extraction_failed', message=str(error)))
    # Each polygon is a separate physical node. A multi-polygon figure must not
    # accidentally join its disconnected parts by virtue of sharing an owner.
    physical = []
    for row in all_physical:
        if row.layer not in rules.conductors:
            continue
        parts = [row.geometry] if row.geometry.geom_type == 'Polygon' else row.geometry.geoms
        for part in parts:
            if part.geom_type == 'Polygon' and not part.is_empty:
                physical.append(
                    dict(
                        owner=row.owner,
                        layer=row.layer,
                        geometry=part,
                        inside_instance=row.inside_instance,
                    )
                )
    return rules, warnings, all_physical, physical


def _contact_graph(workspace, technology, rules, all_physical, physical, warnings):
    """Join only geometrically proven same-layer contacts and verified vias."""
    metals = rules.metals
    uf = _UnionFind(len(physical))
    edges = []

    def edge(a, b, geometry, kind, **details):
        edges.append(
            dict(
                id='e' + str(len(edges) + 1),
                kind=kind,
                node_ids=['p' + str(a + 1), 'p' + str(b + 1)],
                geometry=geometry,
                **details,
            )
        )
        uf.join(a, b)

    indices = defaultdict(list)
    for index, row in enumerate(physical):
        indices[row['layer']].append(index)
    trees = {
        layer: STRtree([physical[i]['geometry'] for i in ids]) for layer, ids in indices.items()
    }

    def hits(layer, geometry):
        if layer not in trees:
            return []
        return [
            indices[layer][int(i)] for i in trees[layer].query(geometry, predicate='intersects')
        ]

    for index, row in enumerate(physical):
        for other in hits(row['layer'], row['geometry']):
            if other > index and _touches_conductively(
                row['geometry'], physical[other]['geometry']
            ):
                edge(
                    index,
                    other,
                    row['geometry'].intersection(physical[other]['geometry']),
                    'same_layer_contact',
                    layer=row['layer'],
                    layers=[row['layer']],
                )
    from .conduction_contacts import contact_links

    links, contact_warnings, via_links = contact_links(
        all_physical, physical, rules, projected(workspace)
    )
    warnings.extend(contact_warnings)
    for a, b, g, details in links:
        edge(a, b, g, 'via', **details)
    declared_cuts = {d.get('cut_layer') for d in technology.vias.values()}
    cut_materials = {r['layer'] for r in technology.layers if r.get('material') == 'cut'}
    for row in all_physical:
        if row.layer in cut_materials and row.layer not in declared_cuts:
            overlapping_metals = [
                layer
                for layer in metals
                if any(
                    physical[i]['geometry'].intersection(row.geometry).area > 0
                    for i in hits(layer, row.geometry)
                )
            ]
            if len(overlapping_metals) > 1:
                warnings.append(
                    dict(
                        kind='unknown_via_cut_mapping',
                        owner_uid=row.owner,
                        cut_layer=row.layer,
                        metal_layers=sorted(overlapping_metals),
                    )
                )
    return uf, edges, hits, via_links


def _endpoint_attachments(endpoints, physical, hits, uf, unresolved):
    """Attach endpoint labels after contacts; labels never join components."""
    endpoint_roots = {}
    endpoint_nodes = defaultdict(set)
    endpoint_contacts = defaultdict(list)
    unattached = set()
    partial_attachments = []
    for name, rows in endpoints.items():
        roots = set()
        for row in rows:
            matches = [
                i
                for i in hits(row['lpp'][0], row['geometry'])
                if physical[i]['geometry'].intersection(row['geometry']).area > 0
            ]
            for i in matches:
                endpoint_nodes[name].add('p' + str(i + 1))
                endpoint_contacts[name].append(
                    dict(
                        node_id='p' + str(i + 1),
                        layer=row['lpp'][0],
                        geometry=row['geometry'].intersection(physical[i]['geometry']),
                    )
                )
            covering = unary_union([physical[i]['geometry'] for i in matches])
            if not matches or not covering.covers(row['geometry']):
                if row['local']:
                    unattached.add(name)
                    covered_area = covering.intersection(row['geometry']).area
                    partial_attachments.append(
                        dict(
                            endpoint=name,
                            reason='partial_metal_coverage' if matches else 'no_metal_contact',
                            # Ratios are diagnostic floats, never a rounded substitute
                            # for the exact geometry.covers check above.
                            covered_fraction=float(
                                max(0.0, min(1.0, covered_area / row['geometry'].area))
                            ),
                            missing_area_dbu2=float(row['geometry'].difference(covering).area),
                            required_bbox=_bbox(row['geometry']),
                            layer=row['lpp'][0],
                            lpp=list(row['lpp']),
                        )
                    )
                else:
                    unresolved.append(
                        dict(
                            endpoint=name,
                            reason='pin_physical_geometry_missing',
                            uid=row['owner_uid'],
                            lpp=list(row['lpp']),
                            bbox=_bbox(row['geometry']),
                        )
                    )
            roots.update(uf.find(i) for i in matches)
        endpoint_roots[name] = roots
    return endpoint_roots, endpoint_nodes, endpoint_contacts, unattached, partial_attachments


def physical_graph(
    workspace, technology, intent: dict, local_pins: dict, *, physical_override=None
) -> dict:
    """Build the shared physical graph for inspection, checking and routing.

    Geometry in nodes/edges is Shapely in DBU; ``report`` and ``endpoints`` are
    JSON serializable. Node/component IDs are only meaningful at this revision.
    Endpoint labels are attached after edges are built, never used to join them.
    """
    endpoints, unresolved = _resolve_endpoints(workspace, technology, intent, local_pins)
    rules, warnings, all_physical, physical = _physical_materials(
        workspace, technology, intent, physical_override
    )
    uf, edges, hits, via_links = _contact_graph(
        workspace, technology, rules, all_physical, physical, warnings
    )
    endpoint_roots, endpoint_nodes, endpoint_contacts, unattached, partial_attachments = (
        _endpoint_attachments(endpoints, physical, hits, uf, unresolved)
    )
    metals = rules.metals
    by_root = defaultdict(list)
    for index in range(len(physical)):
        by_root[uf.find(index)].append(index)
    component_ids = {root: 'c' + str(n) for n, root in enumerate(sorted(by_root), 1)}
    nodes = [
        dict(
            id='p' + str(i + 1),
            owner_uid=row['owner'],
            layer=row['layer'],
            geometry=row['geometry'],
            component_id=component_ids[uf.find(i)],
            inside_instance=row['inside_instance'],
        )
        for i, row in enumerate(physical)
    ]
    root_endpoints = defaultdict(set)
    root_nets = defaultdict(set)
    assignment = defaultdict(set)
    for net, names in intent['nets'].items():
        for name in set(names):
            assignment[name].add(net)
            for root in endpoint_roots[name]:
                root_endpoints[root].add(name)
                root_nets[root].add(net)
            if name.startswith('$') and local_pins.get(name[1:], {}).get('net') not in (None, net):
                unresolved.append(
                    dict(
                        endpoint=name,
                        reason='local_pin_net_mismatch',
                        expected_net=net,
                        pin_net=local_pins[name[1:]]['net'],
                    )
                )
    for endpoint, nets in assignment.items():
        if len(nets) > 1:
            unresolved.append(
                dict(
                    endpoint=endpoint,
                    reason='endpoint_assigned_to_multiple_nets',
                    nets=sorted(nets),
                )
            )
    components = []
    for root, ids in sorted(by_root.items()):
        geometry = unary_union([physical[i]['geometry'] for i in ids])
        owners = sorted({physical[i]['owner'] for i in ids})
        names = sorted(root_endpoints[root])
        components.append(
            dict(
                id=component_ids[root],
                owners=owners,
                owner_uids=owners,
                layers=sorted({physical[i]['layer'] for i in ids}),
                bbox=_bbox(geometry),
                endpoints=names,
                endpoint_names=names,
                nets=sorted(root_nets[root]),
                polygon_count=len(ids),
            )
        )
    shorts = [
        dict(
            component=c['id'],
            nets=c['nets'],
            endpoints=c['endpoints'],
            bbox=c['bbox'],
            owners=c['owners'],
        )
        for c in components
        if len(c['nets']) > 1
    ]
    _short_witnesses(shorts, nodes, edges, endpoint_contacts, assignment)
    opens = []
    unresolved_names = {u.get('endpoint') for u in unresolved}
    net_status = {}
    for net, names in intent['nets'].items():
        roots = set().union(*(endpoint_roots[n] for n in names)) if names else set()
        floating = sorted(set(names) & unattached)
        unknown = sorted(set(names) & unresolved_names)
        groups = [
            dict(component=component_ids[root], endpoints=sorted(set(names) & root_endpoints[root]))
            for root in sorted(roots)
        ]
        if len(roots) > 1 or floating:
            opens.append(
                dict(
                    net=net,
                    groups=groups,
                    unconnected_endpoints=floating,
                    unresolved_endpoints=unknown,
                    partial_attachments=[a for a in partial_attachments if a['endpoint'] in names],
                )
            )
        shorted = any(net in s['nets'] for s in shorts)
        net_status[net] = dict(
            status='shorted'
            if shorted
            else (
                'incomplete'
                if unknown or not names
                else ('open' if len(roots) != 1 or floating else 'connected')
            ),
            groups=groups,
        )
    complete = not warnings and not unresolved
    status = 'fail' if opens or shorts else ('pass' if complete else 'incomplete')
    coverage = dict(
        complete=complete,
        scope='declared endpoints; metal, poly and N-well continuity with verified contacts',
        metal_layers=sorted(metals),
        via_cut_layers=sorted(rules.contact_cuts),
        warnings=warnings,
        conduction=rules.describe(),
        unsupported_conduction=rules.describe()['unsupported_conduction'],
        net_intent_used_as_connection=False,
        local_pins_generate_metal=False,
        physical_polygon_count=len(physical),
        via_link_count=via_links,
        total_endpoints=len(endpoints),
        resolved_endpoints=len(endpoints) - len(unresolved_names),
    )
    report = dict(
        schema_version='colayout-agent-connectivity-1',
        status=status,
        workspace_id=workspace.id,
        revision=workspace.revision,
        opens=opens,
        shorts=shorts,
        unresolved=unresolved,
        components=components,
        nets=net_status,
        coverage=coverage,
        partial_attachments=partial_attachments,
        summary=dict(
            nets=len(intent['nets']),
            endpoints=len(endpoints),
            components=len(components),
            opens=len(opens),
            shorts=len(shorts),
            unresolved=len(unresolved),
        ),
    )
    return dict(
        report=report,
        nodes=nodes,
        edges=edges,
        endpoints={
            name: [
                dict(
                    lpp=list(row['lpp']),
                    bbox=_bbox(row['geometry']),
                    polygons=_polygons(row['geometry']),
                    owner_uid=row['owner_uid'],
                    pin_index=row['pin_index'],
                    figure_index=row['figure_index'],
                    local=row['local'],
                )
                for row in rows
            ]
            for name, rows in endpoints.items()
        },
        endpoint_nodes={name: sorted(endpoint_nodes[name]) for name in endpoints},
    )


def _contact_json(geometry):
    """Preserve an exact area or shared edge, rather than only its bounding box."""
    return dict(bbox=_bbox(geometry), geometry=mapping(geometry))


def _short_witnesses(shorts, nodes, edges, endpoint_contacts, assignment):
    """Give actual contact paths between declared nets; do not guess a culprit.

    An indirect short can be many shapes away from either terminal. A shortest
    edge path is evidence of the connection, not a claim about which edit caused
    it. If both endpoints touch one conductor, its two terminal contact areas
    and shared node are the evidence (there is no invented contact edge).
    """
    by_id = {n['id']: n for n in nodes}
    adjacency = defaultdict(list)
    for e in edges:
        a, b = e['node_ids']
        adjacency[a].append((b, e))
        adjacency[b].append((a, e))
    for short in shorts:
        short['witnesses'] = []
        for net_a, net_b in combinations(short['nets'], 2):
            sources = {}
            destinations = {}
            for endpoint in short['endpoints']:
                for contact in endpoint_contacts[endpoint]:
                    node_id = contact['node_id']
                    if by_id[node_id]['component_id'] != short['component']:
                        continue
                    target = (
                        sources
                        if net_a in assignment[endpoint]
                        else (destinations if net_b in assignment[endpoint] else None)
                    )
                    if target is not None:
                        target.setdefault(node_id, (endpoint, contact))
                    # One endpoint assigned twice is also disclosed as invalid
                    # intent; still show the physical overlap without fabrication.
                    if net_b in assignment[endpoint]:
                        destinations.setdefault(node_id, (endpoint, contact))
            queue = deque(sources)
            previous = {node_id: None for node_id in sources}
            found = None
            while queue:
                current = queue.popleft()
                if current in destinations:
                    found = current
                    break
                for neighbor, contact in adjacency[current]:
                    if neighbor not in previous:
                        previous[neighbor] = (current, contact)
                        queue.append(neighbor)
            if found is None:
                continue  # Impossible for a consistent connected component.
            path_nodes = [found]
            path_edges = []
            while previous[path_nodes[-1]] is not None:
                neighbor, contact = previous[path_nodes[-1]]
                path_nodes.append(neighbor)
                path_edges.append(contact)
            path_nodes.reverse()
            path_edges.reverse()
            contacts = []
            for e in path_edges:
                contacts.append(
                    dict(
                        **{k: v for k, v in e.items() if k != 'geometry'},
                        owner_uids=[by_id[n]['owner_uid'] for n in e['node_ids']],
                        **_contact_json(e['geometry']),
                    )
                )
            terminal_contacts = []
            for net, (endpoint, contact) in (
                (net_a, sources[path_nodes[0]]),
                (net_b, destinations[found]),
            ):
                terminal_contacts.append(
                    dict(
                        net=net,
                        endpoint=endpoint,
                        node_id=contact['node_id'],
                        owner_uid=by_id[contact['node_id']]['owner_uid'],
                        layer=contact['layer'],
                        **_contact_json(contact['geometry']),
                    )
                )
            short['witnesses'].append(
                dict(
                    kind='physical_contact_path',
                    nets=[net_a, net_b],
                    endpoint_sources=terminal_contacts,
                    nodes=[
                        dict(
                            id=n,
                            owner_uid=by_id[n]['owner_uid'],
                            layer=by_id[n]['layer'],
                            bbox=_bbox(by_id[n]['geometry']),
                        )
                        for n in path_nodes
                    ],
                    contacts=contacts,
                    identifies_root_cause=False,
                )
            )


def check_connectivity(workspace, technology, intent: dict, local_pins: dict) -> dict:
    """Check supported physical metals/vias; this is not LVS or signoff.

    Known opens/shorts fail, missing geometry is incomplete, and labels never
    create conductive edges. Includes exact contact-path witnesses for shorts.
    """
    return physical_graph(workspace, technology, intent, local_pins)['report']

"""Exact local material checks and configured DRC for proposed via footprints."""

from collections import defaultdict
from shapely.geometry import box, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree
from ..editor import projected
from ..region_analysis import scope_graph
from ..regions.query import owner_map
from ..model import LiteError
from ..drc.local import run
from ..drc.design_warnings import blocking
from ..drc.models import Region
from .via_candidates import footprints


def touches(a, b):
    contact = a.intersection(b)
    return contact.area > 0 or contact.length > 0


class Access:
    def __init__(self, editor, args, roi, *, generated=frozenset()):
        self.editor = editor
        self.args = args
        self.roi = roi
        self.generated = set(generated)
        self.graph = scope_graph(editor.w, editor.profile, editor.scope_id)
        self.pins = {pin['id']: pin for pin in self.graph['pins']}
        self.nets = defaultdict(set)
        for cid, ids in self.graph['component_pins'].items():
            self.nets[cid].update(
                self.pins[pid]['net'] for pid in ids if self.pins[pid]['net'] is not None
            )
        self.by_layer = defaultdict(list)
        for node in self.graph['nodes']:
            self.by_layer[node['layer']].append(node)
        objects = projected(editor.w)
        owners = owner_map(editor.w)
        self.intent_targets = set()
        for uid in args.targets or []:
            obj = objects.get(uid)
            if obj and obj.shape:
                if obj.shape.net_intent and obj.shape.net_intent != args.net_intent:
                    raise LiteError(
                        'TARGET_INTENT_MISMATCH', uid=uid, net_intent=obj.shape.net_intent
                    )
                # Explicitly requested floating wires are intended endpoints,
                # not proof. Final adoption still requires a real PIN witness.
                self.intent_targets.add(uid)
        from ..materials import extract
        from ..conduction_rules import ConductionRules

        raw, _, warnings, _, _ = extract(
            editor.w,
            editor.profile,
            Region(
                bbox=(
                    (int(roi.bounds[0]), int(roi.bounds[1])),
                    (int(roi.bounds[2]), int(roi.bounds[3])),
                )
            ),
            0,
            owner_filter={uid for uid in objects if owners.get(uid)==editor.scope_id and not (editor.w.layout_connectivity and uid in editor.w.layout_connectivity.instances and editor.w.layout_connectivity.instances[uid].black_box)},
        )
        modeled = defaultdict(list)
        for node in self.graph['nodes']:
            modeled[(node['owner_uid'], node['layer'])].append(node['geometry'])
        modeled = {key: unary_union(rows) for key, rows in modeled.items()}
        metal_layers = ConductionRules(editor.profile).metals
        for index, row in enumerate(raw):
            if row.layer not in metal_layers or not row.geometry.intersects(roi):
                continue
            unmodeled = row.geometry.difference(modeled.get((row.owner, row.layer), Polygon()))
            if unmodeled.area > 0:
                self.by_layer[row.layer].append(
                    {
                        'owner_uid': row.owner,
                        'component_id': f'unmodeled:{index}',
                        'geometry': unmodeled,
                        'outside_region': owners.get(row.owner) != editor.scope_id,
                    }
                )
        self.trees = {
            layer: STRtree([node['geometry'] for node in nodes])
            for layer, nodes in self.by_layer.items()
        }
        allowed = {uid for uid in objects if owners.get(uid) == editor.scope_id} | set(self.pins)
        if args.targets and set(args.targets) - allowed:
            raise LiteError('OBJECT_UNKNOWN_OR_OUTSIDE_REGION')
        self.access = {}
        for layer in (args.start_layer, args.end_layer):
            material = [
                node['geometry']
                for node in self.by_layer[layer]
                if (
                    self.nets[node['component_id']] == {args.net_intent}
                    or node['owner_uid'] in self.generated | self.intent_targets
                )
                and (
                    not args.targets
                    or node['owner_uid'] in args.targets
                    or any(
                        pid in args.targets
                        for pid in self.graph['component_pins'].get(node['component_id'], ())
                    )
                )
            ]
            material += [
                g
                for pin in self.pins.values()
                for l, g in pin['figures']
                if l == layer
                and pin['local']
                and args.allow_landing
                and pin['net'] == args.net_intent
                and (not args.targets or pin['id'] in args.targets or pin['owner'] in args.targets)
            ]
            self.access[layer] = unary_union(material)
            if not self.access[layer].intersects(roi):
                raise LiteError(
                    'AUTOVIA_NET_UNRESOLVED',
                    '允许范围内缺少该层可确认的目标接入。',
                    layer=layer,
                    net=args.net_intent,
                )
        from .via_landing import bases,reference
        self.bases=bases(self);self.reference=reference(self);self.reference_limit=roi
        if self.graph['warnings']:
            raise LiteError(
                'AUTOVIA_GEOMETRY_INCOMPLETE',
                '几何覆盖不完整，不能确认自动接入。',
                warnings=self.graph['warnings'],
            )
        if warnings:
            raise LiteError(
                'AUTOVIA_GEOMETRY_INCOMPLETE', '接入范围内存在未解析的原始几何。', warnings=warnings
            )

    def conflicts(self, figures):
        result = []
        for layer, geometry in figures.items():
            if layer not in self.trees:
                continue
            for index in self.trees[layer].query(geometry, predicate='intersects'):
                node = self.by_layer[layer][index]
                if not touches(geometry, node['geometry']):
                    continue
                nets = self.nets[node['component_id']]
                if nets - {self.args.net_intent}:
                    result.append(
                        {
                            'reason': 'other_net_contact',
                            'layer': layer,
                            'nets': sorted(nets),
                            'uid': node['owner_uid'],
                        }
                    )
                elif not nets and node['owner_uid'] not in self.generated | self.intent_targets:
                    result.append(
                        {
                            'reason': 'unknown_net_contact',
                            'layer': layer,
                            **(
                                {'outside_region': True}
                                if node.get('outside_region')
                                else {'uid': node['owner_uid']}
                            ),
                        }
                    )
        return result

    def landing_ok(self, figures, lower, upper):
        from .via_landing import permits
        if not permits(self,figures):return False
        for layer in (lower, upper):
            if layer not in self.access:
                continue
            if self.args.allow_landing:
                if not touches(figures[layer], self.access[layer]):
                    return False
            elif not self.access[layer].covers(figures[layer]):
                return False
        return True


def checked_candidate(before, after, profile, rules, roi, added_footprints, baseline, checkpoint,*,scope_id=...):
    report = run(
        after,
        profile,
        rules,
        Region(
            bbox=(
                (int(roi.bounds[0]), int(roi.bounds[1])),
                (int(roi.bounds[2]), int(roi.bounds[3])),
            )
        ),
        checkpoint=checkpoint,
        scope_id=scope_id,
    )
    if not report.coverage['complete_for_configured_subset']:
        return False, {'reason': 'check_incomplete', 'coverage': report.coverage}
    touched = unary_union(list(added_footprints.values()))
    new = []
    related = []
    for marker in report.markers:
        if not blocking(marker):
            continue
        if marker.id not in baseline:
            new.append(marker.id)
        elif box(*marker.bbox[0], *marker.bbox[1]).intersects(touched):
            related.append(marker.id)
    if new or related:
        scale = profile.dbu_per_micron
        ids = set(new + related)
        return False, {
            'reason': 'local_drc',
            'new_marker_ids': new,
            'existing_related_marker_ids': related,
            'findings': [
                {
                    'id': m.id,
                    'rule_id': m.rule_id,
                    'message': m.message,
                    'bounds_um': [v / scale for point in m.bbox for v in point],
                    'measured_um': m.measured_um,
                    'required_um': m.required_um,
                    'relation': 'new' if m.id in new else 'existing_related',
                }
                for m in report.markers
                if m.id in ids
            ][:8],
        }
    return True, {
        'status': 'completed',
        'complete_for_configured_subset': True,
        'new_errors': 0,
        'design_warnings': sum(not blocking(m) for m in report.markers),
        'seconds': report.metrics['seconds'],
    }


def cut_material(editor, cut_layer, roi):
    # Ordinary device cuts remain collision obstacles. Native modules are opaque.
    from ..materials import extract
    from ..hierarchy import is_hierarchical_instance

    region = Region(
        bbox=((int(roi.bounds[0]), int(roi.bounds[1])), (int(roi.bounds[2]), int(roi.bounds[3])))
    )
    rows, _, _, _, _ = extract(editor.w, editor.profile, region, 0,
        owner_filter={uid for uid,obj in projected(editor.w).items() if not is_hierarchical_instance(editor.w,obj)})
    return (
        unary_union([row.geometry for row in rows if row.layer == cut_layer]) if rows else Polygon()
    )


def reusable(editor, name, roi, minimum):
    result = []
    for uid, obj in projected(editor.w).items():
        if obj.kind != 'stdVia' or obj.read_only_reason or obj.shape.via_definition != name:
            continue
        if not roi.covers(unary_union(list(footprints(obj.shape, editor.profile).values()))):
            continue
        params = editor.profile.effective_via(obj.shape)
        if params['cutRows'] * params['cutColumns'] >= minimum:
            result.append(uid)
    return result

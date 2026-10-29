"""Dense standard arrays selected by real footprints, contact evidence and DRC."""

from time import perf_counter
from shapely.geometry import box, Polygon
from shapely.ops import unary_union
from ..actions import dbu
from ..editor import Editor
from ..model import LiteError
from ..drc.local import run
from ..drc.models import Region
from ..drc.design_warnings import blocking
from ..region_analysis import scope_graph
from .via_candidates import chain, arrays, footprints
from .via_checks import Access, checked_candidate, cut_material, reusable, touches
from .common import report_bounds


def create(editor, args, rules, *, cancelled=None, generated=frozenset()):
    if rules is None:
        raise LiteError('LOCAL_DRC_REQUIRED', '自动打孔需要已配置的本地 DRC。')
    began = perf_counter()
    p = editor.profile

    def checkpoint():
        if cancelled is not None and cancelled.is_set():
            raise LiteError('EDIT_CANCELLED', '生成未采用。')

    a, b, c, d = [dbu(v, p) for v in args.bounds_um]
    if a >= c or b >= d:
        raise LiteError('INVALID_VIA_BOUNDS')
    roi = box(a, b, c, d)
    region = editor.w.local_data.regions.get(editor.scope_id)
    if region and not box(*region.bbox[0], *region.bbox[1]).covers(roi):
        raise LiteError('AUTOVIA_OUTSIDE_REGION')
    route = chain(p, rules, args.start_layer, args.end_layer, args.via_definitions)
    single=args.array_direction!='any'
    if single and len(route)!=1:raise LiteError('SINGLE_ROW_REQUIRES_ONE_VIA','单排模式仅支持一层标准过孔。')
    minimum = max(
        2,
        args.minimum_cuts,
        rules.design_warnings.minimum_cuts if rules.design_warnings.via_enabled else 2,
    )
    if minimum > args.max_cuts:
        raise LiteError('AUTOVIA_CUT_BUDGET_TOO_SMALL')
    created = []
    reused = []
    levels = []
    trials = 0
    drc_checks = 0
    reasons = []
    source = editor.w
    with editor.transaction() as staged:
        # Logical access is checked against the original outer-layer targets.
        access = Access(staged, args, roi, generated=generated)
        baseline_report = run(
            source, p, rules, Region(bbox=((a, b), (c, d))), checkpoint=checkpoint,scope_id=editor.scope_id
        )
        if not baseline_report.coverage['complete_for_configured_subset']:
            raise LiteError('AUTOVIA_CHECK_INCOMPLETE', coverage=baseline_report.coverage)
        baseline = {marker.id for marker in baseline_report.markers if blocking(marker)}
        for name, lower, upper in route:
            checkpoint()
            from .via_landing import search_window
            fitting_window=search_window(access,name,roi)
            definition = p.vias[name]
            cut_layer = definition['cut_layer']
            occupied = cut_material(staged, cut_layer, roi)
            keep = reusable(staged, name, roi, minimum)
            keep = [
                uid
                for uid in keep
                if not access.conflicts(footprints(staged.object(uid).shape, p))
                and access.landing_ok(footprints(staged.object(uid).shape, p), lower, upper)
                and not any(
                    blocking(m)
                    and box(*m.bbox[0], *m.bbox[1]).intersects(
                        unary_union(list(footprints(staged.object(uid).shape, p).values()))
                    )
                    for m in baseline_report.markers
                )
            ]
            reused.extend(keep)
            level_ids = []
            level_count = sum(
                p.effective_via(staged.object(uid).shape)['cutRows']
                * p.effective_via(staged.object(uid).shape)['cutColumns']
                for uid in keep
            )
            selected_checks = (
                [
                    {
                        'status': 'completed',
                        'complete_for_configured_subset': True,
                        'source': 'existing arrays checked by local DRC',
                        'reused_uids': keep,
                    }
                ]
                if keep
                else []
            )
            search_roi = fitting_window
            if not args.allow_landing:
                for layer in (args.start_layer, args.end_layer):
                    search_roi = search_roi.intersection(access.access[layer])
            if search_roi.is_empty:
                raise LiteError('AUTOVIA_NO_LEGAL_ARRAY', '两侧目标没有足够的共同接入范围。')
            from .via_candidates import single_row_arrays
            def candidates(budget):
                if single:return single_row_arrays(p,name,search_roi,minimum,budget,args.net_intent,args.array_direction)
                return arrays(p,name,search_roi,minimum,budget,args.net_intent)
            maximum = next(candidates(args.max_cuts),None)
            capacity = maximum[1] if maximum else 0
            if single and keep:
                def direction_matches(uid):
                    shape=staged.object(uid).shape;params=p.effective_via(shape)
                    default_shape=shape.model_copy(update={'via_parameters':{'cutRows':params['cutRows'],'cutColumns':params['cutColumns']}})
                    return shape.orientation=='R0' and params==p.effective_via(default_shape) and params['cutRows' if args.array_direction=='horizontal' else 'cutColumns']==1
                if len(keep)!=1 or not all(direction_matches(uid) for uid in keep) or level_count!=capacity:
                    raise LiteError('SINGLE_ROW_EXISTING_ARRAY','窗口中已有阵列不满足可证明的最大单排；保留原物，请明确处理已有过孔后再生成。',reused_uids=keep,edit_applied=False)
            for array_index in range(1 if single else 4):
                if level_count >= min(args.max_cuts, capacity) and level_count >= minimum:
                    break
                found = False
                for candidate, count in candidates(args.max_cuts-level_count):
                    checkpoint()
                    trials += 1
                    if trials > 3000 or drc_checks >= 48:
                        if single:raise LiteError('SINGLE_ROW_SEARCH_LIMIT','搜索预算内未能证明最大合法单排；没有采用较少孔数或修改版图。',geometry_trials=trials,local_drc_checks=drc_checks,edit_applied=False)
                        break
                    geometry = footprints(candidate, p)
                    if single and not search_roi.covers(unary_union(list(geometry.values()))):continue
                    if occupied.intersects(geometry[cut_layer]):
                        continue
                    if not access.landing_ok(geometry, lower, upper):
                        continue
                    conflicts = access.conflicts(geometry)
                    if conflicts:
                        if len(reasons) < 8:
                            reasons.extend(conflicts[:2])
                        continue
                    test = Editor(staged.w, p, scope_id=staged.scope_id)
                    try:
                        uid = test.create(candidate)
                    except LiteError as exc:
                        if len(reasons) < 8:
                            reasons.append({'reason': exc.code})
                        continue
                    drc_checks += 1
                    valid, check = checked_candidate(
                        staged.w, test.w, p, rules, roi, geometry, baseline, checkpoint,scope_id=editor.scope_id
                    )
                    if not valid:
                        if len(reasons) < 8:
                            reasons.append(check)
                        continue
                    staged.publish(test.w)
                    created.append(uid)
                    level_ids.append(uid)
                    level_count += count
                    occupied = unary_union([occupied, geometry[cut_layer]])
                    selected_checks.append(check)
                    found = True
                    break
                if not found:
                    break
            if level_count < minimum:
                code = (
                    'AUTOVIA_SHORT_OR_UNKNOWN_CONTACT'
                    if any(
                        r['reason'] in ('other_net_contact', 'unknown_net_contact') for r in reasons
                    )
                    else 'AUTOVIA_NO_LEGAL_ARRAY'
                )
                raise LiteError(
                    code,
                    '未找到满足每级最少切孔数、局部空间及本地 DRC 的阵列；没有修改工作区。',
                    layer_pair=[lower, upper],
                    minimum_cuts=minimum,
                    landing_policy=args.landing_policy if args.allow_landing else 'existing_metal_only',
                    landing_reference={k:v for k,v in access.reference.items() if k!='geometry'} if access.reference else None,
                    fitting_bounds_um=[v/p.dbu_per_micron for v in fitting_window.bounds] if not fitting_window.is_empty else None,
                    diagnostics=reasons,
                    edit_applied=False,
                )
            levels.append(
                {
                    'definition': name,
                    **({'array_direction':args.array_direction,'maximal_on_grid':True,'geometric_capacity':capacity,
                        'parameter_policy':'native definition defaults; only cutRows/cutColumns vary',
                        'limiting_factors':['window/landing/grid/cut budget'] if level_count==capacity else ['larger counts exhaustively rejected by material, obstacles or configured local DRC']} if single else {}),
                    'layers': [lower, upper],
                    'cut_layer': cut_layer,
                    'cuts': level_count,
                    'created_uids': level_ids,
                    'reused_uids': keep,
                    'checks': selected_checks,
                }
            )
        checkpoint()
        final = scope_graph(staged.w, p, staged.scope_id)
        ids = set(created + reused)
        components = {node['component_id'] for node in final['nodes'] if node['owner_uid'] in ids}
        if len(components) != 1:
            raise LiteError(
                'AUTOVIA_NOT_CONNECTED',
                '各级过孔没有组成同一实际金属连接，结果未采用。',
                edit_applied=False,
            )
        cid = next(iter(components))
        pins = {pin['id']: pin for pin in final['pins']}
        known = {
            pins[pid]['net']
            for pid in final['component_pins'].get(cid, ())
            if pins[pid]['net'] is not None
        }
        if known - {args.net_intent}:
            raise LiteError('AUTOVIA_SHORT_DETECTED', nets=sorted(known), edit_applied=False)
        if not known and not generated:
            raise LiteError(
                'AUTOVIA_NET_UNRESOLVED',
                '完成的几何尚未接到可确认的目标网络；结果未采用。',
                edit_applied=False,
            )
        if args.targets:
            for target in args.targets:
                contacts = (
                    final['pin_components'].get(target)
                    if target in pins
                    else {
                        n['component_id']
                        for n in final['nodes']
                        if n['owner_uid'] == target and n['geometry'].intersects(roi)
                    }
                )
                if not contacts or cid not in contacts:
                    raise LiteError(
                        'AUTOVIA_TARGET_NOT_CONNECTED', target=target, edit_applied=False
                    )
    from .via_landing import report as landing_report
    return {
        **landing_report(access,editor,created,reused),
        'created_uids': created,
        'reused_uids': sorted(set(reused)),
        'levels': levels,
        'total_cuts': sum(level['cuts'] for level in levels),
        'net_intent': args.net_intent,
        'net_confirmed': known == {args.net_intent},
        'internal_connected': True,
        'landing_metals': 'native via enclosures only, bounded by bounds_um',
        'seconds': perf_counter() - began,
        'search': {
            'geometry_trials': trials,
            'local_drc_checks': drc_checks,
            'max_arrays_per_level': 1 if single else 4,
            'limited': trials > 3000 or drc_checks >= 48,
            'cut_budget_per_level': args.max_cuts,
            'method': 'descending counts with exhaustive grid origins; refuses unproven success at budget limit' if single else 'dense rectangular arrays; preserves existing arrays and tests remaining positions; not arbitrary-polygon optimality',
        },
        'constraints': reasons,
        **report_bounds(editor, created + reused),
    }

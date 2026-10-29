"""Authorized region DRC over the existing isolated Calibre worker and raw report."""
from collections import Counter
import re
from time import monotonic

from ..model import LiteError
from ..drc import jobs
from ..drc.models import Region
from ..drc import waivers
from ..regions.query import children, members
from .inspection import direct_ids

def authorized_region(workspace, profile, region_id, bounds_um=None):
    area = workspace.local_data.regions[region_id]
    roi = Region(bbox=area.bbox) if bounds_um is None else Region.from_um(bounds_um, profile.dbu_per_micron)
    (a, b), (c, d) = area.bbox
    (x, y), (xx, yy) = roi.bbox
    if not (a <= x < xx <= c and b <= y < yy <= d):
        raise LiteError('DRC_OUTSIDE_REGION', '检查范围必须完全位于已接入的操作区内。')
    return roi


def categories(marker):
    body = '\n'.join(line for line in marker.message.splitlines()
                     if not line.lower().startswith(('rule file pathname:', 'rule file title:')))
    text = (marker.rule_id + ' ' + body).casefold()
    result = []
    if 'border' in text:
        result.append('border')
    if 'density' in text:
        result.append('density')
    if re.search(r'seal[\s_-]*ring', text):
        result.append('seal_ring')
    return result


def report(raw, workspace, profile, region_id):
    scale = profile.dbu_per_micron
    direct = direct_ids(workspace, region_id)
    child_members = {child.id: members(workspace, child.id) for child in children(workspace, region_id)}
    def location(box):
        return [value / scale for point in box for value in point]
    markers = []
    for marker in raw.markers:
        candidates = []
        hidden_count = 0
        for obj in marker.objects:
            uid = obj.get('uid')
            if uid in direct:
                candidates.append({'uid': uid, 'name': obj.get('name'),
                                   'kind': obj.get('kind'), 'inside_native_instance': bool(obj.get('inside_instance')),
                                   'edit_scope': 'whole_instance_only' if obj.get('inside_instance') or obj.get('kind') in ('inst', 'mosaic') else 'whole_mpp_only' if obj.get('inside_mpp') else 'direct_object',
                                   'read_only_reason': obj.get('read_only_reason'),
                                   'association': marker.association})
            else:
                child = next((cid for cid, ids in child_members.items() if uid in ids), None)
                if child:
                    candidate = {'uid': child, 'name': workspace.local_data.regions[child].name,
                                 'kind': 'local_module', 'edit_scope': 'whole_child_module_only',
                                 'association': 'geometric_candidate_in_child'}
                    if candidate not in candidates:
                        candidates.append(candidate)
                else:
                    hidden_count += 1
        markers.append({'id': marker.id, 'rule_id': marker.rule_id, 'description': marker.message,
                        'severity': marker.severity, 'layers': list(marker.layers),
                        'bbox_um': location(marker.bbox),
                        'geometry': {'kind': marker.kind,
                                     'points_um': [[x / scale, y / scale] for x, y in marker.points],
                                     'edges_um': [[value / scale for value in edge] for edge in marker.edges]},
                        'required_um': marker.required_um, 'measured_um': marker.measured_um,
                        'object_candidates': candidates, 'outside_scope_candidate_count': hidden_count,
                        'suppression_categories': categories(marker),
                        'guidance': '按规则说明和标记坐标核对几何候选；候选关联不证明错误归属。原生实例内部或子模块内部问题需交给人处理。'})
    coverage = dict(raw.coverage)
    passed=waivers.assessment(raw)['passed']
    return {'engine': 'calibre', 'coordinates': 'workspace_absolute_um', 'axis': 'x_right_y_up',
            'completion_eligible':raw.region.bbox==workspace.local_data.regions[region_id].bbox,
            'check_scope':'region' if raw.region.bbox==workspace.local_data.regions[region_id].bbox else 'roi',
            'region_id': region_id, 'bounds_um': location(raw.region.bbox),
            'source_revision': workspace.revision, 'passed': passed,
            'engine_status':raw.status,'technology_fingerprint':raw.technology_fingerprint,
            'configuration_id':raw.configuration_id,
            'checked_snapshot': 'current_local_layout_in_private_server_copy',
            'source_layout_modified': False,
            'coverage': coverage, 'markers': markers,
            'note': '执行已配置主规则文件的全部启用规则；人端工艺过滤设置统一用于 UI、API 和区域完成验收。原始报告保留；区域检查不代表整芯片或 LVS 签核。'}


def filtered_report(result, excluded=None, offset=0, limit=100, *, include_waived=False):
    # Legacy [] means show all; nonempty category lists no longer grant waivers.
    include_waived=include_waived or excluded==[]
    fingerprint=result.get('technology_fingerprint')
    if not fingerprint:raise LiteError('DRC_REPORT_POLICY_CONTEXT_MISSING','旧报告缺少工艺身份，请重新运行检查。')
    policy=waivers.load(fingerprint,result.get('configuration_id'))
    decision=waivers.assess(((m['id'],m['rule_id'],m['description']) for m in result['markers']),
                           policy,result['engine'],result['coverage'],result.get('engine_status','unknown'))
    waived=decision['waived_markers'];visible=[]
    counts=Counter();rules=Counter();reasons=Counter()
    for marker in result['markers']:
        matches=waived.get(marker['id'],[])
        if matches:
            counts.update(marker['suppression_categories']);rules[marker['rule_id']]+=1;reasons.update(matches)
        if include_waived or not matches:
            visible.append(marker)
    page=[{**m,'waived':m['id'] in waived,'waiver_reasons':waived.get(m['id'],[])} for m in visible[offset:offset+limit]]
    return {**result,
            'passed':decision['passed'],'coverage_complete':decision['coverage_complete'],
            'raw_marker_count':decision['total_count'],'active_marker_count':decision['active_count'],
            'suppressed_marker_count':decision['waived_count'],'markers':page,
            'suppressed_by_category':dict(counts),'suppressed_by_rule':dict(rules),'suppressed_by_reason':dict(reasons),
            'report_policy':policy.model_dump(mode='json'),'report_policy_digest':waivers.digest(policy.model_dump()),
            'include_waived':include_waived,'display_marker_count':len(visible),
            'offset': offset, 'limit': limit, 'has_more': offset + limit < len(visible),
            'next_offset': offset + limit if offset + limit < len(visible) else None}


def run(job, roi, progress, *, result_limit=None):
    """The existing DRC process owns native I/O; cancellation waits for its exit."""
    if job.cancelled.is_set():
        raise LiteError('DRC_CANCELLED')
    options={'result_limit':result_limit} if result_limit is not None else {}
    try:
        state = jobs.start(job.source, job.profile, job.rules, roi, 'calibre', scope_id=job.lease.region_id,**options)
    except LiteError as exc:
        raise LiteError(exc.code,str(exc),**{**exc.details,'public_job_id':getattr(job,'id',None)}) from exc
    native_id = state['job_id']
    terminal = [False]
    try:
        return collect(job, native_id, progress, terminal)
    except (LiteError, OSError) as exc:
        details = dict(getattr(exc, 'details', {}))
        details.update(native_job_id=native_id, public_job_id=getattr(job, 'id', None))
        details.setdefault('drc_completed', None)
        details.setdefault('result_available', None)
        details.setdefault('stage', 'job_monitor')
        if isinstance(exc, OSError):
            details.setdefault('failure_kind', 'job_monitor')
        details.setdefault('next_action', 'contact_maintenance')
        details.setdefault('guidance', '本次未取得检查结论；请携带任务 ID 联系维护人员，勿把任务失败当作工艺违规。')
        details['cancellation_requested'] = not terminal[0]
        raise LiteError(getattr(exc, 'code', 'SERVER_DRC_MONITOR_FAILED'), str(exc), **details) from exc
    finally:
        if not terminal[0]:
            # Journal/readback failure must not leave an unobserved server task running.
            try:
                jobs.cancel(native_id)
            except (OSError, LiteError):
                pass


def collect(job, native_id, progress, terminal):
    from ..drc.job_storage import write_json
    write_json(job.folder / 'server-job.json', {'server_job_id': native_id, 'public_job_id':getattr(job,'id',None)})
    cancel_sent = False
    deadline = monotonic() + job.rules.remote.timeout_seconds * 3 + 90
    while True:
        if (job.cancelled.is_set() or monotonic() > deadline) and not cancel_sent:
            jobs.cancel(native_id)
            cancel_sent = True
        state = jobs.status(native_id)
        progress(state.get('message', '服务器全规则 DRC 正在运行…'))
        if state['status'] in ('completed', 'failed', 'cancelled'):
            terminal[0] = True
            break
        # A set Event returns immediately; use a bounded ordinary wait after cancellation.
        from time import sleep
        sleep(.25)
    if job.cancelled.is_set() or state['status'] == 'cancelled':
        raise LiteError('DRC_CANCELLED')
    if cancel_sent:
        raise LiteError('DRC_JOB_TIMEOUT')
    if state['status'] != 'completed':
        cause=state.get('error',{})
        raise LiteError('SERVER_DRC_FAILED',state.get('message','服务器检查失败'),
            **{'stage':state.get('stage','unknown'), 'drc_completed':state.get('drc_completed'),
               'result_available':state.get('result_available',False), **cause.get('details',{}),
               'cause_code':cause.get('code','SERVER_DRC_FAILED'),'native_job_id':native_id})
    raw = jobs.result(native_id)
    if raw.document_id != job.source.id or raw.document_revision != job.source.revision:
        raise LiteError('DRC_RESULT_SNAPSHOT_MISMATCH')
    return report(raw, job.source, job.profile, job.lease.region_id)

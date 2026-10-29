"""Native preparation failures with level-safe ownership and retry guidance."""

from ..regions.query import owner_map
from ..editor import projected


def native_failure(exc, source, region_id, kind):
    code = getattr(exc, 'code', 'JOB_FAILED')
    details = dict(getattr(exc, 'details', {}))
    if details.get('failure_kind') in ('job_storage', 'worker_exit', 'job_monitor') or details.get('drc_completed') is True:
        return {'code': code, 'message': str(exc), 'details': details}
    cause = details.get('cause_code', code)
    relevant = cause.startswith(
        ('READBACK_', 'PRIVATE_COPY_', 'DRC_SNAPSHOT_', 'SOURCE_', 'NATIVE_', 'SERVER_DRC_')
    )
    if not relevant or source is None:
        return {'code': code, 'message': str(exc), 'details': details}
    ids = details.get('objects', [])
    if details.get('uid'):
        ids = [*ids, details['uid']]
    owners = owner_map(source)
    objects = projected(source)
    visible = []
    outside = 0
    regions = {}
    for value in ids:
        uid = value.get('uid') if isinstance(value, dict) else value
        if not isinstance(uid, str):
            continue
        owner = owners.get(uid)
        if owner == region_id and uid in objects:
            visible.append({'uid': uid, 'kind': objects[uid].kind, 'region_id': owner})
        else:
            outside += 1
            row = source.local_data.regions.get(owner)
            if row and row.parent_id == region_id:
                regions[row.id] = {'region_id': row.id, 'name': row.name}
    stage = details.get('stage') or (
        'readback'
        if cause.startswith('READBACK_')
        else 'private_copy'
        if cause.startswith('PRIVATE_COPY_')
        else 'source_verification'
        if cause.startswith('SOURCE_')
        else 'snapshot_preparation'
    )
    message = str(exc)
    if outside:
        message = '服务器快照准备失败，涉及本区之外的对象；请交由上级 Agent 或用户定位。没有完成本次检查或采用本次编辑。'
        # Raw diagnostic details remain in the native job/audit evidence. A child
        # sees neither sibling object IDs nor its geometry or private file paths.
        details = {
            key: details[key] for key in ('native_job_id', 'public_job_id', 'operation_index') if key in details
        }
    details.update(
        cause_code=cause,
        stage=stage,
        objects=visible,
        outside_object_count=outside,
        visible_origin_regions=list(regions.values()),
        failure_kind='outside_region_dependency' if outside else 'native_preparation',
        edit_applied=False,
        drc_completed=False,
        retryable=False,
        next_action='先协调处理区外对象，再重新申请；不要反复更换本区保护环参数。'
        if outside
        else '先处理所列输入/快照问题；本次不是 DRC 违规结论。',
    )
    return {'code': code, 'message': message, 'details': details}

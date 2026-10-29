"""Frozen slow edits, adopted only on the owner thread and exact revision."""

from threading import Event
from uuid import uuid4
from ..editor import Editor
from ..model import LiteError
from ..layout_helpers.contracts import MODELS
from .jobs import Job, TERMINAL


def invoke(session, lease, args):
    registry = session.tasks
    e = lease.editor
    if args.mode in ('status', 'cancel'):
        if args.operations:
            raise LiteError('INVALID_ARGUMENTS', 'status/cancel 不接受 operations。')
        job = registry.get(lease, args.job_id, 'edit')
        if args.mode == 'cancel' and job.state not in TERMINAL:
            registry.cancel(job)
        return registry.status(job)
    batch=len(args.operations)>1 and len(args.operations)<=32 and all(op.action=='create_auto_vias' for op in args.operations)
    if args.mode != 'apply' or len(args.operations) != 1 and not batch:
        raise LiteError('SLOW_EDIT_MUST_BE_ALONE', '保护环/跨层路径须单项提交；自动打孔可一次提交最多 32 个独立位置，整批原子采用。')
    operation = args.operations[0]
    for op in args.operations:
        if op.uid is not None:raise LiteError('CREATE_UID_ASSIGNED_BY_APP')
        MODELS[op.action].model_validate(op.params)
    values = MODELS[operation.action].model_validate(operation.params)
    if operation.action == 'create_guard' and not session.remote_enabled():
        raise LiteError('NATIVE_GUARD_UNAVAILABLE')
    with session.actor(lease, args.expected_revision):
        source = e.w
        profile = e.profile
        rules = session.drc_source()
        if operation.action == 'create_guard':
            from ..layout_helpers.guard import templates

            if values.template_id not in {r['id'] for r in templates(profile)}:
                raise LiteError('UNKNOWN_GUARD_TEMPLATE', '请先查询 rules.guard_templates。')
        ident = uuid4().hex
        folder = session.folder / 'jobs' / ident
        job = Job(ident, lease, 'edit', source, profile, rules, folder, Event())

    def compute():
        if job.cancelled.is_set():
            raise LiteError('EDIT_CANCELLED', '工作区未修改。')
        registry.progress(job, '正在生成；尚未修改工作区。')
        if operation.action == 'create_guard':
            from ..adapter import Adapter
            from ..transport import NativeTransport
            from ..layout_helpers.guard import prepare

            from ..native_lane import channel
            with channel(source.connection_config,cancelled=job.cancelled.is_set,
                         progress=lambda message:registry.progress(job,message)):
                return prepare(source,profile,lease.region_id,values,rules,
                    Adapter(NativeTransport(source.connection_config)),lambda message:registry.progress(job,message))
        from ..layout_helpers.service import execute

        staged = Editor(source, profile, scope_id=lease.region_id)
        results=[]
        for index,op in enumerate(args.operations):
            registry.progress(job,f'正在生成第 {index+1}/{len(args.operations)} 项；整批尚未采用。')
            try:result=execute(staged,op.action,op.params,rules=rules,cancelled=job.cancelled)
            except LiteError as exc:
                exc.details.update(operation_index=index,edit_applied=False,batch_atomic=True,
                                   prepared_not_applied=[{'index':i,'result':r} for i,r in enumerate(results)])
                raise
            results.append(result)
        if batch:
            from ..layout_helpers.via_batch import verify
            verification=verify(source,staged,values= [MODELS[op.action].model_validate(op.params) for op in args.operations],rules=rules,cancelled=job.cancelled)
            result={'created_uids':[u for row in results for u in row['created_uids']],
                    'reused_uids':sorted({u for row in results for u in row.get('reused_uids',[])}),
                    'operations':[{'index':i,'action':'create_auto_vias',**row} for i,row in enumerate(results)],
                    'batch_atomic':True,'batch_check':verification}
        return staged.w, result

    def adopt(value):
        from .edit_adoption import adopt_edit
        candidate,result=value
        return adopt_edit(session,lease,job,source,candidate,result,
                          stale_message='版图、配置或接入已改变，生成结果未采用。')

    job.adopt = adopt
    return {
        **registry.submit(job, compute),
        'edit_applied': False,
        'next': {'tool': 'edit_region', 'mode': 'status', 'job_id': ident},
    }

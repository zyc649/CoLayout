"""Owner-thread API dispatch over shared region leases, edits and background tasks."""

from pathlib import Path
from threading import get_ident
from time import monotonic
from uuid import uuid4
from pydantic import ValidationError
from ..model import LiteError, digest
from .contract import TOOLS, describe_tools
from .audit import Audit
from .leases import RegionLeases
from .jobs import JobRegistry
from .region_tasks import RegionTasks
from .region_edits import edit_region
from .events import CallIdentity
from . import inspection


class AgentSession:
    def __init__(self, editor, drc, folder, *, save=None, capture=None, busy=lambda: False,
                 references=None, remote_enabled=lambda: True, workspace_files=None, process_configuration=None):
        self.editor_source = editor if callable(editor) else lambda: editor
        self.drc_source = drc if callable(drc) else lambda: drc
        self.folder = Path(folder)
        self.audit = Audit(self.folder)
        self.save = save or (lambda: None)
        self.busy = busy
        from ..reference_cases import ReferenceCases
        self.references = references if references is not None else ReferenceCases()
        self.remote_enabled = remote_enabled
        self.workspace_files = workspace_files
        self.process_configuration = process_configuration
        self.thread = get_ident()
        self.closed = False
        self.audit_failure = None
        self.ownership = RegionLeases(self.editor_source, busy)
        self.tasks = JobRegistry(self.editor_source, self.drc_source, self.audit)
        self.operations = RegionTasks(
            self.tasks, self.ownership, folder, busy=busy, saved=self.saved, capture=capture
        )
        self.leases = self.ownership.leases
        self.jobs = self.tasks.jobs
        self.reads = None

    @property
    def editor(self):
        return self.editor_source()

    def on_thread(self):
        if get_ident() != self.thread:
            raise LiteError('EDITOR_THREAD_REQUIRED')

    def invoke_async(self,tool,args,**kwargs):
        return self.invoke(tool,args,_defer_read=True,**kwargs)

    def invoke(self, tool, args, *, client_id='human-test', request_id=None, source='panel',_defer_read=False):
        self.on_thread()
        self.audit_failure = self.audit_failure or self.tasks.audit_failure
        request_id = request_id or uuid4().hex
        began = monotonic()
        key = digest([client_id, request_id])
        if self.closed:
            return {'ok': False, 'error': {'code': 'APP_CLOSED', 'message': 'APP 已关闭。'}}
        if self.audit_failure:
            return {
                'ok': False,
                'error': {
                    'code': 'AUDIT_UNAVAILABLE',
                    'message': '调用日志不可写，接口已暂停；请在人端核对工作区。',
                },
                'request_id': request_id,
            }
        owner = self.leases.get(args.get('session_token')) if isinstance(args, dict) else None
        if owner is None:
            owner = next((item for item in self.leases.values()
                          if item.client_id == client_id and item.editor is self.editor), None)
        context_editor = owner.editor if owner and owner.client_id == client_id else self.editor
        context = {
            **CallIdentity(client_id, request_id, source).fields(),
            'document_id': context_editor.w.id if context_editor else '',
            'region_id': args.get('region_id', '') if tool == 'claim_region' and isinstance(args, dict) else '',
            **(
                {'region_id': owner.region_id, 'agent_name': owner.owner}
                if owner and owner.client_id == client_id
                else {}
            ),
        }
        try:
            prior = self.audit.begin(key, tool, args, source, context)
        except Exception as exc:
            return {
                'ok': False,
                'error': {'code': getattr(exc, 'code', 'AUDIT_ERROR'), 'message': str(exc)},
                'request_id': request_id,
            }
        if prior is not None:
            return prior
        try:
            if tool == 'tools':
                from .discovery import select_tools
                result = {'schema_version': 'colayout-agent-api-2', 'tools': select_tools(describe_tools(),args)}
            else:
                if tool not in TOOLS:
                    raise LiteError('UNKNOWN_TOOL', '只支持 Agent API v2 的区域工具。')
                value = TOOLS[tool][0].model_validate(args)
                if tool == 'claim_region':
                    result = self.claim(value, client_id)
                elif tool == 'reference_cases':
                    result = self.reference_cases(value)
                elif tool == 'workspace':
                    if self.workspace_files is None:
                        raise LiteError('WORKSPACE_FILES_UNAVAILABLE','此宿主没有提供工作区文件服务。')
                    if value.action=='load' and any(j.future and not j.future.done() for j in self.jobs.values()):
                        raise LiteError('WORKSPACE_BUSY','后台任务尚未结束，不能切换文档。')
                    result = self.workspace_files.invoke(value)
                elif tool == 'process_configuration':
                    if self.process_configuration is None:raise LiteError('PROCESS_CONFIGURATION_UNAVAILABLE')
                    from ..process_api import invoke
                    result=invoke(self.process_configuration,value,client_id,request_id)
                else:
                    lease = self.lease(value.session_token, client_id)
                    if _defer_read and (tool=='capture_region' or tool=='inspect_region' and value.kind=='net'):
                        return self.defer_read(tool,value,lease,key,request_id,client_id,began)
                    result = getattr(self, tool)(lease, value)
            response = {
                'schema_version': 'colayout-agent-response-2',
                'ok': True,
                'result': result,
                'revision': self.editor.w.revision if self.editor else None,
                'request_id': request_id,
            }
        except Exception as exc:
            response = {
                'schema_version': 'colayout-agent-response-2',
                'ok': False,
                'error': {
                    'code': getattr(
                        exc,
                        'code',
                        'INVALID_ARGUMENTS' if isinstance(exc, ValidationError) else 'API_ERROR',
                    ),
                    'message': str(exc),
                    'details': getattr(exc, 'details', {}),
                },
                'revision': self.editor.w.revision if self.editor else None,
                'request_id': request_id,
            }
        return self.finish_response(key,response,began,client_id,request_id)

    def finish_response(self,key,response,began,client_id,request_id):
        self.on_thread()
        try:
            for active in self.leases.values():
                if active.client_id==client_id and active.editor is self.editor:self.ownership.observe(active)
            self.audit.finish(key, response, monotonic() - began)
        except Exception as exc:
            self.audit_failure = str(exc)
            return {
                'ok': False,
                'error': {
                    'code': 'OUTCOME_UNKNOWN',
                    'message': '操作可能已经执行，但日志写入失败；请在人端核对，不要换 request_id 重试。',
                },
                'revision': self.editor.w.revision if self.editor else None,
                'request_id': request_id,
            }
        return response

    def defer_read(self,tool,args,lease,key,request_id,client_id,began):
        from .read_pool import ReadPool,DeferredResponse,read_stamp
        source=lease.editor.w;profile=lease.editor.profile
        stamp=read_stamp(source,profile,lease.region_id,tool)
        workspace=self.operations.capture_workspace(lease,args) if tool=='capture_region' else source
        if self.reads is None:self.reads=ReadPool(self.folder/'read-workers')
        future=self.reads.submit(workspace,profile,lease.region_id,tool,args)
        def finish():
            self.on_thread()
            if self.closed:return {'ok':False,'error':{'code':'APP_CLOSED','message':'APP 已关闭。'},'request_id':request_id}
            try:
                active=self.lease(lease.token,client_id)
                if (active.editor.profile is not profile or active.editor.w.baseline is not source.baseline
                        or read_stamp(active.editor.w,profile,lease.region_id,tool)!=stamp):
                    raise LiteError('READ_SNAPSHOT_STALE','查询期间本操作区已改变，请重新读取。',retryable=True,new_read_request=True,source_revision=source.revision)
                data=future.result()
                if not data.get('ok'):
                    error=data['error'];raise LiteError(error['code'],error['message'],**error.get('details',{}))
                result={**data['result'],'current':True,'source_revision':source.revision}
                response={'schema_version':'colayout-agent-response-2','ok':True,'result':result,
                    'revision':active.editor.w.revision,'request_id':request_id}
            except Exception as exc:
                response={'schema_version':'colayout-agent-response-2','ok':False,
                    'error':{'code':getattr(exc,'code','READ_WORKER_FAILED'),'message':str(exc),'details':getattr(exc,'details',{})},
                    'revision':self.editor.w.revision if self.editor else None,'request_id':request_id}
            return self.finish_response(key,response,began,client_id,request_id)
        return DeferredResponse(future,finish)

    def inspect_region(self, lease, args):
        if args.kind=='net':return inspection.net_request(lease.editor.w,lease.editor.profile,lease.region_id,args)
        if args.kind=='terminals':
            from .terminal_query import query
            return query(lease.editor.w,lease.editor.profile,lease.region_id,args.instance_name,args.terminal,args.name_source)
        if args.markup_id:
            from .markup_query import resolve
            location=resolve(lease.editor.w,lease.editor.profile,lease.region_id,args.markup_id,args.padding_um,args.clip_to_region)
            result=self._inspect_region(lease,args.model_copy(update={'bounds_um':tuple(location['bounds_um'])}))
            result['location']=location
            return result
        return self._inspect_region(lease,args)

    def _inspect_region(self, lease, args):
        e = lease.editor
        rid = lease.region_id
        if args.parameter_names is not None and args.kind!='reference':
            raise LiteError('INVALID_ARGUMENTS','parameter_names 仅用于 reference 查询。')
        if args.kind == 'reference':
            if args.pin_ids is not None or args.bounds_um is not None or args.layers is not None or args.target or args.include_members or args.net is not None:
                raise LiteError('INVALID_ARGUMENTS','reference 支持 detail/uids/parameter_names，不接收版图范围、PIN 或物理分量参数。')
            return inspection.reference(e.w,rid,detail=args.detail,uids=args.uids,parameter_names=args.parameter_names,profile=e.profile)
        if args.kind == 'layout':
            if args.net is not None or args.target is not None or args.include_members:raise LiteError('INVALID_ARGUMENTS','net/target/include_members 仅用于 net 查询。')
            result=inspection.layout(e.w, e.profile, rid, detail=args.detail, uids=args.uids, pin_ids=args.pin_ids,bounds_um=args.bounds_um,layers=args.layers)
            for child in result['children']:
                active=e.work_sessions.for_region(child['uid'])
                child['occupancy']={'claimed':bool(active),'owner':active.owner if active else None}
            return result
        if args.detail != 'full' or args.uids is not None or args.pin_ids is not None:
            raise LiteError('INVALID_ARGUMENTS', 'detail/uids/pin_ids 仅用于 layout 查询。')
        if args.kind == 'rules':
            if args.bounds_um is not None or args.layers is not None or args.target or args.include_members or args.net is not None:raise LiteError('INVALID_ARGUMENTS','范围、图层和分量参数不用于 rules。')
            return inspection.rules(e.profile, self.drc_source())
        return inspection.net(e.w, e.profile, rid, args.net,target=args.target,include_members=args.include_members,bounds_um=args.bounds_um,layers=args.layers)

    def saved(self, result):
        try:
            self.save()
        except Exception as exc:
            result['save_warning'] = '本地编辑已执行，但保存失败：' + str(exc)
        return result

    def release_region(self, lease, args):
        from .release_status import verification
        check=verification(self,lease)
        if args.outcome == 'done':
            if check['state']!='passed':
                raise LiteError('REGION_NOT_VERIFIED', '完成需当前全区连通性、本地检查及服务器检查证据。'+check['next_action'],verification=check,edit_applied=False)
        self.release(lease)
        if args.outcome=='handoff':
            return {'released':True,'outcome':'handoff','edits_preserved':True,'verification':check,
                    'overall_verified':False,'note':args.note,'message':'本阶段已交接，修改保留、权限已交还；尚不代表版图整体通过验收。'}
        return {'released': True, 'outcome': args.outcome,'verification':check}

    def revoke(self, token):
        self.on_thread()
        lease = self.leases.get(token)
        if lease:
            try:
                self.audit.emit(
                    {'event': 'human_release', 'region_id': lease.region_id, 'owner': lease.owner,
                     'document_id': lease.editor.w.id}
                )
            finally:
                self.release(lease)

    def lease(self, token, client_id):
        return self.ownership.lease(token, client_id)

    def actor(self, lease, expected_revision):
        return self.ownership.actor(lease, expected_revision)

    def claim(self, value, client_id):
        return self.ownership.claim(value, client_id)

    def edit_region(self, lease, args):
        if self.busy():
            raise LiteError('WORKSPACE_BUSY')
        if args.mode not in ('status','cancel'):
            self.tasks.poll()
            if any(j.lease is lease and j.kind=='edit' and j.state in ('queued','running') for j in self.jobs.values()):
                raise LiteError('REGION_JOB_RUNNING','生成编辑尚未完成，请等待或取消。')
        from ..layout_helpers.contracts import SLOW_ACTIONS
        if args.mode in ('status','cancel') or any(op.action in SLOW_ACTIONS for op in args.operations):
            from .edit_tasks import invoke
            return invoke(self,lease,args)
        from .batch_edits import eligible, submit
        if eligible(args):
            return submit(self,lease,args)
        before=lease.editor.w
        result=edit_region(lease,args,actor=self.actor)
        result['edit_applied']=lease.editor.w is not before
        return self.saved(result)

    def route_region(self, lease, args):
        return self.operations.route_region(lease, args)

    def check_region(self, lease, args):
        return self.operations.check_region(lease, args)

    def capture_region(self, lease, args):
        return self.operations.capture_region(lease, args)

    def reference_cases(self, args):
        if args.action == 'list':
            return self.references.list(args.query, args.offset, args.limit)
        return self.references.inspect(args.case_id, 'preview' if args.action == 'preview' else args.kind,
                                       args.offset, args.limit)

    def server_drc_region(self, lease, args):
        if not self.remote_enabled():
            raise LiteError('REMOTE_DRC_UNAVAILABLE', '当前APP窗口不允许访问服务器。')
        return self.operations.server_drc_region(lease, args)

    def current(self, job):
        return self.tasks.current(job)

    def job(self, lease, ident, kind=None):
        return self.tasks.get(lease, ident, kind)

    def poll(self, job=None):
        self.on_thread()
        if self.audit_failure:
            return
        self.tasks.poll(job)
        self.audit_failure = self.tasks.audit_failure

    def release(self, lease):
        self.tasks.release(lease)
        self.ownership.release(lease)

    def close(self):
        if self.closed:
            return
        self.on_thread()
        try:
            self.audit.emit(
                {
                    'event': 'app_closed',
                    'leases': [
                        {'region_id': l.region_id, 'owner': l.owner} for l in self.leases.values()
                    ],
                }
            )
        except OSError:
            pass
        for lease in list(self.leases.values()):
            self.release(lease)
        self.closed = True
        if self.reads:self.reads.close()
        self.tasks.close()
        self.audit.close()

"""Shared local routing use case. GUI/future Agent adapters use these same calls.

generate() may run on a host thread; it only manages worker processes and logs.
apply() must run on the Editor owner thread, and publishes exactly one history step.
"""
from dataclasses import dataclass
from pathlib import Path
from threading import Event,Lock
from uuid import uuid4
from ..model import LiteError,digest
from ..document import save_document
from ..transactions import write_json_atomic
from ..editor import Editor
from ..local_models import RoutingRecord
from .models import RoutingProblem,Proposal
from .validation import checked_operations
from . import runner
from .plugins import descriptor


@dataclass(frozen=True)
class Candidate:
    id: str
    proposal: Proposal
    validation: dict
    sources: tuple[dict,...]


class RoutingSession:
    def __init__(self,editor,drc,region_id,folder,*,layers=None):
        editor.work_sessions._on_thread()
        editor.check_revision(editor.w.revision)
        reason=editor.work_sessions.readonly_reason(scope_id=region_id)
        if reason:raise LiteError('REGION_WORKING',reason)
        if region_id not in editor.w.local_data.regions:raise LiteError('ROUTING_REGION_REQUIRED')
        drc.check_technology(editor.profile)
        self.editor=editor;self.source=editor.w;self.technology=editor.profile;self.drc=drc;self.region_id=region_id
        self.id=uuid4().hex;self.folder=Path(folder).resolve()/self.id;self.folder.mkdir(parents=True)
        self.selected_layers=tuple(layers) if layers is not None else None
        self.cancelled=Event();self.candidates={};self.problem=None;self.failures=[];self.applied=False
        self._started=False;self._start_lock=Lock()
        self.technology_digest=digest(self.technology.model_dump(mode='json'));self.drc_digest=drc.fingerprint()
        from ..scope_state import fingerprint
        self.scope_fingerprint=fingerprint(self.source,region_id)
        self.document=self.folder/'source.colayout.json';save_document(self.document,self.source,self.technology)
        self.request=self.folder/'request.json'
        write_json_atomic(self.request,{'document':str(self.document),'region_id':region_id,'request_id':self.id,'drc':drc.model_dump(mode='json'),'layers':self.selected_layers})

    def current(self,editor,drc):
        from ..scope_state import fingerprint
        return (not self.applied and editor is self.editor and fingerprint(editor.w,self.region_id)==self.scope_fingerprint
                and digest(editor.profile.model_dump(mode='json'))==self.technology_digest
                and drc is not None and drc.fingerprint()==self.drc_digest)

    def generate(self,algorithms,progress=lambda text:None):
        with self._start_lock:
            if self._started:raise LiteError('ROUTING_JOB_ALREADY_STARTED','重新生成需要创建新的 RoutingSession。')
            self._started=True
        self.candidates={};self.failures=[]
        try:
            progress('准备：读取当前层端口、障碍和工艺规则…')
            raw=runner.host('prepare',self.request,self.folder/'problem.json',self.folder/'prepare.log',self.cancelled)
            self.problem=RoutingProblem.model_validate(raw)
            immutable={path:path.read_bytes() for path in (self.document,self.request,self.folder/'problem.json')}
            fingerprints={}
            for index,algorithm in enumerate(algorithms):
                if self.cancelled.is_set():raise LiteError('ROUTING_CANCELLED')
                path=self.folder/f'algorithm-{index}';path.mkdir()
                provenance={key:algorithm[key] for key in ('id','name','version','digest','builtin')}
                try:
                    progress(f'算法 {index+1}/{len(algorithms)} · '+algorithm['name']+'：生成候选…')
                    if algorithm['builtin']:
                        runner.host('builtin',self.folder/'problem.json',path/'output.json',path/'run.log',self.cancelled,
                                    timeout=algorithm['timeout_seconds'],algorithm=algorithm['id'])
                    else:
                        fresh=descriptor(algorithm['manifest_path'])
                        if fresh['digest']!=algorithm['digest']:raise LiteError('PLUGIN_CHANGED','插件文件已修改，请重新选择算法。')
                        runner.run([runner.python_executable(),'-X','utf8',algorithm['entry_path'],
                            '--input',str(self.folder/'problem.json'),'--output',str(path/'output.json')],
                            path/'output.json',path/'run.log',self.cancelled,algorithm['timeout_seconds'],cwd=Path(algorithm['entry_path']).parent)
                    if any(path.read_bytes()!=value for path,value in immutable.items()):
                        raise LiteError('PLUGIN_MODIFIED_INPUT','插件修改了只读请求文件，已拒绝结果。')
                    progress(f'算法 {index+1}/{len(algorithms)} · '+algorithm['name']+'：检查连通与本地 DRC…')
                    checked=runner.host('validate',path/'output.json',path/'checked.json',path/'check.log',self.cancelled,
                        source=self.request,problem=self.folder/'problem.json')
                    for row in checked['candidates']:
                        proposal=Proposal.model_validate(row['proposal']);validation=row['validation']
                        source={**provenance,'variant':proposal.title,'parameters':proposal.parameters,
                            'routing_layers':[r.name for r in self.problem.layers],
                            'via_definitions':[v.name for v in self.problem.via_rules]}
                        fingerprint=validation.get('geometry_fingerprint')
                        existing=fingerprints.get(fingerprint) if fingerprint else None
                        if existing:
                            prior=self.candidates[existing]
                            self.candidates[existing]=Candidate(prior.id,prior.proposal,prior.validation,prior.sources+(source,))
                        else:
                            ident='route-'+uuid4().hex
                            self.candidates[ident]=Candidate(ident,proposal,validation,(source,))
                            if fingerprint:fingerprints[fingerprint]=ident
                except Exception as exc:
                    if self.cancelled.is_set():raise
                    self.failures.append({'algorithm':provenance,'code':getattr(exc,'code','ALGORITHM_FAILED'),'message':str(exc),'details':getattr(exc,'details',{})})
                finally:
                    # Keep other selected algorithms independent after a buggy
                    # plugin overwrites or removes its input snapshot.
                    for source,value in immutable.items():
                        if not source.exists() or source.read_bytes()!=value:source.write_bytes(value)
            self.save_report();return list(self.candidates.values())
        except Exception as exc:
            self.failures.append({'code':getattr(exc,'code','ROUTING_FAILED'),'message':str(exc),'details':getattr(exc,'details',{})})
            self.save_report();raise

    def save_report(self):
        write_json_atomic(self.folder/'report.json',{'id':self.id,'region_id':self.region_id,'source_revision':self.source.revision,
            'cancelled':self.cancelled.is_set(),'failures':self.failures,'candidates':[
                {'id':c.id,'sources':c.sources,'proposal':c.proposal.model_dump(mode='json'),'validation':c.validation} for c in self.candidates.values()]})

    def recheck(self,candidate,progress=lambda message:None):
        """Revalidate a saved proposal against this newly frozen workspace.

        No plugin rerun and no edits. Caller constructs this session on the
        editor thread, dispatches here, then uses the normal guarded apply().
        """
        with self._start_lock:
            if self._started:raise LiteError('ROUTING_JOB_ALREADY_STARTED')
            self._started=True
        try:
            progress('重新读取当前版图、端口和障碍…')
            self.problem=RoutingProblem.model_validate(runner.host('prepare',self.request,self.folder/'problem.json',self.folder/'prepare.log',self.cancelled))
            from .models import PluginResult
            path=self.folder/'recheck-input.json'
            write_json_atomic(path,PluginResult(request_id=self.problem.request_id,source_digest=self.problem.source_digest,
                candidates=(candidate.proposal,)).model_dump(mode='json'))
            progress('对当前版图重新检查连通性与本地 DRC…')
            checked=runner.host('validate',path,self.folder/'rechecked.json',self.folder/'recheck.log',self.cancelled,
                source=self.request,problem=self.folder/'problem.json')
            row=checked['candidates'][0]
            self.candidates={candidate.id:Candidate(candidate.id,Proposal.model_validate(row['proposal']),row['validation'],candidate.sources)}
            self.save_report();return list(self.candidates.values())
        except Exception as exc:
            self.failures.append({'code':getattr(exc,'code','ROUTING_FAILED'),'message':str(exc),'details':getattr(exc,'details',{})})
            self.save_report();raise

    def apply(self,editor,candidate_id,drc):
        editor.work_sessions._on_thread()
        if self.cancelled.is_set():raise LiteError('ROUTING_CANCELLED')
        if not self.current(editor,drc):raise LiteError('ROUTING_STALE','工作区或规则已改变，请重新生成。')
        if self.problem is None or digest(self.source.model_dump(mode='json'))!=self.problem.source_digest:
            raise LiteError('ROUTING_STALE','工作区内容与已验证快照不一致。')
        if editor.scope_id!=self.region_id:raise LiteError('ROUTING_SCOPE_CHANGED','请返回生成方案的操作区。')
        editor.work_sessions.assert_editable()
        candidate=self.candidates.get(candidate_id)
        if candidate is None:raise LiteError('ROUTING_CANDIDATE_UNKNOWN')
        if candidate.validation['status']!='ready':raise LiteError('ROUTING_CANDIDATE_NOT_READY','只有连接和本地检查均通过的方案才可采用。')
        if not candidate.proposal.shapes:
            self.applied=True
            return {'no_op':True,'object_ids':[]}
        operations=checked_operations(candidate.proposal,self.problem,editor.profile)
        staging=Editor(editor.w,editor.profile,scope_id=self.region_id);staging.apply(operations,expected_revision=editor.w.revision)
        record=RoutingRecord(id=self.id,region_id=self.region_id,source_revision=self.source.revision,candidate_id=candidate_id,
            algorithms=candidate.sources,object_uids=tuple(op.uid for op in operations),
            metrics={k:candidate.validation[k] for k in ('length_um','via_count','shape_count')})
        local=staging.w.local_data.model_copy(update={'routing_records':{**staging.w.local_data.routing_records,self.id:record}})
        editor.publish(staging.w.model_copy(update={'local_data':local}))
        self.applied=True
        reply={'no_op':False,'object_ids':list(record.object_uids),'revision':editor.w.revision}
        try:write_json_atomic(self.folder/'applied.json',{'candidate_id':candidate_id,**reply})
        except OSError as exc:reply['warning']='方案已采用，但附加日志写入失败：'+str(exc)
        return reply

"""Region task ownership, snapshot validity and bounded resource lifetime."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock
from time import monotonic
from typing import Literal
from weakref import ref
from ..model import LiteError, digest

TaskState = Literal['queued', 'running', 'completed', 'failed', 'cancelled']
TERMINAL = ('completed', 'failed', 'cancelled')


@dataclass
class Job:
    id: str
    lease: object
    kind: str
    source: object
    profile: object
    rules: object
    folder: Path
    cancelled: Event
    future: object = None
    routing: object = None
    state: TaskState = 'queued'
    message: str = '等待执行'
    result: object = None
    error: dict | None = None
    started: float = field(default_factory=monotonic)
    state_lock: object = field(default_factory=Lock, repr=False)
    adopt: object = None

    def __post_init__(self):
        self.source_revision = self.source.revision
        self.source_ref = ref(self.source)
        self.profile_digest = digest(self.profile.model_dump(mode='json'))
        self.rules_digest = self.rules.fingerprint() if self.rules else None
        from ..scope_state import fingerprint
        self.scope_fingerprint=fingerprint(self.source,self.lease.region_id)

    def current(self, editor, rules):
        from ..scope_state import fingerprint
        return (
            self.lease.editor is editor
            and fingerprint(editor.w,self.lease.region_id)==self.scope_fingerprint
            and digest(editor.profile.model_dump(mode='json')) == self.profile_digest
            and (rules.fingerprint() if rules else None) == self.rules_digest
        )

    def clear_payload(self, _future=None):
        """Only after a worker has exited; no Qt, Editor or audit callbacks here."""
        self.source = self.profile = self.rules = self.routing = self.result = self.future = self.adopt = None


@dataclass(frozen=True)
class JobStatus:
    job_id: str
    kind: str
    state: TaskState
    message: str
    source_revision: int
    current: bool
    elapsed_seconds: float

    def payload(self):
        from dataclasses import asdict

        return asdict(self)


class JobRegistry:
    def __init__(self, editor, drc, audit):
        self.editor = editor
        self.drc = drc
        self.audit = audit
        self.jobs = {}
        self.audit_failure = None
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='agent-region')

    def current(self, job):
        return job.current(self.editor(), self.drc())

    def submit(self, job, operation):
        self.jobs[job.id] = job
        try:
            job.future = self.executor.submit(operation)
        except Exception:
            self.jobs.pop(job.id, None)
            job.clear_payload()
            raise
        return self.status(job)

    def progress(self, job, message):
        with job.state_lock:
            if not job.cancelled.is_set():
                job.state, job.message = 'running', message

    def get(self, lease, ident, kind=None):
        job = self.jobs.get(ident)
        if job is None or job.lease is not lease or kind and job.kind != kind:
            raise LiteError('JOB_OUTSIDE_REGION')
        self.poll(job)
        if self.audit_failure:
            raise LiteError('AUDIT_UNAVAILABLE', '任务记录保存失败，接口已暂停。')
        return job

    def poll(self, job=None):
        if self.audit_failure:
            return
        for item in [job] if job else list(self.jobs.values()):
            if not item.future or not item.future.done() or item.state in TERMINAL:
                continue
            try:
                item.result = item.future.result()
                if not item.cancelled.is_set() and item.adopt is not None:
                    item.result=item.adopt(item.result)
                item.state = 'cancelled' if item.cancelled.is_set() else 'completed'
                if item.kind == 'check' and item.state == 'completed' and self.current(item) and item.result.get('completion_eligible',False):
                    item.lease.last_check = item.id
                item.message = '候选生成完成' if item.kind == 'route' else '检查完成'
            except Exception as exc:
                if item.kind=='edit':item.result=None
                item.state = 'cancelled' if item.cancelled.is_set() else 'failed'
                from .failure_context import native_failure
                item.error = native_failure(exc,item.source,item.lease.region_id,item.kind)
                item.message = item.error['message']
            item.future = None  # Do not retain a second result graph in Future.
            item.adopt = None
            try:
                self.audit.emit(
                    {
                        'event': 'job_finished',
                        'job_id': item.id,
                        'region_id': item.lease.region_id,
                        'document_id': item.lease.editor.w.id,
                        'owner': item.lease.owner,
                        'kind': item.kind,
                        'state': item.state,
                        'error': item.error,
                        'result': item.result
                        if item.kind != 'route'
                        else [{'id': c.id, 'validation': c.validation} for c in item.result or []],
                    }
                )
            except Exception as exc:
                self.audit_failure = str(exc)
            if item.kind != 'route' or item.state == 'failed':
                # Validity uses a weak identity stamp; completed checks need no full snapshot.
                item.source = item.profile = item.rules = None
                if item.state == 'failed':
                    item.routing = None
            # Several completed edits must not monopolize one Qt timer turn.
            # Each adoption still validates, publishes, saves and journals
            # atomically; let queued input/paint events run before the next.
            if job is None and item.kind == 'edit':
                break

    def status(self, job, *, server_options=None):
        current = self.current(job)
        result = JobStatus(
            job.id,
            job.kind,
            job.state,
            job.message,
            job.source_revision,
            current,
            round(monotonic() - job.started, 2),
        ).payload()
        if job.error:
            result['error'] = job.error
        if job.kind=='edit':
            result['edit_applied']=bool(job.result and isinstance(job.result,dict) and job.result.get('edit_applied'))
            result['next']={'tool':'edit_region','mode':'status','job_id':job.id}
        if job.state == 'completed':
            if job.kind == 'route':
                result['candidates'] = [
                    {
                        'id': c.id,
                        'title': c.proposal.title,
                        'status': c.validation['status'],
                        'validation': c.validation,
                    }
                    for c in job.result
                ]
            elif job.kind=='edit':
                result['edit_applied']=bool(job.result.get('edit_applied'))
                result['result']=job.result
            else:
                checked=job.result
                if job.kind=='server_drc':
                    from .server_drc import filtered_report
                    checked=filtered_report(checked,**(server_options or {}))
                result['passed'] = bool(current and checked['passed'])
                result['result' if current else 'historical_result'] = checked
        return result

    def available(self, lease, busy):
        if busy():
            raise LiteError('WORKSPACE_BUSY')
        self.poll()
        if self.audit_failure:
            raise LiteError('AUDIT_UNAVAILABLE')
        if any(j.lease is lease and j.state not in TERMINAL for j in self.jobs.values()):
            raise LiteError('REGION_JOB_RUNNING', '先等待当前任务或丢弃布线任务。')
        rules = self.drc()
        if rules is None:
            raise LiteError('LOCAL_DRC_REQUIRED')
        return rules

    def cancel(self, job):
        with job.state_lock:
            job.cancelled.set()
            job.state, job.message = 'cancelled', '任务已取消'
        future = job.future
        if future is None:
            job.clear_payload()
        else:
            # A running worker may still use routing/source. Release only after it exits.
            future.add_done_callback(job.clear_payload)
            future.cancel()

    def release(self, lease):
        for ident, job in list(self.jobs.items()):
            if job.lease is lease:
                self.jobs.pop(ident)
                self.cancel(job)
        lease.last_check = None
        lease.history.clear()

    def close(self):
        for job in list(self.jobs.values()):
            self.cancel(job)
        self.jobs.clear()
        self.executor.shutdown(wait=False, cancel_futures=True)

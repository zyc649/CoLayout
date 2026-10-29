"""Exclusive region capabilities over the existing shared WorkSessions."""

from dataclasses import dataclass, field
from contextlib import contextmanager
import secrets
from ..model import LiteError


@dataclass
class Lease:
    token: str
    client_id: str
    editor: object
    region_id: str
    owner: str
    work_id: str
    history: list = field(default_factory=list)
    last_check: str | None = None
    observations: dict = field(default_factory=dict)


class RegionLeases:
    def __init__(self, editor, busy):
        self.editor_source = editor
        self.busy = busy
        self.leases = {}

    @property
    def editor(self):
        return self.editor_source()

    def lease(self, token, client_id):
        lease = self.leases.get(token)
        if not lease or lease.client_id != client_id:
            raise LiteError('SESSION_REQUIRED', '请先用人或父 Agent 分配的操作区 ID 接入。')
        if (
            lease.editor is not self.editor
            or not lease.editor.work_sessions.session_for(lease.region_id)
            or lease.editor.work_sessions.session_for(lease.region_id).id != lease.work_id
        ):
            raise LiteError('SESSION_EXPIRED', '工作区或占用已改变，请重新接入。')
        return lease

    @contextmanager
    def actor(self, lease, expected_revision):
        if type(expected_revision) is not int:
            raise LiteError('EXPECTED_REVISION_REQUIRED')
        from ..scope_state import fingerprint

        editor = lease.editor
        if expected_revision != editor.w.revision:
            if expected_revision not in lease.observations:
                raise LiteError(
                    'STALE_REVISION',
                    '此版本不在本接入的近期读取记录中，请使用最近返回的 revision。',
                    reason='revision_not_observed',
                )
            if lease.observations[expected_revision] != fingerprint(editor.w, lease.region_id):
                raise LiteError(
                    'STALE_REVISION',
                    '本操作层级已改变，请重新读取后再编辑。',
                    reason='scope_changed',
                )
        session = lease.editor.work_sessions.session_for(lease.region_id)
        with lease.editor.work_sessions.actor(
            lease.work_id,
            expected_revision=editor.w.revision,
            expected_pose_revision=session.pose_revision,
        ):
            yield

    def claim(self, value, client_id):
        if self.busy():
            raise LiteError('WORKSPACE_BUSY')
        if any(l.client_id == client_id for l in self.leases.values()):
            raise LiteError('ALREADY_CONNECTED', '请先释放当前操作区。')
        e = self.editor
        if e is None:
            raise LiteError('WORKSPACE_REQUIRED')
        if e.w.validation_only:raise LiteError('VALIDATION_WORKSPACE_ONLY','工艺验证副本不能接入普通绘图 Agent。')
        e.check_revision()
        work = e.work_sessions.start(
            value.region_id, value.agent_name, expected_revision=e.w.revision
        )
        token = secrets.token_urlsafe(32)
        lease = Lease(token, client_id, e, value.region_id, value.agent_name, work.id)
        self.leases[token] = lease
        self.observe(lease)
        return {
            'session_token': token,
            'region_id': value.region_id,
            'pin_mode': e.w.local_data.regions[value.region_id].pin_mode,
            'owner': value.agent_name,
            'exclusive': True,
            'coordinates': 'workspace_um',
            'scope': 'direct objects and child-module interfaces; no child internals',
            'revision': e.w.revision,
        }

    def observe(self, lease):
        from ..scope_state import fingerprint

        lease.observations[lease.editor.w.revision] = fingerprint(lease.editor.w, lease.region_id)
        while len(lease.observations) > 256:
            lease.observations.pop(next(iter(lease.observations)))

    def release(self, lease):
        current = lease.editor.work_sessions.session_for(lease.region_id)
        if current and current.id == lease.work_id:
            lease.editor.work_sessions.finish(lease.work_id)
        self.leases.pop(lease.token, None)

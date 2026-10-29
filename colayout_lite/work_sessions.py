"""Runtime work ownership for local regions, independent of Qt and transport.

This is an in-process editor boundary, not a remote lease or a parallel writer.
Call it on the editor's owning thread. Sessions are deliberately absent from the
document and undo history: reopening a document never restores a fictitious job.
Claims are exclusive per construction level. Parent and child actors may work
concurrently; a parent controls direct-child interfaces, never child contents.
"""
from contextlib import contextmanager
from dataclasses import dataclass, replace
from threading import get_ident
from uuid import uuid4

from .geometry import compose
from .model import LiteError

_CURRENT = object()


@dataclass(frozen=True)
class WorkSession:
    id: str
    region_id: str
    owner: str
    started_revision: int
    pose_revision: int
    local_to_workspace: tuple[int, int, int, int, int, int]


def inverse(matrix):
    """Inverse of a verified orthogonal, unit-scale region pose."""
    a, b, c, d, x, y = matrix
    return a, c, b, d, -a*x-c*y, -b*x-d*y


class WorkSessions:
    def __init__(self, editor):
        self.editor = editor
        self._sessions = {}
        self._listeners = []
        self._actor = None
        self._thread = get_ident()
        self._notification_before = None
        self._session_notification = False
        self._start_holds = {}

    def _on_thread(self):
        if get_ident() != self._thread:
            raise LiteError('WORK_SESSION_THREAD', '工作区操作需提交到 APP 编辑线程。')

    def snapshots(self):
        return tuple(self._sessions.values())

    def session_for(self, region_id):
        return next((s for s in self._sessions.values() if s.region_id == region_id), None)

    for_region = session_for

    def subscribe(self, callback):
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback) if callback in self._listeners else None

    def _notify(self):
        if self._actor is not None:
            self._session_notification = True
            return
        for callback in tuple(self._listeners):
            try:
                callback()
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Work session notification failed')

    def defer_workspace_notification(self, before):
        """Keep an Agent command's temporary scope out of human view listeners."""
        if self._actor is None:
            return False
        if self._notification_before is None:
            self._notification_before = before
        return True

    def suspend_starts(self, reason, *, region_id=None):
        """Hold new sessions across an asynchronous host operation.

        The host obtains this before dispatch and calls the returned idempotent
        resume function in its completion/failure cleanup, on the owning thread.
        Existing sessions are unaffected; replacement still requires require_idle.
        """
        self._on_thread()
        key = uuid4().hex
        self._start_holds[key] = (str(reason),region_id)
        def resume():
            self._on_thread()
            self._start_holds.pop(key, None)
        return resume

    def start(self, region_id, owner, *, expected_revision):
        self._on_thread()
        from .regions.query import descendants
        for reason,scope in self._start_holds.values():
            if scope is None or region_id in descendants(self.editor.w,scope) or scope in descendants(self.editor.w,region_id):
                raise LiteError('WORK_SESSION_UNAVAILABLE', reason)
        if type(expected_revision) is not int:
            raise LiteError('EXPECTED_REVISION_REQUIRED')
        self.editor._check_revision(expected_revision)
        region = self.editor.w.local_data.regions.get(region_id)
        if region is None:
            raise LiteError('REGION_MISSING', region_id)
        from .regions.query import descendants
        conflict=self.for_region(region_id)
        if conflict:
            raise LiteError('REGION_ALREADY_WORKING', '此操作层级已有 Agent 占用。', region_id=conflict.region_id)
        if not isinstance(owner, str) or not owner.strip():
            raise LiteError('WORK_SESSION_OWNER_REQUIRED')
        x, y = region.bbox[0]
        session = WorkSession(uuid4().hex, region_id, owner.strip(), self.editor.w.revision, 0, (1, 0, 0, 1, x, y))
        self._sessions[session.id] = session
        self._notify()
        return session

    def finish(self, session_id):
        """Release exactly this session; a stale ID cannot release its successor."""
        self._on_thread()
        if session_id not in self._sessions:
            raise LiteError('WORK_SESSION_EXPIRED', '任务已结束或已被替换。')
        session = self._sessions.pop(session_id)
        self._notify()
        return session

    release = finish

    def require_idle(self):
        if self._sessions:
            raise LiteError('WORK_SESSIONS_ACTIVE', '请先结束操作区任务，再替换、刷新或同步工作区。')

    @contextmanager
    def actor(self, session_id, *, expected_revision, expected_pose_revision):
        """Reserved internal entry for a future Agent, never a second Editor.

        The caller must convert local coordinates using the snapshot's matrix.
        Both revisions are checked before work starts. Ancestor movement changes
        the pose revision, so a previously prepared local-coordinate command
        cannot silently use an obsolete world placement.

        Commands are synchronous: do not await or pump a GUI event loop inside
        this context. A future scheduler must marshal one command at a time.
        """
        self._on_thread()
        if type(expected_revision) is not int or type(expected_pose_revision) is not int:
            raise LiteError('EXPECTED_REVISION_REQUIRED')
        self.editor._check_revision(expected_revision)
        session = self._sessions.get(session_id)
        if session is None:
            raise LiteError('WORK_SESSION_EXPIRED')
        if expected_pose_revision != session.pose_revision:
            raise LiteError('STALE_REGION_POSE', '上层已移动此模块，请重新读取局部坐标变换。')
        if self._actor is not None:
            raise LiteError('WORK_SESSION_REENTRANT')
        old_scope = self.editor.scope_id
        self._actor = session_id
        self.editor.scope_id = session.region_id
        try:
            yield session
        finally:
            self._actor = None
            self.editor.scope_id = old_scope
            before, changed = self._notification_before, self._session_notification
            self._notification_before, self._session_notification = None, False
            # Successful publications remain real edits, including when a later
            # operation raises. Notify once only after restoring the human view.
            if before is not None:
                self.editor._notify(before)
            if changed:
                self._notify()

    def _ancestors(self, scope_id, workspace):
        while scope_id is not None:
            yield scope_id
            region = workspace.local_data.regions.get(scope_id)
            scope_id = region.parent_id if region else None

    def _blocker(self, scope_id, workspace):
        if self._actor is not None:
            actor = self._sessions.get(self._actor)
            if actor is None:
                raise LiteError('WORK_SESSION_EXPIRED')
            # An explicit child actor may work inside an active parent's black
            # box. A parent actor may never edit the child's internal objects.
            if actor.region_id == scope_id:
                return None
        return self.for_region(scope_id)

    def readonly_reason(self, target_id=None, *, action='edit', scope_id=_CURRENT):
        """Human-facing advisory; validate() remains the publication authority.

        For a region, 'transform' permits a rigid parent-level movement; 'edit'
        covers resizing, interface PIN changes, policy and dissolution.
        """
        if not self._sessions:
            return None
        w = self.editor.w
        scope = self.editor.scope_id if scope_id is _CURRENT else scope_id
        actor = self._sessions.get(self._actor) if self._actor else None
        if self._actor is None and target_id in w.local_data.markups:
            # Guidance boxes are nonphysical human/Agent communication. The
            # command and publication layers still enforce the current level.
            return None
        if target_id in w.local_data.regions:
            region = w.local_data.regions[target_id]
            scope = region.parent_id
            if action != 'transform' and actor and actor.region_id == region.id:
                scope = region.id
            if action!='transform' and self._actor is None and self.editor.scope_id==region.id:
                scope=region.id
        elif target_id is not None:
            from .regions.query import owner_map
            scope = owner_map(w).get(target_id, scope)
            for region in w.local_data.regions.values():
                if target_id in region.pins:
                    scope = region.parent_id
                    if actor and actor.region_id == region.id:scope=region.id
                    if self._actor is None and self.editor.scope_id==region.id:scope=region.id
            for field in ('markups', 'keepouts'):
                record = getattr(w.local_data, field).get(target_id)
                if record:
                    scope = record.scope_id
        blocker = self._blocker(scope, w)
        if action=='dissolve' and self.for_region(target_id):blocker=self.for_region(target_id)
        if blocker:
            return f'{blocker.owner} 正在此操作层级工作；本层对象和直接子模块接口已锁定。'
        return None

    def assert_editable(self, target_id=None, *, action='edit'):
        reason = self.readonly_reason(target_id, action=action)
        if reason:
            raise LiteError('REGION_WORKING', reason, target_id=target_id)

    def check_replacement(self, before, after):
        if not self._sessions:
            return
        # A direct workspace assignment has no validated rigid-pose proof and
        # cannot act as a shortcut around the normal Editor publication path.
        for field in ('baseline', 'operations', 'guard_previews', 'local_data', 'layout_connectivity', 'circuit'):
            if getattr(before, field) != getattr(after, field):
                self.require_idle()

    def validate(self, before, after, *, region_matrices=None):
        if not self._sessions:
            if self._actor is not None:
                raise LiteError('WORK_SESSION_EXPIRED')
            return
        self._on_thread()
        from .editor import projected
        from .regions.query import owner_map, descendants
        old, new = projected(before), projected(after)
        owners, new_owners = owner_map(before), owner_map(after)
        rigid = set()
        for ident in region_matrices or {}:
            parent_scope = before.local_data.regions[ident].parent_id
            blocker = self._blocker(parent_scope, before)
            if blocker:
                raise LiteError('REGION_WORKING', '不能移动正在工作区域内部的子模块；可到上层整体移动该工作区域。',
                                region_id=blocker.region_id)
            rigid.update(descendants(before, ident))
        actor = self._sessions.get(self._actor) if self._actor else None
        if self._actor and not actor:
            raise LiteError('WORK_SESSION_EXPIRED')
        if actor and self.editor.scope_id != actor.region_id:
            raise LiteError('WORK_SESSION_SCOPE', 'Agent 只能编辑被分配操作区的当前层。')
        if actor and any(before.local_data.regions[ident].parent_id != actor.region_id for ident in region_matrices or {}):
            raise LiteError('WORK_SESSION_SCOPE', 'Agent 只能整体移动本层的子模块。')
        if before.circuit != after.circuit or before.layout_connectivity != after.layout_connectivity:
            self.require_idle()

        def check(scope, *, boundary=False):
            if scope in rigid:
                return
            blocker = self._blocker(scope, before)
            if blocker:
                raise LiteError('REGION_WORKING', '任务工作期间不能修改操作区内部、边界或 PIN。',
                                region_id=blocker.region_id, owner=blocker.owner)
            if actor and scope != actor.region_id:
                raise LiteError('WORK_SESSION_SCOPE', 'Agent 只能编辑被分配操作区的当前层。')

        for session in self._sessions.values():
            if session.region_id not in after.local_data.regions:
                raise LiteError('REGION_WORKING', '不能解散正在工作的操作区。', region_id=session.region_id)
        for uid in old.keys() | new.keys():
            if old.get(uid) != new.get(uid):
                parent = before.baseline.text_owners.get(uid, uid)
                check(owners.get(parent, new_owners.get(parent, self.editor.scope_id)))
            if uid in old and uid in new and owners.get(uid)!=new_owners.get(uid):
                old_owner,new_owner=owners.get(uid),new_owners.get(uid)
                added=after.local_data.regions.get(new_owner) if new_owner not in before.local_data.regions else None
                removed=before.local_data.regions.get(old_owner) if old_owner not in after.local_data.regions else None
                if added and added.parent_id==old_owner:check(old_owner)
                elif removed and removed.parent_id==new_owner:check(new_owner)
                else:check(old_owner);check(new_owner)

        a, b = before.local_data, after.local_data
        own_before = a.regions.get(actor.region_id) if actor else None
        own_after = b.regions.get(actor.region_id) if actor else None
        own_boundary_changed = bool(own_before and own_after and any(
            getattr(own_before, key) != getattr(own_after, key)
            for key in ('bbox', 'pins', 'name', 'note', 'blocked_layers', 'pin_mode')))
        for ident in a.regions.keys() | b.regions.keys():
            previous, current = a.regions.get(ident), b.regions.get(ident)
            if previous == current or ident in rigid:
                continue
            # Wrapping an active black box in a new parent is an operation on
            # the old parent layer, not an edit to the black box's interface.
            if previous is not None and current is not None and previous.model_copy(
                    update={'parent_id':current.parent_id}) == current:
                added_parent = b.regions.get(current.parent_id) if current.parent_id not in a.regions else None
                removed_parent = a.regions.get(previous.parent_id) if previous.parent_id not in b.regions else None
                wrapping = added_parent is not None and added_parent.parent_id == previous.parent_id
                unwrapping = removed_parent is not None and removed_parent.parent_id == current.parent_id
                if wrapping or unwrapping:
                    check(previous.parent_id if wrapping else current.parent_id)
                    continue
                raise LiteError('REGION_REPARENT_UNSUPPORTED','仅支持通过创建或解散直接子区调整层次，不能直接改写父级。',region_id=ident)
            # The assigned Agent may edit its own frame/interface, while the
            # parent retains direct-child management. Structural ownership
            # cannot be changed through this exception.
            if actor and ident == actor.region_id:
                check(ident, boundary=True)
                continue
            # Frame/PIN commands bump the parent's counter without changing
            # its content. Permit only this exact derived counter update.
            if (own_boundary_changed and ident == own_before.parent_id and previous and current
                    and previous.model_copy(update={'revision':current.revision}) == current):
                continue
            membership_only = previous is not None and current is not None and previous.model_copy(
                update={'revision':current.revision, 'object_uids':current.object_uids}) == current
            if membership_only:
                check(ident)
            else:
                parent=previous.parent_id if previous else current.parent_id
                if self._actor is None and ident==self.editor.scope_id and self.for_region(ident):
                    raise LiteError('REGION_WORKING','本操作层级已由 Agent 占用。',region_id=ident)
                check(parent,boundary=True)
        for field in ('markups', 'keepouts'):
            aa, bb = getattr(a, field), getattr(b, field)
            for ident in aa.keys() | bb.keys():
                if aa.get(ident) == bb.get(ident):
                    continue
                previous, current = aa.get(ident), bb.get(ident)
                removed = a.regions.get(previous.scope_id) if previous and previous.scope_id not in b.regions else None
                added = b.regions.get(current.scope_id) if current and current.scope_id not in a.regions else None
                transfer = previous and current and previous.model_copy(update={'scope_id':current.scope_id}) == current
                if transfer and removed and removed.parent_id == current.scope_id:
                    check(current.scope_id)
                    continue
                if transfer and added and added.parent_id == previous.scope_id:
                    check(previous.scope_id)
                    continue
                if field == 'markups' and actor is None:
                    continue
                for row in (aa.get(ident), bb.get(ident)):
                    if row:
                        check(row.scope_id)
                        if field == 'keepouts' and row.scope_id not in rigid:
                            # A parent-owned keepout crossing a child's boundary
                            # still changes that child's routing constraints.
                            from .regions.models import overlaps
                            for session in self._sessions.values():
                                from .scope_state import ancestors
                                if row.scope_id not in ancestors(before,session.region_id)|{session.region_id}:continue
                                if session.region_id in rigid or (actor and session.region_id in self._ancestors(actor.region_id, before)):
                                    continue
                                region = before.local_data.regions[session.region_id]
                                if overlaps(row.bbox, region.bbox):
                                    raise LiteError('REGION_WORKING', '禁布区不能改变正在工作模块内的布线限制。',
                                                    region_id=session.region_id)
        for field in ('groups', 'pins', 'annotations'):
            aa, bb = getattr(a, field), getattr(b, field)
            for ident in aa.keys() | bb.keys():
                if aa.get(ident) == bb.get(ident):
                    continue
                for row, state_owners, local in ((aa.get(ident), owners, a), (bb.get(ident), new_owners, b)):
                    if row:
                        refs = set(row.object_uids)
                        group = local.groups.get(getattr(row, 'group_id', None))
                        if group:
                            refs.update(group.object_uids)
                        scopes = {state_owners.get(uid) for uid in refs}
                        if field == 'pins':
                            from .regions.models import enclosing_scope
                            scopes.add(enclosing_scope(local.regions, row.bbox))
                        if not scopes:
                            scopes.add(self.editor.scope_id)
                        for scope in scopes:
                            check(scope)
        for uid in a.native_blocked_layers.keys() | b.native_blocked_layers.keys():
            if a.native_blocked_layers.get(uid) != b.native_blocked_layers.get(uid):
                check(owners.get(uid))
        for ident in a.native_routing_windows.keys() | b.native_routing_windows.keys():
            if a.native_routing_windows.get(ident)==b.native_routing_windows.get(ident):continue
            for row,ownership in ((a.native_routing_windows.get(ident),owners),(b.native_routing_windows.get(ident),new_owners)):
                if row:check(ownership.get(row.owner_uid))
        if a.reference_net_map != b.reference_net_map or a.instructions != b.instructions:
            self.require_idle()

    def moved(self, before, region_matrices):
        """Called only after a successful, verified atomic publication/history step."""
        if not self._sessions or not region_matrices:
            return
        from .regions.query import descendants
        changed = False
        for ident, matrix in region_matrices.items():
            subtree = descendants(before, ident)
            for key, session in tuple(self._sessions.items()):
                if session.region_id in subtree:
                    self._sessions[key] = replace(session, pose_revision=session.pose_revision+1,
                                                  local_to_workspace=compose(matrix, session.local_to_workspace))
                    changed = True
        if changed:
            self._notify()

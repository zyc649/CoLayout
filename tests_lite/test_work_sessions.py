"""Runtime region ownership: authoritative local edits, no transport or Qt."""
from dataclasses import FrozenInstanceError
from concurrent.futures import ThreadPoolExecutor

import pytest

from colayout_lite.document import save_document, load_document
from colayout_lite.editor import Editor, projected
from colayout_lite.frame_edit import FrameEdit
from colayout_lite.geometry import point
from colayout_lite.human_edit import HumanEdit
from colayout_lite.model import LiteError, Shape
from colayout_lite.regions.actions import RegionActions
from tests_lite.test_human_edit import hierarchy
from tests_lite.test_regions import region_editor, profile


@pytest.fixture
def working(region_editor):
    e = region_editor
    left, right, parent = hierarchy(e)
    return e, left, right, parent


def start(e, region, owner='Agent A'):
    return e.work_sessions.start(region, owner, expected_revision=e.w.revision)


def actor(e, session):
    current = e.work_sessions.session_for(session.region_id)
    return e.work_sessions.actor(session.id, expected_revision=e.w.revision,
                                 expected_pose_revision=current.pose_revision)


def unchanged(e, callback, match='REGION_WORKING'):
    state, undo, redo = e.w, tuple(e._undo), tuple(e._redo)
    with pytest.raises(LiteError, match=match):
        callback()
    assert e.w is state and tuple(e._undo) == undo and tuple(e._redo) == redo


def test_runtime_snapshots_events_and_document_do_not_claim_persistent_jobs(working, tmp_path):
    e, left, _, _ = working
    before = e.w
    events = []
    unsubscribe = e.work_sessions.subscribe(lambda: events.append(e.work_sessions.snapshots()))
    session = start(e, left)
    assert e.w is before
    assert session.region_id == left and session.owner == 'Agent A'
    assert session.local_to_workspace == (1, 0, 0, 1, -1000, -1000)
    with pytest.raises(FrozenInstanceError):
        session.owner = 'Changed'
    path = tmp_path/'workspace.json'
    save_document(path, e.w, e.profile)
    loaded, profile = load_document(path)
    assert not Editor(loaded, profile).work_sessions.snapshots()
    e.work_sessions.finish(session.id)
    assert e.w is before and len(events) == 2 and not events[-1]
    successor = start(e, left, 'Agent B')
    unchanged(e, lambda:e.work_sessions.release(session.id), 'WORK_SESSION_EXPIRED')
    assert e.work_sessions.session_for(left) == successor
    unsubscribe()
    e.work_sessions.release(successor.id)
    assert len(events) == 3


def test_start_guards_revision_missing_duplicate_owner_and_thread(working):
    e, left, _, _ = working
    unchanged(e, lambda:e.work_sessions.start(left, 'A', expected_revision=e.w.revision-1), 'STALE_REVISION')
    unchanged(e, lambda:e.work_sessions.start(left, 'A', expected_revision=None), 'EXPECTED_REVISION_REQUIRED')
    unchanged(e, lambda:start(e, 'missing'), 'REGION_MISSING')
    unchanged(e, lambda:start(e, left, ' '), 'OWNER_REQUIRED')
    start(e, left)
    unchanged(e, lambda:start(e, left), 'ALREADY_WORKING')
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(LiteError, match='WORK_SESSION_THREAD'):
            pool.submit(lambda:start(e, left)).result()


def test_humans_cannot_edit_locked_interiors_through_any_editor_entry(working):
    e, left, _, _ = working
    start(e, left)
    e.scope_id = left
    unchanged(e, lambda:e.place('object-A', (100, 0)))
    unchanged(e, lambda:HumanEdit(e).transform(['object-A'], delta=(100, 0)))
    unchanged(e, lambda:e.create(Shape(kind='rect', lpp=('wire_a','drawing'), bbox=((2500,3000),(3000,3500)))))
    changed = e.w.local_data.model_copy(update={'regions':{**e.w.local_data.regions,
        left:e.w.local_data.regions[left].model_copy(update={'name':'bypass'})}})
    unchanged(e, lambda:e._publish(e.w.model_copy(update={'local_data':changed})))
    unchanged(e, lambda:setattr(e, 'w', e.w.model_copy(update={'local_data':changed})), 'WORK_SESSIONS_ACTIVE')


def test_locked_frame_pin_policy_dissolve_and_advisory_are_consistent(working):
    e, left, _, parent = working
    start(e, left)
    e.scope_id = parent
    region = e.w.local_data.regions[left]
    pin = next(iter(region.pins))
    assert not e.work_sessions.readonly_reason(left)
    assert not e.work_sessions.readonly_reason(pin)
    assert not e.work_sessions.readonly_reason(left, action='transform')
    HumanEdit(e).adjust_pin(left, pin, -1000, 4000)
    FrameEdit(e).resize(left, ((-1500,-1500),(7500,7500)))
    RegionActions(e).update_details(left, 'new', '', ('wire_b',))
    unchanged(e, lambda:RegionActions(e).dissolve(left))
    e.scope_id = left
    assert e.work_sessions.readonly_reason()


def test_actor_can_edit_owned_scope_and_its_interface(working):
    e, left, right, parent = working
    session = start(e, left)
    assert e.scope_id is None
    with actor(e, session):
        assert e.scope_id == left
        e.place('object-A', (100, 0))
        assert projected(e.w)['object-A'].placement.origin == (100, 0)
        uid = e.create(Shape(kind='rect', lpp=('wire_a','drawing'), bbox=((2500,3000),(3000,3500))))
        assert uid in e.w.local_data.regions[left].object_uids
        pin = next(iter(e.w.local_data.regions[left].pins))
        HumanEdit(e).adjust_pin(left, pin, -1000, 4000)
        e.scope_id = right
        unchanged(e, lambda:e.place('object-C', (12100, 0)), 'WORK_SESSION_SCOPE')
        e.scope_id = left
        unchanged(e, lambda:RegionActions(e).update_details(parent, 'other', '', ('wire_a',)), 'WORK_SESSION_SCOPE')
    assert e.scope_id is None
    unchanged(e, lambda:e.work_sessions.require_idle(), 'WORK_SESSIONS_ACTIVE')
    e.work_sessions.finish(session.id)
    e.scope_id = left
    e.place('object-A', (200, 0))


@pytest.mark.parametrize('orientation', ['R0','R90','R180','R270','MX','MY','MXR90','MYR90'])
def test_parent_rigid_transform_updates_local_pose_and_undo_redo(working, orientation):
    e, left, right, parent = working
    sessions = [start(e, ident, ident) for ident in (left, right)]
    before = e.w
    local_a = (1000, 1000)  # A's origin in the original left region frame.
    HumanEdit(e).transform([parent], delta=(1000, 500), orientation=orientation)
    left_session = e.work_sessions.session_for(left)
    assert left_session.pose_revision == 1
    assert point(local_a, left_session.local_to_workspace) == projected(e.w)['object-A'].placement.origin
    assert all(e.work_sessions.session_for(s.region_id).pose_revision == 1 for s in sessions)
    e.undo()
    assert e.w.operations == before.operations and e.w.local_data == before.local_data
    assert e.work_sessions.session_for(left).local_to_workspace == sessions[0].local_to_workspace
    e.redo()
    assert e.work_sessions.session_for(left).pose_revision == 3
    assert point(local_a, e.work_sessions.session_for(left).local_to_workspace) == projected(e.w)['object-A'].placement.origin
    with pytest.raises(LiteError, match='STALE_REGION_POSE'):
        with e.work_sessions.actor(sessions[0].id, expected_revision=e.w.revision, expected_pose_revision=0):
            pass


def test_parent_children_and_siblings_can_claim_independent_levels(working):
    e,left,right,parent=working
    lower=start(e,left,'Layout Agent');other=start(e,right,'Other Agent')
    upper=start(e,parent,'Top Agent')
    with actor(e,lower):e.place('object-A',(100,0))
    e.work_sessions.finish(lower.id);e.work_sessions.finish(other.id)
    lower=start(e,left)
    with actor(e,upper):
        HumanEdit(e).transform([left],delta=(100,0))
        unchanged(e,lambda:e.place('object-A',(300,0)),'REGION_SCOPE_VIOLATION')
    e.scope_id=left
    unchanged(e,lambda:HumanEdit(e).transform(['object-A'],delta=(100,0)))


def test_history_rechecks_current_lock_without_losing_undo_redo(working):
    e, left, _, _ = working
    e.scope_id = left
    e.place('object-A', (100, 0))
    session = start(e, left)
    unchanged(e, e.undo)
    with actor(e, session):
        e.undo()
    unchanged(e, e.redo)
    e.work_sessions.finish(session.id)
    e.redo()
    assert projected(e.w)['object-A'].placement.origin == (100, 0)


def test_rigid_history_created_before_start_remains_safe_and_reversible(working):
    e, left, _, parent = working
    HumanEdit(e).transform([parent], delta=(1000, 0))
    session = start(e, left)
    e.undo()
    assert e.work_sessions.session_for(left).local_to_workspace[-2:] == (-1000, -1000)
    e.redo()
    assert e.work_sessions.session_for(left).local_to_workspace == session.local_to_workspace


def test_guidance_boxes_are_allowed_but_keepouts_remain_locked(working):
    e, left, _, _ = working
    a = RegionActions(e)
    note = a.add_markup((2500,3000,3000,3500), 'mark')
    keep = a.add_keepout((3500,4000,4000,4500), [])
    start(e, left)
    e.scope_id = left
    assert not e.work_sessions.readonly_reason(note)
    a.update_box(note, 'new')
    unchanged(e, lambda:a.update_box(keep, '', ['wire_b']))
    unchanged(e, lambda:a.remove_box(keep))
    FrameEdit(e).move(note, (100,0))
    a.add_markup((3000,3000,3500,3500))


def test_group_references_and_crossing_keepout_cannot_change_locked_content(working):
    from colayout_lite.local_models import LocalGroup, LocalAnnotation
    e, left, _, _ = working
    group = LocalGroup(id='group', name='devices', object_uids=('object-A',))
    e._publish(e.w.model_copy(update={'local_data':e.w.local_data.model_copy(update={'groups':{'group':group}})}))
    start(e, left)
    note = LocalAnnotation(id='note', group_id='group', text='move devices')
    local = e.w.local_data.model_copy(update={'annotations':{'note':note}})
    unchanged(e, lambda:e._publish(e.w.model_copy(update={'local_data':local})))
    # This box is parent-owned but enters the protected region through its top.
    unchanged(e, lambda:RegionActions(e).add_keepout((2000,6000,3000,8000), ['wire_b']))
    changed = e.w.layout_connectivity.model_copy(update={'pair_id':'other-pair'})
    unchanged(e, lambda:e._publish(e.w.model_copy(update={'layout_connectivity':changed})), 'WORK_SESSIONS_ACTIVE')


def test_wrapping_working_blackboxes_does_not_change_local_frame(working):
    e, left, _, parent = working
    session = start(e, left)
    grandparent = RegionActions(e).create((-3000,-3000,22000,10000), 'upper')
    assert e.w.local_data.regions[parent].parent_id == grandparent
    assert e.work_sessions.session_for(left) == session
    e.undo()
    assert e.work_sessions.session_for(left) == session


def test_directly_wrapping_active_child_preserves_interface_members_and_session(region_editor):
    e = region_editor
    left = RegionActions(e).create((-1000,-1000,7000,7000), 'child')
    session = start(e, left)
    before = e.w.local_data.regions[left]
    parent = RegionActions(e).create((-2000,-2000,21000,9000), 'new parent')
    assert e.w.local_data.regions[left] == before.model_copy(update={'parent_id':parent})
    assert e.work_sessions.session_for(left) == session
    parent_session=start(e,parent,'Parent Agent')
    e.work_sessions.finish(parent_session.id)
    e.undo()  # Remove only the new wrapper, retaining the live child.
    assert e.w.local_data.regions[left] == before
    assert e.work_sessions.session_for(left).local_to_workspace == session.local_to_workspace
    e.redo()
    assert e.w.local_data.regions[left].parent_id == parent


def test_reparent_to_existing_scope_is_not_a_lock_escape(working):
    e, left, _, parent = working
    RegionActions(e).create((-3000,-3000,22000,10000), 'outer')
    start(e, left)
    top = e.w.local_data.regions[parent].parent_id
    changed = e.w.local_data.model_copy(update={'regions':{**e.w.local_data.regions,
        left:e.w.local_data.regions[left].model_copy(update={'parent_id':top})}})
    unchanged(e, lambda:e._publish(e.w.model_copy(update={'local_data':changed})),'REGION_REPARENT_UNSUPPORTED')


def test_expired_actor_and_forged_rigid_proof_fail_atomically(working):
    from colayout_lite.human_edit import transform_local
    e, left, _, parent = working
    session = start(e, left)
    local = transform_local(e.w.local_data, parent, (1,0,0,1,1000,0))
    unchanged(e, lambda:e._publish(e.w.model_copy(update={'local_data':local}),
                                  region_transforms={parent:((1000,0),'R0',(0,0))}), 'INVALID_REGION_TRANSFORM')
    with actor(e, session):
        e.work_sessions.finish(session.id)
        unchanged(e, lambda:e.place('object-A', (100,0)), 'WORK_SESSION_EXPIRED')


def test_actor_notifications_restore_human_scope_and_merge_real_publications(working):
    e, left, right, _ = working
    session = start(e, left)
    e.scope_id = right
    events = []
    e.subscribe(lambda changed:events.append((e.scope_id, e.w.revision, changed)))
    count = len(e._undo)
    with actor(e, session):
        e.place('object-A', (100,0))
        e.place('object-B', (4100,0))
        assert not events
        assert len(e._undo) == count+2  # No hidden merging of true history entries.
    assert len(events) == 1 and events[0][0] == right
    assert events[0][2] == {'object-A','object-B'}
    assert e.scope_id == right
    with actor(e, session):
        e.undo()
        e.undo()
        assert len(events) == 1
    assert len(events) == 2 and events[1][0] == right
    assert projected(e.w)['object-A'].placement.origin == (0,0)


def test_actor_exception_still_reports_prior_success_in_human_scope(working):
    e, left, right, _ = working
    session = start(e, left)
    e.scope_id = right
    events = []
    e.subscribe(lambda _:events.append(e.scope_id))
    with pytest.raises(RuntimeError, match='later failure'):
        with actor(e, session):
            e.place('object-A', (100,0))
            raise RuntimeError('later failure')
    assert events == [right] and e.scope_id == right
    assert projected(e.w)['object-A'].placement.origin == (100,0)
    with pytest.raises(LiteError, match='OFF_GRID'):
        with actor(e, session):
            e.place('object-A', (101,0))
    assert events == [right]  # A rejected publication does not invent a change.


def test_actor_release_listeners_never_observe_temporary_scope(working):
    e,left,_,parent=working;lower=start(e,left);events=[]
    e.work_sessions.subscribe(lambda:events.append((e.scope_id,e.work_sessions.snapshots())))
    with pytest.raises(RuntimeError):
        with actor(e,lower):
            e.work_sessions.release(lower.id)
            assert not events
            raise RuntimeError('release followed by exception')
    assert len(events)==1 and events[0][0] is None
    assert e.work_sessions.session_for(left) is None


def test_actor_rejects_nested_or_wrong_thread_context_without_changing_scope(working):
    e, left, right, _ = working
    a, b = start(e,left), start(e,right)
    with actor(e,a):
        with pytest.raises(LiteError, match='REENTRANT'):
            with actor(e,b):
                pass
        assert e.scope_id == left
    assert e.scope_id is None
    def wrong_thread():
        with actor(e,a):
            pass
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(LiteError, match='WORK_SESSION_THREAD'):
            pool.submit(wrong_thread).result()
    assert e.scope_id is None


def test_suspend_starts_spans_host_tasks_and_independent_holds(working):
    e, left, _, _ = working
    resume_a = e.work_sessions.suspend_starts('正在从 Virtuoso 刷新')
    resume_b = e.work_sessions.suspend_starts('正在载入文档')
    unchanged(e, lambda:start(e,left), 'WORK_SESSION_UNAVAILABLE')
    resume_a()
    resume_a()  # Duplicate host cleanup is harmless and cannot release another hold.
    unchanged(e, lambda:start(e,left), 'WORK_SESSION_UNAVAILABLE')
    resume_b()
    session = start(e,left)
    resume = e.work_sessions.suspend_starts('只读检查')
    assert e.work_sessions.session_for(left) == session
    unchanged(e,e.work_sessions.require_idle,'WORK_SESSIONS_ACTIVE')
    resume()

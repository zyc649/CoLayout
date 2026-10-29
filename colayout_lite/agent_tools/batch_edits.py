"""Prepare large local batches off the UI thread; publish once on the owner thread.

Every operation still runs the ordinary domain validation in order. Only
direct-object edits and object-scoped routing windows use this lane; child
frame transforms retain their existing rigid-pose transaction semantics.
"""
from threading import Event
from uuid import uuid4
from ..editor import Editor
from ..model import LiteError
from .jobs import Job
from .region_edits import apply_operation


_WINDOW_ACTIONS = {
    'create_native_routing_window', 'set_native_routing_window',
    'delete_native_routing_window', 'set_native_blocked_layers',
}


def eligible(args):
    from ..commands import COMMANDS
    from .contract import EDIT_ACTIONS
    from ..layout_helpers.contracts import SLOW_ACTIONS
    return (args.mode == 'apply' and len(args.operations) >= 8
            and all(op.action in EDIT_ACTIONS and op.action not in SLOW_ACTIONS
                    and (op.action in COMMANDS or op.action in _WINDOW_ACTIONS) for op in args.operations))


def submit(session, lease, args):
    e = lease.editor
    registry = session.tasks
    with session.actor(lease, args.expected_revision):
        source, profile = e.w, e.profile
        ident = uuid4().hex
        job = Job(ident, lease, 'edit', source, profile, session.drc_source(),
                  session.folder / 'jobs' / ident, Event())

    def compute():
        # Heavy Python geometry/validation in several threads still competes
        # with Qt for the GIL. Use the existing cancellable process lifecycle.
        from .batch_worker import prepare
        return prepare(source, profile, lease.region_id, args, job.folder, job.cancelled)

    def adopt(value):
        from .edit_adoption import adopt_edit
        candidate,result=value
        def validate(merged):
            if any(op.action in _WINDOW_ACTIONS for op in args.operations):
                from ..regions.constraints import validate_workspace
                validate_workspace(merged,profile)
        return adopt_edit(session,lease,job,source,candidate,result,changed=result['changed'],validate=validate,
                          stale_message='本层输入、工艺或接入已改变，整批未采用。')

    job.adopt = adopt
    return {**registry.submit(job, compute), 'edit_applied': False,
            'next': {'tool': 'edit_region', 'mode': 'status', 'job_id': ident}}


def prepare_local(source, profile, region_id, operations):
    """Worker-side ordered validation, also usable by deterministic tests."""
    staged = Editor(source, profile, scope_id=region_id)
    results, created = [], []
    # Reuse the same transaction and ordered commands as synchronous edits.
    with staged.transaction(expected_revision=source.revision) as batch:
        for index, operation in enumerate(operations):
            try:
                result = apply_operation(batch, region_id, operation)
            except LiteError as exc:
                exc.details.update(operation_index=index, action=operation.action,
                                   operation_uid=operation.uid, edit_applied=False)
                raise
            if result is not None:
                created.extend(result.get('created_uids', []))
                results.append({'index': index, 'action': operation.action, **result})
    return staged.w, {'created_uids': created, 'operations': results,
                      'changed': staged.w is not source, 'batch_atomic': True}

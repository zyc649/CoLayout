"""Shared owner-thread adoption for computed local edits; no worker/executor policy."""

from weakref import ref
from ..model import LiteError
from ..scope_state import fingerprint
from ..workspace_delta import merge


def adopt_edit(
    session, lease, job, source, candidate, result, *, changed=None, validate=None, stale_message
):
    registry = session.tasks
    if job.cancelled.is_set() or lease.token not in session.leases or not registry.current(job):
        raise LiteError('EDIT_PREVIEW_STALE', stale_message, edit_applied=False)
    if changed is None:
        changed = (
            candidate.operations != source.operations
            or candidate.guard_previews != source.guard_previews
            or candidate.local_data != source.local_data
        )
    editor = lease.editor
    with session.actor(lease, editor.w.revision):
        if changed:
            merged = merge(source, candidate, editor.w)
            if validate is not None:
                validate(merged)
            editor.publish(merged)
            lease.history.append(editor.history_token())
    job.source_ref = ref(editor.w)
    job.source_revision = editor.w.revision
    job.scope_fingerprint = fingerprint(editor.w, lease.region_id)
    result.update(edit_applied=changed, applied_revision=editor.w.revision)
    return session.saved(result)

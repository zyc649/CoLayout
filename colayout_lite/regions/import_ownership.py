"""Place newly imported native objects in the human's existing local hierarchy."""
from collections import defaultdict
from ..editor import projected
from ..local_models import LocalData
from ..model import LiteError
from .query import owner_map, object_bounds
from .models import enclosing_scope
from .constraints import validate_workspace


def assign_unowned(workspace, profile, candidate_uids):
    """Pure candidate; explicit callers decide which newly imported IDs to adopt.

    Existing membership is never reinterpreted. No PIN, network or geometry is
    synthesized, and the deepest completely containing region owns each object.
    """
    objects = projected(workspace)
    owners = owner_map(workspace)
    regions = dict(workspace.local_data.regions)
    assigned = defaultdict(list)
    for uid in sorted(set(candidate_uids)):
        if uid in owners or uid in workspace.baseline.text_owners:
            continue
        obj = objects.get(uid)
        if obj is None:
            raise LiteError('IMPORTED_OBJECT_MISSING', uid)
        bounds = object_bounds(workspace, obj, profile)
        target = enclosing_scope(regions, bounds) if bounds else None
        if target:
            assigned[target].append(uid)
    if not assigned:
        return workspace, {}
    for ident, uids in assigned.items():
        region = regions[ident]
        regions[ident] = region.model_copy(update={
            'object_uids': (*region.object_uids, *uids), 'revision': region.revision + 1})
    local = LocalData.model_validate(workspace.local_data.model_copy(update={'regions': regions}).model_dump())
    candidate = workspace.model_copy(update={'local_data': local})
    validate_workspace(candidate, profile)
    return candidate, {uid: ident for ident, uids in assigned.items() for uid in uids}


def assign_new_objects(previous, refreshed, profile):
    # Limit automatic adoption to IDs absent from the previous canonical baseline.
    # In particular, an intentional existing parent wire is never pulled inside.
    return assign_unowned(refreshed, profile, refreshed.baseline.objects.keys() - previous.baseline.objects.keys())


def adopt_in_editor(editor, uids, *, expected_revision=None):
    """Explicit local maintenance action, through the shared Editor and undo."""
    editor.check_revision(expected_revision)
    candidate, assigned = assign_unowned(editor.w, editor.profile, uids)
    if candidate is not editor.w:
        editor.publish(candidate)
    return assigned

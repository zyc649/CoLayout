"""Current-level routing cleanup through the existing deletion permissions.

Never descends into local children or native instances. Plans are readable;
execution rechecks against the current revision and publishes one undo step.
"""

from ..editor import Editor, projected
from ..human_edit import HumanEdit
from ..model import LiteError
from ..conduction_rules import ConductionRules
from .query import owner_map


def plan(editor, region_id, *, include_guards=False):
    editor.check_revision()
    region = editor.w.local_data.regions.get(region_id)
    if region is None:
        raise LiteError('REGION_MISSING')
    if region_id != editor.scope_id and region.parent_id != editor.scope_id:
        raise LiteError('REGION_SCOPE_VIOLATION', '只能清理当前层或直属操作区。')
    editor.work_sessions.assert_editable(region_id)
    rules = ConductionRules(editor.profile)
    layers = rules.metals | frozenset(
        r['layer'] for r in editor.profile.layers if r.get('material') == 'cut'
    )
    if include_guards:
        layers |= rules.wells
    owners = owner_map(editor.w)
    local = editor.w.local_data
    referenced = {
        u
        for row in (*local.groups.values(), *local.pins.values(), *local.annotations.values())
        for u in row.object_uids
    }
    staged = Editor(editor.w, editor.profile, scope_id=region_id)
    api = HumanEdit(staged)
    ids = []
    protected = []
    for uid, obj in projected(editor.w).items():
        if owners.get(uid) != region_id or obj.kind in ('inst', 'mosaic'):
            continue
        matches = (
            include_guards
            if obj.mpp
            else bool(
                obj.shape and (obj.kind == 'stdVia' or obj.shape.lpp and obj.shape.lpp[0] in layers)
            )
        )
        if not matches:
            continue
        try:
            editor.work_sessions.assert_editable(uid)
            api.deletion_kind(uid)
            if uid in referenced:
                raise LiteError('LOCAL_OBJECT_REFERENCED', '本地 PIN、分组或标注仍引用此图形。')
        except LiteError as exc:
            protected.append({'uid': uid, 'reason': str(exc)})
        else:
            ids.append(uid)
    return {
        'revision': editor.w.revision,
        'region_id': region_id,
        'object_ids': ids,
        'protected': protected,
    }


def clear(editor, region_id, *, include_guards=False, expected_revision=None):
    editor.check_revision(expected_revision)
    if editor.scope_id != region_id:
        raise LiteError('REGION_SCOPE_VIOLATION', '请进入此操作区后清理。')
    result = plan(editor, region_id, include_guards=include_guards)
    if result['object_ids']:
        HumanEdit(editor).delete(result['object_ids'], expected_revision=result['revision'])
    return result

"""Scoped atomic edits through shared Actions/Editor; no separate undo stack."""

from ..model import LiteError
from ..actions import Actions, dbu
from ..human_edit import HumanEdit
from ..regions.query import children
from .contract import EDIT_ACTIONS
from . import inspection


def edit_region(lease, args, *, actor):
    e = lease.editor
    with actor(lease, args.expected_revision):
        if args.mode == 'undo':
            if args.operations:
                raise LiteError('INVALID_ARGUMENTS', 'undo 不接收 operations。')
            token = lease.history[-1] if lease.history else None
            e.undo_owned(token)
            lease.history.pop()
            return {'undone': True}
        if not args.operations:
            raise LiteError('EMPTY_EDIT')
        source = e.w
        created = []
        results = []
        with e.transaction(expected_revision=e.w.revision) as staged:
            for index, operation in enumerate(args.operations):
                try:
                    result = apply_operation(staged, lease.region_id, operation)
                    if result is not None:
                        created.extend(result.get('created_uids',[]))
                        results.append({'index':index,'action':operation.action,**result})
                except LiteError as exc:
                    exc.details.update(
                        operation_index=index,
                        action=operation.action,
                        edit_applied=False,
                        operation_uid=operation.uid,
                    )
                    raise
        if e.w is not source:
            lease.history.append(e.history_token())
    return {'created_uids': created, 'changed': e.w is not source, 'operations':results}


def apply_operation(staged, region_id, operation):
    action = operation.action
    params = operation.params
    uid = operation.uid
    if action not in EDIT_ACTIONS:
        raise LiteError('ACTION_NOT_ALLOWED', '此 API 不支持该操作。', action=action)
    from .child_regions import MODELS as CHILD_MODELS,execute as child_edit
    if action in CHILD_MODELS:return child_edit(staged,action,params,uid)
    from ..layout_helpers.contracts import MODELS
    if action in MODELS:
        if uid is not None:raise LiteError('INVALID_ARGUMENTS','组合动作使用 params.uids/rows，不能提供外层 uid。')
        from ..layout_helpers.service import execute
        return execute(staged,action,params)
    direct = inspection.direct_ids(staged.w, region_id)
    child_ids = {r.id for r in children(staged.w, region_id)}
    if action == 'transform':
        if set(params) - {'uids', 'delta', 'orientation'}:
            raise LiteError('INVALID_ARGUMENTS')
        ids = params.get('uids', [])
        if not ids or not set(ids) <= direct | child_ids:
            raise LiteError('OBJECT_OUTSIDE_REGION')
        delta = tuple(dbu(v, staged.profile) for v in params.get('delta', (0, 0)))
        HumanEdit(staged).transform(ids, delta=delta, orientation=params.get('orientation', 'R0'))
    else:
        if action.startswith('create_'):
            if uid is not None:
                raise LiteError('CREATE_UID_ASSIGNED_BY_APP')
        elif uid not in direct:
            raise LiteError('OBJECT_OUTSIDE_REGION', '只允许本层直属对象。')
        result = Actions(staged).execute(action, params, uid=uid)
        if action.startswith('create_') or action == 'copy':
            return {'created_uids':[result.uid]}
    return {'created_uids':[]}

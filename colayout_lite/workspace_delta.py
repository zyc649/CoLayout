"""Three-way merge for an already validated local edit, never a second writer.

Merge only changed records/fields against their exact preconditions. Publication
still goes through Editor permissions, region validation and the shared history.
"""

from .model import LiteError
from .local_models import LocalData

_MISSING = object()


def _merge(before, after, current, path):
    if before == after:
        return current
    if current == before:
        return after
    if isinstance(before, dict) and isinstance(after, dict) and isinstance(current, dict):
        result = dict(current)
        for key in dict.fromkeys((*before, *after)):
            value = _merge(
                before.get(key, _MISSING),
                after.get(key, _MISSING),
                current.get(key, _MISSING),
                path + '.' + str(key),
            )
            if value is _MISSING:
                result.pop(key, None)
            else:
                result[key] = value
        return result
    raise LiteError(
        'EDIT_MERGE_CONFLICT',
        '此编辑涉及的数据已改变，未采用旧结果。',
        field=path,
        edit_applied=False,
    )


def merge(before, after, current):
    if before.baseline is not current.baseline and before.baseline.model_dump(exclude={'display'}) != current.baseline.model_dump(exclude={'display'}):
        raise LiteError('EDIT_MERGE_CONFLICT', '原生基准已改变。', edit_applied=False)
    old_ops = {o.uid: o for o in before.operations}
    new_ops = {o.uid: o for o in after.operations}
    ops = _merge(old_ops, new_ops, {o.uid: o for o in current.operations}, 'operations')
    # Counters describe publication history, not conflicting content. Rebase
    # changed record counters from current, preserving unrelated child content.
    old = before.local_data.model_dump()
    new = after.local_data.model_dump()
    now = current.local_data.model_dump()
    for rid in old['regions'].keys() & new['regions'].keys() & now['regions'].keys():
        for counter in ('revision', 'interface_revision'):
            if new['regions'][rid][counter] != old['regions'][rid][counter]:
                old['regions'][rid][counter] = now['regions'][rid][counter]
                new['regions'][rid][counter] = now['regions'][rid][counter] + 1
    local = LocalData.model_validate(_merge(old, new, now, 'local_data'))
    return current.model_copy(
        update={
            'operations': tuple(ops.values()),
            'guard_previews': _merge(
                before.guard_previews,
                after.guard_previews,
                current.guard_previews,
                'guard_previews',
            ),
            'local_data': local,
        }
    )

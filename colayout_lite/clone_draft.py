"""Rebind draft preconditions only after proving a private clone is equivalent.

Cadence may enumerate named MPP subparts in a different order after dbCopyCellView.
Names, multiplicity, every definition field and all other geometry stay strict.
Original operation hashes and transaction payloads are never rewritten in place.
"""

from .model import LiteError, digest
from .sync_checks import canonical_object
from .hierarchy import same_dependencies


def clone_object(obj):
    value = canonical_object(obj)
    if obj.mpp:
        parts = value['mpp']['parts']
        names = [part.get('name') for part in parts if isinstance(part, dict)]
        # Only named, unique subparts are an unordered native collection.
        # Unknown formats remain strictly ordered, including duplicates.
        if (
            len(names) == len(parts)
            and all(isinstance(n, str) and n for n in names)
            and len(set(names)) == len(names)
        ):
            value['mpp']['parts'] = sorted(parts, key=lambda p: p['name'])
    return value


def bind(source, private):
    old = source.baseline
    new = private.baseline
    a = old.semantic()
    b = new.semantic()
    metadata = [key for key in a if key not in ('objects', 'dependencies') and a[key] != b[key]]
    changed = [
        uid
        for uid in old.objects.keys() | new.objects.keys()
        if uid not in old.objects
        or uid not in new.objects
        or clone_object(old.objects[uid]) != clone_object(new.objects[uid])
    ]
    if changed or metadata or not same_dependencies(old, new):
        raise LiteError(
            'PRIVATE_COPY_SOURCE_MISMATCH',
            '私有副本与源基准不一致，未应用草稿；请核对外部变化。',
            objects=changed[:20],
            metadata=metadata,
            dependencies_match=same_dependencies(old, new),
        )
    operations = []
    for op in source.operations:
        if op.action in ('update', 'delete', 'transform'):
            original = old.objects.get(op.uid)
            copied = new.objects.get(op.uid)
            if original is None or copied is None or op.before != digest(original.semantic()):
                raise LiteError('OBJECT_CONFLICT', '草稿前提与原导入基准不同。', uid=op.uid)
            op = op.model_copy(update={'before': digest(copied.semantic())})
        operations.append(op)
    return private.model_copy(
        update={
            'operations': tuple(operations),
            'guard_previews': source.guard_previews,
            'local_data': source.local_data,
        }
    )

"""Local programmatic operations; batches validate fully before publication."""

from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, field, replace
from contextlib import contextmanager
from uuid import uuid4
from .model import Object, Shape, Placement, Operation, Workspace, LiteError, digest
from .geometry import transform_shape
from .permissions import delete_exception
from .geometry_memo import GeometryMemo

_projection_cache = GeometryMemo(sources=4, entries=2)
_operation_object_cache = GeometryMemo(sources=3, entries=4096)


def _created_object(baseline, op):
    # A transaction changes one immutable operation at a time. Revalidating
    # every unchanged created Object on every intermediate state is quadratic.
    # Retain the operation with its result so an identity key cannot be reused.
    def build():
        return op, Object(
            uid=op.uid, native_id='', kind=op.shape.kind, shape=op.shape,
            properties=[['colayoutObjectId', 'string', ['string', op.uid]],
                        ['colayoutNetIntent', 'string', ['string', op.shape.net_intent or '']]],
        )
    return _operation_object_cache.get(baseline, id(op), build)[1]


def _updated_object(baseline, op, obj):
    def build():
        return op, obj, obj.model_copy(update={
            'shape': op.shape,
            'properties': intent_properties(obj.properties, op.shape.net_intent),
        })
    return _operation_object_cache.get(baseline, ('update', id(op), id(obj)), build)[2]


@dataclass(frozen=True)
class _HistoryEntry:
    workspace: Workspace
    # A verified transform from the current state to this history target.
    # Keeping its proof avoids guessing a rigid pose from bbox differences.
    region_matrices: dict = field(default_factory=dict)
    after: Workspace | None = None
    key: str = field(default_factory=lambda:uuid4().hex)


def intent_properties(properties, intent):
    return [deepcopy(p) for p in properties if p[0] != 'colayoutNetIntent'] + [
        ['colayoutNetIntent', 'string', ['string', intent or '']]
    ]


def projected(w, *, text_owners=None):
    # Published workspaces are immutable. Return a fresh mapping so consumers
    # cannot change another query's projection; retain custom owner maps too.
    key = id(text_owners) if text_owners is not None else None
    return dict(_projection_cache.get(w, key,
        lambda: (text_owners, _projected(w, text_owners=text_owners)))[1])


def _projected(w, *, text_owners=None):
    objects = dict(w.baseline.objects)
    for op in w.operations:
        if op.action == 'create':
            objects[op.uid] = _created_object(w.baseline, op)
        elif op.action == 'update':
            o = objects[op.uid]
            objects[op.uid] = _updated_object(w.baseline, op, o)
        elif op.action == 'transform':
            from .mpp import placed

            obj = objects[op.uid]
            objects[op.uid] = (
                placed(obj, op.placement)
                if obj.mpp
                else obj.model_copy(update={'placement': op.placement})
            )
        elif op.action == 'delete':
            objects.pop(op.uid)
        elif op.action == 'delete_guard':
            objects = {k: o for k, o in objects.items() if o.group_uid != op.uid}
        elif op.action == 'guard':
            for uid, o in w.guard_previews[op.uid]['objects'].items():
                objects[uid] = Object.model_validate(o)
            if op.placement:
                from .mpp import placed

                objects[op.uid] = placed(objects[op.uid], op.placement)
    from .geometry import ORIENT, compose, transform, box

    owners = w.baseline.text_owners if text_owners is None else text_owners
    moved = {op.uid for op in w.operations if op.action == 'transform'}
    for uid, parent in owners.items():
        if parent not in moved or uid not in objects:
            continue
        before = w.baseline.objects[parent].placement
        after = objects[parent].placement
        a, b, c, d = ORIENT[before.orientation]
        x, y = before.origin
        inverse = (a, c, b, d, -a * x - c * y, -b * x - d * y)
        delta = compose(transform(after.origin, after.orientation), inverse)
        o = objects[uid]
        if o.bbox:
            objects[uid] = o.model_copy(update={'bbox': box(o.bbox, delta)})
    return objects


class Editor:
    @property
    def w(self):
        return self._workspace

    @w.setter
    def w(self, value):
        previous = getattr(self, '_workspace', None)
        if previous is not None and hasattr(self, 'work_sessions'):
            self.work_sessions.check_replacement(previous, value)
        if previous is not None and value.baseline is not previous.baseline:
            # A new native baseline is a history boundary; local Undo must
            # never resurrect a snapshot from before an acknowledged sync.
            self._undo = []
            self._redo = []
        self._workspace = value

    def __init__(self, workspace, profile, *, scope_id=None):
        if workspace.baseline.technology_fingerprint != profile.native_fingerprint:
            raise LiteError('TECHNOLOGY_MISMATCH')
        self.w = workspace
        self.profile = profile
        self._undo = []
        self._redo = []
        self._listeners = []
        self._batch_transforms = None
        self.scope_id = scope_id
        from .work_sessions import WorkSessions

        self.work_sessions = WorkSessions(self)

    def subscribe(self, callback):
        """View adapters observe the same committed local state as callers."""
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback) if callback in self._listeners else None

    def _notify(self, before):
        if self.work_sessions.defer_workspace_notification(before):
            return
        old = {op.uid: op for op in before.operations}
        new = {op.uid: op for op in self.w.operations}
        changed = {uid for uid in old.keys() | new.keys() if old.get(uid) != new.get(uid)}
        for callback in tuple(self._listeners):
            try:
                callback(changed)
            except Exception:
                import logging

                logging.getLogger(__name__).exception('Workspace view notification failed')

    def set_instance_display(self, uid, mode, display=None):
        if uid not in self.w.baseline.objects or self.w.baseline.objects[uid].kind not in (
            'inst',
            'mosaic',
        ):
            raise LiteError('EXPECTED_INSTANCE')
        if mode not in ('auto', 'full', 'box_pins'):
            raise LiteError('INVALID_DISPLAY_MODE')
        old = self.w.baseline
        new = old.model_copy(update={'display': display}) if display is not None else old
        choices = {**self.w.instance_display, uid: mode}

        def display_state(w):
            return w.model_copy(
                update={
                    'baseline': new if w.baseline is old else w.baseline,
                    'instance_display': choices,
                }
            )

        self._workspace = display_state(self.w)
        self._undo = [
            replace(entry, workspace=display_state(entry.workspace),after=display_state(entry.after) if entry.after is not None else None) for entry in self._undo
        ]
        self._redo = [
            replace(entry, workspace=display_state(entry.workspace),after=display_state(entry.after) if entry.after is not None else None) for entry in self._redo
        ]

    def publish(self, w, *, region_transforms=None):
        """Publish a trusted local candidate through validation and one undo step.

        Application services call this after staging edits with Editor. This is
        not a protocol endpoint: external callers continue to use Actions.
        """
        if self.work_sessions.snapshots() and w.baseline is not self.w.baseline:
            self.work_sessions.require_idle()
        if (
            region_transforms
            or (w.operations != self.w.operations or w.guard_previews != self.w.guard_previews)
            and (
                w.local_data.regions
                or w.local_data.keepouts
                or w.local_data.native_blocked_layers
                or w.local_data.native_routing_windows
                or (
                    w.layout_connectivity
                    and any(i.black_box for i in w.layout_connectivity.instances.values())
                )
            )
        ):
            from .regions.constraints import validate_edit

            w = validate_edit(
                self.w, w, self.profile, self.scope_id, region_transforms=region_transforms
            )
        if (
            w.local_data.groups
            or w.local_data.pins
            or w.local_data.annotations
            or w.local_data.regions
            or w.local_data.native_blocked_layers
            or w.local_data.native_routing_windows
        ):
            from .local_models import require_references

            require_references(w.local_data, projected(w))
        from .geometry import rigid_matrix
        from .work_sessions import inverse

        matrices = {ident: rigid_matrix(*spec) for ident, spec in (region_transforms or {}).items()}
        self.work_sessions.validate(self.w, w, region_matrices=matrices)
        if self._batch_transforms is not None:
            from .geometry import compose
            for ident,matrix in matrices.items():
                self._batch_transforms[ident]=compose(matrix,self._batch_transforms.get(ident,(1,0,0,1,0,0)))
        before = self.w
        self._undo.append(
            _HistoryEntry(self.w, {ident: inverse(matrix) for ident, matrix in matrices.items()})
        )
        self._redo.clear()
        if before.baseline is not w.baseline:
            self._undo.clear()  # Preserve the native-baseline history boundary.
        self._workspace = w.model_copy(
            update={
                'revision': self.w.revision + 1,
                'state': 'editing' if w.operations else 'clean',
                'last_result': {},
            }
        )
        if self._undo:self._undo[-1]=replace(self._undo[-1],after=self._workspace)
        self.work_sessions.moved(before, matrices)
        self._notify(before)

    def check_revision(self, revision=None):
        if self.w.state in ('submitting', 'indeterminate', 'conflict'):
            raise LiteError('WORKSPACE_REQUIRES_RECOVERY')
        if revision is not None and revision != self.w.revision:
            raise LiteError('STALE_REVISION')

    @contextmanager
    def transaction(self, *, expected_revision=None):
        """Stage a local batch; a failure publishes nothing, success is one undo."""
        self.check_revision(expected_revision)
        source = self.w
        staged = Editor(source, self.profile, scope_id=self.scope_id)
        staged._batch_transforms = {}
        yield staged
        if self.w is not source or self.scope_id != staged.scope_id:
            raise LiteError('STALE_REVISION', '工作区或编辑层已变化，未采用本次操作。')
        if staged.w is not source:
            from .geometry import ORIENT
            orientations={matrix:name for name,matrix in ORIENT.items()}
            transforms={ident:((matrix[4],matrix[5]),orientations[matrix[:4]],(0,0))
                for ident,matrix in staged._batch_transforms.items()}
            candidate=staged.w
            if transforms:
                from .regions.query import descendants
                moved=set().union(*(descendants(source,ident) for ident in transforms))
                regions={ident:row.model_copy(update={'revision':source.local_data.regions[ident].revision+1,'interface_revision':source.local_data.regions[ident].interface_revision+1}) if ident in moved else row
                    for ident,row in candidate.local_data.regions.items()}
                candidate=candidate.model_copy(update={'local_data':candidate.local_data.model_copy(update={'regions':regions})})
            self.publish(candidate,region_transforms=transforms or None)

    def history_token(self):
        """Opaque identity of the last edit, for guarded region-owner undo."""
        return self._undo[-1] if self._undo else None

    def undo_owned(self,token):
        token=next((entry for entry in self._undo if entry.key==getattr(token,'key',None)),None)
        if token is None:
            raise LiteError('UNDO_NOT_LATEST','此编辑已不在当前撤销历史中。')
        if self.history_token() is token:
            self.undo();return
        from .workspace_delta import merge
        from .geometry import ORIENT
        if token.after is None:raise LiteError('UNDO_NOT_LATEST')
        candidate=merge(token.after,token.workspace,self.w)
        orientations={matrix:name for name,matrix in ORIENT.items()}
        transforms={ident:((m[4],m[5]),orientations[m[:4]],(0,0)) for ident,m in token.region_matrices.items()}
        self.publish(candidate,region_transforms=transforms or None)

    # Frozen Agent callers retain their existing internal entry points during
    # this maintenance pass. Remove only as part of the future Agent redesign.
    def _publish(self, w, *, region_transforms=None):
        return self.publish(w, region_transforms=region_transforms)

    def _check_revision(self, revision):
        return self.check_revision(revision)

    def apply(self, operations, *, expected_revision=None):
        self.check_revision(expected_revision)
        working = self.w
        objects = projected(working)
        touched = set()
        existing = {p.uid: p for p in working.operations}
        for value in operations:
            op = Operation.model_validate(
                value.model_dump() if isinstance(value, Operation) else value
            )
            # Distinct owners are independent; only repeated owners and
            # attached native text need the intermediate projection. This
            # retains sequential semantics without O(batch²) reconstruction.
            if objects is None or op.uid in touched or op.uid in working.baseline.text_owners:
                objects = projected(working)
            obj = objects.get(op.uid)
            if op.action == 'create':
                if obj or op.uid in working.baseline.objects:
                    raise LiteError('UID_EXISTS', op.uid)
                self.profile.check(op.shape)
                if op.shape.kind == 'stdVia':
                    op = op.model_copy(
                        update={
                            'shape': op.shape.model_copy(
                                update={'via_parameters': self.profile.effective_via(op.shape)}
                            )
                        }
                    )
            elif op.action in ('update', 'delete', 'transform'):
                if not obj:
                    raise LiteError('UID_MISSING', op.uid)
                deleting = op.action == 'delete' and (
                    delete_exception(obj) or (obj.mpp and obj.deletion_allowed)
                )
                if obj.read_only_reason and not deleting:
                    raise LiteError('OBJECT_READ_ONLY', obj.read_only_reason)
                if op.before != digest(obj.semantic()):
                    raise LiteError('OBJECT_CONFLICT', op.uid)
                if op.action == 'transform':
                    if obj.kind not in ('inst', 'mpp'):
                        raise LiteError('EXPECTED_INSTANCE_OR_MPP')
                    if any(v % self.profile.grid for v in op.placement.origin):
                        raise LiteError('OFF_GRID')
                else:
                    if obj.kind == 'inst' or (
                        not obj.shape and not deleting and not (obj.mpp and op.action == 'delete')
                    ):
                        raise LiteError('INSTANCE_OR_OPAQUE_READ_ONLY')
                    if obj.mpp and op.action == 'delete' and not obj.deletion_allowed:
                        raise LiteError('MPP_DELETE_READ_ONLY')
                    if op.action == 'update':
                        if obj.kind != op.shape.kind:
                            raise LiteError('TYPE_CHANGE_REQUIRES_REPLACEMENT')
                        self.profile.check(op.shape)
                        if op.shape.kind == 'stdVia':
                            op = op.model_copy(
                                update={
                                    'shape': op.shape.model_copy(
                                        update={
                                            'via_parameters': self.profile.effective_via(op.shape)
                                        }
                                    )
                                }
                            )
                if op.action == 'delete':
                    local = working.local_data
                    if any(
                        op.uid in item.object_uids
                        for item in (
                            *local.groups.values(),
                            *local.pins.values(),
                            *local.annotations.values(),
                        )
                    ):
                        raise LiteError(
                            'LOCAL_OBJECT_REFERENCED', '请先移除本地分组/标注引用。', uid=op.uid
                        )
            else:
                raise LiteError('USE_GUARD_API')
            if op.action == 'update' and obj.shape == op.shape:
                continue
            if op.action == 'transform' and obj.placement == op.placement:
                continue
            prior = existing.get(op.uid)
            if prior and prior.action == 'guard':
                if op.action == 'delete':
                    existing.pop(op.uid)
                    working = working.model_copy(
                        update={
                            'guard_previews': {
                                k: v for k, v in working.guard_previews.items() if k != op.uid
                            }
                        }
                    )
                    objects = None  # A generated group can contain other owners.
                elif op.action == 'transform':
                    existing[op.uid] = prior.model_copy(update={'placement': op.placement})
                else:
                    raise LiteError('MPP_INTERNAL_READ_ONLY')
            elif prior and prior.action == 'create':
                if op.action == 'delete':
                    existing.pop(op.uid)
                else:
                    existing[op.uid] = prior.model_copy(update={'shape': op.shape})
            else:
                if op.uid in working.baseline.objects:
                    op = op.model_copy(
                        update={'before': digest(working.baseline.objects[op.uid].semantic())}
                    )
                existing[op.uid] = op
            working = working.model_copy(update={'operations': tuple(existing.values())})
            touched.add(op.uid)
        if (
            working.operations != self.w.operations
            or working.guard_previews != self.w.guard_previews
        ):
            self.publish(working)
        return self.w

    def object(self, uid):
        obj = projected(self.w).get(uid)
        if obj is None:
            raise LiteError('UID_MISSING', '对象不存在或已被删除，请重新选择', uid=uid)
        return obj

    def create(self, shape, *, uid=None):
        op = Operation(
            action='create',
            uid=uid or str(uuid4()),
            shape=Shape.model_validate(shape.model_dump() if isinstance(shape, Shape) else shape),
        )
        self.apply([op])
        return op.uid

    def edit(self, uid, **changes):
        o = self.object(uid)
        if not o.shape:
            raise LiteError('NOT_EDITABLE_SHAPE')
        data = o.shape.model_dump()
        if o.kind == 'pathSeg':
            from .pathseg import resize_caps

            resize_caps(o.shape, changes, self.profile.grid)
        if o.kind == 'pathSeg' and 'width' in changes:
            for side in ('begin', 'end'):
                style = changes.get(side + '_style', data[side + '_style'])
                if style not in ('variable', 'custom') and side + '_extension' not in changes:
                    changes[side + '_extension'] = 0
        if 'via_parameters' in changes:
            changes['via_parameters'] = {**data['via_parameters'], **changes['via_parameters']}
        data.update(changes)
        self.apply(
            [
                Operation(
                    action='update',
                    uid=uid,
                    before=digest(o.semantic()),
                    shape=Shape.model_validate(data),
                )
            ]
        )

    def reset_via_parameters(self, uid, names):
        o = self.object(uid)
        defaults = self.profile.vias[o.shape.via_definition]['defaults']
        self.edit(uid, via_parameters={name: defaults[name] for name in names})

    def replace_via_definition(self, uid, definition, *, parameters=None):
        """Explicit definition switch uses the new definition's defaults."""
        o = self.object(uid)
        if not o.shape or o.kind != 'stdVia':
            raise LiteError('EXPECTED_STANDARD_VIA')
        shape = Shape(
            kind='stdVia',
            origin=o.shape.origin,
            orientation=o.shape.orientation,
            via_definition=definition,
            via_parameters=parameters or {},
            net_intent=o.shape.net_intent,
        )
        self.apply([Operation(action='update', uid=uid, before=digest(o.semantic()), shape=shape)])

    def delete(self, uid):
        o = self.object(uid)
        self.apply([Operation(action='delete', uid=uid, before=digest(o.semantic()))])

    def place(self, uid, origin, orientation=None):
        o = self.object(uid)
        if not o.placement:
            raise LiteError('EXPECTED_INSTANCE')
        self.apply(
            [
                Operation(
                    action='transform',
                    uid=uid,
                    before=digest(o.semantic()),
                    placement=Placement(
                        origin=origin, orientation=orientation or o.placement.orientation
                    ),
                )
            ]
        )

    def transform_shape(self, uid, **kwargs):
        o = self.object(uid)
        if not o.shape:
            raise LiteError('NOT_EDITABLE_SHAPE')
        s = transform_shape(o.shape, **kwargs)
        self.apply([Operation(action='update', uid=uid, before=digest(o.semantic()), shape=s)])

    def copy_shape(self, uid, **kwargs):
        o = self.object(uid)
        if o.read_only_reason or not o.shape:
            raise LiteError('OBJECT_READ_ONLY')
        return self.create(transform_shape(o.shape, **kwargs))

    def delete_guard(self, uid):
        self.check_revision(None)
        obj = projected(self.w).get(uid)
        if obj and obj.mpp:
            return self.delete(uid)
        if not any(o.group_uid == uid for o in projected(self.w).values()):
            raise LiteError('GROUP_MISSING')
        ops = {p.uid: p for p in self.w.operations}
        previews = dict(self.w.guard_previews)
        if uid in previews:
            ops.pop(uid)
            previews.pop(uid)
        else:
            ops[uid] = Operation(action='delete_guard', uid=uid)
        self.publish(
            self.w.model_copy(
                update={'operations': tuple(ops.values()), 'guard_previews': previews}
            )
        )

    def undo(self):
        self.check_revision(None)
        self._restore_history(self._undo, self._redo)
        return self.w

    def redo(self):
        self.check_revision(None)
        self._restore_history(self._redo, self._undo)
        return self.w

    def _restore_history(self, source, destination):
        if not source:
            return
        from .work_sessions import inverse

        entry = source[-1]
        before = self.w
        self.work_sessions.validate(before, entry.workspace, region_matrices=entry.region_matrices)
        source.pop()
        destination.append(
            _HistoryEntry(
                before, {ident: inverse(matrix) for ident, matrix in entry.region_matrices.items()}
            )
        )
        self._workspace = entry.workspace.model_copy(update={'revision': before.revision + 1})
        self.work_sessions.moved(before, entry.region_matrices)
        self._notify(before)

    def discard(self):
        """Discard local intent only; ordinary undo can restore it in-session."""
        self.check_revision(None)
        self.publish(self.w.model_copy(update={'operations': (), 'guard_previews': {}}))
        return self.w

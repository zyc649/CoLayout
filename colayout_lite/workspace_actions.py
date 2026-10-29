"""Shared local editing entry point for GUI and scripts, backed by one Editor."""

from uuid import uuid4, uuid5, NAMESPACE_URL
from .actions import Actions, dbu
from .editor import Editor, projected
from .geometry import ORIENT, compose, transform, box
from .local_models import LocalData, LocalGroup, LocalPin, LocalAnnotation
from .model import LiteError


def pin_view(workspace):
    return {
        p.name: {'net': p.net, 'lpp': list(p.lpp), 'bbox': [list(x) for x in p.bbox]}
        for p in workspace.local_data.pins.values()
    }


def import_legacy_pins(workspace, pins):
    """One-time migration of old Agent sidecars; never overwrite canonical data."""
    if not pins:
        return workspace
    if workspace.local_data.pins:
        if pin_view(workspace) != pins:
            raise LiteError('LOCAL_PIN_MIGRATION_CONFLICT')
        return workspace
    records = {}
    for name, data in pins.items():
        ident = str(uuid5(NAMESPACE_URL, workspace.id + '/pin/' + name))
        records[ident] = LocalPin(id=ident, name=name, **data)
    return workspace.model_copy(
        update={'local_data': workspace.local_data.model_copy(update={'pins': records})}
    )


def group_bounds(workspace, group):
    objects = projected(workspace)
    bounds = []
    for uid in group.object_uids:
        obj = objects.get(uid)
        if obj is None:
            raise LiteError('GROUP_MEMBER_MISSING', uid)
        if obj.bbox is None:
            continue
        original = workspace.baseline.objects.get(uid)
        if original and original.placement and obj.placement:
            a, b, c, d = ORIENT[original.placement.orientation]
            x, y = original.placement.origin
            delta = compose(
                transform(obj.placement.origin, obj.placement.orientation),
                (a, c, b, d, -a * x - c * y, -b * x - d * y),
            )
            bounds.append(box(original.bbox, delta))
        else:
            bounds.append(obj.bbox)
    if not bounds:
        raise LiteError('GROUP_BOUNDS_MISSING')
    return (
        (min(b[0][0] for b in bounds), min(b[0][1] for b in bounds)),
        (max(b[1][0] for b in bounds), max(b[1][1] for b in bounds)),
    )


class WorkspaceActions:
    def __init__(self, editor):
        self.editor = editor

    def _publish(self, local, expected_revision=None):
        self.editor.check_revision(expected_revision)
        local = LocalData.model_validate(local.model_dump())
        if local != self.editor.w.local_data:
            self.editor.publish(self.editor.w.model_copy(update={'local_data': local}))

    def create_group(self, name, object_uids, *, expected_revision=None):
        self.editor.check_revision(expected_revision)
        objects = projected(self.editor.w)
        uids = tuple(dict.fromkeys(object_uids))
        if not uids or any(uid not in objects or objects[uid].kind != 'inst' for uid in uids):
            raise LiteError('GROUP_EXPECTS_INSTANCES', '分组请选择已有器件/模块实例。')
        local = self.editor.w.local_data
        if any(set(g.object_uids) & set(uids) for g in local.groups.values()):
            raise LiteError('GROUP_MEMBER_ALREADY_ASSIGNED', '本版分组不嵌套或重叠。')
        if any(g.name == name for g in local.groups.values()):
            raise LiteError('GROUP_NAME_EXISTS', name)
        ident = str(uuid4())
        group = LocalGroup(id=ident, name=name, object_uids=uids)
        group_bounds(self.editor.w, group)
        self._publish(
            local.model_copy(update={'groups': {**local.groups, ident: group}}), expected_revision
        )
        return ident

    def set_pin(
        self,
        name,
        net,
        layer,
        x,
        y,
        width,
        height,
        *,
        group_id=None,
        object_uids=(),
        expected_revision=None,
    ):
        self.editor.check_revision(expected_revision)
        w = self.editor.w
        p = self.editor.profile
        local = w.local_data
        if group_id:
            if group_id not in local.groups:
                raise LiteError('LOCAL_GROUP_MISSING', group_id)
            object_uids = local.groups[group_id].object_uids
        if set(object_uids) - set(projected(w)):
            raise LiteError('LOCAL_REFERENCE_MISSING')
        if w.layout_connectivity:
            ports = w.layout_connectivity.ports
            if any(name == t.name or name in t.members for t in ports.values()):
                raise LiteError(
                    'NATIVE_PIN_NAME_RESERVED', '请为本地 PIN 使用不同名称，原生端口保持不变。'
                )
            nets = {
                n
                for i in w.layout_connectivity.instances.values()
                for t in i.terminals.values()
                for n in (t.members or {t.name: t.net}).values()
                if n
            }
            nets.update(
                n for t in ports.values() for n in (t.members or {t.name: t.net}).values() if n
            )
            if net not in nets:
                raise LiteError('UNKNOWN_LAYOUT_NET', net)
        if (layer, 'drawing') not in p.writable_lpps:
            raise LiteError('LAYER_NOT_WRITABLE', layer)
        if not any(row['layer'] == layer and row.get('material') == 'metal' for row in p.layers):
            raise LiteError('PIN_LAYER_NOT_METAL', layer)
        x, y, width, height = (dbu(v, p) for v in (x, y, width, height))
        if width <= 0 or height <= 0:
            raise LiteError('INVALID_PIN_SIZE')
        old = next((pin for pin in local.pins.values() if pin.name == name), None)
        ident = old.id if old else str(uuid4())
        pin = LocalPin(
            id=ident,
            name=name,
            net=net,
            lpp=(layer, 'drawing'),
            bbox=((x, y), (x + width, y + height)),
            group_id=group_id if group_id is not None else old.group_id if old else None,
            object_uids=tuple(object_uids) or (old.object_uids if old else ()),
        )
        self._publish(
            local.model_copy(update={'pins': {**local.pins, ident: pin}}), expected_revision
        )
        return ident

    def delete_pin(self, name, *, expected_revision=None):
        local = self.editor.w.local_data
        if not any(p.name == name for p in local.pins.values()):
            raise LiteError('LOCAL_PIN_MISSING', name)
        self._publish(
            local.model_copy(
                update={'pins': {k: p for k, p in local.pins.items() if p.name != name}}
            ),
            expected_revision,
        )

    def annotate(self, text, *, kind='note', group_id=None, object_uids=(), expected_revision=None):
        self.editor.check_revision(expected_revision)
        local = self.editor.w.local_data
        if group_id:
            if group_id not in local.groups:
                raise LiteError('LOCAL_GROUP_MISSING', group_id)
            object_uids = local.groups[group_id].object_uids
        if set(object_uids) - set(projected(self.editor.w)):
            raise LiteError('LOCAL_REFERENCE_MISSING')
        old = next(
            (
                a
                for a in local.annotations.values()
                if group_id and a.group_id == group_id and a.kind == kind
            ),
            None,
        )
        ident = old.id if old else str(uuid4())
        item = LocalAnnotation(
            id=ident, text=text, kind=kind, group_id=group_id, object_uids=tuple(object_uids)
        )
        self._publish(
            local.model_copy(update={'annotations': {**local.annotations, ident: item}}),
            expected_revision,
        )
        return ident

    def set_instructions(self, text, *, expected_revision=None):
        self._publish(
            self.editor.w.local_data.model_copy(update={'instructions': text}), expected_revision
        )

    def set_group_text(self, group_id, note, requirement, *, expected_revision=None):
        self.editor.check_revision(expected_revision)
        candidate = Editor(self.editor.w, self.editor.profile, scope_id=self.editor.scope_id)
        api = WorkspaceActions(candidate)
        api.annotate(note, group_id=group_id, kind='note')
        api.annotate(requirement, group_id=group_id, kind='requirement')
        if candidate.w.local_data != self.editor.w.local_data:
            self.editor.publish(candidate.w)

    def remove_group(self, group_id, *, expected_revision=None):
        local = self.editor.w.local_data
        if group_id not in local.groups:
            raise LiteError('LOCAL_GROUP_MISSING', group_id)
        self._publish(
            local.model_copy(
                update={
                    'groups': {k: g for k, g in local.groups.items() if k != group_id},
                    'pins': {
                        k: p.model_copy(update={'group_id': None}) if p.group_id == group_id else p
                        for k, p in local.pins.items()
                    },
                    'annotations': {
                        k: a.model_copy(update={'group_id': None}) if a.group_id == group_id else a
                        for k, a in local.annotations.items()
                    },
                }
            ),
            expected_revision,
        )

    def remove_annotation(self, annotation_id, *, expected_revision=None):
        local = self.editor.w.local_data
        if annotation_id not in local.annotations:
            raise LiteError('LOCAL_ANNOTATION_MISSING')
        self._publish(
            local.model_copy(
                update={
                    'annotations': {
                        k: a for k, a in local.annotations.items() if k != annotation_id
                    }
                }
            ),
            expected_revision,
        )

    def move_group(self, group_id, dx, dy, *, expected_revision=None):
        self.editor.check_revision(expected_revision)
        group = self.editor.w.local_data.groups.get(group_id)
        if group is None:
            raise LiteError('LOCAL_GROUP_MISSING', group_id)
        xd, yd = dbu(dx, self.editor.profile), dbu(dy, self.editor.profile)
        if not xd and not yd:
            return self.editor.w
        candidate = Editor(self.editor.w, self.editor.profile, scope_id=self.editor.scope_id)
        api = Actions(candidate)
        for uid in group.object_uids:
            api.execute('move', {'dx': dx, 'dy': dy}, uid)
        pins = {
            key: (
                pin.model_copy(update={'bbox': tuple((x + xd, y + yd) for x, y in pin.bbox)})
                if pin.group_id == group_id
                else pin
            )
            for key, pin in candidate.w.local_data.pins.items()
        }
        local = LocalData.model_validate(
            candidate.w.local_data.model_copy(update={'pins': pins}).model_dump()
        )
        self.editor.publish(candidate.w.model_copy(update={'local_data': local}))
        return self.editor.w

    def geometry_batch(self, operations):
        """Existing geometry Actions, staged into one shared undo step."""
        if not isinstance(operations, list) or not operations:
            raise LiteError('EMPTY_BATCH')
        changed = set()
        results = []
        with self.editor.transaction() as candidate:
            api = Actions(candidate)
            for row in operations:
                if row.get('action') in ('create_guard', 'create_mpp'):
                    raise LiteError('LOCAL_TOOLS_ONLY')
                result = api.execute(row['action'], row.get('params', {}), row.get('uid'))
                changed.update(result.changed_uids)
                results.append(
                    {'action': row['action'], 'uid': result.uid, 'changed': result.changed}
                )
        return {
            'operations': results,
            'changed_uids': sorted(changed),
            'pending_operations': len(self.editor.w.operations),
        }

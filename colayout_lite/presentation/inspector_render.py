"""Read-only inspector selection context and small rendering stages."""

from dataclasses import dataclass
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import QListWidgetItem
from ..editor import projected
from ..human_edit import HumanEdit
from ..model import LiteError
from ..regions.query import owner_map, object_bounds, metals
from ..routing_policy import blocked_layers
from .panel_helpers import _scope_name, _locked


@dataclass(frozen=True)
class SelectionContext:
    editor: object
    uid: str | None
    region: object
    box: object
    native: object
    pin: object
    selected_ids: object
    native_module: object
    owner: str | None

    @classmethod
    def current(cls, panel, uid, ids):
        e = panel.window.editor
        w = e.w
        local = w.local_data
        region = local.regions.get(uid)
        box = local.markups.get(uid) or local.keepouts.get(uid)
        native = projected(w).get(uid)
        pin = region.pins.get(panel._pin) if region else None
        selected_ids = ids if panel._target is None else (uid,) if uid else ()
        native_module = (
            w.layout_connectivity.instances.get(uid) if w.layout_connectivity and native else None
        )
        owner = (
            region.parent_id
            if region
            else box.scope_id
            if box
            else owner_map(w).get(uid)
            if native
            else None
        )
        return cls(e, uid, region, box, native, pin, selected_ids, native_module, owner)


def render(panel, uid, ids):
    context = SelectionContext.current(panel, uid, ids)
    panel.transform_buttons['rotate'].setText(
        '旋转 90° · ' + panel.window.shortcuts.values['rotate']
    )
    render_common(panel, context)
    render_details(panel, context)
    editable = render_permissions(panel, context)
    render_policy(panel, context, editable)


def render_common(panel, c):
    e = c.editor
    w = e.w
    local = w.local_data
    uid, region, box, native, pin = c.uid, c.region, c.box, c.native, c.pin
    selected_ids, native_module = c.selected_ids, c.native_module
    rectangle = bool(native and native.kind == 'rect' and native.shape)
    panel._copy_text = pin.id if pin else uid or '\n'.join(selected_ids)
    panel.identity.setText(
        f'{len(selected_ids)} 个对象' if len(selected_ids) > 1 and not uid else panel._copy_text
    )
    panel.identity.setCursorPosition(0)
    panel.identity.setToolTip(panel._copy_text)
    panel.copy.setEnabled(bool(panel._copy_text))
    panel.name_box.setVisible(bool(region) and not pin)
    panel.pin_mode.setVisible(bool(region) and not pin)
    with QSignalBlocker(panel.pin_mode):
        panel.pin_mode.setCurrentIndex(
            panel.pin_mode.findData(region.pin_mode if region else 'fixed')
        )
    panel.pin_box.setVisible(pin is not None)
    panel.frame_actions.setVisible(bool(region or box or rectangle) and not pin)
    panel.rect_size.setVisible(rectangle)
    if rectangle:
        (x, y), (xx, yy) = native.shape.bbox
        scale = e.profile.dbu_per_micron
        panel.rect_width.setValue((xx - x) / scale)
        panel.rect_height.setValue((yy - y) / scale)
        panel.rect_width.setSingleStep(e.profile.grid / scale)
        panel.rect_height.setSingleStep(e.profile.grid / scale)
    panel.enter.setVisible(bool(region))
    panel.remove.setVisible(
        bool(region or box or native and (native.shape or native.mpp)) and not pin
    )
    panel.region_checks.setVisible(bool(region) and not pin)
    panel.cleanup_box.setVisible(bool(region) and not pin)
    panel.cleanup_box.setEnabled(
        bool(region)
        and not panel.window.busy
        and w.state not in ('submitting', 'indeterminate', 'conflict')
        and not _locked(e, uid)
        and (uid == e.scope_id or region.parent_id == e.scope_id)
    )
    panel.check_local.setEnabled(not panel.window.busy and not panel.window.drc.job_id)
    panel.check_remote.setEnabled(
        not panel.window.busy
        and not panel.window.drc.job_id
        and getattr(panel.window, 'remote_enabled', True)
    )
    panel.remove.setText(
        '解散操作区'
        if region
        else '删除定位框'
        if uid in local.markups
        else '删除禁布区'
        if box
        else '删除保护环'
        if native and native.mpp
        else '删除矩形'
        if rectangle
        else '删除互连'
    )
    panel.hint.setText('拖动当前层对象可移动；Shift 点击可追加选择。')
    panel.status.clear()
    panel.message.clear()
    panel._policy_target = (
        ('area', uid) if region else ('keepout', uid) if uid in local.keepouts else None
    )
    if native_module and native_module.black_box:
        panel._policy_target = ('native', uid)
        panel.hint.clear()


def render_details(panel, c):
    e = c.editor
    w = e.w
    local = w.local_data
    uid, region, box, native, pin = c.uid, c.region, c.box, c.native, c.pin
    selected_ids, native_module, owner = c.selected_ids, c.native_module, c.owner
    item = region or box or native
    rectangle = bool(native and native.kind == 'rect' and native.shape)
    if item:
        kind = (
            '本地模块'
            if region
            else '定位框'
            if uid in local.markups
            else '禁布区'
            if box
            else 'Virtuoso 模块'
            if native_module and native_module.black_box
            else '保护环'
            if native.mpp and native.attributes.get('form') == 'guardring'
            else '复合路径'
            if native.mpp
            else '器件'
            if native.kind == 'inst'
            else '矩形'
            if rectangle
            else '互连'
        )
        name = (
            pin.name
            if pin
            else region.name
            if region
            else native.attributes.get('name', '')
            if native
            else ''
        )
        panel.title.setText(name or kind)
        panel.subtitle.setText('本地接口 PIN' if pin else kind)
        bounds = region.bbox if region else box.bbox if box else object_bounds(w, native, e.profile)
        lines = ['所属层 · ' + _scope_name(w, owner)]
        master = (
            native_module.master
            if native_module
            else native.attributes.get('master')
            if native and native.kind in ('inst', 'mosaic')
            else None
        )
        if isinstance(master, (tuple, list)) and len(master) >= 2:
            lines.extend(('库 · ' + str(master[0]), 'Cell · ' + str(master[1])))
        if rectangle:
            lines.append('绘制层 · ' + native.shape.lpp[0])
        if native and native.mpp:
            from ..guard_ports import names

            nets = names(native, e.profile)
            lines.append('网络 · ' + (' / '.join(sorted(nets)) if nets else '未指定'))
            layers = {part['lpp'][0] for part in native.mpp.parts if part.get('lpp')}
            if native.mpp.master:
                layers.add(native.mpp.master.lpp[0])
            if layers:
                lines.append('图层 · ' + ', '.join(sorted(layers)))
        if bounds:
            (x, y), (xx, yy) = bounds
            scale = e.profile.dbu_per_micron
            lines.append(f'尺寸 · {(xx - x) / scale:g} × {(yy - y) / scale:g} µm')
        if region:
            lines.append(f'{len(region.object_uids)} 个直属对象 · {len(region.pins)} 个接口 PIN')
            from ..regions.query import boundary

            pending = boundary(w, region.id).get('deferred', [])
            names = [row['net'] for row in pending if pin is None or row['net'] == pin.net]
            if names:
                lines.append(
                    '待补实体接入 · '
                    + ', '.join(names)
                    + '\n可先建区；后续补充原生 PIN 或保护环接口。'
                )
            panel.name.setText(region.name)
        if native and native.placement:
            lines.append('方向 · ' + native.placement.orientation)
        panel.details.setText('\n'.join(lines))
        if owner != e.scope_id and uid != e.scope_id:
            panel.hint.setText('当前仅查看属性。进入所属层后可编辑该对象。')
    elif len(selected_ids) > 1:
        panel.title.setText(f'已选择 {len(selected_ids)} 个对象')
        panel.subtitle.setText('多选')
        panel.details.setText('当前层 · ' + _scope_name(w, e.scope_id))
        panel.hint.setText('拖动任一已选对象可整体移动；Shift 点击可增减选择。')
    else:
        panel.title.setText('工作区属性')
        panel.subtitle.setText('当前层 · ' + _scope_name(w, e.scope_id))
        panel.details.setText(f'{len(projected(w))} 个版图对象\n{len(local.regions)} 个本地模块')
        panel.hint.setText(
            '在画布选择对象以查看属性和复制 ID。\n拖出操作区后，接口 PIN 会自动排布。'
        )


def render_permissions(panel, c):
    e = c.editor
    w = e.w
    uid, region, box, native, pin = c.uid, c.region, c.box, c.native, c.pin
    selected_ids, owner = c.selected_ids, c.owner
    item = region or box or native
    rectangle = bool(native and native.kind == 'rect' and native.shape)
    editable_ids = selected_ids if selected_ids else ()
    try:
        kinds = [HumanEdit(e).kind(ident) for ident in editable_ids]
    except LiteError:
        kinds = []
    transform_ok = bool(kinds) and all(k in ('area', 'instance', 'mpp') for k in kinds)
    writable = not panel.window.busy and w.state not in ('submitting', 'indeterminate', 'conflict')
    transform_ok &= (
        not pin
        and writable
        and not any(_locked(e, ident, action='transform') for ident in editable_ids)
    )
    panel.transforms.setVisible(
        bool(kinds) and all(k in ('area', 'instance', 'mpp') for k in kinds) and not pin
    )
    for button in panel.transform_buttons.values():
        button.setEnabled(bool(transform_ok))
    reason = _locked(e, pin.id if pin else uid)
    in_scope = bool(item and (owner == e.scope_id or region and uid == e.scope_id))
    editable = in_scope and not reason and writable
    if rectangle:
        from ..bounds_edit import BoundsEdit

        try:
            BoundsEdit(e).record(uid)
        except LiteError:
            editable = False
    panel.rect_size.setEnabled(editable and rectangle)
    panel.name_box.setEnabled(editable)
    panel.pin_mode.setEnabled(editable)
    panel.enter.setEnabled(bool(region) and not panel.window.busy and uid != e.scope_id)
    panel.resize.setEnabled(bool(editable and uid != e.scope_id))
    panel.tighten.setVisible(bool(region) and not pin)
    panel.tighten.setEnabled(bool(editable and region and not pin))
    with QSignalBlocker(panel.resize):
        panel.resize.setChecked(panel.window.human.resize_target == uid and uid is not None)
    panel.resize.setText('完成边界调整' if panel.resize.isChecked() else '调整边界')
    delete_ok = False
    if not region and uid:
        try:
            HumanEdit(e).deletion_kind(uid)
            delete_ok = True
        except LiteError:
            pass
    panel.remove.setEnabled(
        bool(
            editable
            and uid != e.scope_id
            and (region or delete_ok)
            and not (region and _locked(e, uid, action='dissolve'))
        )
    )
    active = e.work_sessions.for_region(region.id) if region else None
    notice = reason or (
        f'{active.owner} 正在子区内部工作；当前父层可调整外框/接口，不能解散。' if active else ''
    )
    panel.status.setText(notice)
    panel.status.setVisible(bool(notice))
    return editable


def render_policy(panel, c, editable):
    e = c.editor
    w = e.w
    uid, region, box, pin = c.uid, c.region, c.box, c.pin
    native_module = c.native_module
    panel.policy_box.setVisible(bool(panel._policy_target) and not pin)
    panel.policy_box.setEnabled(editable)
    panel.native_windows.set_target(
        uid if native_module and native_module.black_box and not pin else None, editable
    )
    panel.policy_title.setText('禁布区图层' if box else '此模块上方禁止布线层')
    panel.policy_hint.setText('勾选即禁止布线')
    with QSignalBlocker(panel.layers):
        panel.layers.clear()
        current = (
            blocked_layers(w, e.profile, *panel._policy_target) if panel._policy_target else ()
        )
        for layer in metals(e.profile):
            row = QListWidgetItem(layer)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(
                Qt.CheckState.Checked if layer in current else Qt.CheckState.Unchecked
            )
            panel.layers.addItem(row)
    if region:
        panel._fill_pins(region, pin, editable)

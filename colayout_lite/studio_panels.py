"""Formal workspace side panels; presentation over shared local commands.

The shell calls ``refresh`` after model/scope/session changes and
``refresh_selection`` after a committed selection change. No polling, remote
reads, geometry copies, or independent editing/history state live here.
"""
from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QAbstractItemView,
    QScrollArea, QFrame, QComboBox, QDoubleSpinBox, QListWidget,
    QListWidgetItem,
)

from .editor import projected
from .human_edit import HumanEdit
from .model import LiteError
from .regions.actions import RegionActions
from .regions.query import children, metals, owner_map, object_bounds
from .routing_policy import blocked_layers, set_blocked_layers


from .presentation.panel_helpers import _scope_name,_session_key,_locked,_button


class StudioHierarchy(QWidget):
    """Local hierarchy with explicit navigation, separate from selection."""
    inspected = Signal(str)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName('studioHierarchy')
        self._key = None
        self._rows = {}
        self._selected = ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 16, 14, 12)
        title = QLabel('工作区')
        title.setObjectName('studioTitle')
        layout.addWidget(title)
        self.scope = QLabel('顶层')
        self.scope.setObjectName('studioSubtitle')
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.tree = QTreeWidget()
        self.tree.setObjectName('studioHierarchyTree')
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.itemClicked.connect(self._choose)
        self.tree.itemDoubleClicked.connect(self._enter)
        layout.addWidget(self.tree, 1)
        self.hint = QLabel('单击查看属性 · 双击进入本地模块')
        self.hint.setObjectName('studioMuted')
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.refresh()

    def refresh(self):
        e = self.window.editor
        if not e:
            return
        key = (id(e), id(e.w.local_data), e.scope_id, _session_key(e))
        if key == self._key:
            self.refresh_selection()
            return
        self._key = key
        expanded = {uid for uid, item in self._rows.items() if item.isExpanded()}
        first = not self._rows
        prior = self.tree.currentItem()
        selected = prior.data(0, Qt.ItemDataRole.UserRole) if prior else None
        self._rows = {}
        w = e.w
        with QSignalBlocker(self.tree):
            self.tree.clear()
            top = QTreeWidgetItem(['顶层'])
            top.setData(0, Qt.ItemDataRole.UserRole, '')
            self.tree.addTopLevelItem(top)
            self._rows[''] = top

            def add_regions(parent, parent_id):
                for region in children(w, parent_id):
                    sessions = getattr(e, 'work_sessions', None)
                    session = sessions.for_region(region.id) if sessions else None
                    row = QTreeWidgetItem([region.name + ('  · 工作中' if session else '')])
                    row.setData(0, Qt.ItemDataRole.UserRole, region.id)
                    row.setToolTip(0, region.id + (f'\n{session.owner} 正在工作' if session else ''))
                    parent.addChild(row)
                    self._rows[region.id] = row
                    add_regions(row, region.id)
                    row.setExpanded(first or region.id in expanded or region.id == e.scope_id)

            add_regions(top, None)
            for field, label in [('markups', '定位框'), ('keepouts', '禁布区')]:
                for item in getattr(w.local_data, field).values():
                    row = QTreeWidgetItem([f'{label} · {item.id.split("-")[-1][:6]}'])
                    row.setData(0, Qt.ItemDataRole.UserRole, item.id)
                    row.setToolTip(0, item.id)
                    self._rows.get(item.scope_id or '', top).addChild(row)
                    self._rows[item.id] = row
            top.setExpanded(True)
            if selected in self._rows:
                self.tree.setCurrentItem(self._rows[selected])
            else:
                self.tree.setCurrentItem(self._rows.get(e.scope_id or '', top))
        self.scope.setText('当前层 · ' + _scope_name(w, e.scope_id))
        self.refresh_selection()

    def refresh_selection(self):
        ids = tuple(self.window.human.ids()) if self.window.editor else ()
        if ids == self._selected:
            return
        self._selected = ids
        if len(ids) == 1 and ids[0] in self._rows:
            with QSignalBlocker(self.tree):
                self.tree.setCurrentItem(self._rows[ids[0]])

    def _choose(self, item, column=0):
        uid = item.data(0, Qt.ItemDataRole.UserRole)
        w = self.window
        # A tree selection never enters a module, moves the camera, or grants
        # access to hidden geometry. Off-scope rows are property inspection only.
        w.inspection.clear_trace()
        w.human.cancel()
        w.selection_ui.set_ids([uid] if uid else [])
        self.inspected.emit(uid)

    def _enter(self, item, column=0):
        uid = item.data(0, Qt.ItemDataRole.UserRole)
        panel = self.window.region_panel
        if not uid:
            panel.navigate(lambda: panel._set_scope(None))
        elif uid in self.window.editor.w.local_data.regions:
            panel.activate_uid(uid)


class StudioInspector(QWidget):
    """Contextual properties. Commands retain shared validation and undo."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName('studioProperties')
        self._key = None
        self._target = None
        self._canvas_ids = ()
        self._pin = None
        self._editor_context = None
        self._loading = False
        self._policy_target = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName('studioInspectorScroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll)
        body = QWidget()
        body.setObjectName('studioInspectorBody')
        scroll.setWidget(body)
        form = QVBoxLayout(body)
        form.setContentsMargins(18, 16, 18, 14)
        form.setSpacing(12)
        self.title = QLabel('属性')
        self.title.setObjectName('studioTitle')
        self.title.setWordWrap(True)
        form.addWidget(self.title)
        self.subtitle = QLabel()
        self.subtitle.setObjectName('studioSubtitle')
        self.subtitle.setWordWrap(True)
        form.addWidget(self.subtitle)
        self.status = QLabel()
        self.status.setObjectName('studioWorkingBadge')
        self.status.setWordWrap(True)
        form.addWidget(self.status)
        identity = QHBoxLayout()
        self.identity = QLineEdit()
        self.identity.setObjectName('studioObjectId')
        self.identity.setReadOnly(True)
        self.identity.setPlaceholderText('选择对象以查看 ID')
        self.copy = _button('复制 ID', 'studioCopyId', self.copy_ids)
        identity.addWidget(self.identity, 1)
        identity.addWidget(self.copy)
        form.addLayout(identity)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.setObjectName('propertyDetails')
        form.addWidget(self.details)

        from .presentation.inspector_sections import build_region,build_geometry,build_pin,build_policy
        build_region(self,form)

        build_geometry(self,form)

        build_pin(self,form)

        build_policy(self,form)

        self.hint = QLabel()
        self.hint.setObjectName('studioMuted')
        self.hint.setWordWrap(True)
        form.addWidget(self.hint)
        self.message = QLabel()
        self.message.setObjectName('propertyMessage')
        self.message.setWordWrap(True)
        form.addWidget(self.message)
        for label in (self.title, self.subtitle, self.status, self.details, self.hint, self.message):
            label.setTextFormat(Qt.TextFormat.PlainText)
        form.addStretch(1)
        self.refresh()


    def inspect_uid(self, uid):
        self._adopt_editor()
        self._canvas_ids = tuple(self.window.human.ids())
        self._target = uid
        self._pin = None
        self._key = None
        self.refresh()

    def refresh_selection(self):
        ids = tuple(self.window.human.ids()) if self.window.editor else ()
        if ids != self._canvas_ids:
            self._target = None
            self._pin = None
            self._canvas_ids = ids
        self.refresh()

    def _adopt_editor(self):
        """Document replacement invalidates inspection, even with no selection."""
        editor = self.window.editor
        if editor is self._editor_context:
            return False
        self._editor_context = editor
        self._target = None
        self._pin = None
        self._canvas_ids = ()
        self._key = None
        return True

    def _validate_target(self, workspace):
        # Tree inspection may deliberately refer to a different scope. Only
        # existence, not editability/visibility, determines whether it survives.
        if not self._target:
            return
        local = workspace.local_data
        if self._target not in local.regions and self._target not in local.markups and self._target not in local.keepouts and self._target not in projected(workspace):
            self._target = None
            self._pin = None
        elif self._pin:
            region = local.regions.get(self._target)
            if region is None or self._pin not in region.pins:
                self._pin = None

    def refresh(self):
        e = self.window.editor
        if not e:
            return
        changed_editor = self._adopt_editor()
        self._validate_target(e.w)
        ids = tuple(self.window.human.ids())
        if ids != self._canvas_ids:
            self._canvas_ids = ids
            self._target = None
            self._pin = None
        focus = self.window.inspection
        focused_pin = self.window.human.pin_selected or ((focus.focus_region, focus.focus_pin_id)
            if not ids and focus.focus_region and focus.focus_pin_id else None)
        region = e.w.local_data.regions.get(focused_pin[0]) if focused_pin else None
        valid_focus = bool(region and focused_pin[1] in region.pins and
                           (region.id == e.scope_id or region.parent_id == e.scope_id))
        if focused_pin and valid_focus and not changed_editor:
            self._target, self._pin = focused_pin
        uid = self._target if self._target is not None else ids[0] if len(ids) == 1 else None
        key = (id(e), id(e.w), e.scope_id, ids, uid, self._pin, bool(self.window.busy),
               self.window.human.resize_target, _session_key(e), self.window.shortcuts.values['rotate'])
        if key == self._key:
            return
        self._key = key
        self._loading = True
        try:
            self._render(uid, ids)
        finally:
            self._loading = False

    def _render(self, uid, ids):
        from .presentation.inspector_render import render
        render(self,uid,ids)

    def _fill_pins(self, region, pin, editable):
        self.pin_details.setVisible(pin is not None)
        with QSignalBlocker(self.pin_layer):
            self.pin_layer.clear()
            from .interface_layers import ANY_METAL_LABEL,label
            self.pin_layer.addItem(ANY_METAL_LABEL)
            self.pin_layer.addItems(metals(self.window.editor.profile))
            if pin:
                self.pin_layer.setCurrentText(label(pin))
        for widget in (self.pin_layer, self.copy_pin_button):
            widget.setEnabled(bool(pin) and editable)

    def _uid(self):
        if self._target is not None:
            return self._target
        ids = self.window.human.ids()
        return ids[0] if len(ids) == 1 else None

    def _run(self, action):
        if self.window.busy:
            return
        try:
            action()
            self._key = None
            self.refresh()
            self.message.setText('已更新，可撤销。')
        except Exception as exc:
            self._key = None
            self.refresh()
            self.message.setText(str(exc))

    def copy_ids(self):
        QApplication.clipboard().setText(getattr(self, '_copy_text', ''))

    def command(self, action):
        uid = self._uid()
        if self._target is not None and uid:
            self.window.selection_ui.set_ids([uid])
        self.window.human.command(action)
        self.refresh()

    def toggle_resize(self):
        enabled = self.resize.isChecked()
        uid = self._uid()
        self.window.selection_ui.set_ids([uid])
        self.window.human.set_resize_enabled(enabled)
        self.refresh()

    def enter_region(self):
        self.window.region_panel.activate_uid(self._uid())
        self._target = None
        self._pin = None
        self.refresh()

    def apply_rect_size(self):
        from .bounds_edit import BoundsEdit
        from .actions import dbu
        e=self.window.editor;uid=self._uid()
        def apply():
            _,row=BoundsEdit(e).record(uid);(x,y),(xx,yy)=row.bbox
            width=dbu(self.rect_width.value(),e.profile);height=dbu(self.rect_height.value(),e.profile)
            cx,cy=(x+xx)/2,(y+yy)/2
            BoundsEdit(e).resize(uid,((cx-width/2,cy-height/2),(cx+width/2,cy+height/2)),expected_revision=e.w.revision)
        self._run(apply)

    def rename_region(self):
        region = self.window.editor.w.local_data.regions[self._uid()]
        self._run(lambda: RegionActions(self.window.editor).update_details(region.id, self.name.text(), region.note, region.blocked_layers))

    def change_pin_mode(self):
        if self._loading:return
        uid=self._target if self._target is not None else next(iter(self.window.human.ids()), None)
        if uid in self.window.editor.w.local_data.regions:
            self._run(lambda: RegionActions(self.window.editor).set_pin_mode(uid, self.pin_mode.currentData()))

    def remove_object(self):
        uid = self._uid()
        e = self.window.editor
        if uid in e.w.local_data.regions:
            self._run(lambda: RegionActions(e).dissolve(uid))
        elif uid in e.w.local_data.markups or uid in e.w.local_data.keepouts:
            self._run(lambda: RegionActions(e).remove_box(uid))
        else:
            self._run(lambda: HumanEdit(e).delete([uid]))
        self._target = None
        self._pin = None
        self.refresh_selection()

    def check_region(self,engine):
        try:
            from .region_tools import check_region
            check_region(self.window,engine,self._uid())
        except Exception as exc:self.message.setText(str(exc))

    def clear_routing(self,include_guards):
        from .regions.cleanup import plan,clear
        w=self.window;e=w.editor;uid=self._uid()
        if w.busy:return
        try:
            preview=plan(e,uid,include_guards=include_guards)
            if preview['object_ids']:
                if e.scope_id!=uid:w.region_panel.activate_uid(uid)
                result=clear(e,uid,include_guards=include_guards,expected_revision=preview['revision'])
            else:result=preview
            self._target=uid;self._pin=None;self._canvas_ids=tuple(w.human.ids());self._key=None;self.refresh()
            message=f'已清除 {len(result["object_ids"])} 项，可撤销。' if result['object_ids'] else '本层没有可清除的图形。'
            if result['protected']:message+=f' 保留 {len(result["protected"])} 项受保护或仍被引用的图形。'
            self.message.setText(message);w.status.setText(message)
            if result['protected']:w.activity.record('区域清理',message+'\n'+'\n'.join(r['reason'] for r in result['protected']))
        except Exception as exc:self.message.setText(str(exc))




    def copy_pin(self):
        if self._loading or not self._pin:return
        uid,pid=self._uid(),self._pin
        created=[]
        self._run(lambda:created.append(RegionActions(self.window.editor).copy_pin(uid,pid)))
        if created:
            self._target,self._pin=uid,created[0]
            self.window.region_panel.select_pin(uid,created[0])
            self._key=None;self.refresh()

    def tighten_region(self):
        from .frame_edit import FrameEdit
        uid=self._uid()
        if uid:self._run(lambda:FrameEdit(self.window.editor).tighten(uid))

    def change_pin_layer(self, _index):
        if self._loading or not self._pin:return
        from .presentation.pin_layer_edit import save_layer
        uid,pid=self._uid(),self._pin
        try:message=save_layer(self.window,uid,pid,self.pin_layer.currentText())
        except Exception as exc:message=str(exc)
        self._key=None;self.refresh()
        self.message.setText(message)

    def change_layers(self, item):
        if not self._loading:
            self.write_layers(tuple(self.layers.item(i).text() for i in range(self.layers.count())
                if self.layers.item(i).checkState() == Qt.CheckState.Checked))

    def write_layers(self, layers):
        target = self._policy_target
        if target:
            self._run(lambda: set_blocked_layers(self.window.editor, *target, layers))

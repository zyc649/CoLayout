"""Compact human controls; advanced editing remains in the shared Agent API."""
from PySide6.QtCore import Qt,QRectF,QSignalBlocker
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QListWidget,QListWidgetItem,QPushButton
from .native_routing_windows import NativeRoutingWindows,windows_for,describe
from .regions.query import metals
from .editor import projected
from .model import LiteError
from .native_routing_window_dialog import NativeRoutingWindowDialog


class NativeRoutingWindowPanel(QWidget):
    def __init__(self,window):
        super().__init__()
        self.window=window;self.uid=None;self.selected_id=None;self.mode=None
        self.creation_dialog=None;self._context=None;self.editable=False
        window.native_routing_window_panel=self
        form=QVBoxLayout(self);form.setContentsMargins(0,0,0,0)
        title=QLabel('布线豁免区');title.setObjectName('studioSection');form.addWidget(title)
        self.items=QListWidget();self.items.setObjectName('nativeRoutingWindows');self.items.setMaximumHeight(100)
        self.items.currentItemChanged.connect(self.choose)
        # Clicking an already-selected row should focus it again after a pan.
        self.items.itemClicked.connect(self.choose);form.addWidget(self.items)
        self.empty=QLabel('暂无豁免区');self.empty.setObjectName('studioMuted');form.addWidget(self.empty)
        row=QHBoxLayout();form.addLayout(row)
        self.create=QPushButton('画豁免区');self.remove=QPushButton('删除豁免区')
        row.addWidget(self.create);row.addWidget(self.remove)
        self.create.clicked.connect(self.configure);self.remove.clicked.connect(self.delete)
        self.escape=QPushButton('PIN 引出豁免…');self.escape.setObjectName('nativePinEscapes')
        self.escape.clicked.connect(self.configure_escape);form.addWidget(self.escape)
        self.message=QLabel();self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True);self.message.hide();form.addWidget(self.message)
        window.canvas.region_picked.connect(self.drawn);window.canvas.region_cancelled.connect(self.cancel_draw)

    def set_target(self,uid,editable):
        context=(id(self.window.editor),uid)
        if context!=self._context:
            self.cancel_draw();self._context=context;self.uid=uid;self.selected_id=None
            self.message.clear();self.message.hide()
        self.editable=editable
        if not editable:self.cancel_draw()
        self.setVisible(uid is not None)
        rows=windows_for(self.window.editor.w,uid) if uid is not None else []
        all_layers=set(metals(self.window.editor.profile))
        with QSignalBlocker(self.items):
            self.items.clear()
            for row in rows:
                layers='全部金属层' if set(row.layers)==all_layers else ', '.join(row.layers)
                item=QListWidgetItem(row.name+' · '+layers+('（停用）' if not row.enabled else ''))
                item.setData(Qt.ItemDataRole.UserRole,row.id);self.items.addItem(item)
                if row.id==self.selected_id:self.items.setCurrentItem(item)
        self.selected_id=self.items.currentItem().data(Qt.ItemDataRole.UserRole) if self.items.currentItem() else None
        self.items.setVisible(bool(rows));self.empty.setVisible(not rows)
        self.create.setEnabled(editable);self.remove.setEnabled(editable and self.selected_id is not None)
        self.escape.setEnabled(editable)
        self.highlight()

    def highlight(self):
        state=self.window.diagnostics
        if state.native_routing_window_id!=self.selected_id:
            state.native_routing_window_id=self.selected_id
            from .workspace_overlay import refresh
            refresh(self.window)

    def choose(self,*_):
        item=self.items.currentItem();self.selected_id=item.data(Qt.ItemDataRole.UserRole) if item else None
        self.remove.setEnabled(self.editable and self.selected_id is not None);self.highlight()
        e=self.window.editor;row=e.w.local_data.native_routing_windows.get(self.selected_id)
        if row is None:return
        bounds=describe(e.w,row,e.profile)['effective_bounds_um']
        if bounds:
            x,y,xx,yy=(v*e.profile.dbu_per_micron for v in bounds)
            from .camera import fit_bounds,navigation_room
            # Leave context around narrow PIN escape corridors.
            margin=max(xx-x,yy-y)*.25
            fit_bounds(self.window.canvas,QRectF(x,-yy,xx-x,yy-y).adjusted(-margin,-margin,margin,margin))
            navigation_room(self.window.canvas)
            from .workspace_overlay import reflow_labels
            reflow_labels(self.window)

    def error(self,exc):
        self.message.setText(str(exc));self.message.show()

    def run(self,fn):
        try:
            if self.window.busy:raise LiteError('WORKSPACE_BUSY')
            value=fn()
            if value:self.selected_id=value
            self.window.save_local();self.set_target(self.uid,self.editable)
            self.message.clear();self.message.hide()
        except Exception as exc:self.error(exc)

    def delete(self):
        ident=self.selected_id
        if ident:self.run(lambda:NativeRoutingWindows(self.window.editor).delete(ident))

    def cancel_draw(self,*_):
        if self.creation_dialog:
            dialog=self.creation_dialog;self.creation_dialog=None;dialog.reject()
        if self.mode:
            self.mode=None;self.window.canvas.region_select=False;self.window.canvas.setCursor(Qt.CursorShape.ArrowCursor)

    def configure(self):
        try:
            self.cancel_draw()
            e=self.window.editor
            if self.window.busy:raise LiteError('WORKSPACE_BUSY')
            obj=NativeRoutingWindows(e).target(self.uid)
            from .drawing_mode import cancel_drawing
            cancel_drawing(self.window,self)
            stamp=(e,e.w.id,e.scope_id,self.uid,obj.placement)
            names={r.name for r in windows_for(e.w,self.uid)};number=1
            while f'豁免区 {number}' in names:number+=1
            dialog=NativeRoutingWindowDialog(metals(e.profile),f'豁免区 {number}',self.window)
            self.creation_dialog=dialog
            dialog.accepted.connect(lambda:self.start_draw(dialog,stamp))
            dialog.finished.connect(lambda:self.finish_dialog(dialog))
            dialog.open()
        except Exception as exc:self.error(exc)

    def finish_dialog(self,dialog):
        if self.creation_dialog is dialog:self.creation_dialog=None
        dialog.deleteLater()

    def configure_escape(self):
        try:
            self.cancel_draw()
            if self.window.busy:raise LiteError('WORKSPACE_BUSY')
            e=self.window.editor;obj=NativeRoutingWindows(e).target(self.uid)
            from .drawing_mode import cancel_drawing
            from .native_routing_window_dialog import NativePinEscapeDialog
            cancel_drawing(self.window,self)
            stamp=(e,e.w.id,e.scope_id,self.uid,obj.placement)
            dialog=NativePinEscapeDialog(getattr(self,'_escape_width_um',.5),e.profile.grid/e.profile.dbu_per_micron,self.window)
            self.creation_dialog=dialog
            dialog.accepted.connect(lambda:self.generate_escapes(dialog,stamp))
            dialog.finished.connect(lambda:self.finish_dialog(dialog));dialog.open()
        except Exception as exc:self.error(exc)

    def generate_escapes(self,dialog,stamp):
        def apply():
            self.verify_target(stamp)
            width=dialog.width.value();self._escape_width_um=width
            result=NativeRoutingWindows(self.window.editor).auto_escape_um(stamp[3],width)
            self.window.status.setText(f'已生成 {len(result["created_uids"])} 条 PIN 引出豁免，复用 {len(result["reused_uids"])} 条。')
            ids=result['created_uids']+result['reused_uids']
            return ids[0] if ids else None
        self.run(apply)

    def verify_target(self,stamp):
        editor,document,scope,uid,placement=stamp;e=self.window.editor
        obj=projected(e.w).get(uid)
        if e is not editor or e.w.id!=document or e.scope_id!=scope or self.uid!=uid or obj is None or obj.placement!=placement:
            raise LiteError('NATIVE_WINDOW_TARGET_CHANGED','所属模块已变化，请重新画框。')
        if self.window.busy:raise LiteError('WORKSPACE_BUSY')
        NativeRoutingWindows(e).target(uid)

    def start_draw(self,dialog,stamp):
        try:
            self.verify_target(stamp)
            self.mode=(stamp,dialog.values())
            self.window.canvas.region_select=True;self.window.canvas.setCursor(Qt.CursorShape.CrossCursor)
            self.window.status.setText('拖动画出豁免区 · Esc 取消')
            self.message.clear();self.message.hide()
        except Exception as exc:self.error(exc)

    def drawn(self,bounds):
        if self.mode is None:return
        stamp,values=self.mode;self.cancel_draw()
        def apply():
            self.verify_target(stamp)
            return NativeRoutingWindows(self.window.editor).create(stamp[3],bounds,**values)
        self.run(apply)

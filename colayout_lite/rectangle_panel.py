"""Mouse rectangle creation via the existing Actions/Editor contract."""
from PySide6.QtCore import Qt,QSignalBlocker
from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel,QComboBox,QPushButton,QDockWidget
from .drawing_mode import cancel_drawing
from .regions.actions import RegionActions
from .model import LiteError


class RectanglePanel(QWidget):
    def __init__(self,window):
        super().__init__(window);self.setMinimumWidth(240);self.window=window;self.context=None;self._profile=None
        layout=QVBoxLayout(self);layout.addWidget(QLabel('绘制层'))
        self.layers=QComboBox();layout.addWidget(self.layers)
        self.draw=QPushButton('画矩形');self.draw.setObjectName('canvasDraw');self.draw.setCheckable(True);self.draw.clicked.connect(self.start);layout.addWidget(self.draw)
        self.message=QLabel('选择层后，在画布拖出矩形；Esc 取消。');self.message.setWordWrap(True);layout.addWidget(self.message);layout.addStretch()
        window.canvas.region_picked.connect(self.picked);window.canvas.region_cancelled.connect(self.cancel_draw)
        window.view_state_changed.connect(self.refresh);self.layers.currentIndexChanged.connect(self.cancel_draw);self.refresh()

    def refresh(self):
        w=self.window;e=w.editor
        if not e:return
        if self.context and (e is not self.context[0] or e.w is not self.context[1] or e.scope_id!=self.context[2]):self.cancel_draw()
        if self._profile is not e.profile:
            old=self.layers.currentData();self._profile=e.profile
            with QSignalBlocker(self.layers):
                self.layers.clear()
                for layer,purpose in e.profile.writable_lpps:self.layers.addItem(layer+' / '+purpose,(layer,purpose))
                index=self.layers.findData(old or e.profile.editor_defaults.get('layer'))
                if index>=0:self.layers.setCurrentIndex(index)
        enabled=bool(not w.busy and e.w.state not in ('submitting','indeterminate','conflict') and not e.work_sessions.readonly_reason() and self.layers.count())
        self.draw.setEnabled(enabled);self.layers.setEnabled(enabled)

    def start(self,on):
        if not on:self.cancel_draw();return
        w=self.window;cancel_drawing(w,self);w.selection_ui.set_ids([])
        self.context=(w.editor,w.editor.w,w.editor.scope_id,self.layers.currentData())
        self.draw.setChecked(True);w.canvas.region_select=True;w.canvas.setCursor(Qt.CursorShape.CrossCursor);w.canvas.setFocus()
        if hasattr(w,'rectangle_popup'):w.rectangle_popup.dismiss_for_drawing()
        self.message.setText('在画布拖出矩形，松手完成；Esc 取消。')

    def cancel_draw(self,*_):
        if self.context:
            self.window.canvas.region_select=False;self.window.canvas.unsetCursor()
        self.context=None;self.draw.setChecked(False)

    def picked(self,bounds):
        if self.context is None:return
        e,source,scope,lpp=self.context;w=self.window;self.cancel_draw()
        try:
            if e is not w.editor or e.w is not source or e.scope_id!=scope:raise LiteError('DRAW_CONTEXT_CHANGED','工作区已变化，请重新画矩形。')
            e.work_sessions.assert_editable()
            (x,y),(xx,yy)=RegionActions(e).snap_box(bounds);scale=e.profile.dbu_per_micron
            result=w.actions.execute('create_rect',dict(x=x/scale,y=y/scale,width=(xx-x)/scale,height=(yy-y)/scale,lpp=lpp))
            w.selection_ui.set_ids([result.uid]);self.message.setText('矩形已创建；Ctrl+Z 可撤销。')
        except Exception as exc:self.message.setText(str(exc))
        w.status.setText(self.message.text())


def show(window):
    if not hasattr(window,'rectangle_panel'):
        panel=RectanglePanel(window)
        if getattr(getattr(window,'studio',None),'mode',None)=='studio':
            from .tool_popover import ToolPopover
            popup=ToolPopover(window,'矩形',panel,panel.cancel_draw);window.rectangle_popup=popup
            window.rectangle_panel=panel;window.rectangle_dock=popup
        else:
            dock=QDockWidget('矩形',window);dock.setObjectName('rectangleDock');dock.setWidget(panel)
            window.rectangle_panel=panel;window.rectangle_dock=dock;window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,dock)
            from .panel_chrome import style_dock
            style_dock(window,dock);dock.visibilityChanged.connect(lambda visible:panel.refresh() if visible else panel.cancel_draw())
    if hasattr(window,'rectangle_popup'):
        button=window.studio.action_buttons['rectangle'][0];window.rectangle_popup.show_near(button)
    else:window.rectangle_dock.show();window.rectangle_dock.raise_()

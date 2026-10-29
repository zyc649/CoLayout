"""Guard-ring drawing UI over existing Actions/Adapter native MPP generation."""
from PySide6.QtCore import Qt,QRectF,QSignalBlocker,Signal
from PySide6.QtGui import QColor,QPen,QPainterPath
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QComboBox,QPushButton,
    QDoubleSpinBox,QLineEdit,QTableWidget,QTableWidgetItem,QDockWidget)
from .guard_tools import catalog,generate,adopt
from .path_capture import PathCapture
from .regions.actions import RegionActions
from .theme import palette
from .model import LiteError


class GuardPanel(QWidget):
    progress=Signal(str)
    def __init__(self,window):
        super().__init__(window);self.setMinimumWidth(260);self.window=window;self._key=None;self.bounds=None;self.preview_points=[];self._running=False
        layout=QVBoxLayout(self);self.scope=QLabel();layout.addWidget(self.scope)
        form=QFormLayout();layout.addLayout(form);self.templates=QComboBox();form.addRow('保护环类型',self.templates)
        self.mode=QComboBox();self.mode.addItems(['矩形闭环','开放 90° 路径']);form.addRow('形状',self.mode)
        self.net=QLineEdit();self.net.setPlaceholderText('必填，例如 VSS / VDD');form.addRow('网络 / PIN 名',self.net)
        self.box_fields=QWidget();box=QFormLayout(self.box_fields);box.setContentsMargins(0,0,0,0);self.coords=[]
        for label in ('X · µm','Y · µm','宽 · µm','高 · µm'):
            edit=QDoubleSpinBox();edit.setRange(-1e6,1e6);edit.setDecimals(6);edit.setKeyboardTracking(False);edit.valueChanged.connect(self.box_changed)
            self.coords.append(edit);box.addRow(label,edit)
        layout.addWidget(self.box_fields)
        self.vertices=QTableWidget(2,2);self.vertices.setHorizontalHeaderLabels(['X · µm','Y · µm']);self.vertices.setMaximumHeight(240);layout.addWidget(self.vertices)
        self.vertices.itemChanged.connect(lambda:self.window.canvas.viewport().update())
        row=QHBoxLayout();layout.addLayout(row)
        self.draw=QPushButton('在画布画范围');self.draw.setObjectName('canvasDraw');self.draw.setCheckable(True);self.draw.clicked.connect(self.start_draw);row.addWidget(self.draw)
        self.finish=QPushButton('结束折线');self.finish.clicked.connect(lambda:self.capture.end());row.addWidget(self.finish)
        self.add_vertex=QPushButton('增加顶点');self.add_vertex.clicked.connect(lambda:self.vertices.insertRow(self.vertices.rowCount()));row.addWidget(self.add_vertex)
        self.generate_button=QPushButton('生成到本地草稿');self.generate_button.clicked.connect(self.run);layout.addWidget(self.generate_button)
        note=QLabel('使用当前工艺已配置的全部原生模板和已验证配方。框/折线表示主路径，实际外沿按工艺扩展。\n生成在服务器私有副本完成，再放入本地；正式同步仍由你触发。');self.note=note
        note.setWordWrap(True);layout.addWidget(note)
        from .task_activity import TaskActivity
        self.activity=TaskActivity(self,idle_title='准备保护环',running_title='正在生成保护环',idle_message='填写网络名后在画布绘制。')
        self.message=self.activity.message;layout.addWidget(self.activity);layout.addStretch()
        self.progress.connect(lambda message:self.message.setText(message) if self._running else None)
        self.capture=PathCapture(window,self.preview_path,self.path_finished)
        self.capture.active_changed.connect(self.draw.setChecked)
        window.canvas.region_picked.connect(self.box_picked);window.canvas.region_cancelled.connect(self.cancel_draw)
        window.canvas.inspection_clear.connect(self.cancel_draw);window.canvas.guard_overlay=self.paint
        window.view_state_changed.connect(self.refresh);self.mode.currentIndexChanged.connect(self.change_mode)
        self.formal=getattr(getattr(window,'studio',None),'mode',None)=='studio'
        self.change_mode();self.refresh();self.set_presentation(self.formal)

    def set_presentation(self,formal):
        self.formal=formal;self.change_mode()
        self.generate_button.setVisible(not formal)
        self.generate_button.setText('重试生成' if formal else '生成到本地草稿')
        if formal:
            self.note.setText('选好类型后在画布拖出矩形，松手生成保护环。开放路径可逐点绘制，按 Enter 完成。')
            if self.templates.count():self.message.setText('填写网络名后绘制；保护环自带同名 PIN。')
        self.activity.setVisible(not formal or self._running or not self.templates.count())

    def refresh(self):
        popup=getattr(self.window,'guard_popup',None)
        if popup:popup.close_button.setEnabled(not self._running)
        e=self.window.editor
        if not e:return
        key=(id(e),id(e.profile),e.scope_id,id(e.w),self.window.busy)
        if key==self._key:return
        if self._key and self._key[:3]!=key[:3]:self.cancel_draw();self.bounds=None;self.preview_points=[]
        old=self.templates.currentText()
        with QSignalBlocker(self.templates):
            self.templates.clear()
            for row in catalog(e.profile):self.templates.addItem(row['label'],row['template'])
            idx=self.templates.findText(old)
            if idx>=0:self.templates.setCurrentIndex(idx)
        region=e.w.local_data.regions.get(e.scope_id);self.scope.setText('绘制层：'+(region.name if region else '顶层'))
        enabled=not self.window.busy and getattr(self.window,'remote_enabled',True) and not e.work_sessions.readonly_reason() and bool(self.templates.count())
        self.generate_button.setEnabled(enabled);self.draw.setEnabled(enabled)
        for widget in (self.templates,self.mode,self.net):widget.setEnabled(enabled)
        if not self.templates.count():self.message.setText('当前工艺尚未配置保护环模板/配方，请先在工艺库设置中配置。')
        self._key=key

    def change_mode(self):
        self.cancel_draw();opened=self.mode.currentIndex()==1
        formal=getattr(self,'formal',False)
        self.box_fields.setVisible(not opened and not formal);self.vertices.setVisible(opened and not formal);self.finish.setVisible(opened);self.add_vertex.setVisible(opened and not formal)
        self.draw.setText('画开放路径' if opened else '画保护环')

    def start_draw(self,on):
        if not on:self.cancel_draw();return
        from .guard_ports import required_net
        try:required_net(self.net.text())
        except LiteError as exc:
            self.draw.setChecked(False);self.activity.show();self.activity.finish('blocked','请输入网络名',str(exc));self.net.setFocus();return
        w=self.window
        from .drawing_mode import cancel_drawing
        cancel_drawing(w,self);w.selection_ui.set_ids([])
        self._drawing_context=(w.editor,w.editor.w,w.editor.scope_id)
        self.draw.setChecked(True)
        if self.mode.currentIndex():self.capture.start()
        else:w.canvas.region_select=True;w.canvas.setCursor(Qt.CursorShape.CrossCursor)
        w.canvas.setFocus();self.message.setText('在画布拖出矩形，松手生成；Esc 取消。' if not self.mode.currentIndex() else '逐点绘制；Enter 完成，Esc 取消。')
        if hasattr(w,'guard_popup'):w.guard_popup.dismiss_for_drawing()

    def cancel_draw(self):
        if self.draw.isChecked() or self.capture.active:
            self.capture.cancel();self.window.canvas.region_select=False;self.window.canvas.unsetCursor()
        self.draw.setChecked(False)

    def box_picked(self,bounds):
        if not self.draw.isChecked() or self.mode.currentIndex():return
        self.cancel_draw()
        try:self.bounds=RegionActions(self.window.editor).snap_box(bounds)
        except Exception as exc:self.message.setText(str(exc));return
        (x,y),(xx,yy)=self.bounds;scale=self.window.editor.profile.dbu_per_micron
        for edit,value in zip(self.coords,(x,y,xx-x,yy-y)):
            with QSignalBlocker(edit):edit.setValue(value/scale)
        self.window.canvas.viewport().update()
        if self.formal:self.run()

    def box_changed(self):
        if not self.window.editor:return
        x,y,width,height=(e.value()*self.window.editor.profile.dbu_per_micron for e in self.coords)
        self.bounds=((x,y),(x+width,y+height)) if width>0 and height>0 else None;self.window.canvas.viewport().update()

    def preview_path(self,points):self.preview_points=points;self.window.canvas.viewport().update()

    def path_finished(self,points):
        self.draw.setChecked(False);self.preview_points=points;scale=self.window.editor.profile.dbu_per_micron
        self.vertices.blockSignals(True);self.vertices.setRowCount(len(points))
        for i,point in enumerate(points):
            for j,value in enumerate(point):self.vertices.setItem(i,j,QTableWidgetItem(f'{value/scale:g}'))
        self.vertices.blockSignals(False);self.window.canvas.viewport().update()
        if self.formal:self.run()

    def run(self):
        w=self.window
        if w.busy or not w.idle_for_replacement():return
        try:
            self.cancel_draw();e=w.editor;e.work_sessions.assert_editable()
            if self.formal and (e,e.w,e.scope_id)!=getattr(self,'_drawing_context',None):raise LiteError('GUARD_PREVIEW_STALE','工作区已变化，请重新绘制保护环。')
            template=self.templates.currentData()
            if template is None:raise LiteError('GUARD_TEMPLATE_REQUIRED')
            from .guard_ports import required_net
            params={'template':template,'net_intent':required_net(self.net.text())}
            if self.mode.currentIndex():
                if any(self.vertices.item(i,j) is None or not self.vertices.item(i,j).text().strip() for i in range(self.vertices.rowCount()) for j in range(2)):
                    raise LiteError('MPP_POINTS_REQUIRED','请先在画布画折线，或完整填写各顶点。')
                params['points']=[[float(self.vertices.item(i,j).text()) for j in range(2)] for i in range(self.vertices.rowCount())]
                action='create_mpp'
            else:
                x,y,width,height=(v.value() for v in self.coords)
                if width<=0 or height<=0:raise LiteError('GUARD_BOX_REQUIRED','请先画出有效范围。')
                params.update(x=x,y=y,width=width,height=height);action='create_guard'
            source=e.w;scope=e.scope_id;profile=e.profile
            def done(result):
                if w.editor is not e:raise LiteError('GUARD_PREVIEW_STALE')
                uid=adopt(e,source,scope,result);w.selection_ui.set_ids([uid]);self.bounds=None;self.preview_points=[]
                self._running=False;self.activity.finish('ready','创建完成','保护环及同名 PIN 已创建；Ctrl+Z 可撤销。');w.status.setText(self.message.text());w.save_local()
            self._running=True;self.activity.show();self.activity.start()
            if hasattr(w,'guard_popup'):w.guard_popup.show_near(w.studio.action_buttons['guard'][0])
            w.task(lambda:generate(source,profile,scope,w.native(),action,params,progress=self.progress.emit),done)
            if w.job:
                w.job.failed.connect(lambda error:self.failed(error[0]))
                w.job.finished.connect(lambda:self.failed('创建未完成，详情见操作记录。') if self._running else None)
        except Exception as exc:self.failed(str(exc))

    def failed(self,message):
        self._running=False;self.activity.show();self.activity.finish('failed','创建失败',str(message));self.window.status.setText(str(message))

    def paint(self,painter):
        if not self.isVisible() and not self.capture.active and not self.draw.isChecked() and not self._running:return
        path=QPainterPath()
        if self.mode.currentIndex() and self.preview_points:
            for i,(x,y) in enumerate(self.preview_points):path.moveTo(x,-y) if i==0 else path.lineTo(x,-y)
        elif self.bounds:
            (x,y),(xx,yy)=self.bounds;path.addRect(QRectF(x,-yy,xx-x,yy-y))
        else:return
        painter.setTransform(self.window.canvas.viewportTransform());pen=QPen(QColor(palette(self.window.canvas).selection),1.4,Qt.PenStyle.DashLine);pen.setCosmetic(True)
        painter.setPen(pen);painter.setBrush(Qt.BrushStyle.NoBrush);painter.drawPath(path)


def show(window):
    if not hasattr(window,'guard_panel'):
        panel=GuardPanel(window);window.guard_panel=panel
        if getattr(getattr(window,'studio',None),'mode',None)=='studio':
            from .tool_popover import ToolPopover
            popup=ToolPopover(window,'保护环',panel,panel.cancel_draw);window.guard_popup=popup;window.guard_dock=popup
        else:
            dock=QDockWidget('保护环',window);dock.setObjectName('guardDock');dock.setWidget(panel)
            window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,dock);window.guard_dock=dock
            from .panel_chrome import style_dock
            style_dock(window,dock)
            dock.visibilityChanged.connect(lambda visible:panel.cancel_draw() if not visible else panel.refresh())
    if hasattr(window,'guard_popup'):
        window.guard_panel.cancel_draw();window.guard_panel.bounds=None
        panel=window.guard_panel
        panel.activity.reset('填写网络名后绘制；保护环自带同名 PIN。' if panel.templates.count() else '当前工艺尚未配置保护环模板，请先在工艺库设置中配置。')
        panel.activity.setVisible(not panel.templates.count())
        window.guard_popup.show_near(window.studio.action_buttons['guard'][0])
    else:window.guard_dock.show();window.guard_dock.raise_()

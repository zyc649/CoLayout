"""Human interaction with the local construction hierarchy; no remote actions."""
import json
from PySide6.QtCore import Qt,QSignalBlocker,QRectF
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QLineEdit,QPushButton,
    QTreeWidget,QTreeWidgetItem,QTableWidget,QTableWidgetItem,QComboBox,QCheckBox,QDoubleSpinBox,
    QPlainTextEdit,QTabWidget,QApplication,QAbstractItemView,QListWidget,QListWidgetItem,QScrollArea)
from .actions import RegionActions
from .query import boundary,metals,owner_map,children
from ..model import LiteError


class RegionPanel(QWidget):
    def __init__(self,window):
        super().__init__(window);self.owner=window;self.selected_id=None;self.mode=None;self._loaded_id=None
        layout=QVBoxLayout(self)
        self.breadcrumb=QLabel();self.breadcrumb.setWordWrap(True);layout.addWidget(self.breadcrumb)
        row=QHBoxLayout();layout.addLayout(row)
        self.draw_button=QPushButton('画操作区');self.up_button=QPushButton('返回上层 · Ctrl+E')
        row.addWidget(self.draw_button);row.addWidget(self.up_button)
        self.draw_button.clicked.connect(lambda:self.start_draw('region'));self.up_button.clicked.connect(lambda:self.navigate(self.up))
        self.tree=QTreeWidget();self.tree.setHeaderLabels(['操作区 / 定位框 / 禁布区','状态']);self.tree.setMaximumHeight(180)
        self.tree.setColumnWidth(0,285)
        self.tree.itemSelectionChanged.connect(self.choose);self.tree.itemDoubleClicked.connect(lambda *_:self.navigate(self.enter))
        layout.addWidget(self.tree)
        row=QHBoxLayout();layout.addLayout(row);self.id_field=QLineEdit();self.id_field.setReadOnly(True)
        self.copy_button=QPushButton('复制 ID');row.addWidget(self.id_field);row.addWidget(self.copy_button)
        self.copy_button.clicked.connect(lambda:QApplication.clipboard().setText(self.id_field.text()))
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        region_page=QWidget();form=QVBoxLayout(region_page)
        self.name=QLineEdit();self.name.setPlaceholderText('操作区名称');row=QHBoxLayout();row.addWidget(self.name)
        self.rename_button=QPushButton('重命名');row.addWidget(self.rename_button);form.addLayout(row)
        self.rename_button.clicked.connect(lambda:self.run(self.rename_region))
        row=QHBoxLayout();form.addLayout(row)
        self.enter_button=QPushButton('进入内部');row.addWidget(self.enter_button)
        self.enter_button.clicked.connect(lambda:self.navigate(self.enter))
        self.pins=QTableWidget(0,4);self.pins.setHorizontalHeaderLabels(['网络 / PIN','层','中心 X,Y (µm)','位置约束'])
        self.pins.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.pins.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.pins.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.pins.horizontalHeader().setStretchLastSection(True)
        for column,width in enumerate((95,45,160,60)):self.pins.setColumnWidth(column,width)
        self.pins.itemSelectionChanged.connect(self.load_pin);self.pins.setMaximumHeight(180);form.addWidget(self.pins)
        self.pin_id=QLineEdit();self.pin_id.setReadOnly(True);self.pin_id.setPlaceholderText('选择 PIN 后可查看和复制完整 ID');form.addWidget(self.pin_id)
        self.advanced=QCheckBox('更多设置');form.addWidget(self.advanced)
        self.advanced_widgets=[]
        self.pin_layer=QComboBox();self.pin_x=self.number();self.pin_y=self.number()
        self.pin_layer.activated.connect(self.change_pin_layer)
        self.pin_layer.setToolTip('选择图层后立即保存，可撤销；位置仍使用“应用 PIN 位置”。')
        fields=QFormLayout();form.addLayout(fields);fields.addRow('PIN 金属层',self.pin_layer)
        self.pin_layer_status=QLabel();self.pin_layer_status.setWordWrap(True);fields.addRow(self.pin_layer_status)
        xy=QHBoxLayout();xy.addWidget(self.pin_x);xy.addWidget(self.pin_y);fields.addRow('边缘中心 X / Y (µm)',xy)
        row=QHBoxLayout();form.addLayout(row);self.place_button=QPushButton('应用 PIN 位置');self.recompute_button=QPushButton('重新计算接口')
        for button in (self.place_button,self.recompute_button):row.addWidget(button)
        self.place_button.clicked.connect(lambda:self.run(self.place_pin))
        self.recompute_button.clicked.connect(lambda:self.run(lambda:self.api().recompute(self.region_id())))
        self.issues=QPlainTextEdit();self.issues.setReadOnly(True);self.issues.setMaximumHeight(100);form.addWidget(self.issues)
        self.note=QPlainTextEdit();self.note.setPlaceholderText('该操作区的说明 / 要求（不自动解释）');self.note.setMaximumHeight(80);form.addWidget(self.note)
        self.note.hide()
        self.details_button=self.rename_button
        form.addStretch()
        self.add_tab(region_page,'模块 / PIN')
        boxes=QWidget();form=QVBoxLayout(boxes)
        self.box_text=QPlainTextEdit();self.box_text.setPlaceholderText('标注内容 / 禁布原因');self.box_text.setMaximumHeight(100);form.addWidget(self.box_text)
        self.box_text.hide()
        from ..routing_policy import RoutingPolicyPanel
        self.policy=RoutingPolicyPanel(window);form.addWidget(self.policy)
        row=QHBoxLayout();form.addLayout(row);self.markup_button=QPushButton('画定位框（生成 ID）');self.keepout_button=QPushButton('画禁止布线范围')
        row.addWidget(self.markup_button);row.addWidget(self.keepout_button)
        self.markup_button.clicked.connect(lambda:self.start_draw('markup'));self.keepout_button.clicked.connect(lambda:self.start_draw('keepout'))
        self.remove_box_button=QPushButton('删除选中的定位框 / 禁布区');form.addWidget(self.remove_box_button)
        self.remove_box_button.clicked.connect(lambda:self.run(self.remove_selected_box))
        self.check_button=QPushButton('检查现有导线与禁布策略');form.addWidget(self.check_button);self.check_button.clicked.connect(lambda:self.run(self.check_policy))
        form.addStretch();self.add_tab(boxes,'禁布层 / 定位框')
        objects=QWidget();form=QVBoxLayout(objects)
        self.object_ids=QPlainTextEdit();self.object_ids.setReadOnly(True);self.object_ids.setPlaceholderText('点击或框选器件/导线，显示完整对象 ID');form.addWidget(self.object_ids)
        self.copy_objects=QPushButton('复制选中对象 ID');form.addWidget(self.copy_objects)
        self.copy_objects.clicked.connect(lambda:QApplication.clipboard().setText('\n'.join(window.selected_uids())))
        self.add_tab(objects,'对象 ID')
        row=QHBoxLayout();layout.addLayout(row);self.save_button=QPushButton('保存工作区…');self.open_button=QPushButton('打开工作区…')
        row.addWidget(self.save_button);row.addWidget(self.open_button)
        self.save_button.clicked.connect(window.save_document_dialog);self.open_button.clicked.connect(window.open_document_dialog)
        self.message=QLabel('画框即创建模块并自动排列 PIN；拖动 PIN 调整位置，双击模块进入内部。');self.message.setWordWrap(True);layout.addWidget(self.message)
        window.canvas.region_picked.connect(self.drawn)
        window.canvas.region_cancelled.connect(self.cancel)
        # Routine placement stays visible. Audit details, IDs and layer policy
        # are available on demand; legacy text remains stored, not edited here.
        self.advanced_widgets=[self.pin_id,self.issues,self.recompute_button]
        self.advanced.toggled.connect(lambda checked:[widget.setVisible(checked) for widget in self.advanced_widgets])
        for widget in self.advanced_widgets:widget.hide()
        self.refresh()

    def add_tab(self,widget,title):
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(widget);self.tabs.addTab(scroll,title)

    @staticmethod
    def number():
        field=QDoubleSpinBox();field.setDecimals(6);field.setRange(-2000000,2000000);return field

    def api(self):return RegionActions(self.owner.editor)

    def region_id(self):
        if self.selected_id not in self.owner.editor.w.local_data.regions:raise LiteError('REGION_REQUIRED','请在树中选择操作区。')
        return self.selected_id

    def run(self,fn):
        try:
            if self.owner.busy:raise LiteError('WORKSPACE_BUSY')
            value=fn();self.owner.save_local();self.refresh();self.message.setText('已更新本地工作区，可撤销。');return value
        except Exception as exc:
            detail=json.dumps(exc.details,ensure_ascii=False) if isinstance(exc,LiteError) and exc.details else ''
            self.message.setText(str(exc)+' '+detail)

    def cancel(self):
        self.mode=None;self.owner.canvas.region_select=False;self.owner.canvas.setCursor(Qt.CursorShape.ArrowCursor)
        if hasattr(self.owner,'inspection'):self.owner.inspection.focus_pin()
        if hasattr(self.owner,'human'):self.owner.human.cancel()

    def start_draw(self,mode):
        if self.owner.busy or not self.owner.editor:return
        from ..drawing_mode import cancel_drawing
        cancel_drawing(self.owner,self)
        reason=self.owner.editor.work_sessions.readonly_reason()
        if reason and mode!='markup':self.message.setText(reason);self.owner.status.setText(reason);return
        if self.owner.editor.w.state in ('submitting','indeterminate','conflict'):
            self.message.setText('工作区需要先完成或核对原生同步。');return
        self.cancel()
        self.owner.drc.pick.setChecked(False);self.mode=mode;self.owner.canvas.region_select=True
        self.owner.canvas.setCursor(Qt.CursorShape.CrossCursor)
        self.message.setText('在画布拖出矩形，松开即可创建并分配 ID；Esc 取消。')

    def drawn(self,bounds):
        if self.mode not in ('region','markup','keepout'):return
        mode=self.mode;self.cancel()
        def create():
            scope=self.owner.editor.scope_id
            if mode=='region':ident=self.api().create(bounds,parent_id=scope)
            elif mode=='markup':ident=self.api().add_markup(bounds,'',scope)
            else:ident=self.api().add_keepout(bounds)
            self.selected_id=ident;self.policy.refresh();self.policy.select_id(ident);return ident
        ident=self.run(create)
        if ident:
            self.message.setText('已创建：'+ident)
            if mode=='region':self.message.setText('操作区已创建，PIN 已自动排列，可直接拖动调整。ID：'+ident)
            if hasattr(self.owner,'human'):self.owner.human.select(ident)

    def choose(self):
        item=self.tree.currentItem()
        if item:
            if item.data(0,Qt.ItemDataRole.UserRole)!=self.selected_id:self.cancel()
            self.selected_id=item.data(0,Qt.ItemDataRole.UserRole);self.refresh_details();self.policy.select_id(self.selected_id)
            if hasattr(self.owner,'human'):self.owner.human.select(self.selected_id)

    def activate_uid(self,ident):
        self.selected_id=ident;self.navigate(self.enter)

    def navigate(self,fn):
        try:
            if self.owner.busy:return
            fn()
        except Exception as exc:self.message.setText(str(exc))

    def enter(self):
        ident=self.region_id();self._set_scope(ident)

    def up(self):
        ident=self.owner.editor.scope_id
        if ident:self._set_scope(self.owner.editor.w.local_data.regions[ident].parent_id)

    def _set_scope(self,ident):
        self.cancel();w=self.owner
        with QSignalBlocker(w.scene):w.scene.clearSelection()
        w.editor.scope_id=ident;self.selected_id=ident
        if ident:self.fit_region(ident)
        else:w.refresh_workspace_overlay();w.fit()
        self.refresh();w.selected()
        self.message.setText('已进入 '+(w.editor.w.local_data.regions[ident].name if ident else '顶层'))

    def fit_region(self,ident):
        from ..camera import fit_bounds
        (x,y),(xx,yy)=self.owner.editor.w.local_data.regions[ident].bbox
        rect=QRectF(x,-yy,xx-x,yy-y)
        self.owner.scene.setSceneRect(rect);fit_bounds(self.owner.canvas,rect)
        self.owner.refresh_workspace_overlay()

    def select_pin(self,region_id,pin_id,*,trace=True):
        self.selected_id=region_id;self.pin_id.setText(pin_id);self.refresh_details()
        for row in range(self.pins.rowCount()):
            if self.pins.item(row,0).data(Qt.ItemDataRole.UserRole)==pin_id:self.pins.selectRow(row);break
        self.owner.inspection.focus_pin(region_id,pin_id,query=trace)
        self.owner.view_state_changed.emit()

    def place_pin(self):
        scale=self.owner.editor.profile.dbu_per_micron
        from ..human_edit import HumanEdit
        HumanEdit(self.owner.editor).adjust_pin(self.region_id(),self.pin_id.text(),self.pin_x.value()*scale,self.pin_y.value()*scale,
            layer=self.pin_layer.currentText())

    def change_pin_layer(self,_index):
        from ..presentation.pin_layer_edit import save_layer
        rid,pid=self.selected_id,self.pin_id.text()
        if not self.owner.editor or rid not in self.owner.editor.w.local_data.regions or pid not in self.owner.editor.w.local_data.regions[rid].pins:return
        position=(self.pin_x.value(),self.pin_y.value())
        try:message=save_layer(self.owner,rid,pid,self.pin_layer.currentText())
        except Exception as exc:message=str(exc)
        self.refresh();self.load_pin()
        self.pin_x.setValue(position[0]);self.pin_y.setValue(position[1]);self.pin_layer_status.setText(message)

    def load_pin(self):
        rows=self.pins.selectionModel().selectedRows()
        if not rows:self.pin_layer_status.clear();return
        ident=self.pins.item(rows[0].row(),0).data(Qt.ItemDataRole.UserRole)
        r=self.owner.editor.w.local_data.regions.get(self.selected_id)
        if r is None or ident not in r.pins:return
        pin=r.pins[ident];scale=self.owner.editor.profile.dbu_per_micron;self.pin_id.setText(ident)
        from ..interface_layers import label
        self.pin_layer.setCurrentText(label(pin));self.pin_x.setValue(sum(pt[0] for pt in pin.bbox)/(2*scale));self.pin_y.setValue(sum(pt[1] for pt in pin.bbox)/(2*scale))
        self.pin_layer_status.setText('当前设置：'+label(pin)+'；选择后自动保存。')

    @staticmethod
    def checked(widget):return tuple(widget.item(i).text() for i in range(widget.count()) if widget.item(i).checkState()==Qt.CheckState.Checked)

    @staticmethod
    def layers(widget,choices,selected):
        widget.clear()
        for name in choices:
            item=QListWidgetItem(name);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in selected else Qt.CheckState.Unchecked);widget.addItem(item)

    def save_details(self):self.rename_region()

    def remove_selected_box(self):
        target=self.policy.targets.currentData()
        ident=target[1] if target and target[0]=='keepout' else self.selected_id
        self.api().remove_box(ident)

    def rename_region(self):
        r=self.owner.editor.w.local_data.regions[self.region_id()]
        self.api().update_details(r.id,self.name.text(),r.note,r.blocked_layers)

    def check_policy(self):
        from .constraints import check_workspace
        report=check_workspace(self.owner.editor.w,self.owner.editor.profile)
        self.issues.setPlainText(json.dumps(report,ensure_ascii=False,indent=2));self.tabs.setCurrentIndex(0)

    def refresh(self):
        editor=self.owner.editor
        if editor is None:return
        w=editor.w
        if editor.scope_id not in w.local_data.regions:editor.scope_id=None
        if self.selected_id not in (w.local_data.regions.keys()|w.local_data.markups.keys()|w.local_data.keepouts.keys()):
            self.selected_id=editor.scope_id
        scope=editor.scope_id;names=[];cursor=scope
        while cursor:names.append(w.local_data.regions[cursor].name);cursor=w.local_data.regions[cursor].parent_id
        self.breadcrumb.setText('当前编辑层：顶层'+(' / '+' / '.join(reversed(names))+'\n淡显导线来自上层，仅供参考，不能在本层修改。' if names else ''))
        with QSignalBlocker(self.tree):
            self.tree.clear()
            region_items={}
            def add(parent,ident):
                region=w.local_data.regions[ident];row=QTreeWidgetItem([region.name,'本地模块'])
                row.setData(0,Qt.ItemDataRole.UserRole,ident);row.setToolTip(0,ident)
                parent.addChild(row) if parent else self.tree.addTopLevelItem(row)
                region_items[ident]=row
                if ident==self.selected_id:self.tree.setCurrentItem(row)
                for child in children(w,ident):add(row,child.id)
                row.setExpanded(True)
            for region in children(w,None):add(None,region.id)
            for item in (*w.local_data.markups.values(),*w.local_data.keepouts.values()):
                row=QTreeWidgetItem([item.id,'定位框' if item.id in w.local_data.markups else '禁布区'])
                row.setData(0,Qt.ItemDataRole.UserRole,item.id);row.setToolTip(0,item.id)
                parent=region_items.get(item.scope_id)
                parent.addChild(row) if parent else self.tree.addTopLevelItem(row)
                if item.id==self.selected_id:self.tree.setCurrentItem(row)
        self.policy.refresh()
        self.up_button.setEnabled(scope is not None)
        self.refresh_details();self.refresh_selection()

    def refresh_selection(self):
        editor=self.owner.editor
        if not editor:return
        uids=self.owner.selected_uids();owners=owner_map(editor.w)
        self.object_ids.setPlainText('\n\n'.join(f'{uid}\n{editor.object(uid).kind} · {editor.object(uid).attributes.get("name","")}\n所属：{owners.get(uid,"顶层")}' for uid in uids))
        selected=tuple(uids)
        if selected!=getattr(self,'_last_scene_selection',()):
            self._last_scene_selection=selected
            if len(uids)==1:self.policy.select_id(uids[0])

    def refresh_details(self):
        editor=self.owner.editor
        if not editor:return
        w=editor.w;r=w.local_data.regions.get(self.selected_id);changed=self._loaded_id!=self.selected_id
        self._loaded_id=self.selected_id;self.id_field.setText(self.selected_id or '')
        for button in (self.enter_button,self.recompute_button,self.details_button,self.place_button):button.setEnabled(r is not None and not self.owner.busy)
        if r is None:
            self.pins.setRowCount(0);self.pin_id.clear()
            old=getattr(self,'_loaded_box',None)
            current=w.local_data.markups.get(self.selected_id) or w.local_data.keepouts.get(self.selected_id)
            if current:
                value=getattr(current,'text',getattr(current,'note',''));prior=getattr(old,'text',getattr(old,'note',''))
                if changed or old is None or self.box_text.toPlainText()==prior:self.box_text.setPlainText(value)
            self._loaded_box=current
            return
        old=getattr(self,'_loaded_region',None)
        if changed or old is None or self.name.text()==old.name:self.name.setText(r.name)
        if changed or old is None or self.note.toPlainText()==old.note:self.note.setPlainText(r.note)
        self._loaded_region=r
        selected_pin=self.pin_id.text();scale=editor.profile.dbu_per_micron
        with QSignalBlocker(self.pins):
            self.pins.setRowCount(len(r.pins))
            for row,pin in enumerate(r.pins.values()):
                from ..interface_layers import label
                values=[pin.net,label(pin),f'{sum(pt[0] for pt in pin.bbox)/(2*scale):g}, {sum(pt[1] for pt in pin.bbox)/(2*scale):g}', '沿边']
                for col,value in enumerate(values):
                    item=QTableWidgetItem(value);item.setData(Qt.ItemDataRole.UserRole,pin.id);item.setToolTip('\n'.join(pin.evidence));self.pins.setItem(row,col,item)
                if pin.id==selected_pin:self.pins.selectRow(row)
        from ..interface_layers import ANY_METAL_LABEL
        self.pin_layer.clear();self.pin_layer.addItems([ANY_METAL_LABEL,*metals(editor.profile)]);self.load_pin()
        if not self.pins.selectionModel().selectedRows() and r.pins:self.pins.selectRow(0)
        if not r.pins:self.pin_id.clear()
        boundary_key=(id(editor),id(w.baseline),w.revision)
        if getattr(self,'_boundary_key',None)!=boundary_key:self._boundary_key=boundary_key;self._boundaries={}
        if r.id not in self._boundaries:self._boundaries[r.id]=boundary(w,r.id)
        report=self._boundaries[r.id]
        if report['unresolved'] or report.get('deferred'):self.advanced.setChecked(True)
        lines=[f'{len(report["nets"])} 个外部网络；{len(report["unresolved"])} 项待解决；{len(report.get("deferred",[]))} 个接口待补实体接入。']
        lines += [row['net']+'：'+'；'.join(row['evidence']) for row in report['nets']]
        lines += ['待解决：'+row['reason']+(' · '+str(row['reference_net']) if row.get('reference_net') else '') for row in report['unresolved']]
        lines += ['待补接口：'+row['net']+' · '+row['reason'] for row in report.get('deferred',[])]
        self.issues.setPlainText('\n'.join(lines))
        accessible=r.id==editor.scope_id or r.parent_id==editor.scope_id
        for button in (self.place_button,):button.setEnabled(accessible and not self.owner.busy)
        self.recompute_button.setEnabled(accessible and not self.owner.busy)

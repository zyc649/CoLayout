"""GUI adapter for WorkspaceActions; no independent model, history or server calls."""
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QLineEdit,QComboBox,QPushButton,QDoubleSpinBox,QPlainTextEdit,QGroupBox)
from .model import LiteError
from .workspace_actions import group_bounds


class WorkspacePanel(QWidget):
    def __init__(self,window):
        super().__init__(window);self.owner=window;self._group=None;self._texts=('', '')
        layout=QVBoxLayout(self)
        self.selection_label=QLabel('在画布上框选器件，再创建分组。');self.selection_label.setWordWrap(True);layout.addWidget(self.selection_label)
        row=QHBoxLayout();self.group_name=QLineEdit();self.group_name.setPlaceholderText('分组名称')
        self.create_button=QPushButton('从选中器件创建组');row.addWidget(self.group_name);row.addWidget(self.create_button);layout.addLayout(row)
        self.create_button.clicked.connect(lambda:self.run(self.create_group))
        self.group_choice=QComboBox();layout.addWidget(self.group_choice)
        self.group_choice.currentIndexChanged.connect(lambda:self.refresh(force=True))
        move=QHBoxLayout();self.dx=self.number();self.dy=self.number()
        self.move_button=QPushButton('移动整组')
        for widget in (QLabel('ΔX'),self.dx,QLabel('ΔY'),self.dy,self.move_button):move.addWidget(widget)
        layout.addLayout(move);self.move_button.clicked.connect(lambda:self.run(lambda:
            window.workspace_actions.move_group(self.group_id(),self.dx.value(),self.dy.value())))
        self.pin_box=QGroupBox('本地 PIN · 仅为标记，不创建金属');form=QFormLayout(self.pin_box)
        self.pin_name=QLineEdit();self.net=QComboBox();self.net.setEditable(True);self.layer=QComboBox()
        form.addRow('名称',self.pin_name);form.addRow('网络',self.net);form.addRow('层',self.layer)
        self.pin_fields={key:self.number(positive=key in ('width','height')) for key in ('x','y','width','height')}
        for key,title in [('x','X (µm)'),('y','Y (µm)'),('width','宽 (µm)'),('height','高 (µm)')]:form.addRow(title,self.pin_fields[key])
        self.pin_fields['width'].setValue(.6);self.pin_fields['height'].setValue(.6)
        self.pin_button=QPushButton('添加 / 更新组内 PIN');form.addRow(self.pin_button);layout.addWidget(self.pin_box)
        self.pin_button.clicked.connect(lambda:self.run(self.set_pin))
        self.pin_summary=QLabel();self.pin_summary.setWordWrap(True);layout.addWidget(self.pin_summary)
        self.note=QPlainTextEdit();self.note.setPlaceholderText('说明：这组器件的用途、操作备注…');self.note.setMaximumHeight(95)
        self.requirement=QPlainTextEdit();self.requirement.setPlaceholderText('要求：由人或 Agent 提出，软件不自动解释…');self.requirement.setMaximumHeight(95)
        layout.addWidget(self.note);layout.addWidget(self.requirement)
        self.note.hide();self.requirement.hide()
        self.text_button=QPushButton('保存说明与要求');layout.addWidget(self.text_button)
        self.text_button.clicked.connect(lambda:self.run(lambda:window.workspace_actions.set_group_text(
            self.group_id(),self.note.toPlainText(),self.requirement.toPlainText())))
        self.text_button.hide()
        row=QHBoxLayout();self.remove_button=QPushButton('解散分组');self.save_button=QPushButton('保存工作区…');self.open_button=QPushButton('打开工作区…')
        for button in (self.remove_button,self.save_button,self.open_button):row.addWidget(button)
        layout.addLayout(row)
        self.remove_button.clicked.connect(lambda:self.run(lambda:window.workspace_actions.remove_group(self.group_id())))
        self.save_button.clicked.connect(window.save_document_dialog);self.open_button.clicked.connect(window.open_document_dialog)
        self.result=QLabel('分组、PIN、说明与版图共用保存和撤销。');self.result.setWordWrap(True);layout.addWidget(self.result)
        layout.addStretch();self.refresh()

    @staticmethod
    def number(positive=False):
        field=QDoubleSpinBox();field.setDecimals(6);field.setRange(.000001 if positive else -2000000,2000000);field.setSingleStep(1)
        return field

    def group_id(self):
        value=self.group_choice.currentData()
        if not value:raise LiteError('LOCAL_GROUP_REQUIRED','请先创建或选择分组。')
        return value

    def run(self,operation):
        try:
            if self.owner.busy:raise LiteError('WORKSPACE_BUSY','远端操作进行中，请稍后编辑。')
            result=operation();self.owner.save_local();self.refresh()
            self.result.setText('已更新本地工作区，可直接撤销。');return result
        except Exception as exc:self.result.setText(str(exc))

    def create_group(self):
        ident=self.owner.workspace_actions.create_group(self.group_name.text().strip(),self.owner.selected_uids())
        self.refresh();self.group_choice.setCurrentIndex(self.group_choice.findData(ident));return ident

    def set_pin(self):
        self.owner.workspace_actions.set_pin(self.pin_name.text().strip(),self.net.currentText(),self.layer.currentText(),
            **{key:field.value() for key,field in self.pin_fields.items()},group_id=self.group_id())

    def refresh(self,force=False):
        editor=self.owner.editor
        if editor is None:return
        selected=self.group_choice.currentData();local=editor.w.local_data
        with QSignalBlocker(self.group_choice):
            self.group_choice.clear()
            for group in local.groups.values():self.group_choice.addItem(f'{group.name} ({len(group.object_uids)})',group.id)
            index=self.group_choice.findData(selected)
            if index>=0:self.group_choice.setCurrentIndex(index)
        ident=self.group_choice.currentData();changed=force or ident!=self._group
        if changed:
            self._group=ident
            nets=[]
            if editor.w.layout_connectivity:
                from .circuit.query import selection_boundary
                if ident:
                    try:nets=[r['net'] for r in selection_boundary(editor.w,local.groups[ident].object_uids)['boundary_nets']]
                    except LiteError:nets=[]  # Show only explicitly known nets below; never invent missing ones.
                if not nets:
                    nets=sorted({n for inst in editor.w.layout_connectivity.instances.values() for term in inst.terminals.values()
                        for n in (term.members or {term.name:term.net}).values() if n})
            self.net.clear();self.net.addItems(nets)
            self.layer.clear();self.layer.addItems([layer for layer,purpose in editor.profile.writable_lpps
                if purpose=='drawing' and any(r['layer']==layer and r.get('material')=='metal' for r in editor.profile.layers)])
            if ident:
                bounds=group_bounds(editor.w,local.groups[ident]);scale=editor.profile.dbu_per_micron
                self.pin_fields['x'].setValue(bounds[0][0]/scale);self.pin_fields['y'].setValue(bounds[1][1]/scale+1)
        values=tuple(next((a.text for a in local.annotations.values() if a.group_id==ident and a.kind==kind),'') for kind in ('note','requirement'))
        for field,previous,value in zip((self.note,self.requirement),self._texts,values):
            if changed or field.toPlainText()==previous or field.toPlainText()==value:field.setPlainText(value)
        self._texts=values
        pins=[p.name for p in local.pins.values() if p.group_id==ident]
        self.pin_summary.setText('本组 PIN：'+(', '.join(pins) if pins else '尚无'))
        self.selection_label.setText(f'当前选中 {len(self.owner.selected_uids())} 个对象。框选器件后创建组。')
        for button in (self.move_button,self.pin_button,self.text_button,self.remove_button):button.setEnabled(bool(ident) and not self.owner.busy)
        self.create_button.setEnabled(not self.owner.busy)

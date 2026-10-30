"""Reusable DRC fields. Draft editing has no persistence or native side effects."""
from PySide6.QtCore import Qt,QSignalBlocker
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QPushButton,QFormLayout,QLineEdit,QCheckBox,QComboBox,QStyledItemDelegate,QPlainTextEdit)
from .models import DrcProfile,Rule,RemoteConfig


class ChoiceDelegate(QStyledItemDelegate):
    def __init__(self,choices,parent):
        super().__init__(parent);self.choices=choices
    def displayText(self,value,locale):
        return next((label for label,key in self.choices if key==str(value)),str(value))
    def createEditor(self,parent,option,index):
        editor=QComboBox(parent)
        for label,key in self.choices:editor.addItem(label,key)
        return editor
    def setEditorData(self,editor,index):
        editor.setCurrentIndex(editor.findData(str(index.data(Qt.ItemDataRole.EditRole))))
    def setModelData(self,editor,model,index):
        model.setData(index,editor.currentData(),Qt.ItemDataRole.EditRole)


class DrcFields:
    columns=['id','kind','layer','other_layer','value','enabled','severity','note','source']
    def __init__(self,*,separate_warnings=False):
        self.original=None;self.technology=None
        self.local=QWidget();layout=QVBoxLayout(self.local)
        self.local_status=QLabel('尚未配置本地 DRC');self.local_status.setWordWrap(True);layout.addWidget(self.local_status)
        from .mim_fields import MimFields
        self.mim_fields=MimFields();layout.addWidget(self.mim_fields)
        layout.addWidget(QLabel('单位：µm（面积为 µm²）。阈值须来自实际规则，不是默认画线宽度。'))
        note=QLabel('间距检查不区分同网/异网，也不比较网络名称。同层多条间距规则会同时执行，并非条件分支。\n规则 ID、说明和来源不参与条件判断；在检查覆盖范围内，满足全部间距规则须达到最大启用阈值。');note.setWordWrap(True);layout.addWidget(note)
        self.rules=QTableWidget(0,len(self.columns));self.rules.setHorizontalHeaderLabels(['规则 ID','类型','检查层','包围层','阈值','启用','级别','说明/局限','规则来源']);layout.addWidget(self.rules,1)
        self.rules.setItemDelegateForColumn(1,ChoiceDelegate([('线宽','width'),('间距','spacing'),('面积','area'),('包围','enclosure')],self.rules))
        self.rules.setItemDelegateForColumn(5,ChoiceDelegate([('启用','true'),('停用','false')],self.rules))
        self.rules.setItemDelegateForColumn(6,ChoiceDelegate([('工艺错误','error'),('工艺警告','warning')],self.rules))
        self.rule_details=QPlainTextEdit();self.rule_details.setReadOnly(True);self.rule_details.setMaximumHeight(85)
        self.rule_details.setPlaceholderText('选择规则查看完整说明与来源；文字不参与条件判断。');layout.addWidget(self.rule_details)
        self.rules.itemSelectionChanged.connect(self.describe_rule);self.rules.itemChanged.connect(lambda _:self.describe_rule())
        self.rules.setToolTip('类型 width / spacing / area / enclosure；启用 true / false；级别 error / warning。')
        row=QHBoxLayout();layout.addLayout(row);add=QPushButton('增加规则');remove=QPushButton('删除所选规则');row.addWidget(add);row.addWidget(remove)
        add.clicked.connect(lambda:self.add_rule({'id':'new_rule','kind':'spacing','value':'','enabled':False,'severity':'warning'}))
        remove.clicked.connect(lambda:self.rules.removeRow(self.rules.currentRow()) if self.rules.currentRow()>=0 else None)
        self.halo=QLineEdit('2');self.max_markers=QLineEdit('10000');form=QFormLayout();layout.addLayout(form)
        form.addRow('本地上下文 µm',self.halo);form.addRow('本地结果上限',self.max_markers)
        from .warning_fields import WarningFields
        self.warning_fields=WarningFields()
        if not separate_warnings:layout.addWidget(self.warning_fields)
        self.server=QWidget();form=QFormLayout(self.server)
        self.remote_status=QLabel('尚未配置服务器 DRC');self.remote_status.setWordWrap(True);form.addRow(self.remote_status)
        self.enabled=QCheckBox('启用服务器区域全规则检查');form.addRow(self.enabled)
        self.remote_fields={};defaults=RemoteConfig(deck_path='/path/to/foundry.drc',layer_map='/path/to/strmoutMap').model_dump()
        labels={'deck_path':'规则主文件','deck_sha256':'规则 SHA256','layer_map':'GDS 层映射','layer_map_sha256':'层映射 SHA256','calibre':'Calibre 可执行文件','strmout':'XStream 可执行文件','environment':'环境初始化脚本','halo_um':'区域上下文 µm','timeout_seconds':'每阶段超时秒数','max_results_per_rule':'单条规则结果上限'}
        for key,value in defaults.items():
            field=QLineEdit(str(value));self.remote_fields[key]=field;form.addRow(labels[key],field)
            if key.endswith('sha256'):field.setReadOnly(True);field.setToolTip('由路径核对脚本生成；修改路径后在确认时重新核对。')
        note=QLabel('检查选定区域及周边上下文，运行主规则 deck。“摘要与报告”的过滤设置统一用于显示和区域验收，原始报告保留。');note.setWordWrap(True);form.addRow(note)

    def add_rule(self,data):
        row=self.rules.rowCount();self.rules.insertRow(row)
        for col,key in enumerate(self.columns):
            value=data.get(key,'');value='' if value is None else str(value).lower() if isinstance(value,bool) else str(value)
            self.rules.setItem(row,col,QTableWidgetItem(value))

    def set_profile(self,technology,profile,proof=None):
        self.technology=technology;self.original=profile
        from .mim_config import MimCapacitor
        self.mim_fields.set_profile(technology,profile.mim_capacitor if profile else MimCapacitor())
        from .warning_models import DesignWarnings
        self.warning_fields.set_profile(technology,profile.design_warnings if profile else DesignWarnings())
        # Loading a profile is one change, not an edit per table cell.
        # In particular, itemChanged must not repeatedly clear/re-layout the
        # rule detail document while hundreds of cells are being inserted.
        with QSignalBlocker(self.rules):
            self.rules.setRowCount(0)
            for rule in profile.rules if profile else ():self.add_rule(rule.model_dump())
        self.describe_rule()
        self.halo.setText(str(profile.local_halo_um if profile else 2));self.max_markers.setText(str(profile.max_markers if profile else 10000));self.enabled.setChecked(bool(profile and profile.remote))
        values=profile.remote.model_dump() if profile and profile.remote else {k:'' for k in self.remote_fields}
        for k,field in self.remote_fields.items():field.setText(str(values[k]))
        passed=(proof or {}).get('status')=='passed'
        self.local_status.setText(('已验证：故意错误可检出、修复后该错误消失。' if passed else '已有配置，尚未完成本次联合验证。' if profile else '缺少本地规则：由 Agent 读取真实工艺规则后填写。')+'\n本地检查是简化筛查，不覆盖完整 foundry 条件。')
        self.remote_status.setText(('已验证：真实 Calibre 执行、报告解析和坐标回传。' if passed else '服务器配置待验证。')+'\n'+str((proof or {}).get('report','')))

    def describe_rule(self):
        row=self.rules.currentRow()
        if row<0:self.rule_details.clear();return
        def text(column):
            item=self.rules.item(row,column)
            return item.text() if item else ''
        self.rule_details.setPlainText(text(0)+'\n说明/局限（不参与条件判断）：'+text(7)+'\n来源（仅作依据）：'+text(8))

    def value(self):
        rows=[]
        for row in range(self.rules.rowCount()):
            data={key:self.rules.item(row,col).text().strip() for col,key in enumerate(self.columns)}
            data['other_layer']=data['other_layer'] or None;rows.append(Rule.model_validate(data))
        values={k:f.text().strip() for k,f in self.remote_fields.items()}
        for path,checksum in [('deck_path','deck_sha256'),('layer_map','layer_map_sha256')]:
            if self.original and self.original.remote and values[path]!=getattr(self.original.remote,path):values[checksum]=''
        remote=RemoteConfig.model_validate(values) if self.enabled.isChecked() else None
        result=DrcProfile(id=self.original.id if self.original else self.technology.label+' DRC',technology_fingerprint=self.technology.native_fingerprint,configuration_id=self.technology.configuration_id,
            rules=tuple(rows),local_halo_um=float(self.halo.text()),max_markers=int(self.max_markers.text()),remote=remote,
            design_warnings=self.warning_fields.value(),provenance=self.original.provenance if self.original else {})
        result=result.model_copy(update={'mim_capacitor':self.mim_fields.value()})
        result.check_technology(self.technology);return result

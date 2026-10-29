"""Read-only schematic reference: flat occurrence list and explicit details."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QVBoxLayout,QLabel,QPlainTextEdit,QTabWidget,QWidget,QComboBox,QPushButton,QSplitter
from .query import inspect_circuit
from .reference_data import endpoint_rows,instance_records
from .reference_table import ReferenceTable
from ..presentation.dark_dialog import DarkDialog
from ..technology import DEFAULT_SCHEMATIC_SUMMARY_PARAMETERS


class CircuitDialog(DarkDialog):
    def __init__(self,workspace,parent=None,*,profile=None):
        super().__init__(parent)
        self._source_context=(workspace.circuit,workspace.layout_connectivity,
            tuple(profile.schematic_summary_parameters if profile else DEFAULT_SCHEMATIC_SUMMARY_PARAMETERS))
        self.setWindowTitle('原理图参考');self.resize(1100,780)
        layout=QVBoxLayout(self)
        data=inspect_circuit(workspace);source=data['source'];layout_source=workspace.layout_connectivity.source
        pair=workspace.circuit.pair_id or '旧快照：未记录，请刷新导入'
        label=QLabel(f"原理图：{source['library']}/{source['cell']}/{source['view']} · 版本 {source['counter']}\n"
            f"Layout：{layout_source.library}/{layout_source.cell}/{layout_source.view} · 版本 {layout_source.counter}\n"
            f'配对导入 ID：{pair}\n只读缓存；参数按原生值保存，不求值。')
        label.setTextFormat(Qt.TextFormat.PlainText);label.setWordWrap(True);layout.addWidget(label)
        self.tabs=QTabWidget();layout.addWidget(self.tabs)

        self.ports_page=QWidget();ports_layout=QVBoxLayout(self.ports_page)
        bit_count=sum(len(port['members']) or 1 for port in data['ports'].values())
        self.ports_status=QLabel(f'原理图顶层 PIN：{len(data["ports"])} 个端口，{bit_count} 个信号成员；'
            f'Layout 原生顶层 PIN：{len(workspace.layout_connectivity.ports)} 个端口。')
        self.ports_status.setWordWrap(True);ports_layout.addWidget(self.ports_status)
        self.ports=ReferenceTable(['顶层 PIN / 总线成员','原生方向','原生网络','所连原理图器件端点'])
        endpoints={}
        for inst in data['instances'].values():
            for terminal in inst['terminals'].values():
                for member,net in (terminal['members'] or {terminal['name']:terminal['net']}).items():
                    if net is not None:endpoints.setdefault(net,[]).append(inst['name']+'.'+member)
        self.ports.set_rows(endpoint_rows(data['ports'],endpoints))
        for column,width in enumerate((200,125,170)):self.ports.setColumnWidth(column,width)
        ports_layout.addWidget(self.ports);self.tabs.addTab(self.ports_page,f'顶层 PIN（{len(data["ports"])}）')

        self.records=instance_records(workspace,data)
        names=profile.schematic_summary_parameters if profile else DEFAULT_SCHEMATIC_SUMMARY_PARAMETERS
        rows=[]
        for record in self.records:
            inst=record['instance'];params=inst['parameters'];targets=record['targets']
            summary=', '.join(f'{key}={display_value(params[key]["value"])}' for key in names if key in params)
            target_text=', '.join(name for name,uid in targets[:3])
            if len(targets)>3:target_text+=f' …（共 {len(targets)} 个，见下方）'
            rows.append((record['label'],'/'.join(inst['master'][:2]),summary,target_text))
        self.instances_page=QWidget();instances_layout=QVBoxLayout(self.instances_page)
        self.instances=ReferenceTable(['参考实例 / 层次路径','Master','原生参数摘要','对应 Layout 实例'])
        self.instances.set_rows(rows)
        for column,width in enumerate((220,190,300)):self.instances.setColumnWidth(column,width)
        self.selected_label=QLabel('选择器件查看端子和完整对应关系。')
        self.selected_label.setTextFormat(Qt.TextFormat.PlainText);self.selected_label.setWordWrap(True)
        details_page=QWidget();details_layout=QVBoxLayout(details_page);details_layout.setContentsMargins(0,0,0,0)
        details_layout.addWidget(self.selected_label);self.instance_details=QTabWidget();details_layout.addWidget(self.instance_details)
        self.terminals=ReferenceTable(['端子 / 成员','原生方向','原生网络'])
        self.targets=ReferenceTable(['Layout 实例','对象 UID'])
        self.scope_ports=ReferenceTable(['本层接口 / 成员','原生方向','原生网络'])
        self.targets.setColumnWidth(0,420)
        for table in (self.terminals,self.scope_ports):
            table.setColumnWidth(0,220);table.setColumnWidth(1,140)
        self.instance_details.addTab(self.terminals,'端子');self.instance_details.addTab(self.targets,'Layout 对应')
        self.instance_details.addTab(self.scope_ports,'所属层接口')
        splitter=QSplitter(Qt.Orientation.Vertical);splitter.addWidget(self.instances);splitter.addWidget(details_page)
        splitter.setSizes([390,200]);instances_layout.addWidget(splitter)
        self.tabs.addTab(self.instances_page,'器件、连接与对应')

        self.parameter_page=QWidget();form=QVBoxLayout(self.parameter_page)
        self.instance_choice=QComboBox();self.instance_choice.addItems([r['label'] for r in self.records]);form.addWidget(self.instance_choice)
        self.parameter_status=QLabel();self.parameter_status.setTextFormat(Qt.TextFormat.PlainText);form.addWidget(self.parameter_status)
        self.parameters=ReferenceTable(['参数','原生有效值','CDF 默认值','类型 / 单位','来源','实例显式值'])
        for column,width in enumerate((135,190,170,120,150)):self.parameters.setColumnWidth(column,width)
        form.addWidget(self.parameters);self.tabs.addTab(self.parameter_page,'全部原生参数')
        self.instance_choice.currentIndexChanged.connect(self.choose_parameters)
        self.instances.selectionModel().currentRowChanged.connect(self.choose_instance)
        if self.records:self.choose_parameters();self.instances.selectRow(0)

        self._json_data=data;self._json_text=None
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.json_page=QWidget();json_layout=QVBoxLayout(self.json_page)
        self.json_note=QLabel();self.json_note.hide();json_layout.addWidget(self.json_note);json_layout.addWidget(self.details)
        self.tabs.addTab(self.json_page,'本地 JSON');self.tabs.currentChanged.connect(self.show_json)
        copy=QPushButton('复制本地 JSON');copy.clicked.connect(lambda:QApplication.clipboard().setText(self.full_json()))
        layout.addWidget(copy)

    def choose_instance(self,current,*unused):
        if not current.isValid():return
        record=self.records[current.row()];source=record['source']
        self.selected_label.setText(record['label']+' · 所属原理图：'+'/'.join(source[k] for k in ('library','cell','view')))
        self.terminals.set_rows(row[:3] for row in endpoint_rows(record['instance']['terminals']))
        self.targets.set_rows(record['targets'])
        self.scope_ports.set_rows(row[:3] for row in endpoint_rows(record['ports']))
        self.instance_details.setTabText(1,f'Layout 对应（{len(record["targets"])}）')
        self.instance_choice.setCurrentIndex(current.row())

    def choose_parameters(self,*unused):
        index=self.instance_choice.currentIndex()
        if index<0:return
        inst=self.records[index]['instance'];self.parameter_status.setText('原生 CDF · '+inst['parameter_capture'])
        self.parameters.set_rows((name,display_value(param['value']),display_value(param['default']),
            (param['value_type'] or '')+' / '+(param['units'] or ''),param['origin'],display_value(param['instance_value']))
            for name,param in inst['parameters'].items())

    def full_json(self):
        if self._json_text is None:self._json_text=json.dumps(self._json_data,ensure_ascii=False,indent=2)
        return self._json_text

    def same_source(self,workspace,profile):
        names=tuple(profile.schematic_summary_parameters if profile else DEFAULT_SCHEMATIC_SUMMARY_PARAMETERS)
        return self._source_context[0] is workspace.circuit and self._source_context[1] is workspace.layout_connectivity and self._source_context[2]==names

    def show_json(self,*unused):
        if self.tabs.currentWidget() is not self.json_page or self.details.document().characterCount()>1:return
        text=self.full_json();limit=65536;self.details.setPlainText(text[:limit])
        if len(text)>limit:
            self.json_note.setText('这里只预览前 65,536 个字符；“复制本地 JSON”包含完整数据。');self.json_note.show()


def display_value(value):
    if value is None:return 'nil'
    if isinstance(value,list) and len(value)==2 and value[0] in ('string','number','opaque'):return str(value[1])
    return json.dumps(value,ensure_ascii=False)

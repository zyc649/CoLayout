"""One editor for saved configuration, incoming proposals and shared files."""
from math import lcm
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QFormLayout,QLabel,QLineEdit,QDoubleSpinBox,
    QComboBox,QTabWidget,QScrollArea,QTableWidget,QTableWidgetItem,QPlainTextEdit,QCheckBox)
from .process_package import ProcessPackage
from .technology import TechnologyProfile
from .process_widgets import LayerChecklist
from .width_widgets import AdditionalWidths
from .wire_defaults import metal_stack
from .drc.fields import DrcFields
from .drc.waivers import WaiverPolicy
from .mpp_recipe import GuardRecipe,sampled,native_templates


def page(tabs,title,widget):
    scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setObjectName('processConfigScroll');widget.setObjectName('processConfigPage')
    scroll.setWidget(widget);tabs.addTab(scroll,title)
    return scroll


class ConfigurationEditor(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.original=None
        box=QVBoxLayout(self);box.setContentsMargins(0,0,0,0)
        self.tabs=QTabWidget();box.addWidget(self.tabs)
        basic=QWidget();form=QFormLayout(basic)
        self.name=QLineEdit();form.addRow('工艺名称',self.name)
        self.agent_autoroute=QCheckBox('允许 Agent 使用算法自动布线')
        self.agent_autoroute.setToolTip('默认关闭。仅控制 Agent 的 route_region 接口；人类 UI 自动布线及其他 Agent 编辑、排列、对齐、过孔工具不受影响。')
        form.addRow(self.agent_autoroute)
        self.identity=QLabel();self.identity.setWordWrap(True);form.addRow(self.identity)
        self.stack=QLineEdit();self.stack.setPlaceholderText('实际金属层名，按从低到高排列，逗号分隔');form.addRow('金属层次',self.stack)
        self.width=QDoubleSpinBox();self.width.setDecimals(6);self.width.setRange(.000001,10000);self.width.setSuffix(' µm')
        self.width_label=QLabel('首层默认线宽');form.addRow(self.width_label,self.width)
        self.widths=AdditionalWidths();form.addRow(self.widths)
        self.via=QComboBox();form.addRow('默认标准过孔',self.via)
        self.layers=LayerChecklist();self.layers.setMinimumHeight(240);form.addRow(self.layers)
        page(self.tabs,'绘图与图层',basic)
        self.drc=DrcFields(separate_warnings=True)
        page(self.tabs,'本地 DRC',self.drc.local)
        # Direction/cut-count preferences get a dedicated page in the same editor.
        preferences=QWidget();preference_layout=QVBoxLayout(preferences)
        preference_layout.addWidget(self.drc.warning_fields);preference_layout.addStretch(1)
        page(self.tabs,'设计提醒',preferences)
        page(self.tabs,'服务器 DRC',self.drc.server)
        guards=QWidget();layout=QVBoxLayout(guards)
        layout.addWidget(QLabel('单排 / 双排指接触孔排数；同一类型可绘制闭环和开放路径。双排需有真实样例。'))
        self.guards=QTableWidget(0,4);self.guards.setHorizontalHeaderLabels(['启用','保护环类型','支持形状','来源与状态'])
        self.guards.horizontalHeader().setStretchLastSection(True);self.guards.setColumnWidth(0,55)
        self.guards.setColumnWidth(1,230);self.guards.setColumnWidth(2,230)
        layout.addWidget(self.guards)
        self.guard_details=QLabel();self.guard_details.setTextFormat(Qt.TextFormat.PlainText);self.guard_details.setWordWrap(True)
        layout.addWidget(self.guard_details);self.guards.currentCellChanged.connect(self.describe_guard)
        page(self.tabs,'保护环',guards)
        display=QWidget();form=QFormLayout(display)
        self.summary_parameters=QLineEdit();form.addRow('原理图参数摘要',self.summary_parameters)
        self.summary_parameters.setPlaceholderText('PDK 实际参数名，逗号分隔；留空不显示摘要')
        self.report_enabled=QCheckBox('应用服务器报告过滤');form.addRow(self.report_enabled)
        self.report_rules=QPlainTextEdit();self.report_keywords=QPlainTextEdit()
        self.report_rules.setMaximumHeight(100);self.report_keywords.setMaximumHeight(100)
        form.addRow('规则 ID（每行一项）',self.report_rules);form.addRow('关键词（每行一项）',self.report_keywords)
        note=QLabel('UI、Agent API 和区域完成验收共用此过滤设置。原始报告保留；不代表整芯片或 LVS 签核。')
        note.setWordWrap(True);form.addRow(note)
        self.notes=QPlainTextEdit();self.notes.setMaximumHeight(100);form.addRow('配置说明',self.notes)
        page(self.tabs,'摘要与报告',display)

    def set_package(self,package):
        self.original=package;p=package.technology
        self.agent_autoroute.setChecked(package.agent_autoroute_enabled)
        self.name.setText(p.label);self.identity.setText(f'原生技术库：{p.native_technology_name or "旧配置未记录"} · 网格 {p.grid/p.dbu_per_micron:g} µm · {p.dbu_per_micron} DBU/µm\n配置标识：{p.key}')
        try:stack=metal_stack(p,p.editor_defaults.get('metal_stack'))
        except Exception:stack=p.editor_defaults.get('metal_stack',[])
        self.stack.setText(', '.join(stack));self.width_label.setText('首层默认线宽'+(' · '+stack[0] if stack else ''))
        self.width.setSingleStep(lcm(p.grid,2)/p.dbu_per_micron);self.width.setValue(p.editor_defaults.get('width_um',.8))
        self.width.setToolTip('默认线宽取样例标准过孔的外部金属矩形短边，与切孔尺寸及 DRC 最小宽度不同。')
        vias=package.sample_evidence.get('stack_measurement',{}).get('vias',[])
        if stack and vias and stack[0] in vias[0].get('metal_rectangles',{}):
            size=vias[0]['metal_rectangles'][stack[0]]['size_dbu']
            self.width.setToolTip(f'样例 {vias[0]["definition"]} 的 {stack[0]} 金属：'+
                f'{size[0]/p.dbu_per_micron:g} × {size[1]/p.dbu_per_micron:g} µm；默认取金属短边。')
        self.widths.set_profile(p);self.layers.set_profile(p,sampled_lpps=package.sample_evidence.get('standalone_lpps',[]))
        self.via.clear()
        for name,via in p.vias.items():
            if via.get('kind')=='stdViaDef' and not via.get('cut_pattern'):
                self.via.addItem(name+' · '+str(via.get('layer1'))+' / '+str(via.get('layer2')),name)
        self.via.setCurrentIndex(self.via.findData(p.editor_defaults.get('via_definition')))
        self.drc.set_profile(p,package.drc)
        self.drc.local_status.setText('轻量检查；不支持的宽度计算跳过。阈值来自实际工艺规则。')
        self.drc.remote_status.setText('核对本机服务器上的规则文件、层映射和工具路径。')
        entries=[('template',raw,raw in native_templates(p)) for raw in p.guard_templates]
        entries += [('recipe',raw,raw.get('kind')!='double' or sampled(GuardRecipe.model_validate(raw))) for raw in p.guard_recipes]
        self.guards.setRowCount(len(entries))
        for i,(kind,raw,usable) in enumerate(entries):
            item=QTableWidgetItem();item.setData(Qt.ItemDataRole.UserRole,(kind,raw))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled|(Qt.ItemFlag.ItemIsUserCheckable if usable else Qt.ItemFlag.NoItemFlags))
            item.setCheckState(Qt.CheckState.Checked if usable else Qt.CheckState.Unchecked);self.guards.setItem(i,0,item)
            label=raw['name']+(' · 双排接触孔' if raw.get('kind')=='double' else ' · 原生模板' if kind=='template' else ' · 单排接触孔')
            state='原生模板 · '+str(raw['library']) if kind=='template' else '样例：'+str(raw.get('source',{}).get('sample',{}).get('cell',''))
            forms='—'
            if not usable:state='无样例依据，不启用新建能力'
            elif kind=='recipe':
                verified=GuardRecipe.model_validate(raw).ready()
                state+=' · '+('几何已核对' if verified and raw.get('validation',{}).get('kind')=='native_reproduction' else '已有验证记录' if verified else '待核对')
                forms='矩形闭环 / 开放 90° 路径' if verified else '待核对'
            else:forms='矩形闭环 / 开放 90° 路径'
            for column,text in [(1,label),(2,forms),(3,state)]:
                cell=QTableWidgetItem(text);cell.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable);cell.setToolTip(text);self.guards.setItem(i,column,cell)
        self.summary_parameters.setText(', '.join(p.schematic_summary_parameters))
        report=package.report_policy or WaiverPolicy(technology_fingerprint=p.native_fingerprint,configuration_id=p.configuration_id)
        self.report_enabled.setChecked(report.enabled);self.report_rules.setPlainText('\n'.join(report.rule_ids));self.report_keywords.setPlainText('\n'.join(report.keywords))
        self.notes.setPlainText(package.notes)
        if self.guards.rowCount():self.guards.setCurrentCell(0,1)
        self.describe_guard()
        self._initial_drawing=self.drawing_state()
        self._initial_guards=self.guard_state()
        try:self._initial_value=self.value().fingerprint()
        except (ValueError,IndexError,KeyError):self._initial_value=None

    def drawing_state(self):
        return ([s.strip() for s in self.stack.text().replace('，',',').split(',') if s.strip()],
                self.width.value(),self.widths.values(),self.via.currentData())

    def describe_guard(self,*unused):
        row=self.guards.currentRow()
        item=self.guards.item(row,0) if row>=0 else None
        if not item or not self.original:self.guard_details.clear();return
        kind,raw=item.data(Qt.ItemDataRole.UserRole)
        if kind=='template':
            self.guard_details.setText('原生模板：'+raw['name']+' · '+raw['library']);return
        scale=self.original.technology.dbu_per_micron
        self.guard_details.setText('主路径：'+'/'.join(raw['master_lpp'])+
            f" · 宽度 {raw['width']/scale:g} µm\n构造下限：环边 {raw['min_side_dbu']/scale:g} µm · 开放段 {raw['min_length_dbu']/scale:g} µm"+
            '\n截面层：'+', '.join(dict.fromkeys('/'.join(p['lpp']) for p in raw['parts'])))
        if raw.get('validation',{}).get('kind')=='native_reproduction':
            self.guard_details.setText(self.guard_details.text()+'\n已核对原生几何复现；未作 DRC 签核。')
        context=raw.get('validation',{}).get('context',{})
        if context.get('kind')=='nwell_region':
            self.guard_details.setText(self.guard_details.text()+'\n使用条件：搭配完整井区覆盖（'+
                '、'.join(lpp[0] for lpp in context['layers'])+'）。')

    def guard_state(self):
        return tuple(self.guards.item(i,0).checkState() for i in range(self.guards.rowCount()))

    def is_dirty(self):
        try:return self.value().fingerprint()!=self._initial_value
        except (ValueError,IndexError,KeyError):return True

    def value(self):
        if self.original is None:raise ValueError('请选择工艺配置')
        p=self.original.technology;stack=[s.strip() for s in self.stack.text().replace('，',',').split(',') if s.strip()]
        metal_stack(p,stack)
        defaults={**p.editor_defaults,'metal_stack':stack,'layer':[stack[0],'drawing'],
                  'width_um':self.width.value(),'widths_um':{**self.widths.values(),stack[0]:self.width.value()},
                  'via_definition':self.via.currentData()}
        if self.drawing_state()==getattr(self,'_initial_drawing',None) and {tuple(v) for v in self.layers.selected_layers()}==set(p.writable_lpps):defaults=p.editor_defaults
        guards={'template':[],'recipe':[]}
        for row in range(self.guards.rowCount()):
            item=self.guards.item(row,0)
            if item.checkState()==Qt.CheckState.Checked:
                kind,raw=item.data(Qt.ItemDataRole.UserRole);guards[kind].append(raw)
        if self.guard_state()==getattr(self,'_initial_guards',None):
            guards={'template':p.guard_templates,'recipe':p.guard_recipes}
        name=self.name.text().strip()
        if not name:raise ValueError('请填写工艺名称')
        layers=self.layers.selected_layers()
        if {tuple(v) for v in layers}==set(p.writable_lpps):layers=p.writable_lpps
        p=TechnologyProfile.model_validate({**p.model_dump(mode='json'),'id':p.id,'label':name,
            'editor_defaults':defaults,'writable_lpps':layers,
            'guard_templates':guards['template'],'guard_recipes':guards['recipe'],
            'schematic_summary_parameters':[s.strip() for s in self.summary_parameters.text().replace('，',',').split(',') if s.strip()]})
        report=WaiverPolicy(technology_fingerprint=p.native_fingerprint,configuration_id=p.configuration_id,enabled=self.report_enabled.isChecked(),
            rule_ids=tuple(s.strip() for s in self.report_rules.toPlainText().splitlines() if s.strip()),
            keywords=tuple(s.strip() for s in self.report_keywords.toPlainText().splitlines() if s.strip()))
        drc=None if self.original.drc is None and not self.drc.rules.rowCount() and not self.drc.enabled.isChecked() else self.drc.value()
        return self.original.model_copy(update={'technology':p,'drc':drc,
            'report_policy':report,'notes':self.notes.toPlainText(),
            'agent_autoroute_enabled':self.agent_autoroute.isChecked()})

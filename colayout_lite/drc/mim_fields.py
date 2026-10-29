"""Small human-review editor for the MIM layer and adjacent metal pair."""
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QGroupBox,QFormLayout,QComboBox,QLineEdit,QLabel
from .mim_config import MimCapacitor


class MimFields(QGroupBox):
    def __init__(self,parent=None):
        super().__init__('MIM 电容',parent);form=QFormLayout(self)
        self.status=QComboBox()
        for label,value in [('待确认（本项未启用）','unconfigured'),('已确认层位','configured'),('此工艺不支持 MIM','unsupported')]:self.status.addItem(label,value)
        form.addRow('配置状态',self.status)
        self.lpp=QComboBox();self.lower=QComboBox();self.upper=QComboBox();self.source=QLineEdit()
        self.source.setPlaceholderText('规则或资料来源；由人确认可留空')
        form.addRow('MIM 图层 / 用途',self.lpp);form.addRow('下方金属',self.lower);form.addRow('上方金属',self.upper);form.addRow('依据',self.source)
        note=QLabel('独立过孔的切孔与 MIM 重叠时，本地 DRC 报错；原生器件内部的孔除外。');note.setWordWrap(True);form.addRow(note)
        self.status.currentIndexChanged.connect(self.refresh)

    def refresh(self):
        enabled=self.status.currentData()!='unsupported'
        for field in (self.lpp,self.lower,self.upper):field.setEnabled(enabled)

    def set_profile(self,p,value):
        with QSignalBlocker(self.status):self.status.setCurrentIndex(self.status.findData(value.status))
        self.lpp.clear();self.lpp.addItem('选择图层 / 用途',None)
        for lpp in sorted({(r['layer'],r['purpose']) for r in p.layers}):self.lpp.addItem('/'.join(lpp),lpp)
        self.lpp.setCurrentIndex(next((i for i in range(self.lpp.count()) if tuple(self.lpp.itemData(i) or ())==value.lpp),0))
        metals={r['layer'] for r in p.layers if r.get('material')=='metal'}
        order=[v for v in p.editor_defaults.get('metal_stack',[]) if v in metals]
        order+=sorted(metals-set(order))
        for field,selected in ((self.lower,value.lower_metal),(self.upper,value.upper_metal)):
            field.clear();field.addItem('选择金属层',None)
            for metal in order:field.addItem(metal,metal)
            field.setCurrentIndex(max(0,field.findData(selected)))
        self.source.setText(value.source);self.refresh()

    def value(self):
        state=self.status.currentData();source=self.source.text().strip()
        if state=='unsupported':return MimCapacitor(status=state,source=source or '人工确认不支持 MIM')
        return MimCapacitor(status=state,lpp=self.lpp.currentData(),lower_metal=self.lower.currentData(),
            upper_metal=self.upper.currentData(),source=source or ('人工确认' if state=='configured' else ''))

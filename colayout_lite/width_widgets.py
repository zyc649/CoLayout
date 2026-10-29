from math import lcm,ceil
from PySide6.QtWidgets import QTableWidget,QTableWidgetItem,QDoubleSpinBox
from .wire_defaults import metal_stack,default_width


class AdditionalWidths(QTableWidget):
    """M1 keeps the existing spinbox; each higher metal has its own value."""
    def __init__(self):
        super().__init__(0,2);self.setHorizontalHeaderLabels(['金属层','默认线宽（µm）']);self.spins={};self.setMaximumHeight(175)
        self.horizontalHeader().setStretchLastSection(True)
    def set_profile(self,p):
        try:order=metal_stack(p,p.editor_defaults.get('metal_stack'))
        except Exception:
            first=p.editor_defaults.get('layer') or (p.writable_lpps[0] if p.writable_lpps else None)
            order=list(dict.fromkeys(([first[0]] if first else [])+[r['layer'] for r in p.layers if r.get('material')=='metal' and (r['layer'],r['purpose']) in p.writable_lpps]))
        order+=sorted({r['layer'] for r in p.layers if r['purpose']=='drawing' and r.get('material')=='metal'}-set(order))
        for spin in self.spins.values():spin.hide()
        self.clearContents();self.setRowCount(0)
        self.spins={};self.setRowCount(max(0,len(order)-1))
        from PySide6.QtCore import Qt
        for i,name in enumerate(order[1:]):
            item=QTableWidgetItem(name);item.setFlags(Qt.ItemFlag.ItemIsEnabled);self.setItem(i,0,item)
            spin=QDoubleSpinBox(self);spin.setDecimals(6);spin.setRange(.000001,10000);spin.setSingleStep(lcm(p.grid,2)/p.dbu_per_micron)
            value=default_width(p,name)
            if name not in p.editor_defaults.get('widths_um',{}):
                quantum=lcm(p.grid,2);value=ceil(value*p.dbu_per_micron/quantum)*quantum/p.dbu_per_micron
                spin.setToolTip('未记录独立测量值；可按设计需要设置，建议值已对齐网格。')
            spin.setValue(value);self.setCellWidget(i,1,spin);self.spins[name]=spin
    def values(self):return {k:s.value() for k,s in self.spins.items()}

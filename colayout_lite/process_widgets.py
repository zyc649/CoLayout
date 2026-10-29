"""Reusable layer permission checklist for review and saved settings."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QCheckBox,QTableWidget,QTableWidgetItem,QLabel


class LayerChecklist(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);box=QVBoxLayout(self);box.setContentsMargins(0,0,0,0)
        note=QLabel('默认启用金属层和 NW；其他层请先在 Layout 样例中放置独立矩形，再在这里勾选。')
        note.setWordWrap(True);box.addWidget(note)
        self.more=QCheckBox('显示其他工艺层');box.addWidget(self.more)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['允许绘图','图层 / 用途','材质'])
        self.table.horizontalHeader().setStretchLastSection(True);self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(24);self.table.setColumnWidth(0,95);self.table.setColumnWidth(1,230)
        box.addWidget(self.table);self.more.toggled.connect(self.filter)

    def set_profile(self,profile,*,sampled_lpps=()):
        self.sampled_lpps={tuple(v) for v in sampled_lpps}
        rows=[r for r in profile.layers if r['purpose']=='drawing' or (r['layer'],r['purpose']) in profile.writable_lpps];self.table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            item=QTableWidgetItem();item.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsUserCheckable)
            lpp=(r['layer'],r['purpose']);item.setData(Qt.ItemDataRole.UserRole,list(lpp))
            item.setCheckState(Qt.CheckState.Checked if lpp in profile.writable_lpps else Qt.CheckState.Unchecked);self.table.setItem(i,0,item)
            for col,text in [(1,'/'.join(lpp)),(2,r.get('material','unknown'))]:
                item=QTableWidgetItem(text);item.setToolTip(text);item.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable);self.table.setItem(i,col,item)
                if col==2:
                    item.setData(Qt.ItemDataRole.UserRole,r.get('material'))
                    evidence=profile.material_evidence.get(r['layer'])
                    if evidence:
                        item.setText(text+'（补充）');item.setToolTip('原生材质：'+str(evidence.native)+'\n依据：'+evidence.source)
        self.filter()

    def selected_layers(self):
        return [self.table.item(i,0).data(Qt.ItemDataRole.UserRole) for i in range(self.table.rowCount()) if self.table.item(i,0).checkState()==Qt.CheckState.Checked]

    def filter(self):
        for i in range(self.table.rowCount()):
            show=self.more.isChecked() or tuple(self.table.item(i,0).data(Qt.ItemDataRole.UserRole)) in self.sampled_lpps or self.table.item(i,2).data(Qt.ItemDataRole.UserRole) in ('metal','nwell') or self.table.item(i,0).checkState()==Qt.CheckState.Checked
            self.table.setRowHidden(i,not show)

"""Creation-only options, shown on demand before the canvas gesture."""
from PySide6.QtCore import Qt,QSignalBlocker
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLineEdit,QCheckBox,
    QListWidget,QListWidgetItem,QDialogButtonBox,QDoubleSpinBox)


class NativePinEscapeDialog(QDialog):
    def __init__(self,width,minimum,parent):
        super().__init__(parent)
        self.setWindowTitle('PIN 引出豁免');self.setMinimumWidth(280)
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.width=QDoubleSpinBox();self.width.setObjectName('nativePinEscapeWidth')
        self.width.setDecimals(6);self.width.setRange(minimum,1e6);self.width.setSingleStep(minimum)
        self.width.setSuffix(' µm');self.width.setValue(width);form.addRow('通道宽度',self.width)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.generate=buttons.button(QDialogButtonBox.StandardButton.Ok);self.generate.setText('生成豁免区')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消');layout.addWidget(buttons)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject)


class NativeRoutingWindowDialog(QDialog):
    def __init__(self,layers,name,parent):
        super().__init__(parent)
        self.setWindowTitle('画豁免区');self.setMinimumWidth(300)
        form=QVBoxLayout(self);fields=QFormLayout();form.addLayout(fields)
        self.name=QLineEdit(name);self.name.setMaxLength(200);self.name.selectAll()
        fields.addRow('名称',self.name)
        self.all_layers=QCheckBox('全部金属层');form.addWidget(self.all_layers)
        self.layers=QListWidget();self.layers.setObjectName('nativeWindowLayers')
        self.layers.setMaximumHeight(180);form.addWidget(self.layers)
        for index,layer in enumerate(layers):
            item=QListWidgetItem(layer);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if index==0 else Qt.CheckState.Unchecked);self.layers.addItem(item)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        self.draw=self.buttons.button(QDialogButtonBox.StandardButton.Ok);self.draw.setText('开始画框')
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        form.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject)
        self.all_layers.toggled.connect(self.check_all);self.layers.itemChanged.connect(self.sync_layers)
        self.sync_layers()

    def values(self):
        return {'name':self.name.text().strip() or '布线豁免',
                'layers':[self.layers.item(i).text() for i in range(self.layers.count())
                          if self.layers.item(i).checkState()==Qt.CheckState.Checked]}

    def check_all(self,checked):
        with QSignalBlocker(self.layers):
            for i in range(self.layers.count()):
                self.layers.item(i).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.sync_layers()

    def sync_layers(self,*_):
        selected=self.values()['layers']
        with QSignalBlocker(self.all_layers):
            self.all_layers.setChecked(bool(selected) and len(selected)==self.layers.count())
        self.draw.setEnabled(bool(selected))

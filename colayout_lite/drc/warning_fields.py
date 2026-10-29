"""Advisory DRC preferences embedded in both technology configuration dialogs."""

from PySide6.QtWidgets import (
    QWidget,
    QFormLayout,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QDoubleSpinBox,
    QCheckBox,
    QSpinBox,
    QLabel,
    QSizePolicy,
)
from PySide6.QtCore import Qt
from .warning_models import DesignWarnings


class WarningFields(QWidget):
    def __init__(self):
        super().__init__()
        form = QFormLayout(self)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        note = QLabel(
            '设计提醒不阻止普通编辑。方向未指定时不检查逆向；警戒长度由设计偏好决定。'
        )
        note.setWordWrap(True)
        note.setSizePolicy(QSizePolicy.Policy.Preferred,QSizePolicy.Policy.Maximum)
        form.addRow(note)
        self.directions = QTableWidget(0, 4)
        self.directions.setObjectName('drcPreferredDirections')
        self.directions.setHorizontalHeaderLabels(
            ['金属层', '首选方向', '逆向警戒长度 µm', '启用提醒']
        )
        self.directions.setMaximumHeight(190)
        form.addRow(self.directions)
        self.via_enabled = QCheckBox('提醒标准过孔每级切孔数不足')
        self.minimum_cuts = QSpinBox()
        self.minimum_cuts.setRange(1, 10000)
        form.addRow(self.via_enabled, self.minimum_cuts)

    def set_profile(self, technology, settings):
        names = [
            row['layer']
            for row in technology.layers
            if row['purpose'] == 'drawing' and row.get('material') == 'metal'
        ]
        for row in range(self.directions.rowCount()):
            for col in (1,2,3):
                widget=self.directions.cellWidget(row,col)
                if widget:widget.hide()
        self.directions.clearContents();self.directions.setRowCount(0)
        self.directions.setRowCount(len(names))
        for index, name in enumerate(names):
            self.directions.setItem(index, 0, QTableWidgetItem(name))
            choice = QComboBox(self.directions)
            for label, value in [('未指定', ''), ('横向', 'horizontal'), ('竖向', 'vertical')]:
                choice.addItem(label, value)
            direction = settings.directions.get(name)
            choice.setCurrentIndex(choice.findData(direction.preferred if direction else ''))
            length = QDoubleSpinBox(self.directions)
            length.setDecimals(4)
            length.setRange(0.0001, 1e7)
            length.setValue(direction.reverse_limit_um if direction else 9.8)
            self.directions.setCellWidget(index, 1, choice)
            self.directions.setCellWidget(index, 2, length)
            enabled = QCheckBox(self.directions)
            enabled.setChecked(direction.enabled if direction else True)
            self.directions.setCellWidget(index, 3, enabled)
        self.via_enabled.setChecked(settings.via_enabled)
        self.minimum_cuts.setValue(settings.minimum_cuts)

    def value(self):
        directions = {}
        for index in range(self.directions.rowCount()):
            preferred = self.directions.cellWidget(index, 1).currentData()
            if preferred:
                directions[self.directions.item(index, 0).text()] = {
                    'preferred': preferred,
                    'reverse_limit_um': self.directions.cellWidget(index, 2).value(),
                    'enabled': self.directions.cellWidget(index, 3).isChecked(),
                }
        return DesignWarnings(
            directions=directions,
            via_enabled=self.via_enabled.isChecked(),
            minimum_cuts=self.minimum_cuts.value(),
        )

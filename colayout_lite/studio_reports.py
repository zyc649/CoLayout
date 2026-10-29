"""Read-only check results; separate from data-editing and legacy QA wrappers."""
import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QLabel,QTableWidget,QTableWidgetItem,
    QAbstractItemView,QHeaderView,QDialogButtonBox,QPushButton,QApplication)


class PolicyReport(QDialog):
    def __init__(self,parent,report,dbu_per_micron):
        super().__init__(parent);self.report=report;self.setWindowTitle('本地禁布检查')
        self.setObjectName('studioProperties');self.resize(1000,490);self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout=QVBoxLayout(self);self.summary=QLabel(f'发现 {len(report["violations"])} 项违规' if report['violations'] else '检查通过 · 未发现禁布违规')
        self.summary.setObjectName('studioTitle');layout.addWidget(self.summary)
        note=QLabel(report['scope']+'。这是检查时的快照，修改后请重新检查。');note.setWordWrap(True);layout.addWidget(note)
        self.rows=QTableWidget(len(report['violations']),5);self.rows.setHorizontalHeaderLabels(['金属层','原因','对象 ID','限制来源 ID','位置范围 · µm'])
        self.rows.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.rows.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for i,entry in enumerate(report['violations']):
            bounds=entry.get('bbox',());position=', '.join(f'{v/dbu_per_micron:g}' for v in bounds)
            for j,value in enumerate((entry.get('layer',''),entry.get('reason',''),entry.get('object_id',''),entry.get('blocker_id',''),position)):
                item=QTableWidgetItem(value);item.setToolTip(value);self.rows.setItem(i,j,item)
        self.rows.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);layout.addWidget(self.rows,1)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);buttons.rejected.connect(self.close)
        copy=QPushButton('复制检查结果');copy.clicked.connect(lambda:QApplication.clipboard().setText(json.dumps(report,ensure_ascii=False,indent=2)))
        buttons.addButton(copy,QDialogButtonBox.ButtonRole.ActionRole);layout.addWidget(buttons)

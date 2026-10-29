"""Bounded in-memory activity history and an explicit, copyable details view."""
from datetime import datetime,timezone
from collections import deque
from PySide6.QtCore import QObject,Signal,Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QListWidget,QPlainTextEdit,QPushButton,QApplication


class ActivityLog(QObject):
    changed=Signal()
    def __init__(self,window):
        super().__init__(window);self.window=window;self.rows=deque(maxlen=200);self.dialog=None
        window.status.text_changed.connect(self.record)

    def record(self,text,details=None):
        if not str(text).strip():return
        summary=str(text).splitlines()[0]
        row={'time':datetime.now(timezone.utc).isoformat(timespec='seconds'),'summary':summary,'details':details or str(text)}
        if self.rows and self.rows[-1]['summary']==summary:
            if details:self.rows[-1]=row;self.changed.emit()
            return
        self.rows.append(row);self.changed.emit()

    def show(self):
        from shiboken6 import isValid
        if self.dialog is not None and isValid(self.dialog):self.dialog.show();self.dialog.raise_();return
        dialog=QDialog(self.window);dialog.setWindowTitle('操作记录与错误详情');dialog.resize(780,550)
        layout=QVBoxLayout(dialog);entries=QListWidget();layout.addWidget(entries,1)
        detail=QPlainTextEdit();detail.setReadOnly(True);layout.addWidget(detail,2)
        copy=QPushButton('复制完整详情');copy.clicked.connect(lambda:QApplication.clipboard().setText(detail.toPlainText()));layout.addWidget(copy)
        def choose(index):
            if index>=0 and index<entries.count():detail.setPlainText(entries.item(index).data(Qt.ItemDataRole.UserRole))
        entries.currentRowChanged.connect(choose)
        def refresh():
            from PySide6.QtWidgets import QListWidgetItem
            entries.clear()
            for row in reversed(self.rows):
                item=QListWidgetItem(row['time']+'  '+row['summary']);item.setData(Qt.ItemDataRole.UserRole,row['details']);entries.addItem(item)
            if entries.count():entries.setCurrentRow(0)
        self.changed.connect(refresh);dialog.finished.connect(lambda:self.changed.disconnect(refresh))
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose);self.dialog=dialog;refresh();dialog.show()

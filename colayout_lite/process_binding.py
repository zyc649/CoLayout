"""Host binding for a shared process file, with read-only Virtuoso discovery."""
import json
from pathlib import PurePosixPath
from PySide6.QtCore import Qt,QTimer,Slot
from PySide6.QtWidgets import QDialog,QFormLayout,QComboBox,QLineEdit,QLabel,QPushButton,QDialogButtonBox
from .process_center import ConfirmJob
from .paths import ROOT


class BindingDialog(QDialog):
    def __init__(self,service,technology,parent=None):
        super().__init__(parent);self.service=service;self.technology=technology;self.job=None;self.result=None
        self.setWindowTitle('绑定本机服务器');self.resize(680,300)
        form=QFormLayout(self)
        self.connections=QComboBox()
        for key,path in service.connection_choices().items():self.connections.addItem(path.stem,key)
        form.addRow('本机连接',self.connections)
        self.root=QLineEdit();form.addRow('服务器工程目录',self.root)
        self.layouts=QComboBox();self.layouts.addItem('可稍后从 Virtuoso 导入版图',None);form.addRow('打开的 Layout',self.layouts)
        self.discover=QPushButton('从 Virtuoso 读取');form.addRow(self.discover)
        self.message=QLabel('核对本机连接与文件路径；共享配置不要求重建原来的样例。')
        self.message.setWordWrap(True);self.message.setTextFormat(Qt.TextFormat.PlainText);form.addRow(self.message)
        self.buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);form.addRow(self.buttons)
        self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject)
        self.connections.currentIndexChanged.connect(self.selected_connection);self.layouts.currentIndexChanged.connect(self.selected_layout)
        self.discover.clicked.connect(self.inspect)
        self.join=QTimer(self);self.join.setSingleShot(True);self.join.timeout.connect(self.finish_query)
        self.selected_connection()
        self.initial=QTimer(self);self.initial.setSingleShot(True);self.initial.timeout.connect(self.inspect);self.initial.start(0)

    def selected_connection(self,*unused):
        if self.job:return
        if not self.connections.count():
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False);return
        path=self.service.resolve_connection(self.connections.currentData())
        self.root.setText(json.loads(path.read_text(encoding='utf8')).get('allowed_remote_root',''))

    def selected_layout(self,*unused):
        row=self.layouts.currentData()
        if row:self.root.setText(str(PurePosixPath(row['library_path']).parent))

    def inspect(self):
        if self.job or not self.connections.count():return
        path=self.service.resolve_connection(self.connections.currentData())
        cfg=json.loads(path.read_text(encoding='utf8'))
        def operation(progress):
            from .process_setup import inspect_live
            return json.dumps(inspect_live(ROOT/cfg['bridge_env'])[1],ensure_ascii=False)
        self.result=None;self.connections.setEnabled(False);self.discover.setEnabled(False);self.buttons.setEnabled(False)
        self.message.setText('正在只读查询已开的 Layout…')
        self.job=ConfirmJob(operation,self)
        self.job.done.connect(self.received,Qt.ConnectionType.QueuedConnection)
        self.job.failed.connect(self.failed,Qt.ConnectionType.QueuedConnection)
        self.job.finished.connect(self.finish_query,Qt.ConnectionType.QueuedConnection);self.job.start()

    @Slot(str)
    def received(self,value):self.result=json.loads(value)
    @Slot(str)
    def failed(self,message):self.message.setText('未自动读取：'+message+'。可核对连接后重试，或手动填写工程目录。')
    @Slot()
    def finish_query(self):
        job=self.job
        if not job:return
        if not job.wait(0):self.join.start(10);return
        self.job=None;job.deleteLater();self.connections.setEnabled(True);self.discover.setEnabled(True);self.buttons.setEnabled(True)
        if self.result:
            rows=[r for r in self.result['layouts'] if isinstance(r.get('library_path'),str) and r['library_path'] and r['library']!=r['technology'] and
                  (not self.technology.native_technology_name or r['technology']==self.technology.native_technology_name)]
            self.layouts.clear();self.layouts.addItem('可稍后从 Virtuoso 导入版图',None)
            for row in rows:self.layouts.addItem(row['library']+'/'+row['cell']+(' · 未保存' if row['unsaved'] else ''),row)
            if len(rows)==1:self.layouts.setCurrentIndex(1)
            self.message.setText('已读取当前窗口。多个候选时请选择要使用的 Layout。' if rows else '没有找到此工艺的已开 Layout；配置仍可保存，稍后再导入版图。')

    def source(self):
        row=self.layouts.currentData()
        return {'library':row['library'],'cell':row['cell']} if row else {}

    def reject(self):
        if self.job:self.message.setText('读取尚未结束，请稍候。')
        else:self.initial.stop();self.join.stop();super().reject()
    def accept(self):
        if self.job:return
        self.initial.stop();self.join.stop();super().accept()
    def closeEvent(self,event):
        if self.job:event.ignore()
        else:self.initial.stop();self.join.stop();super().closeEvent(event)

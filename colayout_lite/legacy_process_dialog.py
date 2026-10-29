"""Visible process onboarding. No credentials or raw JSON are displayed."""
from pathlib import Path
from PySide6.QtCore import Qt,Signal,QThread
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QPushButton,QLabel,
    QTableWidget,QTableWidgetItem,QComboBox,QDoubleSpinBox,QPlainTextEdit,QFileDialog)
from .paths import ROOT
from . import onboarding


class ProcessJob(QThread):
    done=Signal(object);failed=Signal(str);progress=Signal(str)
    def __init__(self,fn,parent=None):super().__init__(parent);self.fn=fn
    def run(self):
        try:self.done.emit(self.fn(self.progress.emit))
        except Exception as exc:self.failed.emit(str(exc))


class ProcessDialog(QDialog):
    def __init__(self,connection,library,cell,parent=None):
        super().__init__(parent);self.setWindowTitle('工艺接入与配置');self.resize(800,760)
        self.adapter=None;self.profile=None;self.profile_path=None;self.busy=False;self.job=None;self.activation=None
        box=QVBoxLayout(self)
        intro=QLabel('① 在对应 Virtuoso 环境准备一个业务 Layout　② 读取工艺　③ 选可写层/默认值并保存　④ 验证\n这里填写版图所属的业务库（如 ROICv7a），不是直接填写 PDK master 库。切配置文件不会替你切换服务器 PDK。');intro.setWordWrap(True);box.addWidget(intro)
        form=QFormLayout();box.addLayout(form)
        self.connection=QLineEdit(str(connection));self.connection.setObjectName('connection_config')
        row=QHBoxLayout();row.addWidget(self.connection);browse=QPushButton('选择连接配置…');row.addWidget(browse);form.addRow('Bridge连接配置 JSON',row)
        browse.clicked.connect(self.browse)
        self.library=QLineEdit(library);self.cell=QLineEdit(cell);self.name=QLineEdit()
        self.library.setObjectName('sample_library');self.cell.setObjectName('sample_cell');self.name.setObjectName('process_name')
        form.addRow('样例库',self.library);form.addRow('样例 Layout cell',self.cell);form.addRow('工艺名称（自行命名）',self.name)
        self.discover_button=QPushButton('1. 从这个 Virtuoso 读取工艺');box.addWidget(self.discover_button);self.discover_button.clicked.connect(self.discover)
        self.summary=QLabel('原生单位、网格、过孔尺寸和模板会自动读取，不需要手填工艺尺寸。');self.summary.setWordWrap(True);box.addWidget(self.summary)
        self.layers=QTableWidget(0,4);self.layers.setHorizontalHeaderLabels(['允许写入','层','用途','原生材质']);self.layers.horizontalHeader().setStretchLastSection(True);box.addWidget(self.layers,1)
        options=QFormLayout();box.addLayout(options);self.default_layer=QComboBox();self.default_via=QComboBox();self.width=QDoubleSpinBox();self.width.setDecimals(6);self.width.setRange(.000001,10000);self.width.setValue(.8);self.width.setSuffix(' µm')
        options.addRow('默认绘图层',self.default_layer);options.addRow('默认过孔',self.default_via);options.addRow('默认线宽（非DRC最小值）',self.width)
        row=QHBoxLayout();box.addLayout(row);self.save_button=QPushButton('2. 保存配置');self.verify_button=QPushButton('3. 复制样例并验证写回');self.activate_button=QPushButton('4. 保存并导入这个样例')
        for button in (self.save_button,self.verify_button,self.activate_button):row.addWidget(button)
        self.save_button.clicked.connect(self.save);self.verify_button.clicked.connect(self.verify);self.activate_button.clicked.connect(self.activate)
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumHeight(150);box.addWidget(self.log)
        self.layers.itemChanged.connect(self.layers_changed);self.controls()

    def browse(self):
        path,_=QFileDialog.getOpenFileName(self,'选择已有 Bridge 连接配置',str(ROOT/'config'),'JSON (*.json)')
        if path:self.connection.setText(path)

    def controls(self):
        self.discover_button.setEnabled(not self.busy)
        for button in (self.save_button,self.verify_button,self.activate_button):button.setEnabled(self.profile is not None and not self.busy)
        for widget in (self.connection,self.library,self.cell,self.name,self.layers,self.default_layer,self.default_via,self.width):widget.setEnabled(not self.busy)

    def task(self,fn,done):
        self.busy=True;self.controls();job=ProcessJob(fn,self);self.job=job
        job.progress.connect(self.log.appendPlainText)
        def success(value):
            self.busy=False
            try:done(value)
            except Exception as exc:self.log.appendPlainText('未完成：'+str(exc))
            self.controls()
        def fail(message):self.busy=False;self.log.appendPlainText('未完成：'+message);self.controls()
        job.done.connect(success);job.failed.connect(fail)
        def finished():self.job=None;job.fn=None;job.deleteLater()
        job.finished.connect(finished);job.start()

    def discover(self):
        connection=self.connection.text().strip();lib=self.library.text().strip();cell=self.cell.text().strip()
        def done(result):
            self.adapter,snapshot,self.profile=result;p=self.profile
            self.name.setText(p.label if not self.name.text() else self.name.text())
            self.summary.setText(f'已读取 {snapshot.library}/{snapshot.cell}：1 µm = {p.dbu_per_micron} DBU；网格 {p.grid/p.dbu_per_micron:g} µm；{len(p.vias)} 个 via 定义；保护环：'+', '.join(t['name'] for t in p.guard_templates))
            self.layers.blockSignals(True);drawing=[l for l in p.layers if l['purpose']=='drawing'];self.layers.setRowCount(len(drawing))
            for row,l in enumerate(drawing):
                check=QTableWidgetItem();check.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsUserCheckable);check.setCheckState(Qt.CheckState.Checked if (l['layer'],l['purpose']) in p.writable_lpps else Qt.CheckState.Unchecked);self.layers.setItem(row,0,check)
                for col,key in [(1,'layer'),(2,'purpose'),(3,'material')]:
                    item=QTableWidgetItem(str(l[key] or '未知'));item.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable);self.layers.setItem(row,col,item)
            self.layers.blockSignals(False);self.layers_changed()
            self.default_via.clear()
            for name,v in p.vias.items():
                if v['kind']=='stdViaDef' and not v.get('cut_pattern'):self.default_via.addItem(name,name)
            if p.editor_defaults:
                self.width.setValue(p.editor_defaults.get('width_um',.8))
                for combo,value in [(self.default_layer,p.editor_defaults.get('layer')),(self.default_via,p.editor_defaults.get('via_definition'))]:
                    index=combo.findData(value)
                    if index>=0:combo.setCurrentIndex(index)
            self.log.appendPlainText('读取成功。勾选允许编辑的层，设置默认值后保存；不会更改服务器 PDK。')
        self.task(lambda progress:onboarding.discover(connection,lib,cell),done)

    def layers_changed(self,*unused):
        previous=self.default_layer.currentData();self.default_layer.clear()
        for row in range(self.layers.rowCount()):
            if self.layers.item(row,0).checkState()==Qt.CheckState.Checked:
                lpp=[self.layers.item(row,1).text(),self.layers.item(row,2).text()];self.default_layer.addItem('/'.join(lpp),lpp)
        if previous is not None and self.default_layer.findData(previous)>=0:self.default_layer.setCurrentIndex(self.default_layer.findData(previous))

    def save(self):
        try:
            layers=[self.default_layer.itemData(i) for i in range(self.default_layer.count())]
            if not layers:raise ValueError('至少选择一个可写层')
            defaults={'layer':self.default_layer.currentData(),'width_um':self.width.value()}
            if self.default_via.currentData():defaults['via_definition']=self.default_via.currentData()
            self.profile,self.profile_path=onboarding.save_profile(self.adapter,self.profile,name=self.name.text(),writable_lpps=layers,defaults=defaults)
            self.log.appendPlainText('已保存：'+str(self.profile_path)+'\n下一步点击“复制样例并验证写回”。')
            return True
        except Exception as exc:self.log.appendPlainText('未保存：'+str(exc));return False

    def verify(self):
        if not self.save():return
        lib=self.library.text().strip();cell=self.cell.text().strip();profile=self.profile
        def done(result):
            report,path=result;self.profile=self.profile.model_copy(update={'validation':{'status':'smoke-tested','report':str(path),'scope':report['scope']}});self.profile.save(self.profile_path)
            self.log.appendPlainText('验证通过：矩形、90°/45°线、过孔写回和删除核对。\n测试副本：'+report['target']+'\n报告：'+str(path))
        self.task(lambda progress:onboarding.validate_sample(self.adapter,lib,cell,profile,progress),done)

    def activate(self):
        if self.save():
            self.activation=(self.adapter,self.library.text().strip(),self.cell.text().strip());self.accept()

    def reject(self):
        if self.busy:self.log.appendPlainText('正在验证，请等任务结束再关闭。');return
        super().reject()


def main():
    import json,argparse
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont
    parser=argparse.ArgumentParser();parser.add_argument('--connection',default=str(ROOT/'config/colayout_lite.json'));args=parser.parse_args()
    cfg=json.loads(Path(args.connection).read_text(encoding='utf-8'))
    app=QApplication([]);app.setFont(QFont('Microsoft YaHei UI',9))
    dialog=ProcessDialog(args.connection,cfg.get('default_library',''),cfg.get('default_source_cell',''))
    dialog.activate_button.setText('保存并退出');dialog.exec()


if __name__=='__main__':main()

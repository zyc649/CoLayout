"""Unified process library, review, preferences and portable configuration files."""
import json
from pathlib import Path
from uuid import uuid4
from PySide6.QtCore import Qt,QThread,Signal,Slot,QTimer
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,
    QComboBox,QTabWidget,QTextBrowser,QFileDialog,QFrame)
from .model import LiteError
from .process_library import ProcessLibrary,write_json
from .process_configuration import ProcessConfiguration
from .process_package import ProcessPackage,decode
from .process_editor import ConfigurationEditor
from .technology import TechnologyProfile
from .drc.models import DrcProfile
from .presentation.dark_dialog import DarkDialog


class ConfirmJob(QThread):
    done=Signal(str);failed=Signal(str);progress=Signal(str)
    def __init__(self,operation,parent):
        super().__init__(parent);self.operation=operation
    def run(self):
        try:self.done.emit(self.operation(self.progress.emit))
        except Exception as exc:self.failed.emit(str(exc))


class ProcessFeedback(QLabel):
    """Compact, initially absent status; retain full messages for diagnostics."""
    def __init__(self,parent=None):
        super().__init__(parent);self.messages=[];self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText);self.hide()

    @Slot(str)
    def appendPlainText(self,message):
        self.messages.append(str(message));self.setText(str(message));self.setToolTip(self.toPlainText());self.show()

    def toPlainText(self):return '\n'.join(self.messages)


class ProcessDialog(DarkDialog):
    def __init__(self,store=None,parent=None,*,current_key=None):
        super().__init__(parent)
        self.store=store or ProcessLibrary();self.store.migrate_existing()
        hub=getattr(parent,'agent_hub',None)
        self.service=hub.process_configuration if hub else ProcessConfiguration(self.store,
            connection=lambda:getattr(parent,'connection_config',None))
        self.current_key=current_key;self.selected_key=None;self.modified_keys=set()
        self.busy=False;self.job=None;self._result=None;self.proposal=None;self._saved_profile=None
        self._reload_timer=QTimer(self);self._reload_timer.setSingleShot(True);self._reload_timer.timeout.connect(self.reload)
        self._join_timer=QTimer(self);self._join_timer.setSingleShot(True);self._join_timer.timeout.connect(self._finished)
        self.setWindowTitle('工艺库');self.resize(1040,820)
        box=QVBoxLayout(self);self.tabs=QTabWidget();box.addWidget(self.tabs,1)
        saved=QWidget();layout=QVBoxLayout(saved);self.tabs.addTab(saved,'已配置')
        bar=QHBoxLayout();layout.addLayout(bar)
        self.saved=QComboBox();bar.addWidget(self.saved,1)
        self.import_button=QPushButton('导入配置…');self.export_button=QPushButton('导出配置…')
        bar.addWidget(self.import_button);bar.addWidget(self.export_button)
        self.saved_summary=QLabel();self.saved_summary.setTextFormat(Qt.TextFormat.PlainText);self.saved_summary.setWordWrap(True);layout.addWidget(self.saved_summary)
        self.saved_editor=ConfigurationEditor(saved);layout.addWidget(self.saved_editor,1)
        buttons=QHBoxLayout();layout.addLayout(buttons)
        self.save_settings_button=QPushButton('保存设置');self.select_button=QPushButton('使用此工艺')
        buttons.addWidget(self.save_settings_button);buttons.addWidget(self.select_button)
        review=QWidget();layout=QVBoxLayout(review);self.tabs.addTab(review,'待审核')
        bar=QHBoxLayout();layout.addLayout(bar);self.pending=QComboBox();bar.addWidget(self.pending,1)
        self.refresh_button=QPushButton('刷新');bar.addWidget(self.refresh_button)
        self.evidence=QLabel();self.evidence.setTextFormat(Qt.TextFormat.PlainText);self.evidence.setWordWrap(True);layout.addWidget(self.evidence)
        self.review_editor=ConfigurationEditor(review);layout.addWidget(self.review_editor,1)
        bar=QHBoxLayout();layout.addLayout(bar)
        self.confirm_button=QPushButton('审核并启用');self.reject_button=QPushButton('拒绝此提案')
        bar.addWidget(self.confirm_button);bar.addWidget(self.reject_button)
        help_page=QWidget();layout=QVBoxLayout(help_page);self.tabs.addTab(help_page,'如何配置')
        from .process_help import GUIDE
        self.guide=QTextBrowser();self.guide.setFrameShape(QFrame.Shape.NoFrame)
        self.guide.setHtml(GUIDE);layout.addWidget(self.guide,1)
        self.log=ProcessFeedback();box.addWidget(self.log)
        close=QPushButton('关闭');close.clicked.connect(self.reject);box.addWidget(close)
        self.saved.currentIndexChanged.connect(self.show_saved);self.pending.currentIndexChanged.connect(self.show_proposal)
        self.refresh_button.clicked.connect(self.reload);self.save_settings_button.clicked.connect(self.save_settings)
        self.select_button.clicked.connect(self.use_saved);self.confirm_button.clicked.connect(self.confirm)
        self.reject_button.clicked.connect(self.reject_proposal);self.import_button.clicked.connect(self.import_file)
        self.export_button.clicked.connect(self.export_file)
        # Stable controls for existing UI integration; all fields are shared.
        self.saved_width=self.saved_editor.width;self.saved_widths=self.saved_editor.widths;self.saved_layers=self.saved_editor.layers
        self.saved_summary_parameters=self.saved_editor.summary_parameters
        self.name=self.review_editor.name;self.width=self.review_editor.width;self.review_layers=self.review_editor.layers
        self.review_widths=self.review_editor.widths;self.layers=self.review_layers.table;self.more=self.review_layers.more
        self.review_summary_parameters=self.review_editor.summary_parameters;self.drc_fields=self.review_editor.drc
        self.review_tabs=self.review_editor.tabs
        self.reload()

    def showEvent(self,event):
        super().showEvent(event)
        if not getattr(self,'_placed',False):
            self._placed=True;area=self.screen().availableGeometry()
            self.resize(min(1040,area.width()-40),min(820,area.height()-40));self.move(area.center()-self.rect().center())

    def reload(self):
        if self.busy:return
        key=self.saved.currentData() or self.current_key
        self.saved.blockSignals(True);self.saved.clear()
        for ident,entry in self.store.entries().items():self.saved.addItem(entry['label'],ident)
        if self.saved.findData(key)>=0:self.saved.setCurrentIndex(self.saved.findData(key))
        self.saved.blockSignals(False);self.show_saved()
        selected=self.pending.currentData()
        self.pending.blockSignals(True);self.pending.clear()
        for path,data in self.store.drafts():
            self.pending.addItem(data['profile']['label']+' · '+{'pending_review':'待审核','ready_for_confirmation':'旧版提案','needs_attention':'需处理','validating':'验证中'}.get(data['status'],data['status']),str(path))
        if self.pending.findData(selected)>=0:self.pending.setCurrentIndex(self.pending.findData(selected))
        self.pending.blockSignals(False);self.show_proposal();self.tabs.setTabText(1,f'待审核（{self.pending.count()}）')
        for error in getattr(self.store,'scan_errors',[]):self.log.appendPlainText('保留但未加载的提案：'+error['path']+' · '+error['error'])

    def show_saved(self):
        key=self.saved.currentData();self._saved_profile=None;self._saved_package=None
        self.saved_editor.setEnabled(bool(key));self.save_settings_button.setEnabled(bool(key))
        self.select_button.setEnabled(bool(key));self.export_button.setEnabled(bool(key))
        if not key:self.saved_summary.setText('尚无工艺配置。导入配置文件，或让配置 Agent 提交方案。');return
        try:
            package=self.service.load(key);self._saved_package=package;self._saved_profile=package.technology
            self._saved_base=self.service.base(package,self.store.entries()[key]['connection'])
            self.saved_editor.set_package(package)
            self.saved_summary.setText('统一维护绘图、DRC、设计提醒和保护环；保存不会改变已有几何。')
        except Exception as exc:self.saved_summary.setText(str(exc));self.saved_editor.setEnabled(False);self.save_settings_button.setEnabled(False)

    def show_proposal(self):
        path=self.pending.currentData();self.proposal=None
        self.review_editor.setEnabled(bool(path));self.confirm_button.setEnabled(False);self.reject_button.setEnabled(False)
        if not path:self.evidence.setText('暂无待审核提案。');return
        try:
            data=json.loads(Path(path).read_text(encoding='utf8'));self.proposal=data
            package=ProcessPackage.model_validate(data['package']) if data.get('schema_version')=='colayout-process-proposal-3' else ProcessPackage(
                technology=TechnologyProfile.model_validate(data['profile']),
                drc=DrcProfile.model_validate(data['drc_profile']) if data.get('drc_profile') else None)
            self.review_editor.set_package(package);p=package.technology
            source=data.get('source',{});label='/'.join(source.get(k,'') for k in ('library','cell')).strip('/')
            self.evidence.setText(('配置文件导入' if data.get('imported') else '样例：'+label)+
                f' · {len(p.layers)} 个层用途 · {len(p.vias)} 种过孔 · {len(p.guard_recipes)} 个样例配方'+
                ('\n'+data['error'] if data.get('error') else ''))
            if p.material_evidence:self.evidence.setText(self.evidence.text()+f'\n补充 {len(p.material_evidence)} 层原生缺失的材质；在图层列表查看依据。')
            if package.drc and package.drc.mim_capacitor.status=='unconfigured':
                self.evidence.setText(self.evidence.text()+'\nMIM 层位待确认：请在“本地 DRC → MIM 电容”填写后启用。')
            if p.key in self.store.entries():
                from .process_package import changes
                self.evidence.setText(self.evidence.text()+'\n'+changes(self.service.load(p.key),package))
            ready=data['status'] in ('pending_review','needs_attention','ready_for_confirmation')
            current=data.get('schema_version')=='colayout-process-proposal-3'
            self.confirm_button.setEnabled(current and ready);self.reject_button.setEnabled(current and ready)
            self.review_editor.setEnabled(current)
            if not current:self.evidence.setText(self.evidence.text()+'\n旧格式提案仅供参考，请通过工艺配置 API 重新提交。')
        except Exception as exc:self.evidence.setText('提案无法读取：'+str(exc))

    def preflight(self,package):
        parent=self.parentWidget();e=getattr(parent,'editor',None)
        if e is None or e.profile.key!=package.technology.key:return
        e.work_sessions.require_idle()
        if e.w.state in ('submitting','indeterminate','conflict'):raise LiteError('WORKSPACE_BUSY','请先核对未完成的原生同步。')
        from .permissions import apply_profile_permissions
        candidate=apply_profile_permissions(e.w.baseline,package.technology)
        if e.w.operations and (candidate.semantic()!=e.w.baseline.semantic() or
            any(op.shape and op.shape.kind!='stdVia' and op.shape.lpp not in package.technology.writable_lpps for op in e.w.operations)):
            raise LiteError('PROCESS_POLICY_CHANGED_WITH_DRAFT','图层权限修改会影响现有草稿，请先处理草稿。')

    def save_settings(self):
        if self.busy or self._saved_package is None:return
        try:
            package=self.saved_editor.value();self.preflight(package);key=self.saved.currentData()
            try:
                if self.service.base(self._saved_package,self.store.entries()[key]['connection'])!=self._saved_base:raise LiteError('PROCESS_CONFIGURATION_CHANGED')
                self.service.save_settings(key,package,self._saved_package.fingerprint())
                self.modified_keys.add(key);self.show_saved();self.log.appendPlainText('设置已保存，已有几何保持不变。')
            except LiteError as exc:
                if exc.code!='PROCESS_REVIEW_REQUIRED':raise
                from .process_package import portable
                effective=portable(package)
                if effective.technology.guard_recipes!=package.technology.guard_recipes:
                    self.log.appendPlainText('旧版未验证或无样例的保护环不再启用；原配置会备份，已有图形保留。')
                package=effective
                entry=self.store.entries()[key];cp=Path(entry['connection'])
                connection_id=next(k for k,v in self.service.connection_choices().items() if v.resolve()==cp.resolve())
                submitted=self.service.submit(package.model_dump(mode='json'),{},client_id='human-settings',request_id=uuid4().hex,connection_id=connection_id,imported=True)
                from .process_review import approve
                self.start_job(lambda progress:approve(self.service,submitted['proposal_id'],submitted['review_digest'],package,progress))
        except Exception as exc:self.log.appendPlainText('未保存：'+str(exc))

    def confirm(self):
        if self.busy or not self.proposal:return
        try:
            if self.proposal.get('schema_version')!='colayout-process-proposal-3':raise LiteError('LEGACY_PROPOSAL_READ_ONLY')
            package=self.review_editor.value().require_complete().require_mim_review();self.preflight(package);data=self.proposal
            from .process_review import approve
            operation=lambda progress:approve(self.service,data['id'],data['review_digest'],package,progress)
            self.start_job(operation)
        except Exception as exc:self.log.appendPlainText('未启用：'+str(exc))

    def start_job(self,operation):
        self.busy=True;self.tabs.setEnabled(False);self._result=None
        self.log.appendPlainText('正在核对样例、配置与服务器文件路径…')
        job=ConfirmJob(operation,self);self.job=job
        job.progress.connect(self.log.appendPlainText,Qt.ConnectionType.QueuedConnection)
        job.done.connect(self._confirmed,Qt.ConnectionType.QueuedConnection);job.failed.connect(self._failed,Qt.ConnectionType.QueuedConnection)
        job.finished.connect(self._finished,Qt.ConnectionType.QueuedConnection);job.start()

    @Slot(str)
    def _confirmed(self,key):self._result=key
    @Slot(str)
    def _failed(self,message):self.log.appendPlainText('未启用：'+message)
    @Slot()
    def _finished(self):
        job=self.job
        if job is None:return
        if not job.wait(0):self._join_timer.start(10);return
        self.job=None;job.deleteLater();self.busy=False;self.tabs.setEnabled(True)
        if self._result:self.modified_keys.add(self._result);self.log.appendPlainText('工艺配置已保存。')
        self._reload_timer.start(0)

    def reject_proposal(self):
        if not self.proposal or self.busy:return
        try:self.service.reject(self.proposal['id'],self.proposal['review_digest']);self.reload()
        except Exception as exc:self.log.appendPlainText(str(exc))

    def use_saved(self):
        if not self.saved.currentData() or self.busy:return
        if self.saved_editor.is_dirty():
            self.log.appendPlainText('当前修改还没有保存，请先保存设置。');return
        self.selected_key=self.saved.currentData();self.accept()

    def export_file(self):
        key=self.saved.currentData()
        if not key:return
        try:
            data=self.service.export(key)
            path,_=QFileDialog.getSaveFileName(self,'导出已保存工艺配置',self._saved_profile.label+'.colayout-process.json','工艺配置 (*.json)')
            if path:write_json(path,data);self.log.appendPlainText('已导出配置；不包含 Bridge 凭据、工作区或 PDK 文件。')
        except Exception as exc:self.log.appendPlainText('导出失败：'+str(exc))

    def import_file(self):
        path,_=QFileDialog.getOpenFileName(self,'导入工艺配置','','工艺配置 (*.json)')
        if not path:return
        try:
            package=decode(json.loads(Path(path).read_text(encoding='utf8')))
            # A shared package does not grant this installation's Agent access.
            package=package.model_copy(update={'agent_autoroute_enabled':False})
            from .process_binding import BindingDialog
            dialog=BindingDialog(self.service,package.technology,self)
            self.busy=True
            try:accepted=dialog.exec()==QDialog.DialogCode.Accepted
            finally:self.busy=False
            if not accepted:dialog.deleteLater();return
            result=self.service.submit(package.model_dump(mode='json'),dialog.source(),client_id='human-import',request_id=uuid4().hex,
                connection_id=dialog.connections.currentData(),project_root=dialog.root.text().strip() or None,imported=True)
            dialog.deleteLater()
            self.reload();self.tabs.setCurrentIndex(1)
            target=str((self.store.folder/'drafts'/result['proposal_id']/'proposal.json'))
            self.pending.setCurrentIndex(self.pending.findData(target))
        except Exception as exc:self.log.appendPlainText('未导入：'+str(exc))

    def closeEvent(self,event):
        if self.busy:event.ignore()
        else:super().closeEvent(event)
    def reject(self):
        if self.busy:self.log.appendPlainText('验证尚未结束，请等待完成。')
        else:super().reject()

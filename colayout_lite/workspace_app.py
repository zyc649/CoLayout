"""Human workspace entry; optional loopback Agent service shares this Editor."""
from pathlib import Path
import argparse
from PySide6.QtCore import QLockFile,QTimer
from PySide6.QtWidgets import QApplication,QMessageBox
from .ui import Window
from .document import load_document,save_document
from .model import LiteError


class WorkspaceWindow(Window):
    def __init__(self,path,*,shortcut_path=None,installation_path=None,storage=None):
        from .workspace_storage import WorkspaceStorage
        self.storage=storage or WorkspaceStorage()
        self.installation_path=Path(installation_path).resolve() if installation_path else None
        self.document_path_warning=None
        path,archive=self.storage.prepare(path,resume=True)
        self.project_lock=self.lock_path(path)
        try:
            w,p=load_document(path)
            if w.validation_only:raise LiteError('VALIDATION_WORKSPACE_ONLY','这是工艺验证数据，不是普通工作区。')
            from .sync_recovery import restore_pending_state
            w=restore_pending_state(w)
            super().__init__(w,p,persist=False,shortcut_path=shortcut_path)
        except Exception:
            self.project_lock.unlock()
            raise
        self.document_path=archive;self.project_path=path
        self.replace_lock(path,self.project_lock)
        self.save_local()
        self.region_dock.hide()
        self.setWindowTitle('CoLayout Lite · 本地工作区 · '+w.baseline.cell)
        self.workspace_button.hide();self.samples_button.hide()  # Legacy demo/group controls remain in their separate entry points.
        from .mouse_edit import MouseEdit
        self.human=MouseEdit(self)
        self.canvas.customContextMenuRequested.disconnect(self.instance_menu)
        self.canvas.customContextMenuRequested.connect(self.human.context_menu)
        if w.state in ('submitting','indeterminate'):
            from .sync_recovery import recovery_message
            self.status.setText(recovery_message(w))
        else:self.status.setText('已恢复工作区；编辑自动保存在软件内部，使用“保存”更新 JSON 存档。')

    def save_local(self):
        if getattr(self,'project_path',None) and self.editor:
            current=(self.project_path,self.editor.w,self.editor.profile)
            previous=getattr(self,'_saved_local',None)
            if previous and previous[0]==current[0] and all(a is b for a,b in zip(previous[1:],current[1:])):return
            save_document(self.project_path,self.editor.w,self.editor.profile)
            self._saved_local=current

    def focus_initial(self):
        roots=[r for r in self.editor.w.local_data.regions.values() if r.parent_id is None]
        if roots:
            self.region_panel.selected_id=roots[0].id;self.region_panel.refresh();self.region_panel.fit_region(roots[0].id)
        else:self.fit()

    def pull(self,checked=False,*,fresh=False):
        super().pull(fresh=fresh)

    def open_document(self,path,*,prepared=False):
        if not self.idle_for_replacement():return
        if self.document_busy():raise LiteError('WORKSPACE_BUSY')
        path,archive=self.storage.prepare(path,resume=prepared)
        lock=self.project_lock if path==self.project_path else self.lock_path(path)
        try:self.save_local();super().open_document(path,backup_current=not prepared)
        except Exception:
            if lock is not self.project_lock:lock.unlock()
            raise
        self.replace_lock(path,lock)
        self.document_path=archive
        self.save_local()
        self.setWindowTitle('CoLayout Lite · 本地工作区 · '+self.editor.w.baseline.cell)

    def open_prepared_document(self,path):
        self.open_document(path,prepared=True)

    def save_document(self,path):
        path=Path(path).resolve()
        self.save_local()
        result=super().save_document(path)
        self.storage.remember_archive(self.project_path,path)
        return result

    def save_user_document(self):
        if self.document_path:self.save_document(self.document_path)
        else:self.save_document_dialog()

    def install(self,*args,**kwargs):
        if args and args[0].validation_only:raise LiteError('VALIDATION_WORKSPACE_ONLY','这是工艺验证数据，不是普通工作区。')
        result=super().install(*args,**kwargs)
        if self.editor:
            self.setWindowTitle('CoLayout Lite · 本地工作区 · '+self.editor.w.baseline.cell)
        return result

    @staticmethod
    def lock_path(path):
        path.parent.mkdir(parents=True,exist_ok=True)
        lock=QLockFile(str(path)+'.lock');lock.setStaleLockTime(0)
        if not lock.tryLock(0):raise LiteError('WORKSPACE_ALREADY_OPEN','这个工作副本已经打开，请切换到现有窗口。')
        return lock

    def replace_lock(self,path,lock):
        if lock is not self.project_lock:self.project_lock.unlock()
        self.project_path=path;self.project_lock=lock
        self.document_path_warning=None
        try:
            if self.installation_path is not None:
                import json
                from .transactions import write_json_atomic
                settings=json.loads(self.installation_path.read_text(encoding='utf8'))
                from .paths import ROOT
                if Path(settings['app_root']).resolve()!=ROOT.resolve():raise ValueError('Installation source mismatch')
                settings['document']=str(path)
                write_json_atomic(self.installation_path,settings)
            if hasattr(self,'agent_hub'):
                self.agent_hub.document_changed(path)
        except Exception as exc:
            self.document_path_warning='文档已切换，但启动路径或连接描述保存失败：'+str(exc)
            self.status.setText(self.document_path_warning)

    def document_busy(self):
        if getattr(self,'process_configuration_open',False):return True
        if self.busy or (self.job and self.job.isRunning()):return True
        if getattr(getattr(self,'drc',None),'job_id',None):return True
        routing=getattr(self,'routing_workbench',None)
        if routing and any(p.future for p in routing.panels.values()):return True
        hub=getattr(self,'agent_hub',None)
        return bool(hub and any(j.future and not j.future.done() for j in hub.runtime.jobs.values()))

    def closeEvent(self,event):
        super().closeEvent(event)
        if event.isAccepted():self.project_lock.unlock()


def main():
    from .diagnostics import install
    install();parser=argparse.ArgumentParser();parser.add_argument('document')
    parser.add_argument('--agent-api',action='store_true');parser.add_argument('--agent-panel',action='store_true')
    parser.add_argument('--installation',type=Path);args=parser.parse_args()
    path=Path(args.document).resolve();app=QApplication([]);app.setStyle('Fusion')
    from .app_identity import configure_application
    configure_application(app)
    from .studio_window import StudioWindow
    try:window=StudioWindow(path,installation_path=args.installation)
    except Exception as exc:QMessageBox.warning(None,'CoLayout Lite',str(exc));return
    if args.agent_api or args.agent_panel:
        from .agent_tools.app import enable
        hub=enable(window)
        if args.agent_panel:hub.show()
    from .ui_watchdog import UiWatchdog
    from .paths import ROOT
    import os
    watchdog=UiWatchdog(app,ROOT/'artifacts/lite/diagnostics'/f'{os.getpid()}-ui-stall.log')
    window.showMaximized();QTimer.singleShot(250,window.focus_initial)
    try:app.exec()
    finally:watchdog.stop()


if __name__=='__main__':main()

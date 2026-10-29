"""Window task lifecycle, Qt dispatch and terminal cleanup.

The host retains its public busy/job/task attributes for existing callers.
All model installation and callbacks remain on the owning UI thread.
"""

import json
import traceback
from PySide6.QtCore import QThread, Signal
from ..model import LiteError


class Job(QThread):
    done = Signal(object)
    failed = Signal(object)
    progress = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as exc:
            detail = (
                '\n' + json.dumps(exc.details, ensure_ascii=False, indent=2)
                if isinstance(exc, LiteError) and exc.details
                else ''
            )
            self.failed.emit((str(exc) + detail, traceback.format_exc()))


class TaskController:
    def __init__(self, window):
        self.window = window

    def task(self, fn, done):
        host = self.window
        if host.busy:
            return
        host.busy = True
        host.controls()
        host.status.setText('正在处理…')
        job = Job(fn, host)
        host.job = job
        job.work_holds = []
        if host.editor:
            job.work_holds.append(
                host.editor.work_sessions.suspend_starts(
                    '正在执行工作区任务，请完成后再接入 Agent。'
                )
            )
        job.progress.connect(host.status.setText)

        def succeeded(value):
            host.busy = False
            try:
                done(value)
            except Exception as exc:
                host.error((str(exc), traceback.format_exc()))
            host.controls()

        job.done.connect(succeeded)
        job.failed.connect(host.error)

        def finished():
            for resume in job.work_holds:
                resume()
            job.work_holds = []
            if host.job is job:
                host.job = None
            job.fn = None
            job.deleteLater()

        job.finished.connect(finished)
        job.start()

    def communication_task(self, fn, done):
        host = self.window
        if host.busy:
            return
        host.communication_active = True
        host.communication_action = getattr(host,'communication_action',None) or 'sync'

        def completed(value):
            host.communication_active = False
            host.communication_action = None
            done(value)

        try:
            host.task(fn, completed)
        except Exception:
            host.communication_active = False
            host.communication_action = None
            host.controls()
            raise

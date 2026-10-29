"""Process selection and configuration UI; model ownership stays with the host."""

import json
import traceback
from pathlib import Path
from PySide6.QtCore import QSignalBlocker, QTimer
from PySide6.QtWidgets import QVBoxLayout, QComboBox, QLabel
from ..adapter import Adapter
from ..transport import NativeTransport
from ..model import LiteError


class ProcessController:
    def __init__(self, window, *, root):
        self.window = window
        self._root = root

    @property
    def root(self):
        return self._root()

    def process_settings(self, checked=False, *, tab=None, page=None):
        host = self.window
        if not host.idle_for_replacement():
            return
        if getattr(host, 'document_busy', lambda: host.busy)():
            host.status.setText('请先等待当前任务完成，再维护工艺配置。')
            return
        from ..process_dialog import ProcessDialog

        host.save_local()
        current = host.editor.profile.key if host.editor else None
        dialog = ProcessDialog(host.process_store, host, current_key=current)
        if tab is not None:
            dialog.tabs.setCurrentIndex(tab)
        if page is not None:
            dialog.saved_editor.tabs.setCurrentIndex(page)
        host.process_configuration_open = True
        try:
            host.idle_dialog(dialog)
        finally:
            host.process_configuration_open = False
        selected_key = dialog.selected_key
        reload_current = current in dialog.modified_keys
        dialog.deleteLater()
        host.refresh_process_choices()
        if selected_key:
            host.switch_process(selected_key)
        elif reload_current:
            host.apply_process_preferences(current)
        host.drc._current_key = None
        host.drc.refresh_profile()
        from virtuoso_bridge.env import set_runtime_env_file

        if host.connection_config.exists():
            cfg = json.loads(host.connection_config.read_text(encoding='utf-8'))
            set_runtime_env_file(self.root / cfg['bridge_env'])

    def apply_process_preferences(self, key):
        host = self.window
        if not host.editor or host.editor.profile.key != key:
            return
        from ..process_configuration import ProcessConfiguration
        from ..permissions import apply_profile_permissions

        p = ProcessConfiguration(host.process_store).load(key).technology
        baseline = apply_profile_permissions(host.editor.w.baseline, p)
        if host.editor.w.operations and baseline.semantic() != host.editor.w.baseline.semantic():
            host.status.setText('工艺配置已保存；原草稿保留，请处理草稿后再加载新的图层权限。')
            return
        host.editor.work_sessions.require_idle()
        host.editor.profile = p
        if baseline != host.editor.w.baseline:
            host.editor.w = host.editor.w.model_copy(update={'baseline': baseline})
        host.save_local()
        host.status.setText('工艺设置已更新，已有几何保持不变。')
        host.controls()

    def refresh_process_choices(self):
        host = self.window
        selected = host.editor.profile.key if host.editor else None
        with QSignalBlocker(host.process_choice):
            host.process_choice.clear()
            for key, entry in host.process_store.entries().items():
                host.process_choice.addItem(entry['label'], key)
            host.process_choice.setCurrentIndex(host.process_choice.findData(selected))

    def switch_process(self, key):
        host = self.window
        if not key or host.busy:
            return
        if not host.idle_for_replacement():
            return
        try:
            host.save_local()
            entry, p, w = host.process_store.load(key)
            if host.editor:
                from uuid import uuid4

                host.editor.w.save(
                    host.process_store.folder
                    / 'before-switch'
                    / f'{host.editor.w.id}-{uuid4().hex[:8]}.json'
                )

            def done(result):
                host.connection_config = Path(entry['connection'])
                host.adapter = None
                host.install(*result)
                host.save_local()
                host.refresh_process_choices()
                host.status.setText(
                    '已切换到 ' + p.label + '；已保存原工艺草稿。同步前请连接对应工艺的 Virtuoso。'
                )

            if w:
                done((w, p))
            else:
                cfg = json.loads(Path(entry['connection']).read_text(encoding='utf8'))
                if entry.get('configuration_origin') == 'shared' and not entry.get('sample'):
                    host.choose_process_layout(p, entry, cfg, done)
                    return
                source = entry.get('sample') or {
                    'library': cfg.get('default_library'),
                    'cell': cfg.get('default_source_cell'),
                }
                if not source.get('library') or not source.get('cell'):
                    raise LiteError(
                        'PROCESS_LAYOUT_REQUIRED',
                        '配置已保存，请在对应工艺的 Virtuoso 中打开版图后导入。',
                    )
                host.task(
                    lambda: Adapter(NativeTransport(entry['connection'])).open_workspace(
                        source['library'], source['cell']
                    ),
                    done,
                )
        except Exception as exc:
            host.refresh_process_choices()
            host.error((str(exc), traceback.format_exc()))

    def choose_process_layout(self, profile, entry, cfg, done):
        """A shared package has no foreign sample/workspace to open on this host."""
        host = self.window
        from ..process_setup import inspect_live
        from pathlib import PurePosixPath

        original = host.editor

        def choose(live):
            rows = [
                r
                for r in live['layouts']
                if r.get('library_path')
                and PurePosixPath(r['library_path']).parent
                == PurePosixPath(cfg['allowed_remote_root'])
                and r['library'] != r['technology']
                and (
                    not profile.native_technology_name
                    or r['technology'] == profile.native_technology_name
                )
            ]
            if not rows:
                host.refresh_process_choices()
                host.status.setText(
                    '配置已保存。请在对应工艺的 Virtuoso 中打开版图，再使用此工艺。'
                )
                return
            source = rows[0]
            if len(rows) > 1:
                from PySide6.QtWidgets import QDialog, QDialogButtonBox

                dialog = QDialog(host)
                dialog.setWindowTitle('选择要打开的 Layout')
                layout = QVBoxLayout(dialog)
                combo = QComboBox()
                for row in rows:
                    combo.addItem(row['library'] + '/' + row['cell'], row)
                layout.addWidget(combo)
                buttons = QDialogButtonBox(
                    QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                )
                layout.addWidget(buttons)
                buttons.accepted.connect(dialog.accept)
                buttons.rejected.connect(dialog.reject)
                if host.idle_dialog(dialog) != QDialog.DialogCode.Accepted:
                    host.refresh_process_choices()
                    return
                source = combo.currentData()

            def start():
                if (
                    host.editor is not original
                    or not host.isVisible()
                    or not host.idle_for_replacement()
                ):
                    return
                host.task(
                    lambda: Adapter(NativeTransport(entry['connection'])).open_workspace(
                        source['library'], source['cell']
                    ),
                    done,
                )

            QTimer.singleShot(0, start)

        host.task(lambda: inspect_live(self.root / cfg['bridge_env'])[1], choose)

    def open_help(self):
        host = self.window
        host.process_settings(tab=2)

    def choose_sample(self):
        host = self.window
        if not host.idle_for_replacement():
            return
        from PySide6.QtWidgets import QDialog, QDialogButtonBox

        catalog = self.root / 'config/test_samples.json'
        if not catalog.exists():
            host.status.setText('样例目录尚未生成。')
            return
        data = json.loads(catalog.read_text(encoding='utf-8'))
        dialog = QDialog(host)
        dialog.setWindowTitle('选择通信测试样例')
        layout = QVBoxLayout(dialog)
        note = QLabel('当前草稿会先保存备份；直接打开所选 Layout，后续同步写回该 cell。')
        note.setWordWrap(True)
        layout.addWidget(note)
        combo = QComboBox()
        for entry in data['samples']:
            combo.addItem(entry['label'], entry)
        layout.addWidget(combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if host.idle_dialog(dialog) != QDialog.DialogCode.Accepted:
            return
        if not host.idle_for_replacement():
            return
        entry = combo.currentData()
        if host.editor:
            from uuid import uuid4

            host.editor.w.save(
                self.root
                / 'artifacts/lite-02/workspace-before-switch'
                / f'{host.editor.w.id}-{uuid4().hex[:8]}.json'
            )
        host.task(
            lambda: host.native().open_workspace(entry['library'], entry['cell']),
            lambda result: host.install(*result),
        )

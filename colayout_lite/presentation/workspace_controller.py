"""Document persistence and installation orchestration over the host Editor/scene."""

from pathlib import Path
import traceback
from PySide6.QtWidgets import QFileDialog
from ..editor import Editor, projected
from ..actions import Actions
from ..model import LiteError
from ..display_changes import affected_owners
from ..scene import figures_by_owner
from ..render import make_texture


class WorkspaceController:
    def __init__(self, window, *, root):
        self.window = window
        self._root = root

    @property
    def root(self):
        return self._root()

    def install(self, w, p):
        host = self.window
        if host.editor:
            host.editor.work_sessions.require_idle()
        if hasattr(host, 'human'):
            host.human.escape()
        if hasattr(host, 'selection_ui'):
            host.selection_ui.cancel()
        if hasattr(host, 'inspection'):
            host.inspection.focus_pin()
        preserve = hasattr(host, '_install_scope')
        from ..workspace_actions import WorkspaceActions

        host.clear_workspace_overlay()
        if host._editor_unsubscribe:
            host._editor_unsubscribe()
            host._editor_unsubscribe = None
        if host._work_unsubscribe:
            host._work_unsubscribe()
            host._work_unsubscribe = None
        if getattr(host, 'circuit_dialog', None):
            try:
                host.circuit_dialog.close()
            except RuntimeError:
                pass
        old = host.editor.w if host.editor else None
        next_objects = projected(w)
        selected = (
            host.diagnostics.selected_uid
            if old
            and (old.baseline.library, old.baseline.cell) == (w.baseline.library, w.baseline.cell)
            else None
        )
        reuse = bool(
            old
            and (old.baseline.library, old.baseline.cell) == (w.baseline.library, w.baseline.cell)
            and old.baseline.dependency_digest == w.baseline.dependency_digest
            and old.baseline.display.get('styles') == w.baseline.display.get('styles')
            and old.instance_display == w.instance_display
        )
        changed = set()
        if reuse:
            changed = {
                uid
                for uid in old.baseline.objects.keys() | w.baseline.objects.keys()
                if uid not in old.baseline.objects
                or uid not in w.baseline.objects
                or old.baseline.objects[uid].semantic() != w.baseline.objects[uid].semantic()
            }
            changed.update(op.uid for op in old.operations)
            for preview in old.guard_previews.values():
                changed.update(preview['objects'])
            changed = affected_owners(
                changed,
                host.groups,
                next_objects,
                sources=(
                    old.baseline.objects,
                    getattr(host, '_visible_objects', {}),
                    w.baseline.objects,
                ),
                text_owners={**old.baseline.text_owners, **w.baseline.text_owners},
            )
        host._painting = True
        host.editor = Editor(
            w,
            p,
            scope_id=host._install_scope
            if preserve and host._install_scope in w.local_data.regions
            else None,
        )
        host.actions = Actions(host.editor)
        host.library.setText(w.baseline.library)
        host.cell.setText(w.baseline.cell)
        if host.job is not None and hasattr(host.job, 'work_holds'):
            host.job.work_holds.append(
                host.editor.work_sessions.suspend_starts('工作区任务尚未完成，请稍后再接入 Agent。')
            )
        host.workspace_actions = WorkspaceActions(host.editor)
        if not reuse:
            host.scene.clear()
            host.groups = {}
            host.scene_rebuilds += 1
        if reuse:
            updated, _ = (
                figures_by_owner(w.baseline, modes=host.display_choices(), owner_filter=changed)
                if changed
                else ({}, {})
            )
            host.base_figures = {
                **{uid: f for uid, f in host.base_figures.items() if uid not in changed},
                **updated,
            }
        else:
            host.base_figures, host.styles = figures_by_owner(
                w.baseline, modes=host.display_choices()
            )
            host.textures = {k: make_texture(v) for k, v in host.styles.items()}
        host.canvas.owner_ids = lambda: list(host.groups)
        host.canvas.owner_items = host.visible_owner_items
        host.canvas.overlay_items = lambda: host._workspace_overlay_items
        host.canvas.configure_preview(
            sum(map(len, host.base_figures.values())), changed_owners=changed if reuse else None
        )
        host._visible_objects = next_objects
        for uid in set(host.groups) - set(host._visible_objects):
            host.groups.pop(uid).remove()
        for uid in changed if reuse else w.baseline.objects:
            host.draw_owner(uid)
        if reuse:
            host.extend_scene_bounds(changed)
        host.diagnostics.bind(host.editor)
        host.local_refresh(set(o.uid for o in w.operations))
        if selected in host._visible_objects:
            host.diagnostics.set_selected(selected)
            host.select_uid(selected)
        if not reuse:
            host.visibility()
            if not preserve:
                host.fit()
        from ..inspection_data import prime_pin_geometry

        prime_pin_geometry(host.editor.w, host.editor.profile)
        host.canvas.prime_vector_records(lambda uid: host.groups[uid].childItems())
        host._painting = False
        host.controls()
        host.status.setText(
            f'{w.baseline.library}/{w.baseline.cell}/layout · {len(w.baseline.objects)} 对象 · {len(w.baseline.display["nodes"])} 共享视图缓存 · {len(w.operations)} 项待同步'
        )
        if w.circuit:
            host.status.setText(
                host.status.text()
                + f' · 原生绑定：{len(w.circuit.instances)} 个参考实例 / {len(w.circuit.bindings)} 个版图实例'
            )
        else:
            host.status.setText(host.status.text() + ' · 旧版图快照：重新配对导入后才能同步')
        missing = [
            o.attributes.get('name', o.uid[:8])
            for o in w.baseline.objects.values()
            if o.read_only_reason == 'master_unresolved'
        ]
        if missing:
            host.status.setText(
                host.status.text() + ' · 源master缺失：' + ', '.join(missing) + '（只读外框）'
            )
        owner = host.editor
        host._editor_unsubscribe = owner.subscribe(
            lambda changed: host.workspace_changed.emit((owner, changed))
        )
        host._work_unsubscribe = owner.work_sessions.subscribe(host._on_work_sessions_changed)
        host.view_state_changed.emit()

    def install_preserving_view(self, w, p):
        host = self.window
        from ..camera import capture, restore

        camera = capture(host.canvas)
        host._install_scope = host.editor.scope_id if host.editor else None
        try:
            host.install(w, p)  # Keep subclass/session adoption hooks intact.
        finally:
            del host._install_scope
            restore(host.canvas, camera)
            host.refresh_workspace_overlay()
        return camera

    def save_local(self):
        host = self.window
        if host.persist and host.editor:
            host.editor.w = host.editor.w.model_copy(
                update={'connection_config': str(host.connection_config)}
            )
            host.editor.w.save(self.root / 'artifacts/lite/user-workspace.json')
            host.editor.profile.save(self.root / 'artifacts/lite/user-profile.json')
            host.process_store.remember(host.editor.w)

    def save_document(self, path):
        host = self.window
        from ..document import save_document

        if not host.editor:
            raise LiteError('WORKSPACE_REQUIRED')
        save_document(path, host.editor.w, host.editor.profile)
        host.document_path = Path(path)
        host.status.setText('本地工作区已保存：' + str(path))
        return host.document_path

    def open_document(self, path, *, backup_current=True):
        host = self.window
        if host.editor:
            host.editor.work_sessions.require_idle()
        from ..document import load_document

        candidate, profile = load_document(path)
        from ..sync_recovery import restore_pending_state

        candidate = restore_pending_state(candidate)
        if host.editor and backup_current:
            from ..sync_recovery import backup

            backup(host, 'before-open')
        host.install(candidate, profile)
        host.document_path = Path(path)
        if candidate.connection_config:
            host.connection_config = Path(candidate.connection_config)
        host.adapter = None
        host.status.setText('已打开本地工作区：' + str(path))

    def save_document_dialog(self):
        host = self.window
        if host.busy or not host.editor:
            return
        path, _ = QFileDialog.getSaveFileName(
            host,
            '保存本地工作区',
            str(host.document_path or self.root / 'artifacts/lite/workspace.colayout.json'),
            'CoLayout (*.json)',
        )
        if path:
            try:
                host.save_document(path)
            except Exception as exc:
                host.error((str(exc), traceback.format_exc()))

    def open_document_dialog(self):
        host = self.window
        if host.busy:
            return
        if not host.idle_for_replacement():
            return
        path, _ = QFileDialog.getOpenFileName(
            host, '打开本地工作区', str(self.root / 'artifacts'), 'CoLayout (*.json)'
        )
        if path:
            try:
                host.open_document(path)
            except Exception as exc:
                host.error((str(exc), traceback.format_exc()))

"""Shared canvas controllers over the public local API."""
from __future__ import annotations
import argparse,json,traceback
from pathlib import Path
from PySide6.QtCore import Qt,Signal,QTimer,QSignalBlocker
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,
    QLineEdit,QComboBox,QCheckBox,QSplitter,QGraphicsScene,QDockWidget,QFileDialog)
from .model import Workspace,LiteError
from .technology import TechnologyProfile
from .editor import Editor,projected
from .adapter import Adapter
from .paths import ROOT
from .transport import NativeTransport
from .scene import figures_by_owner
from .render import NativeFigureItem,make_texture
from .actions import Actions
from .presentation.view_state import ViewState
from .hierarchy import node_info
from .display_changes import affected_owners
from .ui_signals import StatusLabel
from .presentation.canvas import Canvas as Canvas
from .presentation.owner_graphics import OwnerGraphics as OwnerGraphics, qt_transform as qt_transform
from .presentation.tasks import Job as Job, TaskController
from .presentation.synchronization import SyncController


class Window(QMainWindow):
    workspace_changed=Signal(object)
    view_state_changed=Signal()
    def __init__(self,workspace=None,profile=None,*,persist=True,adapter=None,connection=None,shortcut_path=None):
        super().__init__();self.tasks=TaskController(self);self.communication=SyncController(self);self.persist=persist;self.adapter=adapter;self.editor=None;self.busy=False;self.job=None
        from .app_identity import application_icon
        self.setWindowIcon(application_icon())
        from .presentation.process_controller import ProcessController
        from .presentation.workspace_controller import WorkspaceController
        self.process_controller=ProcessController(self,root=lambda:ROOT)
        self.workspace_controller=WorkspaceController(self,root=lambda:ROOT)
        self._editor_unsubscribe=None;self._work_unsubscribe=None;self._workspace_overlay_items=[];self._local_pin_items=[];self.document_path=None
        self.workspace_changed.connect(self._on_workspace_changed)
        self.setFont(QFont('Microsoft YaHei UI',9))
        self.connection_config=Path(connection or (workspace.connection_config if workspace else None) or ROOT/'config/colayout_lite.json')
        self.groups={};self.base_figures={};self.styles={};self.textures={};self.scene_rebuilds=0
        self.setWindowTitle('CoLayout · 工艺与 DRC 统一配置');self.resize(1380,900);self._painting=False
        outer=QWidget();self.setCentralWidget(outer);layout=QVBoxLayout(outer)
        bar=QHBoxLayout();layout.addLayout(bar)
        connection=json.loads((self.connection_config if self.connection_config.exists() else ROOT/'config/colayout_lite.json').read_text(encoding='utf-8'))
        self.library=QLineEdit(connection.get('default_library',''));self.library.setMaximumWidth(150)
        self.cell=QLineEdit(connection.get('default_source_cell',''));bar.addWidget(self.library);bar.addWidget(self.cell)
        self.pull_button=QPushButton('拉取（先备份草稿）');self.sync_button=QPushButton('同步到 Virtuoso')
        self.pull_button.setToolTip('重新读取服务器当前版图；存在本地草稿或未决回执时先备份，不自动重发旧操作。')
        self.native_button=QPushButton('打开对应 Layout');self.recover_button=QPushButton('核对未完成同步')
        for button in [self.pull_button,self.sync_button,self.native_button,self.recover_button]:bar.addWidget(button)
        self.pull_button.clicked.connect(self.pull);self.sync_button.clicked.connect(self.sync)
        self.native_button.clicked.connect(self.open_native);self.recover_button.clicked.connect(self.reconcile)
        viewbar=QHBoxLayout();layout.addLayout(viewbar)
        fit=QPushButton('适合窗口');self.fit_button=fit;fit.clicked.connect(self.fit);viewbar.addWidget(fit)
        self.internal=QCheckBox('显示实例内部');self.internal.setChecked(True)
        self.cuts=QCheckBox('显示切孔');self.cuts.setChecked(True)
        self.pattern=QCheckBox('原生纹理');self.pattern.setChecked(True)
        # Display is controlled per instance; keep the programmatic global
        # switch for regression tools, but do not expose conflicting UI rules.
        for v in [self.cuts,self.pattern]:viewbar.addWidget(v)
        viewbar.addStretch();self.undo_button=QPushButton('撤销本地');self.redo_button=QPushButton('重做')
        viewbar.addWidget(self.undo_button);viewbar.addWidget(self.redo_button)
        from .process_library import ProcessLibrary
        self.process_store=ProcessLibrary()
        if self.persist:self.process_store.migrate_existing()
        self.process_choice=QComboBox();self.process_choice.setMinimumWidth(135);viewbar.addWidget(self.process_choice)
        self.process_choice.activated.connect(lambda index:self.switch_process(self.process_choice.itemData(index)))
        self.process_button=QPushButton('工艺库…');viewbar.addWidget(self.process_button);self.process_button.clicked.connect(self.process_settings)
        self.samples_button=QPushButton('选择测试样例…');viewbar.addWidget(self.samples_button);self.samples_button.clicked.connect(self.choose_sample)
        self.help_button=QPushButton('使用教程');viewbar.addWidget(self.help_button);self.help_button.clicked.connect(self.open_help)
        self.circuit_button=QPushButton('查看本地原理图');viewbar.addWidget(self.circuit_button)
        self.circuit_button.clicked.connect(self.show_circuit)
        self.undo_button.clicked.connect(lambda:self.undo(False));self.redo_button.clicked.connect(lambda:self.undo(True))
        self.scene=QGraphicsScene(self);self.canvas=Canvas(self.scene);split=QSplitter();layout.addWidget(split,1);split.addWidget(self.canvas)
        self.canvas.owner_selection_rect=lambda uid:self.groups[uid].selection_rect() if uid in self.groups else None
        self.scene.setMinimumRenderSize(.4)
        self.fast_preview=QCheckBox('矢量加速');self.fast_preview.setChecked(True);viewbar.addWidget(self.fast_preview)
        self.fast_preview.setToolTip('每帧按当前比例绘制矢量，不放大旧截图。远景省略亚像素小图形与不可读文字；放大即显示。关闭可对照逐对象绘制。')
        self.fast_preview.toggled.connect(self.canvas.set_preview_enabled)
        self.preview_label=QLabel('精细几何');self.preview_label.setFixedWidth(185);viewbar.addWidget(self.preview_label);self.canvas.preview_mode.connect(self.preview_label.setText)
        self.diagnostics=ViewState()
        self.canvas.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu);self.canvas.customContextMenuRequested.connect(self.instance_menu)
        self.canvas.clicked_at.connect(self.show_coordinate)
        self.fork_button=QPushButton('保留草稿另建副本');viewbar.addWidget(self.fork_button);self.fork_button.clicked.connect(self.fork_draft)
        self.fork_button.setToolTip('将本地修改迁到新副本；冲突对象采用本地修改意图，原服务器版图完整保留。')
        self.recover_button.setToolTip('仅用于提交中断或结果不明；服务器内容冲突请用“保留草稿另建副本”。')
        self.status=StatusLabel('输入库和 Layout cell；直接关联该版图，点击同步时写回同一个 cell。');self.status.setWordWrap(True);layout.addWidget(self.status)
        from .activity import ActivityLog
        self.activity=ActivityLog(self)
        self.scene.selectionChanged.connect(self.selected)
        for v in [self.internal,self.cuts,self.pattern]:v.toggled.connect(self.visibility)
        if workspace:self.install(workspace,profile)
        self.refresh_process_choices()
        from .drc.panel import DrcPanel
        self.drc=DrcPanel(self);self.drc_dock=QDockWidget('检查',self);self.drc_dock.setWidget(self.drc)
        self.drc_dock.setMinimumWidth(385);self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,self.drc_dock);self.drc_dock.hide()
        self.drc_button=QPushButton('区域 DRC…');bar.addWidget(self.drc_button)
        self.drc_button.clicked.connect(self.show_manual_drc)
        self.drc_dock.visibilityChanged.connect(lambda visible:self.canvas.viewport().update())
        from .workspace_panel import WorkspacePanel
        self.workspace_panel=WorkspacePanel(self);self.workspace_dock=QDockWidget('本地工作区',self)
        self.workspace_dock.setWidget(self.workspace_panel);self.workspace_dock.setMinimumWidth(380)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,self.workspace_dock);self.workspace_dock.hide()
        self.workspace_button=QPushButton('分组 / 本地 PIN');bar.addWidget(self.workspace_button)
        self.workspace_button.clicked.connect(lambda:(self.workspace_dock.show(),self.workspace_dock.raise_()))
        from .regions.panel import RegionPanel
        self.region_panel=RegionPanel(self);self.region_dock=QDockWidget('操作区与本地层次',self)
        self.region_dock.setWidget(self.region_panel);self.region_dock.setMinimumWidth(420)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,self.region_dock);self.region_dock.hide()
        self.region_button=QCheckBox('操作区工具');viewbar.addWidget(self.region_button)
        self.region_button.setToolTip('显示/隐藏操作区与本地层次。Ctrl+E 返回上层；Ctrl+滚轮切换黑盒三档透视。')
        self.region_button.toggled.connect(self.region_dock.setVisible)
        self.region_dock.visibilityChanged.connect(self.region_button.setChecked)
        self.canvas.peek_changed.connect(self.change_blackbox_peek)
        self.canvas.object_activated.connect(self.region_panel.activate_uid)
        self.canvas.view_changed.connect(self.refresh_camera_overlay)
        from .inspection_view import InspectionView
        self.inspection=InspectionView(self);self.refresh_workspace_overlay()
        from .shortcuts import ShortcutManager
        self.shortcuts=ShortcutManager(self,shortcut_path or ROOT/'config/gui-shortcuts.json')
        self.shortcuts.bind({'fit':self.fit,'up':lambda:self.region_panel.navigate(self.region_panel.up),
            'rotate':lambda:getattr(self,'human',None) and self.human.command('rotate'),
            'undo':lambda:self.undo(False),'redo':lambda:self.undo(True),'redo_alt':lambda:self.undo(True),
            'delete':lambda:getattr(self,'human',None) and self.human.command('delete')})
        from .selection_view import SelectionView
        selection_bar=QHBoxLayout();layout.insertLayout(2,selection_bar)
        self.selection_ui=SelectionView(self,selection_bar,self.shortcuts.path.with_name('gui-selection.json'))
        self.shortcuts_button=QPushButton('快捷键…');viewbar.insertWidget(1,self.shortcuts_button);self.shortcuts_button.clicked.connect(self.shortcuts.edit)





    def change_blackbox_peek(self,level):
        self.refresh_workspace_overlay()
        modifier=self.shortcuts.values['peek'] if hasattr(self,'shortcuts') else 'Ctrl'
        self.status.setText('本地黑盒：'+('不透明','半透明','透视')[level]+' · '+modifier+'+滚轮切换，仅影响显示')

    def native(self):
        if not getattr(self,'remote_enabled',True):raise LiteError('OFFLINE_TRIAL','当前窗口是离线试用副本。请通过“启动CoLayout工作区.cmd”打开正式工作区使用通信。')
        if self.adapter is None:self.adapter=Adapter(NativeTransport(self.connection_config,
            progress=lambda message:self.job.progress.emit(message) if self.job else None))
        self.adapter.native.progress=lambda message:self.job.progress.emit(message) if self.job else None
        return self.adapter

    def display_choices(self):
        if self.internal.isChecked():return self.editor.w.instance_display
        return {uid:'box_pins' for uid,obj in self.editor.w.baseline.objects.items() if obj.kind in ('inst','mosaic')}

    def instance_menu(self,pos):
        from PySide6.QtWidgets import QMenu
        if self.busy or not self.editor:return
        candidates={}
        for item in self.canvas.items(pos):
            while item and not item.data(0):item=item.parentItem()
            uid=item.data(0) if item else None;obj=self.editor.w.baseline.objects.get(uid)
            if obj and obj.kind in ('inst','mosaic') and obj.bbox:
                candidates[uid]=abs((obj.bbox[1][0]-obj.bbox[0][0])*(obj.bbox[1][1]-obj.bbox[0][1]))
        if not candidates:return
        # A pad ring enclosing the die must not swallow every smaller module.
        uid=min(candidates,key=candidates.get)
        self.diagnostics.set_selected(uid);self.select_uid(uid);menu=QMenu(self)
        for title,mode in [('自动（有子实例→框＋Pin）','auto'),('全部显示','full'),('框＋Pin','box_pins')]:
            action=menu.addAction(title);action.setCheckable(True);action.setChecked(self.editor.w.instance_display.get(uid,'auto')==mode)
            action.triggered.connect(lambda checked=False,u=uid,m=mode:self.change_instance_display(u,m))
        menu.exec(self.canvas.viewport().mapToGlobal(pos))

    def change_instance_display(self,uid,mode):
        if not uid or self.busy or not self.editor:return
        obj=self.editor.w.baseline.objects.get(uid)
        if not obj or obj.kind not in ('inst','mosaic'):return
        node=self.editor.w.baseline.display['nodes'].get(obj.attributes.get('master_key'))
        def apply(display=None):
            candidate=self.editor.w.baseline.model_copy(update={'display':display}) if display is not None else self.editor.w.baseline
            choices={**self.editor.w.instance_display,uid:mode}
            figures,styles=figures_by_owner(candidate,modes=choices if self.internal.isChecked() else self.display_choices())
            # Validate the complete scene budget before publishing the preference.
            self.editor.set_instance_display(uid,mode,display)
            self.base_figures,self.styles=figures,styles;self.textures={k:make_texture(v) for k,v in styles.items()}
            self._visible_objects=projected(self.editor.w);self.draw_owner(uid);self.local_refresh({uid})
            self.diagnostics.set_selected(uid);self.select_uid(uid);self.save_local()
            self.status.setText('实例显示已切换；版图数据与待同步操作不变。'+(' 存在缺失/未支持的引用，请留意占位框。' if candidate.display.get('unsupported') else ''))
        try:
            if mode=='full' and node is None:raise LiteError('MASTER_UNRESOLVED','源master缺失，无法展开。')
            if mode=='full' and node_info(node).get('collapsed'):
                self.task(lambda:self.native().expanded_display(self.editor.w,uid),apply)
            else:apply()
        except Exception as exc:self.error((str(exc),traceback.format_exc()))

    def show_coordinate(self,x,y):
        if not self.editor:return
        scale=self.editor.profile.dbu_per_micron;grid=self.editor.profile.grid
        sx,sy=round(x/grid)*grid,round(y/grid)*grid
        self.diagnostics.set_coordinates(f'点击坐标：X={x/scale:.6f}，Y={y/scale:.6f} µm\n网格点：({sx/scale:.6f}, {sy/scale:.6f}) µm · ({sx}, {sy}) DBU')

    def fork_draft(self):
        if not self.editor or self.busy:return
        if not self.idle_for_replacement():return
        self.task(lambda:self.native().fork_draft(self.editor.w),lambda result:(self.install(*result),self.save_local(),self.status.setText('草稿已迁移到新副本；原服务器版图保留。可检查后点击同步。')))

    def process_settings(self,checked=False,*,tab=None,page=None):
        return self.process_controller.process_settings(checked, tab=tab, page=page)

    def apply_process_preferences(self,key):
        return self.process_controller.apply_process_preferences(key)

    def refresh_process_choices(self):
        return self.process_controller.refresh_process_choices()

    def switch_process(self,key):
        return self.process_controller.switch_process(key)

    def choose_process_layout(self,profile,entry,cfg,done):
        return self.process_controller.choose_process_layout(profile, entry, cfg, done)

    def open_help(self):
        return self.process_controller.open_help()

    def choose_sample(self):
        return self.process_controller.choose_sample()

    def showEvent(self,event):
        from .app_identity import configure_window
        configure_window(self)
        super().showEvent(event)
        if not getattr(self,'_initial_fit_done',False):
            self._initial_fit_done=True;QTimer.singleShot(0,self.fit)

    def task(self,fn,done):
        return self.tasks.task(fn,done)

    def communication_task(self,fn,done):
        return self.tasks.communication_task(fn,done)

    def error(self,result):
        self.refresh_process_choices()
        summary='操作未完成：'+(str(result[0]).splitlines() or ['未知错误'])[0]
        self.busy=False;self.communication_active=False;self.communication_action=None;self.status.setText(summary);self.diagnostics.show_error(result[0])
        self.activity.record(summary,str(result[0])+'\n\n'+str(result[1]))
        folder=ROOT/'artifacts/lite';folder.mkdir(parents=True,exist_ok=True)
        from datetime import datetime,timezone
        target=self.editor.w.baseline.library+'/'+self.editor.w.baseline.cell if self.editor else '未载入工程'
        with (folder/'ui-errors.log').open('a',encoding='utf-8') as f:
            f.write(f'\n[{datetime.now(timezone.utc).isoformat(timespec="seconds")}] {target}\n{result[0]}\n{result[1]}\n')
        if self.editor and self.adapter:
            path=self.adapter.state/'workspaces'/f'{self.editor.w.id}.json'
            if path.exists():
                try:
                    pending=self.adapter.load_workspace(self.editor.w.id)
                    if pending.state in ('submitting','indeterminate'):
                        self.editor.w=pending;self.save_local()
                        from .sync_recovery import recovery_message
                        self.status.setText(recovery_message(pending))
                        self.activity.record('同步结果待核对',recovery_message(pending))
                except Exception as exc:
                    self.activity.record('同步状态读取失败，请先核对持久状态。',str(exc))
        self.controls()

    def show_manual_drc(self):
        if not self.drc.job_id:self.drc.bind_region(None)
        self.drc_dock.setVisible(not self.drc_dock.isVisible())

    def controls(self):
        if hasattr(self,'workspace_panel'):
            self.workspace_panel.setEnabled(not self.busy and bool(self.editor) and self.editor.w.state not in ('submitting','indeterminate','conflict'))
        if hasattr(self,'region_panel'):
            self.region_panel.setEnabled(not self.busy and bool(self.editor) and self.editor.w.state not in ('submitting','indeterminate','conflict'))
            if self.busy:self.region_panel.cancel()
        self.circuit_button.setEnabled(not self.busy and bool(self.editor and self.editor.w.circuit))
        self.process_choice.setEnabled(not self.busy)
        for b in [self.pull_button,self.sync_button,self.native_button,self.recover_button,self.undo_button,self.redo_button,self.process_button,self.samples_button,self.fork_button]:b.setEnabled(not self.busy)
        if self.editor and self.editor.w.state in ('submitting','indeterminate','conflict'):
            for b in [self.undo_button,self.redo_button,self.sync_button]:b.setEnabled(False)
        self.diagnostics.set_busy(self.busy or bool(self.editor and self.editor.w.state in ('submitting','indeterminate','conflict')))
        self.recover_button.setEnabled(not self.busy and bool(self.editor and self.editor.w.state in ('submitting','indeterminate')))
        self.fork_button.setEnabled(not self.busy and bool(self.editor and self.editor.w.operations and self.editor.w.state not in ('submitting','indeterminate')))
        if self.editor and self.editor.work_sessions.snapshots():
            for button in (self.pull_button,self.sync_button,self.recover_button,self.fork_button,self.process_button,self.samples_button,self.process_choice):button.setEnabled(False)
        self.diagnostics.set_discard_enabled(not self.busy and bool(self.editor) and self.editor.w.state not in ('submitting','indeterminate','conflict') and not self.editor.work_sessions.snapshots())
        if hasattr(self,'selection_ui'):self.selection_ui.selection_changed()
        self.view_state_changed.emit()

    def idle_for_replacement(self):
        try:
            if self.editor:self.editor.work_sessions.require_idle()
            return True
        except LiteError as exc:self.status.setText(str(exc));return False

    def _on_work_sessions_changed(self):
        if hasattr(self,'human'):self.human.escape()
        if hasattr(self,'selection_ui'):self.selection_ui.cancel();self.selection_ui.selection_changed()
        if hasattr(self,'region_panel'):self.region_panel.cancel()
        self.controls();self.refresh_workspace_overlay()

    def idle_dialog(self,dialog):
        """Modal setup must not admit a new worker while it pumps UI events."""
        from PySide6.QtWidgets import QDialog
        if not self.idle_for_replacement():return QDialog.DialogCode.Rejected
        resume=self.editor.work_sessions.suspend_starts('正在配置或切换工作区，请关闭对话框后接入 Agent。') if self.editor else lambda:None
        try:return dialog.exec()
        finally:resume()

    def install(self,w,p):
        return self.workspace_controller.install(w, p)

    def install_preserving_view(self,w,p):
        return self.workspace_controller.install_preserving_view(w, p)

    def _on_workspace_changed(self,event):
        editor,changed=event
        if editor is not self.editor:return
        try:
            self.local_refresh(changed)
            self.save_local()
        except Exception as exc:self.error((str(exc),traceback.format_exc()))

    def clear_workspace_overlay(self):
        from .workspace_overlay import clear
        clear(self)

    def visible_owner_items(self,uid):
        graphics=self.groups.get(uid)
        if graphics is None or not any(p.isVisible() for p in graphics.parts.values()):return []
        return graphics.childItems()

    def refresh_workspace_overlay(self):
        from .workspace_overlay import refresh
        refresh(self)
        if hasattr(self,'inspection'):self.inspection.refresh()
        self.view_state_changed.emit()

    def refresh_camera_overlay(self):
        # Camera motion changes caption spacing, not the model, permissions,
        # PIN projection or tool-panel state. Those have their own refresh path.
        from .workspace_overlay import reflow_labels
        reflow_labels(self)
        self.canvas.viewport().update()

    def draw_owner(self,uid,figures=None):
        from .presentation.layout_scene import draw_owner
        return draw_owner(self,uid,figures)

    def visibility(self):
        self.canvas.invalidate_preview()
        if self.editor and self.sender() is self.internal:
            self.base_figures,self.styles=figures_by_owner(self.editor.w.baseline,modes=self.display_choices())
            self.textures={k:make_texture(v) for k,v in self.styles.items()}
            uids={u for u,o in self.editor.w.baseline.objects.items() if o.kind in ('inst','mosaic')}
            self._visible_objects=projected(self.editor.w)
            for uid in uids:self.draw_owner(uid)
            self.local_refresh(uids)
        objects=projected(self.editor.w) if self.editor else {}
        for uid,group in self.groups.items():
            o=objects.get(uid)
            for item in group.childItems():
                if item.data(1) not in ('instance_outline','interface'):item.setVisible(self.internal.isChecked() or not o or o.kind not in ('inst','mosaic'))
                if isinstance(item,NativeFigureItem):
                    item.patterned=self.pattern.isChecked()
                    visible=(item.data(1)=='interface' or self.internal.isChecked() or not o or o.kind not in ('inst','mosaic')) and (self.cuts.isChecked() or not item.style['is_cut'])
                    item.setVisible(visible);item.update()
        if self.editor:self.refresh_workspace_overlay()

    def local_refresh(self,changed):
        blocker=QSignalBlocker(self.scene)
        previous=getattr(self,'_visible_objects',{})
        objects=projected(self.editor.w);self._visible_objects=objects
        changed=affected_owners(changed,self.groups,objects,
            sources=(self.editor.w.baseline.objects,previous),text_owners=self.editor.w.baseline.text_owners)
        if changed:
            from .display_translation import instance_translations
            self.canvas.invalidate_preview(changed,translations=instance_translations(previous,objects,changed,self.editor.w.baseline,self.groups))
        old_index=self.scene.itemIndexMethod()
        bulk_remove=sum(uid in self.groups and uid not in objects for uid in changed)>=512
        if bulk_remove:self.scene.setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        try:self.refresh_graphics(changed,objects)
        finally:
            if bulk_remove:self.scene.setItemIndexMethod(old_index)
        self.extend_scene_bounds(changed)
        del blocker
        self.diagnostics.refresh_objects(changed)
        self.refresh_workspace_overlay()
        if hasattr(self,'workspace_panel'):self.workspace_panel.refresh()
        if hasattr(self,'region_panel'):self.region_panel.refresh()
        self.status.setText(f'{self.editor.w.baseline.cell} · {len(self.editor.w.operations)} 项本地变更 · 尚未同步' if self.editor.w.operations else f'{self.editor.w.baseline.cell} · 无待同步变更')

    def refresh_graphics(self,changed,objects):
        from .presentation.layout_scene import refresh_graphics
        return refresh_graphics(self,changed,objects)

    def extend_scene_bounds(self,owners):
        if not owners:return
        bounds=self.scene.sceneRect()
        deferred=getattr(self,'_deferred_graphics',set())
        from .regions.query import object_bounds
        from .geometry_paths import box_rect
        for uid in owners:
            if uid in deferred:
                # Hidden Qt items deliberately retain their old pose. Camera
                # extents must still follow the committed model immediately.
                obj=self._visible_objects.get(uid)
                current=object_bounds(self.editor.w,obj,self.editor.profile) if obj else None
                rect=box_rect(current) if current is not None else None
            else:rect=self.groups[uid].selection_rect() if uid in self.groups else None
            if rect is not None:bounds=bounds.united(rect)
        self.scene.setSceneRect(bounds)

    def selected(self):
        if self._painting:return
        items=self.scene.selectedItems()
        if not self.editor:return
        uid=items[0].data(0) if items else None
        self.diagnostics.set_selected(uid if uid in projected(self.editor.w) else None,reload=not hasattr(self,'human'))
        if hasattr(self,'workspace_panel'):self.workspace_panel.refresh()
        if hasattr(self,'region_panel'):
            self.region_panel.refresh_selection()
            if uid and (uid in self.editor.w.local_data.regions or uid in self.editor.w.local_data.markups or uid in self.editor.w.local_data.keepouts):
                self.region_panel.selected_id=uid;self.region_panel.refresh_details()
                self.region_panel.policy.select_id(uid)
        if hasattr(self,'human'):self.human.refresh_selection()
        self.diagnostics.set_discard_enabled(not self.busy and bool(self.editor) and self.editor.w.state not in ('submitting','indeterminate','conflict') and not self.editor.work_sessions.snapshots())
        if hasattr(self,'selection_ui'):self.selection_ui.selection_changed()
        self.view_state_changed.emit()

    def selected_uids(self):
        if not self.editor:return []
        objects=projected(self.editor.w);owners=self.editor.w.baseline.text_owners
        return sorted({owners.get(item.data(0),item.data(0)) for item in self.scene.selectedItems()
                       if owners.get(item.data(0),item.data(0)) in objects})

    def select_uid(self,uid):
        with QSignalBlocker(self.scene):
            self.scene.clearSelection()
            if uid in self.groups:
                for part in self.groups[uid].parts.values():part.setSelected(True)
        # Panel/API selection intentionally blocks scene signals; request the
        # same overlay repaint explicitly after the complete selection change.
        self.canvas.refresh_selection()

    def locate_selected(self):
        owner=self.groups.get(self.diagnostics.selected_uid)
        if not owner:return
        rect=owner.selection_rect()
        if rect is not None:
            margin=max(rect.width(),rect.height(),1000)*.2
            self.canvas.fitInView(rect.adjusted(-margin,-margin,margin,margin),Qt.AspectRatioMode.KeepAspectRatio)

    def fit(self):
        if self.editor and self.editor.scope_id in self.editor.w.local_data.regions and hasattr(self,'region_panel'):
            self.region_panel.fit_region(self.editor.scope_id);return
        from .camera import displayed_bounds,fit_bounds
        bounds=displayed_bounds(self)
        if not bounds.isEmpty():
            self.scene.setSceneRect(bounds);fit_bounds(self.canvas,bounds)
            self.refresh_workspace_overlay()

    def pull(self,checked=False,*,fresh=False):
        return self.communication.pull(checked,fresh=fresh)

    def show_circuit(self):
        if not self.editor:return
        from .circuit.panel import CircuitDialog
        from shiboken6 import isValid
        try:
            previous=getattr(self,'circuit_dialog',None)
            if previous is not None and isValid(previous):
                if previous.same_source(self.editor.w,self.editor.profile):
                    if previous.isMinimized():previous.showNormal()
                    else:previous.show()
                    previous.raise_();previous.activateWindow();return
                previous.close();previous.deleteLater()
            dialog=CircuitDialog(self.editor.w,self,profile=self.editor.profile)
            self.circuit_dialog=dialog
            dialog.show()
        except LiteError as exc:
            self.error((str(exc),traceback.format_exc()))

    def sync(self):
        return self.communication.sync()

    def reconcile(self):
        return self.communication.reconcile()

    def open_native(self):
        return self.communication.open_native()


    def save_local(self):
        return self.workspace_controller.save_local()

    def save_document(self,path):
        return self.workspace_controller.save_document(path)

    def open_document(self,path,*,backup_current=True):
        return self.workspace_controller.open_document(path, backup_current=backup_current)

    def save_document_dialog(self):
        return self.workspace_controller.save_document_dialog()

    def open_document_dialog(self):
        return self.workspace_controller.open_document_dialog()

    def undo(self,redo):
        if self.busy or not self.editor:return
        if hasattr(self,'human'):self.human.cancel()
        if self.canvas.selection_ui:self.canvas.selection_ui.cancel()
        before={o.uid for o in self.editor.w.operations}
        try:self.editor.redo() if redo else self.editor.undo()
        except LiteError as exc:self.status.setText(str(exc));return
        self.local_refresh(before|{o.uid for o in self.editor.w.operations}|set(self.editor.w.guard_previews))
        self.save_local()

    def discard(self):
        if self.busy or not self.editor:return
        from uuid import uuid4
        self.editor.w.save(ROOT/'artifacts/lite/drafts'/f'{self.editor.w.id}-{uuid4().hex[:8]}.json')
        changed={o.uid for o in self.editor.w.operations};self.editor.discard();self.local_refresh(changed);self.save_local()

    def closeEvent(self,event):
        if getattr(self,'process_configuration_open',False):
            self.status.setText('请先关闭工艺配置窗口。');event.ignore();return
        if self.busy or (self.job and self.job.isRunning()):self.status.setText('操作尚未结束，请等待完成后关闭。');event.ignore();return
        if hasattr(self,'agent_hub'):self.agent_hub.close()
        if hasattr(self,'routing_workbench'):self.routing_workbench.shutdown()
        elif hasattr(self,'routing_panel'):self.routing_panel.shutdown()
        if hasattr(self,'guard_panel'):self.guard_panel.cancel_draw()
        if hasattr(self,'drc'):self.drc.timer.stop();self.drc.activity.timer.stop()
        self.save_local()
        if self._editor_unsubscribe:self._editor_unsubscribe();self._editor_unsubscribe=None
        if self._work_unsubscribe:self._work_unsubscribe();self._work_unsubscribe=None
        if hasattr(self,'inspection'):self.inspection.close()
        if hasattr(self,'shortcuts'):self.shortcuts.close()
        if hasattr(self,'selection_ui') and not self.selection_ui._closed:self.selection_ui.close()
        from .app_identity import clear_window
        clear_window(self)
        event.accept()


def main():
    from .diagnostics import install
    install()
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path);parser.add_argument('--profile',type=Path);parser.add_argument('--capture',type=Path);parser.add_argument('--no-persist',action='store_true',help='QA only: do not replace the user draft');parser.add_argument('--maximized',action='store_true')
    args=parser.parse_args();app=QApplication([]);app.setStyle('Fusion')
    from .app_identity import configure_application
    configure_application(app)
    w=None;p=None
    wp=args.workspace or ROOT/'artifacts/lite/user-workspace.json';pp=args.profile or ROOT/'artifacts/lite/user-profile.json'
    if not wp.exists():wp=ROOT/'artifacts/lite/default-workspace.json';pp=ROOT/'artifacts/lite/default-profile.json'
    if wp.exists() and pp.exists():w=Workspace.model_validate_json(wp.read_text(encoding='utf-8'));p=TechnologyProfile.model_validate_json(pp.read_text(encoding='utf-8'))
    window=Window(w,p,persist=not args.no_persist);window.showMaximized() if args.maximized else window.show()
    if args.capture:
        args.capture.parent.mkdir(parents=True,exist_ok=True)
        QTimer.singleShot(800,lambda:window.grab().save(str(args.capture)))
    app.exec()


if __name__=='__main__':main()

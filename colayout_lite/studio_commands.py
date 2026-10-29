"""Human UI commands. Thin adapters to the existing shared editor/controllers."""
from PySide6.QtCore import QObject,QSignalBlocker
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLineEdit,QDialogButtonBox,QLabel,QApplication
from .human_edit import HumanEdit
from .studio_icons import icon


class StudioCommands(QObject):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.actions={};self.rules={}
        self.add('open','打开工作区…',window.open_document_dialog,'open',idle=True)
        self.add('save','保存',self.save,'save')
        self.add('save_as','另存为…',window.save_document_dialog,'save')
        self.add('import','从 Virtuoso 重新导入…',self.import_dialog,'import',idle=True)
        for key,text,button,glyph in [('sync','写入 Virtuoso',window.sync_button,'sync'),('refresh','读取服务器',window.pull_button,'import'),
                ('native','在 Virtuoso 中打开',window.native_button,'open'),('recover','核对未完成同步',window.recover_button,'check'),
                ('fork','保留草稿另建副本',window.fork_button,'copy'),('circuit','原理图参考',window.circuit_button,'circuit'),
                ('process','工艺库设置',window.process_button,'settings')]:
            self.add(key,text,button.click,glyph,enabled=button.isEnabled,idle=key in ('sync','refresh','recover','fork','process'))
        self.actions['refresh'].setIconText('读取')
        self.actions['sync'].setIconText('写入')
        self.add('fit','适合窗口',window.fit,'fit')
        self.add('up','返回上层',lambda:window.region_panel.navigate(window.region_panel.up),'up',enabled=lambda:bool(window.editor.scope_id))
        self.add('undo','撤销',lambda:window.undo(False),'undo',enabled=lambda:window.undo_button.isEnabled())
        self.add('redo','重做',lambda:window.undo(True),'redo',enabled=lambda:window.redo_button.isEnabled())
        for mode,text in [('region','操作区'),('markup','定位框'),('keepout','禁布区')]:
            self.add(mode,text,lambda m=mode:self.draw(m),mode,
                enabled=self.can_guide if mode=='markup' else self.can_edit_scope)
        for key,text,glyph in [('rotate','旋转 90°','rotate'),('mirror_h','左右镜像','mirror'),('mirror_v','上下镜像','mirror'),('delete','删除','delete')]:
            self.add(key,text,lambda k=key:window.human.command(k),glyph,enabled=lambda k=key:self.can_transform(k))
        self.add('dissolve','解散操作区',window.selection_ui.dissolve_selected,'region',enabled=lambda:window.selection_ui.dissolve_button.isEnabled())
        self.add('copy_id','复制 ID',self.copy_ids,'copy',enabled=lambda:bool(self.copy_targets()))
        self.add('shortcuts','快捷键设置',window.shortcuts.edit,'settings')
        self.add('activity','操作记录与错误详情',window.activity.show,'more')
        from .region_tools import target_region
        region_ready=lambda:bool(target_region(window)) and not window.drc.job_id
        self.add('drc','操作区 DRC…',self.show_drc,'check',enabled=region_ready)
        self.add('region_drc_local','操作区 · 本地 DRC',lambda:self.check_region('local'),'check',enabled=region_ready)
        self.add('region_drc_remote','操作区 · 服务器全规则 DRC',lambda:self.check_region('calibre'),'check',enabled=region_ready)
        self.add('clear_net','清除网络高亮',window.inspection.clear_trace,'inspect')
        self.add('autoroute','自动布线',self.show_routing,'route')
        from .agent_tools.app import toggle as show_agent
        self.add('agent_api','Agent',lambda:show_agent(window),'inspect')
        from .reference_cases_panel import show as show_cases
        self.add('reference_cases','参考案例库…',lambda:show_cases(window),'circuit')
        self.add('guard','保护环',self.show_guard,'region',enabled=self.can_edit_scope,idle=True)
        self.add('rectangle','矩形',self.show_rectangle,'rectangle',enabled=self.can_edit_scope)
        for key in ('agent_api','autoroute'):self.actions[key].setCheckable(True)
        self.refresh()

    def add(self,key,text,callback,glyph,*,enabled=lambda:True,idle=False):
        action=QAction(icon(glyph),text,self);action.setObjectName('studioAction_'+key)
        action.setProperty('iconName',glyph)
        action.triggered.connect(lambda checked=False,k=key,cb=callback:self.invoke(k,cb))
        self.actions[key]=action;self.rules[key]=(enabled,idle);return action

    def invoke(self,key,callback):
        self.refresh()
        if not self.actions[key].isEnabled():return
        try:callback()
        except Exception as exc:self.window.status.setText(str(exc))
        self.window.view_state_changed.emit()

    def refresh(self):
        w=self.window;e=w.editor
        active=bool(e and getattr(e,'work_sessions',None) and e.work_sessions.snapshots())
        for key,action in self.actions.items():
            if key=='rotate':action.setText('旋转 90° · '+w.shortcuts.values['rotate'])
            enabled,idle=self.rules[key]
            remote_ok=getattr(w,'remote_enabled',True) or key not in ('sync','refresh','import','native','recover','fork','region_drc_remote','guard')
            action.setEnabled(bool(e and not w.busy and remote_ok and (not idle or not active) and enabled()))
            hint='请先结束操作区内的 Agent 任务。' if idle and active else action.text()
            if key in ('sync','refresh') and not active:
                hint=('将当前本地修改写入 Virtuoso，并读回核对。' if key=='sync' else
                      '从 Virtuoso 读取最新数据，保留本地层次；有待同步修改时不可读取覆盖。')
            if e and key in ('region','markup','keepout','rectangle','guard'):
                if e.w.state in ('submitting','indeterminate','conflict'):
                    hint={
                        'submitting':'同步正在提交，完成或核对结果后可继续创建和编辑。',
                        'indeterminate':'上次同步结果尚未核对，创建和编辑暂时锁定。请使用“文件 → 核对未完成同步”；草稿保留。',
                        'conflict':'本地草稿与服务器存在冲突，创建和编辑暂时锁定。请先备份并处理冲突或重新导入。',
                    }[e.w.state]
                elif key!='markup' and e.work_sessions.readonly_reason(scope_id=e.scope_id):
                    hint=e.work_sessions.readonly_reason(scope_id=e.scope_id)
            shortcut=w.shortcuts.values.get(key)
            action.setToolTip(hint+(f' · {shortcut}' if shortcut else ''))
        self.refresh_panel_checks()

    def refresh_panel_checks(self):
        w=self.window;hub=getattr(w,'agent_hub',None)
        agent_dock=getattr(hub,'dock',None)
        from .autoroute.workbench import selected_region
        routing=getattr(w,'routing_workbench',None)
        panel=routing.panels.get((id(w.editor),selected_region(w))) if routing else None
        for key,dock in (('agent_api',agent_dock),('autoroute',panel.dock if panel else None)):
            with QSignalBlocker(self.actions[key]):self.actions[key].setChecked(bool(dock and not dock.isHidden()))

    def can_edit_scope(self):
        e=self.window.editor
        return bool(e and e.w.state not in ('submitting','indeterminate','conflict') and
            not e.work_sessions.readonly_reason(scope_id=e.scope_id))

    def can_guide(self):
        e=self.window.editor
        return bool(e and e.w.state not in ('submitting','indeterminate','conflict'))

    def can_transform(self,command):
        w=self.window;ids=w.human.ids()
        if not ids or w.human.pin_selected or w.editor.w.state in ('submitting','indeterminate','conflict'):return False
        try:
            if command=='delete':
                for uid in ids:HumanEdit(w.editor).deletion_kind(uid)
                return True
            kinds=[HumanEdit(w.editor).kind(uid) for uid in ids]
            if not all(k in ('instance','area','mpp') for k in kinds):return False
            return all(not w.editor.work_sessions.readonly_reason(uid,action='transform' if command!='delete' else 'edit') for uid in ids)
        except Exception:return False

    def draw(self,mode):
        self.window.region_panel.start_draw(mode)
        self.window.status.setText(self.window.region_panel.message.text())
        self.window.canvas.setFocus()

    def save(self):
        if hasattr(self.window,'save_user_document'):self.window.save_user_document()
        else:
            self.window.save_local();self.window.status.setText('工作区已保存。')

    def copy_targets(self):
        w=self.window;ids=w.human.ids();focus=w.inspection
        pin=w.human.pin_selected or ((focus.focus_region,focus.focus_pin_id) if not ids else None)
        if pin:
            region=w.editor.w.local_data.regions.get(pin[0])
            if region and pin[1] in region.pins and (region.id==w.editor.scope_id or region.parent_id==w.editor.scope_id):return [pin[1]]
        return ids

    def copy_ids(self):
        w=self.window;ids=self.copy_targets()
        QApplication.clipboard().setText('\n'.join(ids));w.status.setText(f'已复制 {len(ids)} 个对象 ID。')

    def show_drc(self):
        self.check_region()

    def check_region(self,engine=None,region_id=None):
        from .region_tools import check_region
        check_region(self.window,engine,region_id)

    def show_routing(self):
        from .autoroute.panel import show
        from .autoroute.workbench import selected_region
        w=self.window;host=getattr(w,'routing_workbench',None)
        panel=host.panels.get((id(w.editor),selected_region(w))) if host else None
        if panel and not panel.dock.isHidden():panel.dock.close()
        else:show(w)

    def show_guard(self):
        from .guard_panel import show
        show(self.window)

    def show_rectangle(self):
        from .rectangle_panel import show
        show(self.window)

    def import_dialog(self):
        w=self.window;dialog=QDialog(w);dialog.setWindowTitle('从 Virtuoso 导入')
        layout=QVBoxLayout(dialog);note=QLabel('重新导入服务器的版图与配对原理图。本地操作区、PIN、标注和未提交编辑会完整保留在备份中，新导入的工作区从服务器状态开始。\n若希望继续保留本地组织，请使用“刷新（保留本地层次）”。');note.setWordWrap(True);layout.addWidget(note)
        form=QFormLayout();library=QLineEdit(w.library.text());cell=QLineEdit(w.cell.text())
        form.addRow('库',library);form.addRow('Layout 单元',cell);layout.addLayout(form)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('导入');layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject)
        if w.idle_dialog(dialog)==QDialog.DialogCode.Accepted:
            if not library.text().strip() or not cell.text().strip():raise ValueError('库与单元名称不能为空。')
            w.library.setText(library.text().strip());w.cell.setText(cell.text().strip());w.pull(fresh=True)

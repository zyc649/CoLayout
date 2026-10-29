"""On-demand human routing panel; preview paint never becomes editable geometry."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,Signal,QRectF,QSignalBlocker
from PySide6.QtGui import QColor,QPen,QFont
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QListWidget,QListWidgetItem,
    QTableWidget,QTableWidgetItem,QAbstractItemView,QHeaderView,QPlainTextEdit,QFileDialog,QDockWidget,QCheckBox)
from ..model import LiteError
from ..paths import ROOT
from ..drc import config
from ..inspection_view import polygon_path
from ..theme import palette
from .plugins import Registry
from .service import RoutingSession
from collections import OrderedDict
from .preview_display import PreviewDrawing
from .activity import RoutingActivity,blocked_reason


def failure_text(failures):
    lines=[]
    for failure in failures:
        detail=failure.get('details',{})
        while isinstance(detail,dict) and 'details' in detail:detail=detail['details']
        code=failure.get('code','');message=failure.get('message','未完成')
        if code=='ROUTING_PIN_LAYER_UNSUPPORTED':message='部分端口没有所选金属层的接入。请勾选端口所在金属层及所需的中间过孔层，或先手动引出。'
        elif code=='ROUTING_TIMEOUT':message='计算超时；可尝试其他算法，或缩小操作区。'
        elif code=='ROUTING_EXISTING_SHORT':message='已有导体连接了不同网络，请先修复短接。'
        elif code:message=message.replace(code+': ','')
        lines.append(failure.get('algorithm',{}).get('name','检查')+'：'+message)
        if isinstance(detail,dict):
            if detail.get('selected_layers'):lines.append('  当前布线层：'+' / '.join(detail['selected_layers']))
            if detail.get('nets'):lines.append('  网络：'+' / '.join(detail['nets']))
            for short in detail.get('shorts',[]):lines.append('  短接网络：'+' / '.join(short['nets']))
            if detail.get('missing_nets'):lines.append('  缺少区域接口：'+' / '.join(detail['missing_nets']))
            for pin in detail.get('pins',[]):
                lines.append(f'  {pin["name"]} · {pin["net"]} · {"/".join(pin["layers"])}')
    return '\n'.join(lines)


class RoutingPanel(QWidget):
    progress=Signal(str,str)

    def __init__(self,window,*,registry_path=None,job_root=None,workbench=None,region_id=None):
        super().__init__(window);self.window=window;self.session=None;self.future=None;self._closed=False;self._running_session=None;self._applying=False
        self.workbench=workbench;self.region_id=region_id;self.editor_context=window.editor;self.region_name=''
        self.dock=None;self.preview=None;self._recheck_previous=None;self.exposed=False;self._preview_requested=False
        self.registry=Registry(registry_path or ROOT/'config/router-plugins.json');self.job_root=job_root or ROOT/'artifacts/autoroute/jobs'
        self.executor=workbench.executor if workbench else ThreadPoolExecutor(max_workers=1,thread_name_prefix='routing-host')
        self.paths=[];self.drawing=None;self._preview_cache=OrderedDict();self.preview_key=None;self.current_id=None;self._view_key=None;self.resume=lambda:None
        self.setObjectName('routingPanel');layout=QVBoxLayout(self);layout.setContentsMargins(14,12,14,12)
        self.region_label=QLabel();self.region_label.setWordWrap(True);layout.addWidget(self.region_label)
        self.return_button=QPushButton('返回此操作区');self.return_button.clicked.connect(self.return_to_region);layout.addWidget(self.return_button)
        self.scope_note=QLabel('所选金属层＋已验证标准过孔 · 最多 64 个当层器件/子模块\n保留已有布线，只生成新增连线；接口位置不变。')
        self.scope_note.setWordWrap(True);layout.addWidget(self.scope_note)
        layout.addWidget(QLabel('允许布线的金属层'))
        self.layer_box=QWidget();self.layer_row=QHBoxLayout(self.layer_box);self.layer_row.setContentsMargins(0,0,0,0)
        self.layer_checks={};self._layer_key=None;layout.addWidget(self.layer_box)
        layout.addWidget(QLabel('选择算法（可多选）'))
        self.algorithms=QListWidget();self.algorithms.setMaximumHeight(125);self.algorithms.setToolTip('内置和导入的算法均返回候选，由 CoLayout 独立检查。')
        layout.addWidget(self.algorithms)
        row=QHBoxLayout();layout.addLayout(row)
        self.import_button=QPushButton('加入算法…');self.remove_button=QPushButton('移除登记');row.addWidget(self.import_button);row.addWidget(self.remove_button)
        self.import_button.clicked.connect(self.import_plugin);self.remove_button.clicked.connect(self.remove_plugin)
        hint=QLabel('插件清单不会执行代码；生成时运行勾选的本机插件。请仅使用可信插件。')
        hint.setWordWrap(True);layout.addWidget(hint)
        row=QHBoxLayout();layout.addLayout(row)
        self.generate_button=QPushButton('生成候选');self.cancel_button=QPushButton('取消计算')
        self.generate_button.setObjectName('routingGenerate');self.cancel_button.setObjectName('routingCancel')
        row.addWidget(self.generate_button);row.addWidget(self.cancel_button)
        self.generate_button.clicked.connect(self.generate);self.cancel_button.clicked.connect(self.cancel)
        self.activity=RoutingActivity(self);self.message=self.activity.message;layout.addWidget(self.activity)
        self.recovery_box=QWidget();recovery=QHBoxLayout(self.recovery_box);recovery.setContentsMargins(0,0,0,0)
        self.recover_button=QPushButton('核对同步');self.reimport_button=QPushButton('备份后重新导入…')
        recovery.addWidget(self.recover_button);recovery.addWidget(self.reimport_button);layout.addWidget(self.recovery_box)
        self.recover_button.clicked.connect(window.reconcile)
        self.reimport_button.clicked.connect(lambda:window.studio.commands.import_dialog())
        self.progress.connect(self.on_progress)
        self.results=QTableWidget(0,4);self.results.setObjectName('routingCandidates')
        self.results.setHorizontalHeaderLabels(['方案 / 算法来源','连通','线长 / 过孔','检查'])
        self.results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        for i in range(1,4):self.results.horizontalHeader().setSectionResizeMode(i,QHeaderView.ResizeMode.ResizeToContents)
        self.results.verticalHeader().hide();self.results.setMinimumHeight(180);layout.addWidget(self.results,1)
        self.results.itemSelectionChanged.connect(self.choose)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(170);layout.addWidget(self.details)
        row=QHBoxLayout();layout.addLayout(row)
        self.apply_button=QPushButton('采用所选方案');self.apply_button.setObjectName('routingApply')
        self.clear_button=QPushButton('隐藏预览');row.addWidget(self.apply_button);row.addWidget(self.clear_button)
        self.apply_button.clicked.connect(self.apply);self.clear_button.clicked.connect(self.hide_preview)
        self.discard_button=QPushButton('丢弃结果');self.discard_button.setObjectName('routingDiscard');row.addWidget(self.discard_button)
        self.discard_button.clicked.connect(self.discard)
        self.timer=QTimer(self);self.timer.setInterval(80);self.timer.timeout.connect(self.poll)
        self.reload_plugins()
        if not workbench:window.canvas.routing_overlay=self.paint
        window.view_state_changed.connect(self.refresh);self.refresh()

    def on_progress(self,ident,message):
        if self.session and self.session.id==ident and self.future is not None:
            self.activity.title.setText('正在重新检查' if self._recheck_previous else '正在生成候选');self.message.setText(message)

    def clear_review(self,message='请选择当前操作区并重新生成候选。'):
        if self.session and not self.session.applied:self.session.cancelled.set()
        if self.future and self.future.cancel():self.timer.start()
        self._recheck_previous=None
        self._preview_requested=False
        self.clear_preview();self._preview_cache.clear();self.session=None;self.current_id=None;self._view_key=None
        with QSignalBlocker(self.results):self.results.setRowCount(0)
        self.details.clear();self.apply_button.setEnabled(False);self.discard_button.setEnabled(False)
        if self.future:
            self.activity.title.setText('正在停止计算');self.message.setText(message)
        else:self.activity.reset(message)

    def selected_layers(self):return tuple(k for k,v in self.layer_checks.items() if v.isChecked())

    def load_layers(self):
        if self.session is not None:return
        e=self.editor_context;drc=getattr(self.window.drc,'profile',None)
        key=(id(e.profile) if e else None,id(drc))
        if key==self._layer_key:return
        self._layer_key=key
        for c in self.layer_checks.values():self.layer_row.removeWidget(c);c.deleteLater()
        self.layer_checks={}
        if not e or not drc:return
        from .layers import capabilities
        caps=capabilities(e.profile,drc)
        for row in caps['layers']:
            c=QCheckBox(row['layer']);c.setEnabled(row['supported']);c.setChecked(row['layer'] in caps['default_layers'])
            c.setToolTip(f'默认线宽：{row["default_width_um"]:g} µm。未选择的层不会生成布线。' if row['supported'] else '缺少规则：'+', '.join(row['missing_rules']))
            c.toggled.connect(self.layers_changed);self.layer_row.addWidget(c);self.layer_checks[row['layer']]=c

    def layers_changed(self):
        self.clear_review('布线层已改变，请重新生成候选。');self.refresh()

    def reload_plugins(self):
        selected={self.algorithms.item(i).data(Qt.ItemDataRole.UserRole)['id'] for i in range(self.algorithms.count())
                  if self.algorithms.item(i).checkState()==Qt.CheckState.Checked}
        self.algorithms.clear()
        for row in self.registry.list():
            item=QListWidgetItem(('内置 · ' if row['builtin'] else '插件 · ')+row['name']+' '+row.get('version',''))
            item.setData(Qt.ItemDataRole.UserRole,row);item.setToolTip(row.get('error') or row.get('description',''))
            if row.get('error'):
                item.setFlags(Qt.ItemFlag.ItemIsSelectable|Qt.ItemFlag.ItemIsEnabled);item.setText(item.text()+'（不可用）')
            else:
                item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if row['id'] in (selected or {'builtin.astar','builtin.pattern'}) else Qt.CheckState.Unchecked)
            self.algorithms.addItem(item)

    def import_plugin(self):
        path,_=QFileDialog.getOpenFileName(self,'加入自动布线算法','','算法清单 (*.json)')
        if not path:return
        try:
            self.registry.register(path);self.reload_plugins();self.message.setText('算法已登记。勾选后点击生成；未执行插件代码。')
        except Exception as exc:self.message.setText(str(exc))

    def remove_plugin(self):
        item=self.algorithms.currentItem()
        if item and not item.data(Qt.ItemDataRole.UserRole)['builtin']:
            self.registry.remove(item.data(Qt.ItemDataRole.UserRole)['manifest_path']);self.reload_plugins()
            self.message.setText('仅移除了登记，插件文件保留。')

    def target(self):
        from .workbench import selected_region
        return self.region_id or selected_region(self.window)

    def return_to_region(self):
        if self.window.editor is not self.editor_context:return
        region=self.target()
        if region in self.editor_context.w.local_data.regions:
            self.window.region_panel.activate_uid(region);self.restore_preview()

    def owns_preview(self):
        return self.preview is not None and self.window.inspection.preview is self.preview

    def can_show_preview(self):
        """Separate explicit tool hiding/tab choice from native exposure events.

        Qt can report a top-level exposure transition while an un-tabbed dock
        remains explicitly open. That must not suppress a requested preview.
        Background completion behind another tool tab still stays unobtrusive.
        """
        if self.dock is None:
            return True
        if self.dock.isHidden():
            return False
        if self.exposed or self.owns_preview():
            return True
        return not any(not peer.isHidden()
                       for peer in self.window.tabifiedDockWidgets(self.dock))

    def restore_preview(self):
        e=self.window.editor
        if self._preview_requested and self.session and self.current_id and e is self.editor_context and e.scope_id==self.target() and not self.future:
            self.choose()

    def refresh(self):
        w=self.window;e=w.editor
        self.load_layers()
        key=(id(e),id(e.w) if e else None,e.scope_id if e else None,w.busy,self.target(),bool(self.future),self.current_id,
             id(getattr(w.drc,'profile',None)),self.selected_layers())
        if key==self._view_key:return
        self._view_key=key
        target=self.target()
        valid=bool(self.session and not self.session.cancelled.is_set() and self.session.current(e,getattr(w.drc,'profile',None)))
        if self.preview and (not valid or e.scope_id!=self.target()):self.clear_preview()
        region=e.w.local_data.regions.get(target) if e and e is self.editor_context else None
        if region:self.region_name=region.name
        self.region_label.setText('操作区：'+(self.region_name or '请选择操作区'))
        self.return_button.setVisible(bool(region and e.scope_id!=target))
        self.return_button.setEnabled(not w.busy)
        reason=blocked_reason(w,target,self.selected_layers()) if e is self.editor_context else '此任务属于先前的工作区，结果保留供查看。'
        editable=not reason
        self.generate_button.setEnabled(editable and self.future is None and self.session is None)
        self.generate_button.setToolTip(reason or ('请先丢弃已有结果再重新生成' if self.session else '为此操作区生成并检查候选方案'))
        recovery=bool(e and e.w.state in ('submitting','indeterminate','conflict'))
        self.recovery_box.setVisible(recovery)
        self.recover_button.setEnabled(not w.busy and w.recover_button.isEnabled())
        self.reimport_button.setEnabled(not w.busy and bool(e) and not e.work_sessions.snapshots() and getattr(w,'remote_enabled',True))
        if reason and self.future is None and self.session is None:
            self.activity.finish('blocked','当前不能开始布线',reason)
            if recovery and e.w.last_result.get('error'):self.details.setPlainText('上次同步原因：\n'+e.w.last_result['error'])
        elif self.activity.outcome=='blocked':
            self.activity.reset('可以生成候选。');self.details.clear()
        self.layer_box.setEnabled(self.future is None and self.session is None and editable)
        self.cancel_button.setEnabled(self.future is not None)
        self.algorithms.setEnabled(self.future is None and self.session is None);self.import_button.setEnabled(self.future is None);self.remove_button.setEnabled(self.future is None)
        valid=bool(self.session and not self.session.cancelled.is_set() and self.session.current(e,getattr(w.drc,'profile',None)))
        candidate=self.session.candidates.get(self.current_id) if self.session else None
        self.apply_button.setEnabled(bool(e and e is self.editor_context and e.scope_id==target and editable and candidate and candidate.validation['status']=='ready' and not self.future))
        self.apply_button.setText('采用所选方案' if valid else '重新检查并采用')
        if self.session and not valid and not self.future and not self.session.cancelled.is_set():
            self.message.setText(reason or '版图或规则已改变；结果已保留，采用前会重新检查当前版图。')
        self.discard_button.setEnabled(self.session is not None and self.future is None)
        self.results.setEnabled(self.future is None)
        if self.dock:
            suffix=' · 计算中' if self.future else ' · 结果已保留' if self.session else ''
            self.dock.setWindowTitle((self.region_name+' · ' if self.region_name else '')+'自动布线'+suffix)
        if self._preview_requested and self.can_show_preview() and valid and not self.preview and self.current_id and e.scope_id==target and not self.future:
            self.choose()

    def generate(self):
        if self.future:
            self.window.status.setText('自动布线正在计算；可在面板查看阶段或取消。');return
        w=self.window;target=self.target()
        if w.editor is not self.editor_context:
            self.message.setText('此面板属于先前工作区，请为当前操作区重新打开自动布线。');return
        if self.session:
            self.message.setText('请先丢弃已有结果，再重新生成。');return
        try:
            if reason:=blocked_reason(w,target,self.selected_layers()):
                self.refresh();self.activity.finish('blocked','当前不能开始布线',reason);w.status.setText(reason);return
            drc=config.load(w.editor.profile)
            if drc is None:raise LiteError('ROUTING_RULES_MISSING','请先在工艺库设置中确认本地规则。')
            ids=[self.algorithms.item(i).data(Qt.ItemDataRole.UserRole)['id'] for i in range(self.algorithms.count())
                 if self.algorithms.item(i).checkState()==Qt.CheckState.Checked]
            algorithms=self.registry.resolve(ids)
            if self.workbench:self.workbench.bind(self,target)
            else:self.region_id=target
            if target!=w.editor.scope_id:w.region_panel.activate_uid(target)
            self.clear_review()
            self.activity.start()
            self.session=RoutingSession(w.editor,drc,target,self.job_root,layers=self.selected_layers())
            self.resume=w.editor.work_sessions.suspend_starts('此区域正在计算布线候选，请等待完成或取消后再接入 Agent。',region_id=target)
            session=self.session;self._running_session=session
            self.future=self.executor.submit(session.generate,algorithms,lambda message:self.progress.emit(session.id,message) if not self._closed else None)
            if not self.future.running():self.activity.title.setText('等待执行')
            self.timer.start();self.message.setText('任务已提交；等待执行时可查看其他操作区。');w.status.setText('自动布线已开始，可在面板查看阶段和用时。');self.refresh()
        except Exception as exc:
            if self.future is None:self.resume();self.resume=lambda:None;self._running_session=None
            self.clear_review();self.activity.finish('failed','未能开始',str(exc));w.status.setText('自动布线未能开始：'+str(exc));self.refresh()
            w.activity.record('自动布线未能开始',str(exc))

    def poll(self):
        if self.future is None or not self.future.done():return
        future=self.future;session=self._running_session;self.future=None;self._running_session=None;self.timer.stop();self.resume();self.resume=lambda:None
        if session is not self.session:
            self.activity.finish('cancelled','已停止计算',self.message.text().replace('正在取消计算…','已取消，工作区未修改。'))
            self.window.status.setText('自动布线已停止：'+self.message.text())
            self._view_key=None;self.refresh();return
        try:
            candidates=future.result()
            candidates.sort(key=lambda c:(c.validation['status']!='ready',c.validation['length_um'],c.validation['via_count']))
            self.results.setRowCount(len(candidates))
            for i,c in enumerate(candidates):
                report=c.validation;links=report.get('connectivity') or {}
                sources=' / '.join(dict.fromkeys(('内置 ' if s['builtin'] else '插件 ')+s['name']+' '+s['version'] for s in c.sources))
                values=[f'方案 {i+1} · {c.proposal.title}\n{sources}',f'{links.get("connected_nets",0)}/{links.get("total_nets",0)}',
                        f'{report["length_um"]:.2f} µm\n{report["via_count"]} 个孔',{'ready':'通过','partial':'未布通','invalid':'未通过'}[report['status']]]
                for j,value in enumerate(values):
                    item=QTableWidgetItem(value);item.setData(Qt.ItemDataRole.UserRole,c.id)
                    self.results.setItem(i,j,item)
                self.results.setRowHeight(i,52)
            ready=sum(c.validation['status']=='ready' for c in candidates)
            self.activity.finish('ready' if ready else 'partial' if candidates else 'failed',
                '计算完成' if ready else '没有可采用的方案',
                f'{len(candidates)} 个不同方案，{ready} 个检查通过。'+('选择方案可在画布预览。' if candidates else '请查看下面的失败原因。'))
            if self.session.failures:self.message.setText(self.message.text()+f' {len(self.session.failures)} 个算法/阶段失败，原因见下方。')
            if candidates:self.results.selectRow(0)
            else:self.details.setPlainText(failure_text(self.session.failures) or '所选算法没有返回候选。可尝试其他算法，或调整布线层和区域。')
        except Exception as exc:
            self.activity.finish('failed','生成失败',str(exc));self.details.setPlainText(failure_text(self.session.failures) or str(exc))
        self.window.status.setText(self.region_name+' · 自动布线：'+self.activity.title.text()+' · '+self.message.text())
        self.window.activity.record('自动布线：'+self.activity.title.text(),self.message.text()+'\n'+self.details.toPlainText())
        self._view_key=None;self.refresh()
        if self._recheck_previous is not None:
            previous=self._recheck_previous;self._recheck_previous=None
            if self.session and self.session.candidates:
                candidate=self.session.candidates.get(self.current_id)
                if candidate and candidate.validation['status']=='ready' and self.session.current(self.window.editor,getattr(self.window.drc,'profile',None)) and self.window.editor.scope_id==self.region_id:self.apply()
            elif self.session is not None:
                message=self.details.toPlainText();self.session,self.current_id=previous
                self.message.setText('重新检查失败，原方案已保留。');self.details.setPlainText(message);self._view_key=None;self.refresh()

    def choose(self):
        rows=self.results.selectedItems()
        if not rows or not self.session:return
        self._preview_requested=True
        self.current_id=rows[0].data(Qt.ItemDataRole.UserRole);c=self.session.candidates[self.current_id];report=c.validation
        labels={p['id']:p['name'] for p in self.session.problem.pins}
        lines=['来源：'+' / '.join(dict.fromkeys(s['name']+' '+s['version'] for s in c.sources)),
               '检查范围：当前层连接及已配置的本地规则；不是服务器 DRC/LVS 签核。']
        if not self.session.problem.coverage.get('via_cut_width_rule_checked'):
            lines.append('过孔：使用工艺冻结的标准尺寸，当前规则集未独立检查 cut 宽度。')
        for row in (report.get('connectivity') or {}).get('nets',[]):
            if not row['connected']:
                names=', '.join(labels.get(pid,pid) for pid in row['unattached']+row['partial'])
                lines.append(f'未完成 {row["net"]}：{len(row["components"])} 个物理分量'+('；待接 '+names if names else ''))
                for part in row.get('components_detail',[])[:8]:
                    lines.append('  '+part['id']+'：'+', '.join(labels.get(pid,pid) for pid in part['pin_ids']))
        for error in report['errors'][:8]:
            reason={'ROUTING_COLLISION':'导体碰撞、间距或禁布约束未通过','ROUTING_UNPROVEN_NET':'导线的实际连接与网络标记不一致',
                'ROUTING_DRC_FAILED':'存在本地规则错误','ROUTING_DRC_INCOMPLETE':'本地规则检查存在未覆盖项',
                'ROUTING_SHORT':'存在短路','ROUTING_CONNECTIVITY_INCOMPLETE':'连接几何信息不完整'}.get(error['code'],error.get('message',error['code']))
            lines.append(reason)
        for marker in (report.get('drc') or {}).get('markers',[])[:6]:
            actual=marker.get('measured_um');required=marker.get('required_um');bounds=marker['bbox'];scale=self.session.problem.dbu_per_micron
            lines.append(f'{"/".join(marker["layers"])} {marker["message"]}：实测 {actual} µm，要求 {required} µm；位置 ({bounds[0][0]/scale:g}, {bounds[0][1]/scale:g})')
        for item in c.proposal.diagnostics:
            if 'code' in item:lines.append(str(item.get('net',''))+'：'+item.get('message',item['code']))
        if self.session.failures:lines.append(failure_text(self.session.failures))
        self.details.setPlainText('\n'.join(lines))
        e=self.window.editor
        if self.session.current(e,getattr(self.window.drc,'profile',None)) and e.scope_id==self.session.region_id and self.can_show_preview():
            from .preview import RoutingPreview
            try:
                priorities={r.name:self.window.styles.get(r.name+'/drawing',{}).get('priority',0) for r in self.session.problem.layers}
                key=(id(e),id(e.w),e.scope_id,c.id,tuple(sorted(priorities.items())))
                cached=self._preview_cache.pop(key,None)
                if cached is None:
                    preview=RoutingPreview(e,self.session,c,layer_priority=priorities)
                    paths=[(layer,polygon_path(g)) for uid,layer,g in preview.all_figures]
                    paths.sort(key=lambda row:self.window.styles.get(row[0]+'/drawing',{}).get('priority',0))
                    cached=(preview,PreviewDrawing(paths))
                preview,self.drawing=cached;self.preview=preview;self.paths=self.drawing.paths
                self._preview_cache[key]=cached
                while len(self._preview_cache)>2:self._preview_cache.popitem(last=False)
                self.window.inspection.set_preview(preview)
                self.preview_key=(id(e),id(e.w),e.scope_id);self.window.canvas.viewport().update()
            except (LiteError,ValueError,KeyError,TypeError) as exc:
                self._preview_requested=False;self.clear_preview();self.message.setText('此候选几何无法预览：'+str(exc))
        self._view_key=None;self.refresh()

    def clear_preview(self):
        if self.owns_preview():self.window.inspection.set_preview(None)
        self.paths=[];self.drawing=None;self.preview_key=None;self.preview=None
        self.window.canvas.viewport().update()

    def hide_preview(self):
        self._preview_requested=False;self.clear_preview()

    def paint(self,painter):
        e=self.window.editor
        if (self.dock and self.dock.isHidden()) or not self.paths or self.preview_key!=(id(e),id(e.w),e.scope_id):return
        colors=palette(self.window.canvas);candidate=self.session.candidates[self.current_id]
        painter.setTransform(self.window.canvas.viewportTransform())
        visible=self.window.canvas.mapToScene(self.window.canvas.viewport().rect()).boundingRect()
        margin=2/max(abs(self.window.canvas.transform().m11()),1e-12)
        self.drawing.paint(painter,visible.adjusted(-margin,-margin,margin,margin),self.window.styles,
            None if candidate.validation['status']=='ready' else colors.net_short)
        painter.resetTransform();painter.setFont(QFont('Microsoft YaHei UI',10));painter.setPen(QColor(colors.local_label))
        badge=QRectF(12,12,310,28);painter.fillRect(badge,QColor(colors.background))
        painter.drawText(badge,Qt.AlignmentFlag.AlignVCenter,'布线候选预览 · 尚未写入工作区')

    def apply(self):
        if not self.session or not self.current_id:return
        if not self.session.current(self.window.editor,getattr(self.window.drc,'profile',None)):
            self.recheck();return
        session=self.session;ident=self.current_id;self._applying=True
        try:
            self.clear_preview()
            result=session.apply(self.window.editor,ident,config.load(self.window.editor.profile))
            message=('方案已采用；可 Ctrl+Z 撤销。再次布线请重新生成候选。' if not result['no_op'] else '当前网络已连通，无需新增导线。')
            if result.get('warning'):message+=' '+result['warning']
            self.clear_review(message);self.window.status.setText(message);self.window.save_local()
            if self.dock:self.dock.hide()
        except Exception as exc:self.message.setText(str(exc))
        finally:self._applying=False;self._view_key=None;self.refresh()

    def recheck(self):
        if self.future or self.window.editor is not self.editor_context:return
        w=self.window;old=self.session;ident=self.current_id
        if w.editor.scope_id!=self.region_id:self.message.setText('请先返回此操作区。');return
        try:
            drc=config.load(w.editor.profile)
            self.session=RoutingSession(w.editor,drc,self.region_id,self.job_root,layers=old.selected_layers)
            self._recheck_previous=(old,ident);self._running_session=self.session
            self.clear_preview();self.activity.start();self.activity.title.setText('正在重新检查')
            self.resume=w.editor.work_sessions.suspend_starts('此区域正在重新检查布线候选。',region_id=self.region_id)
            session=self.session
            self.future=self.executor.submit(session.recheck,old.candidates[ident],lambda message:self.progress.emit(session.id,message) if not self._closed else None)
            self.results.setEnabled(False);self.timer.start();self._view_key=None;self.refresh()
        except Exception as exc:
            self.session=old;self._recheck_previous=None;self.resume();self.resume=lambda:None
            self.activity.finish('failed','重新检查失败',str(exc));self._view_key=None;self.refresh()

    def discard(self):
        if self.future:return
        self.clear_review('结果已丢弃，可以重新生成候选。');self.refresh()

    def cancel(self):
        self.clear_review('正在取消计算…' if self.future else '已取消候选。');self.refresh()

    def shutdown(self):
        self._closed=True;self.cancel();self.timer.stop();self.resume();self.resume=lambda:None
        self.activity.timer.stop()
        if not self.workbench:self.executor.shutdown(wait=False,cancel_futures=True)


class RoutingDock(QDockWidget):
    def __init__(self,window):
        self.owner=window
        super().__init__('自动布线 · 候选方案',window)

    def setVisible(self,visible):
        from ..camera import capture,restore
        state=capture(self.owner.canvas)
        super().setVisible(visible)
        self.owner.layout().activate();restore(self.owner.canvas,state)


def show(window,*,registry_path=None,job_root=None):
    from .workbench import RoutingWorkbench
    if not hasattr(window,'routing_workbench'):window.routing_workbench=RoutingWorkbench(window)
    return window.routing_workbench.open(registry_path=registry_path,job_root=job_root)

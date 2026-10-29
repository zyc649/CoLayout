"""Region DRC controls and a vector-only, non-editable diagnostic overlay."""
import json
from PySide6.QtCore import Qt,QTimer,QRectF,QPointF
from PySide6.QtGui import QColor,QPen,QPainterPath,QDesktopServices
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,
    QLineEdit,QListWidget,QListWidgetItem,QPlainTextEdit,QComboBox,QFileDialog,QCheckBox)
from . import jobs,config
from . import waivers
from .models import Region
from ..render import box_rect
from ..task_activity import TaskActivity


class DrcPanel(QWidget):
    def __init__(self,window):
        super().__init__(window);self.window=window;self.job_id=None;self.result=None;self.profile=None
        self.region=None;self.paths=[];self.selected_id=None;self.stale=False;self._current_key=None;self.bound_region_id=None
        self.waiver_policy=None;self.waived={};self.formal=False;self.engine='local'
        self._starting=False
        layout=QVBoxLayout(self)
        title=QLabel('区域 DRC');self.title=title;title.setStyleSheet('font-size:17px;font-weight:600');layout.addWidget(title)
        self.scope_label=QLabel();self.scope_label.setWordWrap(True);layout.addWidget(self.scope_label)
        self.process=QLabel();self.process.setWordWrap(True);layout.addWidget(self.process)
        self.coordinate_box=QWidget();grid=QGridLayout(self.coordinate_box);grid.setContentsMargins(0,0,0,0);layout.addWidget(self.coordinate_box);self.coords=[]
        for i,label in enumerate(['X min','Y min','X max','Y max']):
            edit=QLineEdit();edit.setPlaceholderText('µm');self.coords.append(edit)
            grid.addWidget(QLabel(label),i//2,i%2*2);grid.addWidget(edit,i//2,i%2*2+1)
            edit.editingFinished.connect(self.update_region)
        row=QHBoxLayout();layout.addLayout(row)
        self.pick=QPushButton('框选检查区域');self.pick.setCheckable(True);row.addWidget(self.pick)
        self.pick.toggled.connect(self.pick_region)
        self.view_region=QPushButton('使用当前视野');row.addWidget(self.view_region);self.view_region.clicked.connect(self.from_view)
        note=QLabel('坐标单位 µm。边界外自动保留上下文；只返回与所选区域相交的错误。服务器检查使用当前草稿的私有副本。');self.note=note
        note.setWordWrap(True);layout.addWidget(note)
        row=QHBoxLayout();layout.addLayout(row)
        self.local_button=QPushButton('本地轻量检查');self.remote_button=QPushButton('服务器全规则')
        row.addWidget(self.local_button);row.addWidget(self.remote_button)
        self.local_button.clicked.connect(lambda:self.start('local'));self.remote_button.clicked.connect(lambda:self.start('calibre'))
        self.run_button=QPushButton('开始检查');self.run_button.setObjectName('drcRun');self.run_button.clicked.connect(lambda:self.start(self.engine));layout.addWidget(self.run_button);self.run_button.hide()
        self.more_results=QPushButton('提高结果上限并重新检查');self.more_results.setObjectName('drcMoreResults')
        self.more_results.clicked.connect(self.retry_more_results);layout.addWidget(self.more_results);self.more_results.hide()
        row=QHBoxLayout();layout.addLayout(row)
        self.cancel_button=QPushButton('取消任务');self.cancel_button.setEnabled(False);row.addWidget(self.cancel_button)
        self.cancel_button.clicked.connect(self.cancel)
        self.settings_button=QPushButton('DRC 配置…');row.addWidget(self.settings_button);self.settings_button.clicked.connect(self.settings)
        self.resume_button=QPushButton('恢复最近任务');row.addWidget(self.resume_button);self.resume_button.clicked.connect(self.resume)
        self.activity=TaskActivity(self,idle_title='准备检查',running_title='正在检查',idle_message='先选择检查区域。')
        self.message=self.activity.message;layout.addWidget(self.activity)
        self.filter=QComboBox();self.filter.addItem('全部规则',None);layout.addWidget(self.filter);self.filter.currentIndexChanged.connect(self.populate)
        row=QHBoxLayout();layout.addLayout(row)
        self.waiver_filter=QComboBox()
        for label,value in [('未 Waive','active'),('已 Waive','waived'),('全部错误','all')]:self.waiver_filter.addItem(label,value)
        row.addWidget(self.waiver_filter);self.waiver_filter.currentIndexChanged.connect(self.populate)
        self.waive_button=QPushButton('Waive 所选类型');row.addWidget(self.waive_button);self.waive_button.clicked.connect(self.waive_selected)
        self.waiver_settings=QPushButton('Waive 设置…');row.addWidget(self.waiver_settings);self.waiver_settings.clicked.connect(self.edit_waivers)
        self.only_selected=QCheckBox('选中错误时，仅高亮这一项');self.only_selected.setChecked(True);layout.addWidget(self.only_selected)
        self.only_selected.toggled.connect(lambda:self.window.canvas.viewport().update())
        self.dim=QCheckBox('Dim 其他版图（突出 DRC）');self.dim.setChecked(True);layout.addWidget(self.dim)
        self.dim.toggled.connect(lambda:self.window.canvas.viewport().update())
        self.markers=QListWidget();self.markers.setUniformItemSizes(True);layout.addWidget(self.markers,1)
        self.markers.currentItemChanged.connect(self.choose)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(175);layout.addWidget(self.details)
        row=QHBoxLayout();layout.addLayout(row)
        self.export_button=QPushButton('导出审阅 JSON');row.addWidget(self.export_button);self.export_button.clicked.connect(self.export)
        self.logs_button=QPushButton('打开任务目录');row.addWidget(self.logs_button);self.logs_button.clicked.connect(self.open_logs)
        self.clear_button=QPushButton('清除标记');row.addWidget(self.clear_button);self.clear_button.clicked.connect(self.clear)
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(400)
        self.window.canvas.region_picked.connect(lambda bounds:self.picked(bounds) if self.pick.isChecked() else None)
        self.window.canvas.region_cancelled.connect(lambda:self.pick.setChecked(False))
        self.window.canvas.drc_overlay=self.paint
        self.refresh_profile()
        if self.window.editor:
            self.job_id=jobs.latest(self.window.editor.w.id)
            if self.job_id:self.last_job_id=self.job_id

    def set_presentation(self,formal):
        self.formal=formal
        for widget in (self.coordinate_box,self.process,self.note,self.local_button,self.remote_button,self.settings_button,
                       self.resume_button,self.filter,self.waive_button,self.waiver_settings,self.only_selected,self.export_button,self.logs_button):
            widget.setVisible(not formal)
        self.pick.setVisible(not formal and self.bound_region_id is None);self.view_region.setVisible(not formal and self.bound_region_id is None)
        self.run_button.setVisible(formal);self.cancel_button.setVisible(not formal or bool(self.job_id))
        self.cancel_button.setText('停止检查' if formal else '取消任务')
        self.dim.setText('突出显示检查结果' if formal else 'Dim 其他版图（突出 DRC）')
        self.waiver_filter.setVisible(not formal or self.engine=='calibre' and bool(self.waived))
        if formal:self.filter.setCurrentIndex(0);self.waiver_filter.setCurrentIndex(0)
        for i,label in enumerate(('待处理问题','已忽略问题','全部问题') if formal else ('未 Waive','已 Waive','全部错误')):self.waiver_filter.setItemText(i,label)
        self.update_title()
        if self.result:
            self.describe()
            if self.markers.currentItem():self.choose(self.markers.currentItem(),navigate=False)

    def update_title(self):
        if not self.formal:self.title.setText('区域 DRC');return
        self.title.setText('本地 DRC' if self.engine=='local' else '服务器全规则 DRC')
        region=self.window.editor.w.local_data.regions.get(self.bound_region_id) if self.window.editor else None
        self.scope_label.setText('检查范围 · '+region.name if region else '请先选择一个操作区')

    def refresh_profile(self):
        editor=self.window.editor
        if not editor:self.process.setText('尚未载入版图');return
        p=editor.profile;key=p.key
        if self._current_key==key:return
        self._current_key=key
        try:self.profile=config.load(p)
        except Exception as exc:self.profile=None;self.message.setText(str(exc))
        try:self.waiver_policy=waivers.load(p.native_fingerprint,p.configuration_id)
        except Exception as exc:
            self.waiver_policy=waivers.WaiverPolicy(technology_fingerprint=p.native_fingerprint,configuration_id=p.configuration_id,enabled=False)
            self.message.setText('Waive 配置读取失败，显示全部错误：'+str(exc))
        if self.result:self.apply_waivers()
        self.process.setText(p.label+' · '+(self.profile.id if self.profile else 'DRC 尚未配置'))

    def pick_region(self,on):
        self.window.canvas.region_select=on
        self.window.canvas.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)
        if on:self.message.setText('在版图上按住左键拖出矩形区域。Esc 可取消。')

    def bind_region(self,ident):
        if self.job_id:raise ValueError('请先等待当前检查结束，或取消当前任务。')
        if ident!=self.bound_region_id:self.clear()
        self.bound_region_id=ident
        for widget in (self.pick,self.view_region):widget.setVisible(ident is None and not self.formal)
        self.pick.setChecked(False)
        for edit in self.coords:edit.setReadOnly(ident is not None)
        if ident:self.update_region()
        else:self.scope_label.setText('通信测试：手动检查范围')

    def picked(self,bounds):
        if not self.window.editor:return
        scale=self.window.editor.profile.dbu_per_micron
        for edit,n in zip(self.coords,bounds):edit.setText(f'{round(n)/scale:.6f}')
        self.pick.setChecked(False);self.update_region()

    def from_view(self):
        rect=self.window.canvas.mapToScene(self.window.canvas.viewport().rect()).boundingRect()
        self.picked((rect.left(),-rect.bottom(),rect.right(),-rect.top()))

    def update_region(self):
        if not self.window.editor:return False
        try:
            if self.bound_region_id:
                region=self.window.editor.w.local_data.regions.get(self.bound_region_id)
                if region is None:raise ValueError('原操作区已解散，请重新选择操作区。')
                self.region=Region(bbox=region.bbox);scale=self.window.editor.profile.dbu_per_micron
                for edit,value in zip(self.coords,(*region.bbox[0],*region.bbox[1])):edit.setText(f'{value/scale:g}')
                self.scope_label.setText('检查范围 · '+region.name if self.formal else '检查操作区：'+region.name+'\n'+region.id)
            else:self.region=Region.from_um([e.text().strip() for e in self.coords],self.window.editor.profile.dbu_per_micron)
            self.window.canvas.viewport().update();return True
        except Exception as exc:self.message.setText('区域坐标无效：'+str(exc));return False

    def retry_more_results(self):
        if not self.result or self.result.engine!='calibre':return
        limits=self.result.coverage.get('result_limits',{})
        previous=max(limits.get('per_rule',10000),limits.get('retained_markers',10000))
        self.start('calibre',result_limit=min(1000000,max(50000,previous*5)))

    def start(self,engine,*,result_limit=None):
        if engine=='calibre' and not getattr(self.window,'remote_enabled',True):
            self.message.setText('离线试用窗口不能执行服务器检查；请使用正式工作区。');return
        if self.job_id or self.window.busy or not self.window.editor:return
        self.engine=engine;self.update_title()
        if not self.update_region():return
        self.refresh_profile()
        if not self.profile:self.message.setText('请先在“文件 → 工艺库设置”中配置 DRC。' if self.formal else '请先打开“DRC 配置…”配置当前工艺。');return
        self.clear();self.more_results.hide();self._starting=True;self.activity.start();self.message.setText('正在启动本地 DRC…' if engine=='local' else '正在启动服务器全规则 DRC…')
        w,p=self.window.editor.w,self.window.editor.profile;profile=self.profile;region=self.region
        def done(state):
            self._starting=False
            self.job_id=state['job_id'];self.last_job_id=self.job_id
            self.message.setText('正在检查；你可以继续查看版图。');self.cancel_button.setEnabled(True);self.cancel_button.show()
            self.window.status.setText('DRC 已在后台启动；可继续查看或编辑版图。')
        def failed(error):
            self._starting=False
            self.activity.finish('failed','检查未启动',str(error[0]).splitlines()[0])
        try:
            scope=self.bound_region_id if self.bound_region_id else self.window.editor.scope_id
            options={'result_limit':result_limit} if result_limit is not None else {}
            self.window.task(lambda:jobs.start(w,p,profile,region,engine,scope_id=scope,**options),done)
            if self.window.job:self.window.job.failed.connect(failed)
        except Exception as exc:failed((str(exc),))

    def cancel(self):
        if self.job_id:
            jobs.cancel(self.job_id);self.cancel_button.setEnabled(False);self.message.setText('已请求取消，正在结束后台任务…')

    def resume(self):
        if self.job_id or not self.window.editor:return
        self.job_id=jobs.latest(self.window.editor.w.id)
        if self.job_id:self.last_job_id=self.job_id;self.poll()
        else:self.message.setText('此工作区还没有保存的 DRC 任务。')

    def poll(self):
        self.refresh_profile()
        if self.job_id:
            try:
                if self.activity.outcome!='running':self.activity.start()
                state=jobs.status(self.job_id);self.message.setText(state.get('message',state['status']))
                if state['status'] in ('completed','failed','cancelled'):
                    uid=self.job_id
                    if state['status']=='completed':self.accept_result(jobs.result(uid))
                    else:
                        from .presentation import failure_text
                        self.details.setPlainText(failure_text(state))
                    self.job_id=None;self.cancel_button.setEnabled(False)
                    if not self.window.busy:self.window.status.setText('DRC：'+state.get('message',state['status']))
                    self.activity.finish(state['status'],{'completed':'检查完成','failed':'检查失败','cancelled':'已停止检查'}[state['status']],self.message.text())
            except Exception as exc:
                if getattr(exc,'code',None)=='DRC_JOB_STORAGE_UNAVAILABLE':
                    self.message.setText('任务文件暂时不可读，正在重查同一任务；尚无检查结论。')
                    self.details.setPlainText('任务 ID：'+self.job_id+'\n持续失败时请联系维护人员；不会自动重复启动服务器检查。')
                else:
                    self.job_id=None;self.cancel_button.setEnabled(False)
                    self.activity.finish('failed','检查失败','读取任务结果失败；不能据此判断通过：'+str(exc))
        if self.result and self.window.editor:
            stale=not self.result.is_current(self.window.editor.w,self.profile) or self.region!=self.result.region
            if stale!=self.stale:
                self.stale=stale;self.describe();self.window.canvas.viewport().update()
        running=bool(self._starting or self.job_id or self.window.busy)
        self.local_button.setEnabled(not running and self.profile is not None)
        self.remote_button.setEnabled(not running and self.profile is not None and self.profile.remote is not None and getattr(self.window,'remote_enabled',True))
        self.settings_button.setEnabled(not running and self.window.editor is not None)
        self.resume_button.setEnabled(not running and self.window.editor is not None)
        if self.formal:
            self.cancel_button.setVisible(bool(self.job_id))
            ready=self.profile is not None and (self.engine=='local' or self.profile.remote is not None and getattr(self.window,'remote_enabled',True))
            self.run_button.setEnabled(not running and ready and bool(self.bound_region_id))

    def accept_result(self,result):
        self.result=result;self.region=result.region;self.engine=result.engine;self.update_title();self.stale=not result.is_current(self.window.editor.w,self.profile)
        self.run_button.setText('重新检查')
        limits=result.coverage.get('result_limits',{})
        self.more_results.setVisible(result.engine=='calibre' and result.coverage.get('truncated',False)
            and max(limits.get('per_rule',10000),limits.get('retained_markers',10000))<1000000)
        scale=result.dbu_per_micron
        for edit,value in zip(self.coords,(*result.region.bbox[0],*result.region.bbox[1])):edit.setText(f'{value/scale:.6f}')
        self.filter.blockSignals(True);self.filter.clear();self.filter.addItem('全部规则',None)
        for name in sorted({m.rule_id for m in result.markers}):self.filter.addItem(name,name)
        self.filter.blockSignals(False);self.apply_waivers()

    def apply_waivers(self):
        if not self.result:return
        # A result from a previous process retains that process's own policy.
        policy=self.waiver_policy
        if policy is None or policy.technology_fingerprint!=self.result.technology_fingerprint or (policy.configuration_id or policy.technology_fingerprint)!=(self.result.configuration_id or self.result.technology_fingerprint):
            policy=waivers.load(self.result.technology_fingerprint,self.result.configuration_id)
        self.waived=waivers.assessment(self.result,policy)['waived_markers']
        if self.formal:
            visible=self.result.engine=='calibre' and bool(self.waived);self.waiver_filter.setVisible(visible)
            if not visible:
                self.waiver_filter.blockSignals(True);self.waiver_filter.setCurrentIndex(0);self.waiver_filter.blockSignals(False)
        self.populate();self.describe()

    def waive_selected(self):
        if not self.result or self.result.engine!='calibre':
            self.message.setText('Waive 设置用于服务器 DRC 报告。');return
        item=self.markers.currentItem();rule=item.data(Qt.ItemDataRole.UserRole).rule_id if item else self.filter.currentData()
        if not rule:self.message.setText('先选择一个错误或一种规则。');return
        policy=waivers.load(self.result.technology_fingerprint,self.result.configuration_id)
        policy=policy.model_copy(update={'enabled':True,'rule_ids':tuple(dict.fromkeys((*policy.rule_ids,rule)))})
        waivers.save(policy);self.waiver_policy=policy;self.apply_waivers()

    def edit_waivers(self):
        if hasattr(self.window,'process_settings'):
            self.window.process_settings(page=5);return
        from .waiver_dialog import WaiverDialog
        if not self.window.editor:return
        key=self.result.technology_fingerprint if self.result else self.window.editor.profile.native_fingerprint
        configuration_id=self.result.configuration_id if self.result else self.window.editor.profile.configuration_id
        dialog=WaiverDialog(waivers.load(key,configuration_id),self.window)
        if dialog.exec():
            waivers.save(dialog.policy);self.waiver_policy=dialog.policy;self.apply_waivers()
        dialog.deleteLater()

    def describe(self):
        if not self.result:return
        if self.formal:
            from .presentation import summary,coverage_text
            self.message.setText(summary(self.result,self.waived,self.stale))
            if not self.window.busy:self.window.status.setText(('历史 DRC（已过期） · ' if self.stale else 'DRC · ')+self.message.text().replace('\n',' · '))
            self.details.setPlainText(coverage_text(self.result));return
        label='本地轻量' if self.result.engine=='local' else '服务器区域全规则'
        counts=len(self.result.markers);warning='；存在覆盖限制' if self.result.coverage.get('warnings') or self.result.coverage.get('truncated') else ''
        summary=f'{counts-len(self.waived)} 未 Waive / {len(self.waived)} 已 Waive / {counts} 总计' if self.result.engine=='calibre' else f'{counts} 个标记'
        self.message.setText(('结果已过期，请重新检查。\n' if self.stale else '')+f'{label}完成：{summary}{warning}。区域检查不代表整芯片签核。')
        if not self.window.busy:self.window.status.setText(('DRC 结果已过期 · ' if self.stale else 'DRC 审阅 · ')+summary)
        self.message.setStyleSheet('color:#b87914' if self.stale else '')
        self.details.setPlainText(json.dumps(self.result.coverage,ensure_ascii=False,indent=2))

    def populate(self):
        self.markers.clear();self.paths=[];self.selected_id=None
        if not self.result:return
        selected=self.filter.currentData();scale=self.result.dbu_per_micron
        for m in self.result.markers:
            if selected and m.rule_id!=selected:continue
            mode=self.waiver_filter.currentData();waived=m.id in self.waived
            if mode=='active' and waived or mode=='waived' and not waived:continue
            path=QPainterPath();path.setFillRule(Qt.FillRule.OddEvenFill)
            if m.kind=='polygon':
                for i,(x,y) in enumerate(m.points):path.moveTo(x,-y) if i==0 else path.lineTo(x,-y)
                path.closeSubpath()
            elif m.kind=='edges':
                for x,y,xx,yy in m.edges:path.moveTo(x,-y);path.lineTo(xx,-yy)
            else:path.addRect(box_rect(m.bbox))
            self.paths.append((m,path))
            x,y=m.bbox[0]
            item=QListWidgetItem(('［Waived］' if waived else '')+f'{m.rule_id}  ·  ({x/scale:.3f}, {y/scale:.3f}) µm')
            item.setData(Qt.ItemDataRole.UserRole,m);item.setForeground(QColor('#e6a23c' if m.severity=='warning' else '#df6060'));self.markers.addItem(item)
        self.window.canvas.viewport().update()

    def choose(self,item,previous=None,*,navigate=True):
        if not item:return
        m=item.data(Qt.ItemDataRole.UserRole);self.selected_id=m.id
        scale=self.result.dbu_per_micron;(x,y),(xx,yy)=m.bbox
        lines=[m.rule_id+' · '+('提示' if m.severity=='warning' else '错误'),m.message,
            f'位置：({x/scale:.6f}, {y/scale:.6f}) → ({xx/scale:.6f}, {yy/scale:.6f}) µm']
        if m.required_um is not None:lines.append(f'要求 ≥ {m.required_um:g} µm；测量 '+(f'{m.measured_um:g} µm' if m.measured_um is not None else '见几何标记'))
        if m.id in self.waived:lines.insert(1,'已 Waive：'+', '.join(self.waived[m.id]))
        if m.objects:lines.append('相关对象：'+', '.join((o.get('name') or (o['uid'] if len(o['uid'])<=24 else o['uid'][:8]+'…'+o['uid'][-12:]))+('（实例内部只读）' if o.get('inside_instance') else '') for o in m.objects))
        else:lines.append('没有确定对象关联；请按错误区域与规则文字检查。')
        if not self.formal:lines.append('坐标与对象详细数据（DBU）：\n'+json.dumps(m.model_dump(),ensure_ascii=False,indent=2))
        self.details.setPlainText('\n'.join(lines))
        rect=box_rect(m.bbox);pad=max(rect.width(),rect.height(),self.result.dbu_per_micron)*.65
        if navigate:self.window.canvas.fitInView(rect.adjusted(-pad,-pad,pad,pad),Qt.AspectRatioMode.KeepAspectRatio)
        self.window.canvas.viewport().update()

    def paint(self,painter):
        if not self.isVisible() or self.visibleRegion().isEmpty():return
        if self.dim.isChecked() and self.paths:
            painter.resetTransform();painter.fillRect(self.window.canvas.viewport().rect(),QColor(0,0,0,195))
        painter.setTransform(self.window.canvas.viewportTransform());painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.region:
            pen=QPen(QColor('#5baaff'),1,Qt.PenStyle.DashLine);pen.setCosmetic(True);painter.setPen(pen);painter.drawRect(box_rect(self.region.bbox))
        visible=self.window.canvas.mapToScene(self.window.canvas.viewport().rect()).boundingRect()
        for m,path in self.paths:
            if self.only_selected.isChecked() and self.selected_id and self.selected_id!=m.id:continue
            if not visible.intersects(path.boundingRect().adjusted(-1,-1,1,1)):continue
            chosen=m.id==self.selected_id
            color=QColor('#aaaaaa' if self.stale else '#ffb840' if m.severity=='warning' else '#ffff55' if chosen else '#ff6778')
            shadow=QPen(QColor('#080808'),9 if chosen else 5);shadow.setCosmetic(True);painter.setPen(shadow);painter.setBrush(Qt.BrushStyle.NoBrush);painter.drawPath(path)
            pen=QPen(color,4 if chosen else 2);pen.setCosmetic(True);painter.setPen(pen)
            color.setAlpha(110);painter.setBrush(color if chosen else Qt.BrushStyle.NoBrush);painter.drawPath(path)
            if chosen:
                painter.save();rect=self.window.canvas.viewportTransform().mapRect(path.boundingRect()).adjusted(-7,-7,7,7)
                painter.resetTransform();painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(QColor('#ffffff'),1,Qt.PenStyle.DashLine));painter.drawRect(rect);painter.restore()

    def clear(self):
        self.result=None;self.paths=[];self.markers.clear();self.details.clear();self.window.canvas.viewport().update()
        if self.formal and not (self.job_id or self._starting):self.activity.reset('点击“开始检查”检查所选操作区。');self.run_button.setText('开始检查')

    def settings(self):
        if hasattr(self.window,'process_settings'):
            self.window.process_settings(page=1);return
        from .settings import DrcSettings
        dialog=DrcSettings(self.window.editor.profile,self.profile,self.window)
        if dialog.exec():
            self._current_key=None;self.refresh_profile();self.poll()
        dialog.deleteLater()

    def export(self):
        if not self.result:return
        path,_=QFileDialog.getSaveFileName(self,'保存 DRC 结果','drc-result.json','JSON (*.json)')
        if path:
            from ..process_library import write_json
            policy=self.waiver_policy
            if policy and (policy.technology_fingerprint!=self.result.technology_fingerprint or (policy.configuration_id or policy.technology_fingerprint)!=(self.result.configuration_id or self.result.technology_fingerprint)):
                policy=None
            write_json(path,waivers.review(self.result,policy))

    def open_logs(self):
        from PySide6.QtCore import QUrl
        uid=self.job_id or getattr(self,'last_job_id',None)
        if uid:QDesktopServices.openUrl(QUrl.fromLocalFile(str(jobs.job_folder(uid))))

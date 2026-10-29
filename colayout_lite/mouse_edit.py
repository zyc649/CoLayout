"""Mouse gestures delegate to shared commands; previews never enter the workspace."""
from PySide6.QtCore import Qt,QPointF,QRectF,QSignalBlocker
from PySide6.QtGui import QColor,QPen,QTransform
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QLabel,QPushButton,QMenu,QGraphicsItem
from .human_edit import HumanEdit
from .model import LiteError
from .frame_edit import FrameEdit,resized_bounds
from .bounds_edit import BoundsEdit
from .pin_placement import candidate as pin_candidate,center as pin_center
from .canvas_hits import handles,editable_at,foreground_frame_at
from .drag_visual import DragVisual,FrameVisual


class MouseEdit:
    def __init__(self,window):
        self.window=window;self.armed=None;self.dragging=False;self.pin_selected=None
        self.resize_target=None
        self.visual=None;self.preview_pins={};self.preview_bounds=None;self.error=None
        window.canvas.human=self
        window.canvas.inspection_clear.connect(self.escape)
        window.canvas.setMouseTracking(True)

    def ids(self):
        w=self.window
        if not w.editor:return []
        local=w.editor.w.local_data
        # Membership probes cost only the selection size, not every scene owner.
        return sorted({uid for item in w.scene.selectedItems() if isinstance(uid:=item.data(0),str)
            and (uid in w.groups or uid in local.regions or uid in local.markups or uid in local.keepouts)})

    def select(self,uid,add=False):
        w=self.window
        with QSignalBlocker(w.scene):
            if not add:w.scene.clearSelection()
            for item in (list(w.groups[uid].parts.values()) if uid in w.groups else w._workspace_overlay_items):
                if item.data(0)==uid and item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:item.setSelected(True)
        w.selected();w.canvas.viewport().update()

    def handle_at(self,pixel):
        ids=self.ids()
        if len(ids)!=1 or self.resize_target!=ids[0]:return None
        return next(((ids[0],key) for key,rect in handles(self.window,ids[0]) if rect.adjusted(-3,-3,3,3).contains(pixel)),None)

    def begin(self,event):
        w=self.window
        if w.busy or not w.editor or event.button()!=Qt.MouseButton.LeftButton:return False
        if w.region_panel.mode or w.canvas.region_select:return False
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.cancel();w.inspection.clear_trace();return False
        pixel=event.position();scene=w.canvas.mapToScene(pixel.toPoint());hit=w.inspection.hit_pin(pixel)
        frame_target=foreground_frame_at(w,pixel)
        if hit and not hit['pin']['local'] and frame_target:hit=None
        handle=self.handle_at(pixel)
        if handle:hit=None
        selected=self.ids();picked=hit['pin']['owner'] if hit and not hit['pin']['local'] else editable_at(w,pixel) if hit is None else None
        shift=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if shift:
            try:kind=HumanEdit(w.editor).kind(picked) if picked else None
            except LiteError:kind=None
            if kind not in ('instance','area'):
                self.cancel();w.inspection.clear_trace();return False
        move_selection=bool(selected and picked in selected and not (hit and hit['pin'].get('guard') and not w.selection_ui.move_conductors))
        if move_selection:
            try:
                for uid in selected:HumanEdit(w.editor).kind(uid)
            except LiteError:move_selection=False
        self.cancel();self.error=None
        if shift:
            # Defer Shift-click's selection toggle until release; an actual
            # drag instead moves the device/group with an axis constraint.
            self.armed={'ids':selected if picked in selected else [picked],
                'shift_click':picked,'old_selection':set(selected)}
            w.inspection.clear_trace()
        elif handle:
            ident,key=handle;edit=BoundsEdit(w.editor);field,row=edit.record(ident)
            self.armed={'resize':ident,'handle':key,'bounds':row.bbox,'limits':edit.limits(ident),'rect':field=='rectangle'}
            self.armed['outer']=edit.outer(ident)
            w.inspection.clear_trace()
        elif move_selection:
            self.armed={'ids':selected};w.inspection.clear_trace()
        else:
            if hit:
                pin=hit['pin'];rid=pin['owner']
                if pin['local'] and rid in w.editor.w.local_data.regions:
                    r=w.editor.w.local_data.regions[rid]
                    if r.id!=w.editor.scope_id and r.parent_id!=w.editor.scope_id:return True
                    reason=w.editor.work_sessions.readonly_reason(pin['id'])
                    if reason:
                        self.pin_selected=(rid,pin['id']);w.scene.clearSelection()
                        w.region_panel.select_pin(rid,pin['id'],trace=False)
                        self.armed={'readonly_pin':hit}
                        w.status.setText(reason);return True
                    self.pin_selected=(rid,pin['id']);w.scene.clearSelection();w.region_panel.select_pin(rid,pin['id'],trace=False)
                    self.armed={'pin':self.pin_selected}
                else:
                    if pin.get('guard'):self.select(rid)
                    else:w.scene.clearSelection()
                    w.inspection.clear_trace();w.inspection.request({'pin_id':pin['id']})
                    self.armed={'readonly_pin':hit};return True
            else:
                uid=editable_at(w,pixel)
                if not uid:return False
                try:HumanEdit(w.editor).kind(uid)
                except LiteError as exc:
                    if w.editor.work_sessions.readonly_reason(uid):
                        self.select(uid);w.status.setText(str(exc));return True
                    return False
                selected=self.ids()
                if uid not in selected:self.select(uid);selected=[uid]
                self.armed={'ids':selected};w.inspection.clear_trace()
        self.armed.update(frame_foreground=frame_target if hit is None else None,pixel=QPointF(pixel),start=(scene.x(),-scene.y()),revision=w.editor.w.revision,
            editor=w.editor,scope=w.editor.scope_id,camera=QTransform(w.canvas.viewportTransform()),delta=(0,0))
        if 'ids' in self.armed:
            from .gesture_policy import movable_selection
            if not movable_selection(w,self.armed['ids']):
                self.armed['inspect_only']=True
                if not self.armed.get('frame_foreground'):w.inspection.pick(scene.x(),-scene.y())
        return True

    def valid_context(self):
        r=self.armed;w=self.window
        if w.editor is not r['editor'] or w.editor.scope_id!=r['scope'] or w.editor.w.revision!=r['revision']:
            raise LiteError('DRAG_CONTEXT_CHANGED','工作区或编辑层次已变化，拖动已取消。')
        if w.canvas.viewportTransform()!=r['camera']:raise LiteError('DRAG_VIEW_CHANGED','视图已变化，拖动已取消。')

    def move(self,event):
        if not self.armed:
            if self.window.editor and not self.window.canvas.region_select:
                hit=self.handle_at(event.position())
                cursors={'nw':Qt.CursorShape.SizeFDiagCursor,'se':Qt.CursorShape.SizeFDiagCursor,'ne':Qt.CursorShape.SizeBDiagCursor,
                    'sw':Qt.CursorShape.SizeBDiagCursor,'n':Qt.CursorShape.SizeVerCursor,'s':Qt.CursorShape.SizeVerCursor,
                    'e':Qt.CursorShape.SizeHorCursor,'w':Qt.CursorShape.SizeHorCursor}
                if hit:self.window.canvas.setCursor(cursors[hit[1]])
                else:self.window.canvas.unsetCursor()
            return False
        if 'readonly_pin' in self.armed or self.armed.get('inspect_only'):return True
        if not self.dragging and (event.position()-self.armed['pixel']).manhattanLength()<QApplication.startDragDistance():return True
        w=self.window;r=self.armed
        try:self.valid_context()
        except LiteError as exc:self.cancel();w.status.setText(str(exc));return True
        point=w.canvas.mapToScene(event.position().toPoint());grid=w.editor.profile.grid
        dx=round((point.x()-r['start'][0])/grid)*grid;dy=round((-point.y()-r['start'][1])/grid)*grid
        if 'ids' in r:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                axis=r.setdefault('axis','x' if abs(dx)>=abs(dy) else 'y')
                dx,dy=(dx,0) if axis=='x' else (0,dy)
            else:r.pop('axis',None)
            if not self.dragging and 'shift_click' in r:
                w.selection_ui.set_ids(r['ids']);w.selection_ui.selection_changed()
        self.dragging=True;self.error=None
        try:
            if 'pin' in r:
                rid,pid=r['pin'];region=w.editor.w.local_data.regions[rid];pin=region.pins[pid];cx,cy=pin_center(pin)
                updated=pin_candidate(region,pin,cx+dx,cy+dy,grid)
                nx,ny=pin_center(updated);dx,dy=nx-cx,ny-cy
                if self.visual is None:self.visual=DragVisual(w,pin=r['pin'])
                self.visual.move((dx,dy))
            elif 'resize' in r:
                bounds=resized_bounds(r['bounds'],r['handle'],(point.x(),-point.y()),grid,r['limits'],r['outer'])
                self.preview_bounds=bounds
                if self.visual is None:
                    from .drag_visual import RectVisual
                    self.visual=RectVisual(w,r['resize'],r['bounds']) if r['rect'] else FrameVisual(w,r['resize'])
                self.visual.resize(bounds)
                if not r['rect']:
                    candidate=BoundsEdit(w.editor).candidate(r['resize'],bounds)
                    if r['resize'] in candidate.local_data.regions:self.preview_pins=candidate.local_data.regions[r['resize']].pins
                r['result_bounds']=bounds
            else:
                if self.visual is None:self.visual=DragVisual(w,r['ids'])
                self.visual.move((dx,dy))
            r['delta']=(dx,dy)
        except Exception as exc:self.error=str(exc);w.status.setText(self.error)
        w.canvas.setCursor(Qt.CursorShape.ForbiddenCursor if self.error else Qt.CursorShape.ClosedHandCursor)
        w.canvas.viewport().update();return True

    def finish(self,event):
        if not self.armed:return False
        w=self.window;r=self.armed;dragged=self.dragging
        if 'readonly_pin' in r or r.get('inspect_only'):self.cancel();return True
        if not dragged:
            self.armed=None
            if 'pin' in r:w.inspection.focus_pin(*r['pin'])
            if 'shift_click' in r:
                w.selection_ui.set_ids(r['old_selection'] ^ {r['shift_click']});w.selection_ui.selection_changed();return True
            if 'pin' not in r and 'resize' not in r and not r.get('frame_foreground'):
                # A click owns its press target. Sub-threshold hand movement
                # must not select one thin wire and inspect blank space (or
                # another wire) at release. Actual drags still commit below.
                w.inspection.pick(*r['start'])
            return True
        try:
            self.valid_context()
            if self.error:raise LiteError('DRAG_INVALID',self.error)
            # Restore disposable graphics before the model publication rebuilds
            # them. The newly committed pose is identical to the last preview.
            if self.visual:self.visual.close();self.visual=None
            w.canvas.unsetCursor()
            api=HumanEdit(w.editor);dx,dy=r['delta']
            if 'pin' in r:
                rid,pid=r['pin'];pin=w.editor.w.local_data.regions[rid].pins[pid];cx,cy=pin_center(pin)
                api.adjust_pin(rid,pid,cx+dx,cy+dy,expected_revision=r['revision'])
                w.inspection.focus_pin(rid,pid,query=False)
            elif 'resize' in r:BoundsEdit(w.editor).resize(r['resize'],r['result_bounds'],expected_revision=r['revision'])
            else:api.transform(r['ids'],delta=(dx,dy),expected_revision=r['revision'])
        except Exception as exc:w.status.setText(str(exc))
        finally:self.cancel();self.refresh_selection()
        return True

    def cancel(self):
        if self.visual:self.visual.close();self.visual=None
        self.armed=None;self.dragging=False;self.pin_selected=None;self.preview_pins={};self.preview_bounds=None;self.error=None
        self.window.canvas.unsetCursor();self.window.canvas.viewport().update()

    def can_resize(self):
        if self.window.busy or not self.window.editor or self.window.editor.w.state in ('submitting','indeterminate','conflict'):return False
        ids=self.ids()
        if len(ids)!=1:return False
        try:BoundsEdit(self.window.editor).record(ids[0]);return True
        except LiteError:return False

    def set_resize_enabled(self,enabled):
        self.cancel()
        self.resize_target=self.ids()[0] if enabled and self.can_resize() else None
        self.refresh_resize_mode();self.window.canvas.viewport().update()

    def refresh_resize_mode(self):
        if self.resize_target and (self.ids()!=[self.resize_target] or not self.can_resize()):self.resize_target=None
        button=getattr(getattr(self.window,'selection_ui',None),'resize_button',None)
        if button:
            with QSignalBlocker(button):button.setChecked(bool(self.resize_target))
            button.setEnabled(self.can_resize() and not self.window.busy)
            button.setText('完成边界调整' if self.resize_target else '调整边界')

    def escape(self):
        self.cancel();self.resize_target=None;self.refresh_resize_mode()

    def command(self,action):
        w=self.window
        if w.busy or not w.editor:return
        try:
            if self.pin_selected:raise LiteError('LOCAL_PIN_MOVE_ONLY','PIN 只能调整位置，不能删除、旋转或镜像。')
            api=HumanEdit(w.editor)
            if action=='delete':
                ids=self.ids();api.delete(ids);w.status.setText(f'已删除 {len(ids)} 个当前层对象；Ctrl+Z 可撤销。')
            else:api.transform(self.ids(),orientation={'rotate':'R90','rotate_back':'R270','mirror_h':'MY','mirror_v':'MX'}[action])
        except Exception as exc:w.status.setText(str(exc))
        self.refresh_selection()

    def context_menu(self,pos):
        studio=getattr(self.window,'studio',None)
        if not self.ids() and not studio:return
        hit=self.window.inspection.hit_pin(pos)
        pin_target=None
        if hit and hit['pin'].get('local'):
            pin_target=(hit['pin']['owner'],hit['pin']['id'])
            self.window.region_panel.select_pin(*pin_target,trace=False)
        elif hit is None and studio and studio.inspector._pin:
            pin_target=(studio.inspector._uid(),studio.inspector._pin)
        menu=QMenu(self.window)
        if pin_target:
            action=menu.addAction('复制 PIN');action.setObjectName('contextCopyPin')
            try:
                FrameEdit(self.window.editor).record(pin_target[0])
                enabled=not self.window.busy
            except LiteError:enabled=False
            action.setEnabled(enabled)
            action.triggered.connect(lambda:self.copy_pin(*pin_target));menu.addSeparator()
        if studio:
            menu.addAction('属性',studio.show_properties)
            studio.commands.refresh();menu.addAction(studio.commands.actions['copy_id']);menu.addSeparator()
            if len(self.ids())==1 and self.ids()[0] in self.window.editor.w.local_data.regions:
                for key in ('region_drc_local','region_drc_remote'):menu.addAction(studio.commands.actions[key])
                menu.addSeparator()
        if self.can_resize():
            action=menu.addAction('完成边界调整' if self.resize_target else '调整边界')
            action.triggered.connect(lambda:self.set_resize_enabled(not bool(self.resize_target)));menu.addSeparator()
        if studio:
            if self.ids():
                for key in ('rotate','mirror_h','mirror_v','delete','dissolve'):menu.addAction(studio.commands.actions[key])
        else:
            for label,key in [('旋转 90°','rotate'),('左右镜像','mirror_h'),('上下镜像','mirror_v'),('删除互连','delete')]:
                action=menu.addAction(label);action.triggered.connect(lambda _=False,k=key:self.command(k))
        menu.exec(self.window.canvas.mapToGlobal(pos))

    def copy_pin(self,region_id,pin_id):
        try:
            if self.window.busy:raise LiteError('WORKSPACE_BUSY')
            from .regions.actions import RegionActions
            ident=RegionActions(self.window.editor).copy_pin(region_id,pin_id)
            self.window.save_local();self.window.region_panel.select_pin(region_id,ident)
            self.window.status.setText('已复制 PIN，可拖动到所需位置；Ctrl+Z 撤销。')
        except Exception as exc:self.window.status.setText(str(exc))

    def refresh_selection(self):
        self.refresh_resize_mode()
        panel=getattr(self.window,'human_panel',None)
        if panel:panel.refresh()

    def paint(self,painter):
        if self.window.selection_ui.gesture is not None:return
        from .canvas_hits import handles
        ids=self.ids()
        if len(ids)!=1 or self.resize_target!=ids[0]:return
        ident=ids[0];bounds=self.preview_bounds if self.armed and self.armed.get('resize')==ident else None
        if self.dragging and self.armed and ident in self.armed.get('ids',[]):
            dx,dy=self.armed['delta'];bounds=HumanEdit(self.window.editor).bounds(ident)
            if bounds:bounds=tuple(tuple(v+d for v,d in zip(p,(dx,dy))) for p in bounds)
        boxes=handles(self.window,ident,bounds)
        painter.save();painter.resetTransform()
        from .theme import palette
        colors=palette(self.window.canvas)
        color=QColor(colors.pin_error if self.error else colors.selection) if colors.name=='compact' else QColor('#ff7777' if self.error else '#9ee4df')
        painter.setPen(QPen(color,1.2));painter.setBrush(QColor(colors.local_fill if colors.name=='compact' else '#173333'))
        for key,rect in boxes:painter.drawRect(rect)
        painter.restore()



class HumanEditPanel(QWidget):
    def __init__(self,window):
        super().__init__(window);self.window=window;layout=QVBoxLayout(self)
        self.selection=QLabel();self.selection.setWordWrap(True);layout.addWidget(self.selection)
        text=QLabel('拖动当层对象，图形实时跟随；Esc 取消。\n互连：移动、Delete / Backspace 删除。\n器件／本地模块：移动、旋转、镜像。\n选中本地框后点“调整边界”，才显示缩放手柄。\n原生 PIN 和黑盒内部不能单独修改。');text.setWordWrap(True);layout.addWidget(text)
        self.buttons={}
        for label,key in [('旋转 90°','rotate'),('反向旋转 90°','rotate_back'),('左右镜像','mirror_h'),('上下镜像','mirror_v'),('删除所选互连','delete')]:
            button=QPushButton(label);layout.addWidget(button);button.clicked.connect(lambda _=False,k=key:window.human.command(k));self.buttons[key]=button
        layout.addStretch();self.refresh()

    def refresh(self):
        w=self.window;ids=w.human.ids();self.selection.setText('当前选择：\n'+'\n'.join(ids) if ids else '在画布选择当层对象')
        try:kinds=[HumanEdit(w.editor).kind(uid) for uid in ids] if w.editor else []
        except LiteError:kinds=[]
        for key,button in self.buttons.items():
            permitted=bool(kinds) and not w.human.pin_selected and not w.busy
            if key=='delete':
                try:
                    for uid in ids:HumanEdit(w.editor).deletion_kind(uid)
                except LiteError:permitted=False
            else:permitted &= all(k in ('area','instance','mpp') for k in kinds)
            button.setEnabled(permitted)

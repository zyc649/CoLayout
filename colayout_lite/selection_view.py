"""Selection gestures, presentation and preferences. No geometry edits or history."""
import json
from PySide6.QtCore import Qt,QPointF,QRectF,QSignalBlocker,QObject
from shiboken6 import isValid
from PySide6.QtGui import QColor,QPen,QPainterPath,QFont,QTransform,QPainterPathStroker
from PySide6.QtWidgets import QComboBox,QCheckBox,QLabel,QPushButton,QGraphicsItem,QApplication
from .selection_data import entries,in_box
from .transactions import write_json_atomic
from .render import box_rect
from .canvas_hits import editable_at
from .theme import palette,alpha


class SelectionView(QObject):
    def __init__(self,window,bar,path):
        super().__init__(window);self._closed=False
        self.window=window;self.path=path;self.gesture=None;self.rubber=None;self.key=None;self.rows={}
        self.mode='contains';self.dim_objects=False;self.move_conductors=False
        if path.exists():
            try:
                data=json.loads(path.read_text(encoding='utf8'))
                if data.get('marquee') in ('contains','intersects'):self.mode=data['marquee']
                self.dim_objects=data.get('dim_objects') is True
                self.move_conductors=data.get('move_conductors') is True
            except (ValueError,OSError):pass
        bar.addWidget(QLabel('框选：'))
        self.mode_combo=QComboBox();self.mode_combo.addItem('完整包含','contains');self.mode_combo.addItem('相交即选','intersects')
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(self.mode));bar.addWidget(self.mode_combo)
        self.dim_box=QCheckBox('选择对象时 DIM');self.dim_box.setChecked(self.dim_objects);bar.addWidget(self.dim_box)
        self.dim_box.setToolTip('只影响普通对象选择；选中的对象保持明亮。点击 PIN 或有效金属的网络查看始终 DIM。')
        self.move_box=QCheckBox('允许拖动金属线和过孔');self.move_box.setChecked(self.move_conductors);bar.addWidget(self.move_box)
        self.move_box.setToolTip('默认关闭以便点击查看网络；Delete / Backspace 删除不受影响。')
        self.move_box.toggled.connect(self.configure)
        self.resize_button=QPushButton('调整边界');self.resize_button.setCheckable(True);self.resize_button.setEnabled(False);bar.addWidget(self.resize_button)
        self.resize_button.setToolTip('选中一个当前层本地框后开启，才出现缩放手柄；Esc 或改选其他对象退出。')
        self.dissolve_button=QPushButton('解散操作区');self.dissolve_button.setEnabled(False);bar.addWidget(self.dissolve_button)
        self.dissolve_button.setToolTip('在上层选中操作区后解散。保留器件、导线、子模块和定位/禁布框；移除此层外框与本地接口，可撤销。')
        self.dissolve_button.clicked.connect(self.dissolve_selected)
        hint=QLabel('空白处拖框 · Shift 点击增减 / 框选追加 · Esc 清除');bar.addWidget(hint);bar.addStretch()
        self.count=QLabel();self.count.setFixedWidth(150);bar.addWidget(self.count)
        self.mode_combo.currentIndexChanged.connect(self.configure);self.dim_box.toggled.connect(self.configure)
        self.resize_button.toggled.connect(lambda enabled:getattr(window,'human',None) and window.human.set_resize_enabled(enabled))
        window.canvas.selection_ui=self;window.scene.selectionChanged.connect(self.selection_changed)
        window.canvas.inspection_clear.connect(self.escape)

    def configure(self,*_):
        self.cancel();self.mode=self.mode_combo.currentData();self.dim_objects=self.dim_box.isChecked()
        self.move_conductors=self.move_box.isChecked()
        if getattr(self.window,'human',None):self.window.human.cancel()
        write_json_atomic(self.path,{'schema_version':'colayout-selection-1','marquee':self.mode,'dim_objects':self.dim_objects,'move_conductors':self.move_conductors})
        self.window.canvas.viewport().update()

    def state_key(self):
        e=self.window.editor
        return (id(e),id(e.w.baseline),e.w.revision,e.scope_id) if e else None

    def refresh(self):
        key=self.state_key()
        if key!=self.key:
            self.key=key;self.rows=entries(self.window.editor) if self.window.editor else {};self._outline_paths={}

    def ids(self):
        if self.gesture is not None and self.gesture.get('preview') is not None:return self.gesture['preview']
        return self.committed_ids()

    def committed_ids(self):
        w=self.window;items=w.scene.selectedItems()
        if not items:return set()  # Idle drawing does not need a geometry selection index.
        self.refresh();owners=w.editor.w.baseline.text_owners if w.editor else {}
        return {owners.get(i.data(0),i.data(0)) for i in items if owners.get(i.data(0),i.data(0)) in self.rows}

    def set_ids(self,ids):
        self.refresh();ids=set(ids)&self.rows.keys();w=self.window
        old=self.committed_ids()
        if ids==old:return
        with QSignalBlocker(w.scene):
            for uid in ids^old:
                items=w.groups[uid].parts.values() if uid in w.groups else (i for i in w._workspace_overlay_items if i.data(0)==uid)
                for item in items:
                    if item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:item.setSelected(uid in ids)
        w.selected();w.canvas.viewport().update()

    def selection_changed(self):
        if self._closed or not isValid(self.window.scene):return
        ids=self.ids();self.count.setText(f'已选 {len(ids)} 个对象' if ids else '')
        human=getattr(self.window,'human',None)
        if human:human.refresh_resize_mode()
        e=self.window.editor
        ident=next(iter(ids)) if len(ids)==1 else None
        region=e.w.local_data.regions.get(ident) if e else None
        self.dissolve_button.setEnabled(bool(region and region.parent_id==e.scope_id and not self.window.busy
            and e.w.state not in ('submitting','indeterminate','conflict') and not e.work_sessions.readonly_reason(ident,action='dissolve')))
        self.window.canvas.viewport().update()

    def dissolve_selected(self):
        w=self.window;ids=self.ids()
        if w.busy or len(ids)!=1:return
        try:
            from .regions.actions import RegionActions
            if getattr(w,'human',None):w.human.escape()
            w.inspection.clear_trace();RegionActions(w.editor).dissolve(next(iter(ids)))
            self.set_ids([]);self.selection_changed()
            w.status.setText('操作区已解散，内部版图与子模块保留；Ctrl+Z 可撤销。')
        except Exception as exc:w.status.setText(str(exc))

    def close(self):
        self._closed=True;self.gesture=None;self.rubber=None
        self.window.scene.selectionChanged.disconnect(self.selection_changed)

    def pick_id(self,pixel):
        w=self.window;self.refresh()
        hit=w.inspection.hit_pin(pixel)
        uid=hit['pin']['owner'] if hit else None
        if uid in self.rows:return uid
        uid=editable_at(w,pixel)
        if uid in self.rows:return uid
        for item in w.canvas.items(pixel.toPoint()):
            if item.data(0) in self.rows:return item.data(0)
        return None

    def begin(self,event):
        w=self.window
        if not w.editor or event.button()!=Qt.MouseButton.LeftButton or w.busy or w.canvas.region_select:return False
        additive=bool(event.modifiers() & (Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier))
        uid=self.pick_id(event.position())
        if uid and not additive:return False  # Normal object press is handled by its edit adapter/Qt.
        w.inspection.clear_trace();self.refresh()
        self.gesture={'start':QPointF(event.position()),'old':self.ids(),'add':additive,'uid':uid,'key':self.state_key(),
            'camera':w.canvas.viewportTransform(),'mode':self.mode}
        self.rubber=None
        return True

    def move(self,event):
        if not self.gesture:return False
        # Windows can queue a hover across window activation / a synthetic
        # press. An unpressed move must not change an active drag preview.
        if not event.buttons() & Qt.MouseButton.LeftButton:return True
        return self._update_preview(event.position())

    def _update_preview(self,position):
        if not self.gesture:return False
        g=self.gesture;w=self.window
        if g['key']!=self.state_key() or g['camera']!=w.canvas.viewportTransform():self.cancel();return True
        if not self.rubber and (position-g['start']).manhattanLength()<QApplication.startDragDistance():return True
        self.rubber=QRectF(g['start'],position).normalized()
        rect=w.canvas.mapToScene(self.rubber.toRect()).boundingRect()
        hits=in_box(self.rows,((rect.left(),-rect.bottom()),(rect.right(),-rect.top())),g['mode'])
        g['preview']=hits | (g['old'] if g['add'] else set())
        self.count.setText(f'已选 {len(g["preview"])} 个对象')
        w.canvas.viewport().update();return True

    def finish(self,event):
        if not self.gesture:return False
        g=self.gesture
        if g['key']!=self.state_key() or g['camera']!=self.window.canvas.viewportTransform():self.cancel();return True
        # Release carries the final position even if the last move was
        # coalesced, delayed, or absent. It has no LeftButton in buttons().
        self._update_preview(event.position())
        final=g.get('preview')
        if not self.rubber:
            final=g['old'] ^ {g['uid']} if g['add'] and g['uid'] else g['old'] if g['add'] else set()
        self.gesture=None;self.rubber=None;self.set_ids(final or set());self.selection_changed();return True

    def cancel(self):
        g=self.gesture;self.gesture=None;self.rubber=None
        if g:self.selection_changed()  # The real scene selection was never changed during preview.

    def escape(self):
        self.cancel();self.set_ids([])

    def screen_rects(self):
        w=self.window;tr=w.canvas.viewportTransform();visual=w.canvas.drag_visual
        for uid in self.ids():
            rect=box_rect(self.rows[uid]['bbox'])
            human=getattr(w,'human',None)
            if human and human.preview_bounds and human.armed and human.armed.get('resize')==uid:
                rect=box_rect(human.preview_bounds)
            elif visual and uid in visual.ids:
                dx,dy=visual.delta;rect.translate(dx,-dy)
            yield uid,tr.mapRect(rect)

    @property
    def object_dim_active(self):return self.dim_objects and bool(self.ids())

    def screen_paths(self):
        from .inspection_view import polygon_path
        w=self.window;tr=w.canvas.viewportTransform();visual=w.canvas.drag_visual
        for uid in self.ids():
            row=self.rows[uid];human=getattr(w,'human',None)
            if human and human.preview_bounds and human.armed and human.armed.get('resize')==uid:
                path=QPainterPath();path.addRect(box_rect(human.preview_bounds))
            else:
                if uid not in self._outline_paths:self._outline_paths[uid]=polygon_path(row['geometry'])
                path=self._outline_paths[uid]
                if visual and uid in visual.ids:
                    dx,dy=visual.delta;path=QTransform.fromTranslate(dx,-dy).map(path)
            path=tr.map(path)
            if not row.get('shape_outline'):
                frame=QPainterPath();frame.addRect(path.boundingRect().adjusted(-2,-2,2,2));path=frame
            yield uid,path

    def dim_background(self,painter):
        mask=QPainterPath();mask.addRect(QRectF(self.window.canvas.viewport().rect()))
        selected=QPainterPath()
        stroke=QPainterPathStroker();stroke.setWidth(6)
        for uid,path in self.screen_paths():selected.addPath(path.united(stroke.createStroke(path)))
        selected.setFillRule(Qt.FillRule.WindingFill)
        painter.fillPath(mask.subtracted(selected),alpha(palette(self.window.canvas).background,185/255))

    def pin_selected(self,pin):
        ids=self.ids();owner=pin['owner'];w=self.window.editor.w
        if owner in ids:return True
        from .regions.query import owner_map
        if owner_map(w).get(owner) in ids:return True
        region=w.local_data.regions.get(owner)
        return bool(region and region.parent_id in ids)

    def paint(self,painter):
        painter.save();painter.resetTransform()
        try:
            colors=palette(self.window.canvas)
            for uid,path in self.screen_paths():
                if self.rows[uid].get('shape_outline') and self.window.inspection.highlights_owner(uid):
                    # The physical network overlay already draws this conductor
                    # in green/red. Do not cover it with a second selection pen.
                    continue
                painter.setBrush(Qt.BrushStyle.NoBrush if colors.name=='compact' else alpha(colors.selection,22/255))
                painter.setPen(QPen(QColor(colors.selection_halo),5));painter.drawPath(path)
                painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(QColor(colors.selection),2 if colors.name=='compact' else 2.5));painter.drawPath(path)
            if self.rubber:
                color=QColor(colors.marquee_contains if self.gesture['mode']=='contains' else colors.marquee_intersects)
                painter.setPen(QPen(color,2,Qt.PenStyle.SolidLine if self.gesture['mode']=='contains' else Qt.PenStyle.DashLine))
                fill=QColor(color);fill.setAlpha(32);painter.setBrush(fill);painter.drawRect(self.rubber)
                painter.setFont(QFont('Microsoft YaHei UI',9));painter.drawText(self.rubber.topLeft()+QPointF(5,-6),
                    ('完整包含' if self.gesture['mode']=='contains' else '相交即选')+f' · {len(self.ids())} 个对象')
        finally:painter.restore()

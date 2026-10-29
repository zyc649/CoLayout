"""Display-only overlays for canonical Workspace.local_data."""
from PySide6.QtCore import Qt,QRectF,QSignalBlocker
from PySide6.QtGui import QColor,QPen,QBrush,QTransform,QPainterPath,QPainterPathStroker,QLinearGradient,QGradient
from PySide6.QtWidgets import QGraphicsItem,QGraphicsRectItem,QGraphicsSimpleTextItem
from .workspace_actions import group_bounds
from .theme import palette,alpha


class LocalFrame(QGraphicsRectItem):
    def __init__(self,bounds,filled):super().__init__(bounds);self.filled=filled;self.working=False
    def paint(self,painter,option,widget=None):
        super().paint(painter,option,widget)
        if self.working:
            from .working_glow import paint
            paint(painter,self.rect())
    def shape(self):
        path=QPainterPath();path.addRect(self.rect())
        if self.filled:return path
        views=self.scene().views() if self.scene() else []
        scale=abs(views[0].transform().m11()) if views else 1
        stroke=QPainterPathStroker();stroke.setWidth(6/max(scale,1e-9))
        return stroke.createStroke(path)  # Empty frames cannot swallow interior clicks.


def clear(window):
    for item in getattr(window,'_workspace_overlay_items',[]):
        try:
            if item.scene() is window.scene:window.scene.removeItem(item)
        except RuntimeError:pass
    window._workspace_overlay_items=[];window._local_pin_items=[]
    window._overlay_context=None;window._overlay_labels=[];window._overlay_scale=None


def reflow_labels(window):
    """Pan moves every caption equally; only scale/rotation/DPI changes spacing."""
    tr=window.canvas.viewportTransform()
    signature=(tr.m11(),tr.m12(),tr.m21(),tr.m22(),window.canvas.devicePixelRatioF())
    if signature==getattr(window,'_overlay_scale',None):return
    from .screen_rect_index import ScreenRectIndex
    boxes=ScreenRectIndex()
    for item,offset in window._overlay_labels:
        if getattr(item,'native',False) and item.module_bounds is not None:
            bounds=tr.mapRect(item.module_bounds)
            item.setVisible(bounds.width()>=36 and bounds.height()>=28)
            if not item.isVisible():continue
        for attempt in range(30):
            item.setTransform(QTransform.fromTranslate(0,offset+attempt*(-18 if offset<0 else 18)))
            bounds=item.deviceTransform(tr).mapRect(item.boundingRect()).adjusted(-2,-2,2,2)
            if not boxes.intersects(bounds):break
        boxes.add(bounds)
    window._overlay_scale=signature


def hidden_geometry_only(window, previous):
    """Conservative fast path: an existing opaque child's internals changed.

    Local metadata, membership, scene owners, ancestor context, and all visible
    objects must be unchanged. This only reuses frame graphics, never physics.
    """
    e=window.editor;current=e.w
    if previous is None or any(getattr(previous,k) is not getattr(current,k) for k in
            ('baseline','layout_connectivity','guard_previews','instance_display')):
        return False
    a,b=previous.local_data,current.local_data
    if a is not b:
        if any(getattr(a,k)!=getattr(b,k) for k in type(a).model_fields if k!='regions'):return False
        if a.regions.keys()!=b.regions.keys():return False
        for uid,row in a.regions.items():
            other=b.regions[uid]
            if row is not other and row.model_copy(update={'revision':other.revision})!=other:return False
    if current.local_data.groups:return False
    from .editor import projected
    from .regions.query import owner_map
    from .scope_state import ancestors
    before,after=projected(previous),projected(current)
    if before.keys()!=after.keys():return False
    owners=owner_map(current);protected=ancestors(current,e.scope_id)|{e.scope_id}
    visible=getattr(window,'_displayed_uids',set())
    for uid,obj in after.items():
        if obj is before[uid] or obj==before[uid]:continue
        if uid in visible or owners.get(current.baseline.text_owners.get(uid,uid)) in protected:return False
    return True


def refresh(window):
    if window.editor:
        editor=window.editor;manager=getattr(editor,'work_sessions',None);sessions=manager.snapshots() if manager else ()
        cache_context=(id(editor),id(editor.w),id(editor.profile),editor.scope_id,window.canvas.blackbox_peek,palette(window.canvas),
                 hasattr(window,'inspection'),window.pattern.isChecked(),window.cuts.isChecked(),window.internal.isChecked(),
                 tuple((s.id,s.pose_revision,s.owner) for s in sessions),
                 getattr(getattr(window,'diagnostics',None),'native_routing_window_id',None))
        prior=getattr(window,'_overlay_context',None)
        if (prior and cache_context[:1]+cache_context[2:]==prior[:1]+prior[2:]
                and cache_context!=prior and hidden_geometry_only(window,getattr(window,'_overlay_source',None))):
            window._overlay_context=cache_context;window._overlay_source=editor.w
            window.canvas.display_scope((editor.w,id(editor),window.pattern.isChecked(),window.cuts.isChecked(),window.internal.isChecked()),
                (editor.scope_id,window.canvas.blackbox_peek),set())
            window.canvas.viewport().update();return
        if cache_context==getattr(window,'_overlay_context',None):
            reflow_labels(window);window.canvas.viewport().update();return
    selected={item.data(0) for item in window.scene.selectedItems() if isinstance(item.data(0),str)}
    selection_blocker=QSignalBlocker(window.scene)
    clear(window)
    if not window.editor:return
    colors=palette(window.canvas)
    local_pin_color=colors.pin if colors.name=='compact' else colors.pin_target if colors.name=='studio' else '#ffcf5b'
    local=window.editor.w.local_data
    inspect_pins=hasattr(window,'inspection')  # PIN labels now share one exact-anchor painter in every mode.
    def text(label,x,y,color,tip='',offset=0,ident=None,module=None):
        from .module_chrome import ModuleCaption
        item=ModuleCaption(label,native=module=='native',color=color,background=colors.background) if module else QGraphicsSimpleTextItem(label)
        item.setBrush(QColor(color));item.setPos(x,-y)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations,True)
        # Collision placement is performed once after all captions exist,
        # then only when the camera's scale/rotation/DPI changes.
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton);item.setZValue(100031);item.setToolTip(tip)
        if ident:item.setData(0,ident)
        window._overlay_labels.append((item,offset))
        window.scene.addItem(item);window._workspace_overlay_items.append(item);return item
    def rect(bounds,color,tip,ident=None,filled=False,opaque=False,selectable=True,working=False,module=False):
        (x,y),(xx,yy)=bounds;item=LocalFrame(QRectF(x,-yy,xx-x,yy-y),False)
        item.working=working
        pen=QPen(QColor(color));pen.setCosmetic(True);pen.setWidth(2);pen.setStyle(Qt.PenStyle.DashLine)
        if colors.name in ('studio','compact'):
            pen.setWidthF(1.25)
            if module:pen.setStyle(Qt.PenStyle.DashLine);pen.setWidthF(1.5)
        if working:pen.setStyle(Qt.PenStyle.SolidLine)
        item.setPen(pen);item.setBrush(QBrush(Qt.BrushStyle.NoBrush));item.setZValue(100030)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton);item.setToolTip(tip)
        if ident:
            item.setData(0,ident);item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable,selectable)
            item.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if selectable else Qt.MouseButton.NoButton)
        if filled:
            background=LocalFrame(item.rect(),True);background.setPen(QPen(Qt.PenStyle.NoPen))
            background.setZValue(-100000);background.setData(0,ident);background.setToolTip(tip)
            background.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable,selectable)
            background.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if selectable else Qt.MouseButton.NoButton)
            # Hit testing uses full bounds even when the visible fill is absent.
            opacity=1.0 if opaque else (1.0,.3,0.0)[window.canvas.blackbox_peek]
            if working:
                # A fixed warm glow signals a real working session. It is a
                # brush, not an animation or an additional geometry/cache pass.
                light=QLinearGradient(0,0,1,1);light.setCoordinateMode(QGradient.CoordinateMode.ObjectBoundingMode)
                light.setColorAt(0,alpha(colors.working_glow,opacity))
                light.setColorAt(.65,alpha(colors.working_fill,opacity))
                light.setColorAt(1,alpha(colors.local_fill,opacity))
                background.setBrush(QBrush(light))
            else:background.setBrush(alpha(colors.local_fill,opacity))
            window.scene.addItem(background);window._workspace_overlay_items.append(background)
        window.scene.addItem(item);window._workspace_overlay_items.append(item);return item
    from .regions.query import object_bounds
    from .regions.models import overlaps
    from .editor import projected
    scope=window.editor.scope_id
    if scope not in local.regions:scope=None;window.editor.scope_id=None
    from .view_scope import visible_geometry
    candidates=set(window.groups)|getattr(window,'_deferred_graphics',set())
    view,visible,context=visible_geometry(window.editor.w,window.editor.profile,scope,window.canvas.blackbox_peek>0,uids=candidates)
    ownership=view.owners
    shown=list(view.direct_regions)+list(view.nested_regions)
    peeked={uid for uid in visible-context if ownership.get(window.editor.w.baseline.text_owners.get(uid,uid))!=scope}
    previous=getattr(window,'_region_visible',{})
    deferred = getattr(window, '_deferred_graphics', set()) & visible
    if deferred:
        from .presentation.layout_scene import refresh_graphics
        refresh_graphics(window, set(deferred), projected(window.editor.w), force=True)
    changed=set()
    for uid,graphics in window.groups.items():
        show=uid in visible
        opacity=.35 if uid in context else (.35 if uid in peeked and window.canvas.blackbox_peek==1 else 1.0)
        for part in graphics.parts.values():
            part.setVisible(show);part.setOpacity(opacity)
            part.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable,uid not in peeked)
            part.setAcceptedMouseButtons(Qt.MouseButton.NoButton if uid in peeked else Qt.MouseButton.AllButtons)
        if previous.get(uid,(True,1.0))!=(show,opacity):changed.add(uid)
    window._region_visible={uid:(uid in visible,next(iter(g.parts.values())).opacity() if g.parts else 1.0) for uid,g in window.groups.items()}
    window._displayed_uids=visible;window._peek_uids=peeked;window._displayed_regions=[r.id for r in shown]+([scope] if scope else [])
    window.canvas.display_scope((window.editor.w,id(window.editor),window.pattern.isChecked(),window.cuts.isChecked(),window.internal.isChecked()),
        (scope,window.canvas.blackbox_peek),changed)
    objects=projected(window.editor.w)
    for uid in sorted(visible):
        group=window.groups.get(uid)
        native=window.editor.w.layout_connectivity.instances.get(uid) if window.editor.w.layout_connectivity else None
        if group and (getattr(group,'native_box',False) or native and native.black_box):
            bounds=object_bounds(window.editor.w,objects[uid],window.editor.profile)
            if bounds:
                name=objects[uid].attributes.get('name',uid[:8])
                node=window.editor.w.baseline.display.get('nodes',{}).get(objects[uid].attributes.get('master_key'))
                cell=node[2] if node and len(node)>2 else (native.master[1] if native else '')
                caption=text(name+(' · '+cell if cell else ''),bounds[0][0],bounds[1][1],colors.native_label,
                    name+'：原生模块不能进入内部；当层可整体移动、旋转和镜像。',-24,uid,module='native')
                caption.module_bounds=QRectF(bounds[0][0],-bounds[1][1],bounds[1][0]-bounds[0][0],bounds[1][1]-bounds[0][1])
    for group in local.groups.values():
        if not set(group.object_uids)&visible:continue
        bounds=group_bounds(window.editor.w,group)
        notes=[a.text for a in local.annotations.values() if a.group_id==group.id and a.text]
        rect(bounds,colors.group,group.name+'\n'+'\n'.join(notes))
        label=group.name+(' · '+notes[0].splitlines()[0][:45] if notes else '')
        text(label,bounds[0][0],bounds[1][1],colors.group,'\n'.join(notes),-22)
    for pin in local.pins.values():
        r=rect(pin.bbox,local_pin_color,f'{pin.name} · {pin.net} · 仅本地标记')
        window._local_pin_items.append(r)
        if not inspect_pins:
            label=text(pin.name+' [LOCAL]',pin.bbox[0][0],pin.bbox[1][1],local_pin_color);window._local_pin_items.append(label)
    if scope:shown=[local.regions[scope],*shown]
    sessions=getattr(window.editor,'work_sessions',None)
    for region in shown:
        session=sessions.session_for(region.id) if sessions else None
        color=colors.working_border if session else colors.local_border
        tip=f'{region.name}\nID: {region.id}\n{region.note}'
        if session:tip+=f'\n{session.owner} 正在工作 · 本操作层级已锁定'
        rect(region.bbox,color,tip,region.id,filled=region.id!=scope,opaque=region in view.nested_regions,
             selectable=region.parent_id==scope,working=bool(session),module=True)
        if session:suffix=' · '+session.owner+' 工作中'
        elif colors.name=='compact':suffix=''
        elif colors.name=='studio':suffix=' · 当前层' if region.id==scope else ' · 操作区'
        else:suffix=' [内部]' if region.id==scope else ' [模块]'
        text(region.name+suffix,region.bbox[0][0],region.bbox[1][1],colors.working_border if session else colors.local_label,tip,-24,region.id,module='local')
        for pin in region.pins.values():
            if not inspect_pins:rect(pin.bbox,local_pin_color,pin.id)
            if not inspect_pins:text(pin.name,pin.bbox[0][0],pin.bbox[1][1],local_pin_color,pin.id)
    box_scopes={scope,None}
    ancestor=local.regions[scope].parent_id if scope else None
    while ancestor:box_scopes.add(ancestor);ancestor=local.regions[ancestor].parent_id
    box_scopes.update(view.open_scopes)
    for mark in local.markups.values():
        if mark.scope_id not in box_scopes:continue
        rect(mark.bbox,colors.markup,mark.id+'\n'+mark.text,mark.id,selectable=mark.scope_id==scope)
        text(mark.text.splitlines()[0][:50] if mark.text else '定位框 '+mark.id[:13],mark.bbox[0][0],mark.bbox[1][1],colors.markup,mark.id,-20,mark.id)
    for keep in local.keepouts.values():
        if keep.scope_id not in box_scopes:continue
        rect(keep.bbox,colors.keepout,keep.id+'\n'+keep.note,keep.id,selectable=keep.scope_id==scope)
        text('禁布 '+', '.join(keep.layers) if keep.layers else '范围：全部开放',keep.bbox[0][0],keep.bbox[1][1],colors.keepout,keep.id,ident=keep.id)
    from .native_routing_windows import describe
    for opening in local.native_routing_windows.values():
        if opening.owner_uid not in visible or opening.owner_uid in context:continue
        row=describe(window.editor.w,opening,window.editor.profile,objects)
        if row['effective_bounds_um'] is None:continue
        scale=window.editor.profile.dbu_per_micron;b=[v*scale for v in row['effective_bounds_um']]
        bounds=((b[0],b[1]),(b[2],b[3]));color='#61c4a7' if opening.enabled else '#80858c'
        label=opening.name+' · '+', '.join(opening.layers)+('（停用）' if not opening.enabled else '')
        frame=rect(bounds,color,label,selectable=False)
        frame.setData(1,opening.id)
        if opening.id==getattr(getattr(window,'diagnostics',None),'native_routing_window_id',None):
            color='#ffd16a'
            pen=QPen(QColor(color),2.5);pen.setCosmetic(True);frame.setPen(pen)
            fill=QColor(color);fill.setAlpha(30);frame.setBrush(QBrush(fill));frame.setZValue(100032)
        # Keep the exemption frame/focus and hover identity; its name/layers
        # belong in the property list, not as another canvas label over PINs.
    for item in window._workspace_overlay_items:
        if item.data(0) in selected and item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:item.setSelected(True)
    del selection_blocker
    window._overlay_context=cache_context
    window._overlay_source=window.editor.w
    reflow_labels(window)
    window.canvas.viewport().update()

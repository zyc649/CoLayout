"""Screen-sized PIN labels and physical metal/via tracing, entirely local."""
from PySide6.QtCore import QRectF,QPointF,Qt,QTimer
from PySide6.QtGui import QColor,QPen,QBrush,QPainterPath,QFont,QFontMetricsF,QTransform
from .inspection_data import scope_pins,build_scope_graph
from .net_selection import select_net
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from .theme import palette,alpha,NET_ACCENTS,net_fill
from .pin_projection import prepared_record,facts,PinFrameCache


def polygon_path(geometry):
    path=QPainterPath();path.setFillRule(Qt.FillRule.OddEvenFill)
    pieces=[geometry] if geometry.geom_type=='Polygon' else getattr(geometry,'geoms',[])
    for polygon in pieces:
        if polygon.geom_type!='Polygon':continue
        for ring in (polygon.exterior,*polygon.interiors):
            pts=list(ring.coords)
            if not pts:continue
            path.moveTo(pts[0][0],-pts[0][1])
            for x,y in pts[1:]:path.lineTo(x,-y)
            path.closeSubpath()
    return path


class InspectionView:
    """Main-view PIN projection and asynchronous, revision-bound local net selection."""
    def __init__(self,window):
        self.window=window;self.pin_key=None;self.records=[];self.pin_warnings=[];self.pin_hits=[]
        self._pin_cache=OrderedDict();self._pin_sources={}
        self._pin_frame=PinFrameCache();self._pin_geometry_revision=0;self._paint_revision=0;self._hits_context=None
        self.graph=None;self.graph_key=None;self.pending=None;self.trace=None;self.highlight=[]
        self.highlighted_owners=set()
        self._color_index=-1
        self.conflict_points=[]
        self.preview=None
        self.focus_region=None;self.focus_net=None;self.focus_pin_id=None;self.focus_owners=set()
        self._executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='local-net-view');self._future=None
        self._timer=QTimer(window);self._timer.setInterval(20);self._timer.timeout.connect(self._poll)
        window.destroyed.connect(lambda:self._executor.shutdown(wait=False,cancel_futures=True))
        window.canvas.inspection_overlay=self.paint
        window.canvas.inspection_clicked.connect(self.pick)
        window.canvas.inspection_clear.connect(self.clear_trace)

    @property
    def computing(self):return self._future is not None

    def workspace(self):
        e=self.window.editor
        return self.preview.workspace if self.preview and self.preview.current(e) else e.w

    def set_preview(self,preview=None):
        if preview is self.preview:return
        self.preview=preview;self.graph=None;self.graph_key=None;self.pin_key=None
        self.clear_trace();self.refresh()

    def preview_hit(self,x,y):
        if self.preview and self.preview.current(self.window.editor):
            return self.preview.hit(x,y,3/max(abs(self.window.canvas.transform().m11()),1e-12))
        return None

    def close(self):
        self._timer.stop();self.pending=None
        if self._future:self._future.cancel()
        self._future=None
        self._executor.shutdown(wait=False,cancel_futures=True)

    @property
    def dim_active(self):
        if self.trace:return bool(self.trace['nodes'] or self.trace['target_pin_ids'])
        selected=self.pending.get('pin_id') if self.pending else self.focus_pin_id
        return bool(selected and selected in {r['pin']['id'] for r in self.records})

    def highlights_owner(self,uid):
        return self.trace is not None and uid in self.highlighted_owners

    def clear_trace(self):
        self._paint_revision+=1
        was_active=bool(self.trace or self.pending)
        had_focus=bool(self.focus_region or self.focus_pin_id)
        self.trace=None;self.highlight=[];self.pending=None
        self.conflict_points=[]
        self.highlighted_owners=set()
        self.focus_region=None;self.focus_net=None;self.focus_pin_id=None;self.focus_owners=set()
        if had_focus:self.pin_key=None;self.refresh()
        self.window.canvas.viewport().update()
        if was_active:self.window.status.setText('网络高亮已清除，可继续选择和移动对象。')

    def state_key(self):
        e=self.window.editor
        source=self.workspace() if e else None
        return (id(source.baseline),source.id,source.revision,e.scope_id,self.window.canvas.blackbox_peek>0,id(e),id(e.profile),id(source)) if e else None

    def refresh(self):
        w=self.window
        if not w.editor:self.records=[];self.pin_key=None;return
        state=self.state_key()
        requery=self.pending if self.pin_key and self.pin_key[0][:4]==state[:4] and self.pin_key[0][4]!=state[4] else None
        selected_nets=set(self.trace['nets']) if self.trace else ({self.focus_net} if self.focus_net is not None else set())
        if self.pin_key and self.pin_key[0]!=state:
            # Invalidate physical evidence after every edit, undo or scope change.
            self.graph=None;self.graph_key=None;self.trace=None;self.highlight=[];self.pending=None
            if not self.focus_region or self.pin_key[0][3]!=state[3]:self.focus_region=None;self.focus_net=None;self.focus_pin_id=None
        key=(state,self.focus_region,self.focus_pin_id)
        if key==self.pin_key:return
        self.pin_key=key
        # Routing previews add only conductors, never PINs or placements. Keep
        # their unchanged PIN projection cached while the physical graph above
        # still uses the candidate workspace and is invalidated on every switch.
        context=(w.editor.w,w.editor.profile)
        view_key=(w.editor.scope_id,w.canvas.blackbox_peek>0)
        from .inspection_data import pin_view_signature
        signature=pin_view_signature(*context,*view_key)
        previous=self._pin_sources.get(view_key)
        cached=self._pin_cache.pop(view_key,None)
        if previous is None or signature!=previous[0]:cached=None
        self._pin_sources[view_key]=(signature,*context)
        if cached is None:
            pins,warnings=scope_pins(*context,*view_key)
            from .conduction_rules import ConductionRules
            wells=ConductionRules(w.editor.profile).wells
            pins=[{**pin,'noninteractive_layers':wells} for pin in pins]
            records=[prepared_record(pin,[polygon_path(g) for layer,g in pin['figures']]) for pin in pins]
            cached=(pins,warnings,records)
        if cached[2] is not self.records:self._pin_geometry_revision+=1
        pins,self.pin_warnings,self.records=cached;self._pin_cache[view_key]=cached
        while len(self._pin_cache)>6 or sum(len(r['paths']) for _,_,rows in self._pin_cache.values() for r in rows)>20000:
            expired,_=self._pin_cache.popitem(last=False);self._pin_sources.pop(expired,None)
        self.focus_owners={p['owner'] for p in pins if p.get('preview')}
        region=w.editor.w.local_data.regions.get(self.focus_region)
        if region and self.focus_pin_id in region.pins:self.focus_net=region.pins[self.focus_pin_id].net
        elif self.focus_pin_id:self.focus_region=None;self.focus_net=None;self.focus_pin_id=None
        if requery:
            from .view_scope import view_scope
            visible=view_scope(w.editor.w,w.editor.scope_id,state[4])
            available=(requery.get('pin_id') in {p['id'] for p in pins} if 'pin_id' in requery
                else visible.visible(requery['point'][0]))
            if not available:
                pin=next((p for p in pins if p['net'] in selected_nets),None)
                requery={'pin_id':pin['id']} if pin else None
            if requery:self.request(requery,cycle=False)

    def focus_pin(self,region_id=None,pin_id=None,*,query=True):
        if not region_id or not pin_id:self.clear_trace();return
        region=self.window.editor.w.local_data.regions.get(region_id)
        if region is None or region.id!=self.window.editor.scope_id and region.parent_id!=self.window.editor.scope_id:
            self.clear_trace();return
        if not query:
            self.trace=None;self.pending=None;self.highlight=[];self.conflict_points=[];self.highlighted_owners=set();self._paint_revision+=1
        self.focus_region=region_id;self.focus_pin_id=pin_id;self.pin_key=None;self.refresh()
        if query:self.request({'pin_id':pin_id})

    def hit_pin(self,pixel,*,include_preview=False):
        context=(self.pin_key,QTransform(self.window.canvas.viewportTransform()),self._paint_revision)
        hits=[h for h in self.pin_hits if (include_preview or not h['pin'].get('preview')) and h['rect'].contains(pixel)] if self._hits_context==context else []
        if hits:return min(hits,key=lambda h:(not h['label'],(h['anchor']-pixel).manhattanLength()))
        # Large PIN polygons are clickable across their material, not only at
        # the label anchor. Never turn a native PIN drag into a device move.
        tr=self.window.canvas.viewportTransform();inverse,ok=tr.inverted()
        if ok:
            from .pin_labels import detail_level
            point=inverse.map(pixel)
            for record in self.records:
                pin=record['pin']
                geometry=facts(record)
                if not geometry.bounds.contains(point):continue
                if (pin.get('preview') and not include_preview) or not detail_level(pin,tr,record['paths'],pin['net']==self.focus_net and self.focus_net is not None,geometry):continue
                if any(path.contains(point) for (layer,g),path in zip(pin['figures'],record['paths']) if layer not in pin.get('noninteractive_layers',())):
                    return {'pin':pin,'anchor':pixel,'rect':QRectF(pixel.x()-2,pixel.y()-2,4,4),'label':False}
        return None

    def pick(self,x,y):
        w=self.window
        if not w.editor or w.canvas.region_select:return
        if getattr(w,'region_panel',None) and w.region_panel.mode:return
        point=w.canvas.mapFromScene(QPointF(x,-y));hit=self.hit_pin(QPointF(point),include_preview=True)
        if hit:
            self.clear_trace();self.request({'pin_id':hit['pin']['id']});return
        candidate=self.preview_hit(x,y)
        if candidate:
            self.clear_trace();self.request({'point':candidate});return
        # Ignore overlay frames/labels and peeking geometry when finding metal.
        from .editor import projected
        from .regions.query import owner_map
        from .view_scope import view_scope
        from .conduction_rules import ConductionRules
        rules=ConductionRules(w.editor.profile)
        objects=projected(w.editor.w);visible=view_scope(w.editor.w,w.editor.scope_id,w.canvas.blackbox_peek>0)
        for item in w.canvas.items(point):
            source=item;uid=item.data(0)
            while item is not None and uid is None:
                item=item.parentItem();uid=item.data(0) if item else None
            if uid not in objects or not visible.visible(uid):continue
            obj=objects[uid]
            layer=getattr(source,'style',{}).get('lpp',[None])[0]
            # A well may be highlighted by a connected metal, but never starts
            # an inspection. Ordinary body selection/drag remains unchanged.
            if layer in rules.wells:continue
            if obj.kind in ('inst','mosaic'):
                native=w.editor.w.layout_connectivity.instances.get(uid) if w.editor.w.layout_connectivity else None
                if native and native.black_box or layer not in rules.gates:continue
            elif obj.mpp or obj.kind=='stdVia':
                if layer not in rules.clickable|rules.contact_cuts:continue
            elif not obj.shape or obj.shape.lpp[0] not in rules.clickable:continue
            self.clear_trace()
            self.request({'point':(uid,x,y,layer,3/max(abs(w.canvas.transform().m11()),1e-12))});return
        self.clear_trace()

    @property
    def query_color(self):return NET_ACCENTS[max(0,self._color_index)%len(NET_ACCENTS)]

    def request(self,selection,*,cycle=True):
        if cycle:self._color_index=(self._color_index+1)%len(NET_ACCENTS)
        self._paint_revision+=1
        self.pending=selection;self.trace=None;self.highlight=[]
        # Show intended endpoints immediately; graph computation does not lock
        # the editor, so a press can continue into a PIN drag without a pause.
        if 'pin_id' in selection:
            pin=next((r['pin'] for r in self.records if r['pin']['id']==selection['pin_id']),None)
            if pin:self.focus_net=pin['net']
        if self.graph is not None and self.graph_key==self.state_key():self.apply_trace()
        elif not self.computing:self._start()
        self.window.canvas.viewport().update()

    def _start(self):
        e=self.window.editor
        if not e or not self.pending:return
        self._query_key=self.state_key()
        self._future=self._executor.submit(build_scope_graph,self.workspace(),e.profile,e.scope_id,self.window.canvas.blackbox_peek>0)
        self._timer.start();self.window.status.setText('正在计算本地连通关系；可继续拖动和缩放…')

    def _poll(self):
        if self._future is None or not self._future.done():return
        future=self._future;self._future=None;self._timer.stop()
        if self._query_key!=self.state_key():
            if self.pending:self._start()
            return
        try:self.graph=future.result();self.graph_key=self._query_key
        except Exception as exc:
            self.window.status.setText('本地连通查询未完成：'+str(exc));self.pending=None;return
        self.apply_trace()

    def apply_trace(self):
        if not self.pending:return
        self._paint_revision+=1
        self.trace=select_net(self.graph,**self.pending)
        if not self.trace['nodes'] and not self.trace['target_pin_ids']:
            self.clear_trace();return
        self.highlight=[polygon_path(row['geometry']) for row in self.trace['nodes']+self.trace['vias']]
        self.highlighted_owners={row['owner_uid'] for row in self.trace['nodes']}|{row.get('via_owner_uid') for row in self.trace['vias']}
        from .conflict_overlay import terminals
        self.conflict_points=terminals(self.graph,self.trace)
        message=self.trace['message']+' · 同网目标统一高亮；同时高亮不代表物理已连通；Esc 清除'
        if self.conflict_points:message+=' · × 标记冲突端口，不代表实际短接位置'
        if self.window.canvas.blackbox_peek:message+=' · 已包含透视的一层，深层黑盒仍止于接口'
        self.window.status.setText(message);self.window.canvas.viewport().update()

    def paint(self,painter):
        w=self.window
        if not w.editor:return
        tr=w.canvas.viewportTransform();viewport=QRectF(w.canvas.viewport().rect())
        colors=palette(w.canvas)
        painter.save()
        try:
            dim=self.dim_active
            if dim:painter.fillRect(viewport,alpha(colors.background,colors.net_dim_alpha/255))
            selection=getattr(w,'selection_ui',None)
            object_dim=bool(selection and selection.object_dim_active and not dim)
            if object_dim:selection.dim_background(painter)
            painter.setTransform(tr)
            color=QColor(self.query_color)
            if colors.name=='compact' and self.highlight:
                under=QPen(QColor('#111317'),colors.net_line_width+2);under.setCosmetic(True)
                painter.setPen(under);painter.setBrush(Qt.BrushStyle.NoBrush)
                for path in self.highlight:painter.drawPath(path)
            pen=QPen(color,colors.net_line_width);pen.setCosmetic(True);painter.setPen(pen)
            painter.setBrush(net_fill(self.query_color,colors.background))
            for path in self.highlight:painter.drawPath(path)
            from .pin_labels import render_pins
            targets=self.trace['target_pin_ids'] if self.trace else set()
            touched=self.trace['pin_ids'] if self.trace else set()
            contacts=self.trace['seed_pin_ids']-self.trace['partial_pin_ids'] if self.trace else set()
            active_ids=targets|touched
            selected_ids=frozenset(selection.ids()) if object_dim else frozenset()
            if object_dim:
                from .regions.query import owner_map
                owners=owner_map(w.editor.w);regions=w.editor.w.local_data.regions
            def selected_pin(pin):
                owner=pin['owner'];region=regions.get(owner)
                return owner in selected_ids or owners.get(owner) in selected_ids or bool(region and region.parent_id in selected_ids)
            def active(pin):
                return pin['id'] in active_ids or (self.focus_net is not None and pin['net']==self.focus_net)
            def color_for(pin):
                if w.canvas.drag_visual and w.canvas.drag_visual.pin and pin['id']==w.canvas.drag_visual.pin[1]:return colors.pin_target
                if active(pin):return self.query_color
                if object_dim and not selected_pin(pin):return colors.pin_dim
                return colors.pin_dim if dim else colors.pin
            visual=w.canvas.drag_visual
            human=getattr(w,'human',None)
            preview_pins=human.preview_pins if human else None
            key=(self._pin_geometry_revision,self._paint_revision,QTransform(tr),viewport.width(),viewport.height(),w.canvas.devicePixelRatioF(),
                colors,dim,object_dim,selected_ids,self.focus_net,(id(visual),visual.delta) if visual else None,
                tuple((uid,p.bbox) for uid,p in preview_pins.items()) if preview_pins else None,
                human.preview_bounds if preview_pins else None)
            def render(target):
                records=[visual.pin_record(r) for r in self.records] if visual else self.records
                if preview_pins:
                    from shapely.geometry import box
                    records=[prepared_record({**r['pin'],'boundary_bbox':human.preview_bounds,'owner_bbox':human.preview_bounds},
                        [polygon_path(box(*preview_pins[r['pin']['id']].bbox[0],*preview_pins[r['pin']['id']].bbox[1]))])
                        if r['pin']['id'] in preview_pins else r for r in records]
                return render_pins(target,tr,viewport,records,color_for,active,
                    label_background=colors.pin_label_fill,label_style=colors.pin_label_style)
            self.pin_hits=self._pin_frame.paint(painter,key,render)
            self._hits_context=None if visual or preview_pins else (self.pin_key,QTransform(tr),self._paint_revision)
            if self.trace and self.trace['short_nets']:
                from .conflict_overlay import paint
                paint(painter,tr,viewport,self.conflict_points,colors.pin_error)
            if self.trace or self.pending:
                painter.resetTransform();font=QFont('Microsoft YaHei UI');font.setPixelSize(12);painter.setFont(font)
                text=self.trace['message'] if self.trace else '正在计算本地连通关系…'
                metrics=QFontMetricsF(font);width=max(1,min(viewport.width()-16,metrics.horizontalAdvance(text)+16))
                badge=QRectF(8,viewport.height()-34,width,26)
                painter.setPen(QPen(QColor(colors.pin_error) if self.trace and self.trace['short_nets'] else color,1));painter.setBrush(QColor(colors.net_badge));painter.drawRoundedRect(badge,4,4)
                painter.drawText(badge.adjusted(6,0,-6,0),Qt.AlignmentFlag.AlignVCenter,metrics.elidedText(text,Qt.TextElideMode.ElideRight,int(width-12)))
        finally:painter.restore()

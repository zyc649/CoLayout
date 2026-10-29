"""Disposable transforms of existing graphics; no model edits during mouse motion.

Large scenes split only the moving owners out of the vector cache once. Each
mouse move then changes a transform, not the cached polygons or whole scene.
"""
from PySide6.QtCore import QPointF
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QGraphicsRectItem
from .render import box_rect
from .regions.query import members,descendants
from .geometry import box


class DragVisual:
    def __init__(self,window,idents=(),pin=None):
        self.window=window;self.ids=set(idents);self.pin=pin;self.delta=(0,0);self.native=set();self.regions=set()
        local=window.editor.w.local_data
        for uid in idents:
            if uid in local.regions:
                self.regions.update(descendants(window.editor.w,uid));self.native.update(members(window.editor.w,uid))
            elif uid in window.groups:self.native.add(uid)
        self.native.update(u for u,parent in window.editor.w.baseline.text_owners.items() if parent in self.native)
        self.overlay_ids=self.ids|self.regions
        self.overlay_ids.update(self.native)  # Screen-sized native module captions follow whole/subtree moves.
        self.overlay_ids.update(r.id for r in (*local.markups.values(),*local.keepouts.values()) if r.scope_id in self.regions)
        self.cache_native={uid for uid in self.native if uid in window.groups and any(p.isVisible() for p in window.groups[uid].parts.values())}
        self.parts=[part for uid in self.cache_native for part in window.groups[uid].parts.values()]
        self.items=[item for item in window._workspace_overlay_items if item.data(0) in self.overlay_ids]
        self.originals=[(item,item.pos()) for item in (*self.parts,*self.items)]
        self.moving_cache=None;self.stationary_cache=None;self.original_cache=None
        canvas=window.canvas
        if canvas.preview_enabled and canvas.large_scene and self.cache_native:
            canvas.prepare_preview()
            if canvas._vectors and self.cache_native:
                self.original_cache=canvas._vectors
                self.stationary_cache,self.moving_cache=self.original_cache.split(self.cache_native)
                self.cache_revision=canvas._revision
                canvas._vectors=self.stationary_cache
        canvas.drag_visual=self

    def move(self,delta):
        self.delta=delta;dx,dy=delta
        for item,pos in self.originals:item.setPos(pos+QPointF(dx,-dy))
        self.window.canvas.viewport().update()

    def paint_vectors(self,painter,visible,scale):
        if not self.moving_cache:return
        dx,dy=self.delta;painter.save()
        try:
            painter.translate(dx,-dy);inverse,ok=painter.worldTransform().inverted()
            if ok:self.moving_cache.paint(painter,visible.translated(-dx,dy),scale,inverse)
        finally:painter.restore()

    def pin_record(self,record):
        pin=record['pin']
        if not ((self.pin and pin['id']==self.pin[1]) or pin['owner'] in self.native|self.regions):return record
        dx,dy=self.delta;pin=dict(pin)
        if not self.pin:
            for key in ('owner_bbox','boundary_bbox'):
                if pin.get(key):pin[key]=box(pin[key],(1,0,0,1,dx,dy))
        from .pin_projection import translated_record
        return translated_record(record,pin,dx,-dy)

    def close(self):
        for item,pos in self.originals:
            try:item.setPos(pos)
            except RuntimeError:pass  # Workspace refresh already replaced the display items.
        canvas=self.window.canvas;canvas.drag_visual=None
        if self.moving_cache:
            if canvas._vectors is self.stationary_cache and canvas._revision==self.cache_revision:
                canvas._vectors=self.original_cache
            else:
                # Model/style changes can cancel a gesture after invalidation.
                # Never restore a stale snapshot over a newer display.
                canvas.invalidate_preview(self.cache_native)
        canvas.viewport().update()


class RectVisual(DragVisual):
    """Transform only this rect's disposable rendering, including vector cache."""
    def __init__(self,window,ident,bounds):
        super().__init__(window,[ident]);self.bounds=bounds;self.matrix=QTransform()
        self.transforms=[(part,QTransform(part.transform())) for part in self.parts]

    def resize(self,bounds):
        old=box_rect(self.bounds);new=box_rect(bounds)
        sx=new.width()/old.width();sy=new.height()/old.height()
        self.matrix=QTransform(sx,0,0,sy,new.x()-sx*old.x(),new.y()-sy*old.y())
        for part,tr in self.transforms:part.setTransform(tr*self.matrix)
        self.window.canvas.viewport().update()

    def paint_vectors(self,painter,visible,scale):
        if not self.moving_cache:return
        painter.save()
        try:
            painter.setWorldTransform(self.matrix,True);inverse,ok=painter.worldTransform().inverted()
            local,valid=self.matrix.inverted()
            if ok and valid:self.moving_cache.paint(painter,local.mapRect(visible),scale,inverse)
        finally:painter.restore()

    def close(self):
        for part,tr in self.transforms:
            try:part.setTransform(tr)
            except RuntimeError:pass
        super().close()


class FrameVisual:
    def __init__(self,window,ident):
        self.window=window;self.items=[]
        for item in window._workspace_overlay_items:
            if item.data(0)==ident:self.items.append((item,item.rect() if isinstance(item,QGraphicsRectItem) else item.pos()))

    def resize(self,bounds):
        for item,original in self.items:
            if isinstance(item,QGraphicsRectItem):item.setRect(box_rect(bounds))
            else:item.setPos(bounds[0][0],-bounds[1][1])
        self.window.canvas.viewport().update()

    def close(self):
        for item,original in self.items:
            try:
                if isinstance(item,QGraphicsRectItem):item.setRect(original)
                else:item.setPos(original)
            except RuntimeError:pass
        self.window.canvas.viewport().update()

"""Sharp vector command cache. Camera motion never scales a rendered bitmap."""
import time
from collections import OrderedDict
from PySide6.QtCore import Qt,QTimer,Signal
from PySide6.QtGui import QPainter,QColor,QPen,QPalette
from PySide6.QtWidgets import QGraphicsView,QStyleOptionGraphicsItem
from .vector_preview import VectorCache, VectorRecords
from .theme import palette

# Native PCell contacts already cost a frame at a few thousand Qt items.
# Compile before that point; this is the existing exact vector renderer.
VECTOR_CACHE_THRESHOLD = 1500

class PreviewView(QGraphicsView):
    preview_mode=Signal(str)
    def __init__(self,scene):
        super().__init__(scene)
        # This view supplies its own full-frame renderer. Do not let the base
        # view scroll/blit old viewport pixels and repaint only exposed strips.
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.preview_enabled=True;self.large_scene=False;self._vectors=None;self._records=VectorRecords()
        self._dirty=None;self._revision=0;self._mode='';self._building=False
        self.owner_ids=None;self.owner_items=None
        self.overlay_items=None
        self.owner_selection_rect=None
        self.drag_visual=None
        self._scope_cache=OrderedDict();self._scope_context=None;self._scope_key=None;self.scope_cache_hits=0
        self._build_timer=QTimer(self);self._build_timer.setSingleShot(True);self._build_timer.timeout.connect(self.prepare_preview)
        self.preview_stats={'vector_frames':0,'batch_frames':0,'raster_frames':0,'invalidations':0,'build_ms':[],'bytes':0,'compiled_batches':0,'drawn_batches':0,
                            'translated_owners':0,'translation_ms':[]}
        scene.selectionChanged.connect(self.refresh_selection)

    def setBackgroundBrush(self,brush):
        super().setBackgroundBrush(brush)
        # At fractional Windows DPI the viewport can end halfway through a
        # device pixel. Qt's scene background may leave that final column to
        # the viewport's Base brush; it must match the cached renderer too.
        viewport=self.viewport();colors=viewport.palette();color=self.backgroundBrush().color()
        colors.setColor(QPalette.ColorRole.Base,color);colors.setColor(QPalette.ColorRole.Window,color)
        viewport.setPalette(colors)

    def refresh_selection(self):
        # Selection is a view overlay, outside the cached native item paints.
        # Scene selection alone does not reliably schedule a viewport repaint.
        # Repaint only: geometry commands remain valid and must not recompile.
        self.viewport().update()

    def configure_preview(self,primitives,*,changed_owners=None):
        large=primitives>=VECTOR_CACHE_THRESHOLD
        if self.large_scene!=large:changed_owners=None
        self.large_scene=large;self.invalidate_preview(changed_owners)

    def set_preview_enabled(self,enabled):
        self.preview_enabled=bool(enabled);self.invalidate_preview()

    def invalidate_preview(self,owners=None,*,translations=None,geometry=True):
        if owners is not None:owners=set(owners)
        if geometry:self._records.clear(owners)
        self._scope_cache.clear()
        self._revision+=1;self.preview_stats['invalidations']+=1
        if owners is None:self._vectors=None;self._dirty=None
        elif self._vectors is not None:
            owners=set(owners);satisfied=set()
            if translations and not self._dirty and self.preview_enabled and self.large_scene and self.drag_visual is None:
                start=time.perf_counter()
                satisfied=self._vectors.translate_owners({u:delta for u,delta in translations.items() if u in owners})
                if satisfied:
                    self.preview_stats['translated_owners']+=len(satisfied)
                    self.preview_stats['translation_ms']=(self.preview_stats['translation_ms']+[(time.perf_counter()-start)*1000])[-32:]
                    self.preview_stats['bytes']=self._vectors.bytes
                    self.preview_stats['compiled_batches']=self._vectors.compiled
            if self._dirty is None:self._dirty=set()
            self._dirty.update(owners-satisfied)
        if self.preview_enabled and self.large_scene:self._build_timer.start(0)
        self.viewport().update()

    def display_scope(self,context,key,changed):
        """Reuse compiled, read-only views across navigation. Edits invalidate all views."""
        # Compare workspace identity, never deep-compare an entire imported document.
        same=self._scope_context is not None and self._scope_context[0] is context[0] and self._scope_context[1:]==context[1:]
        if not same:
            self._scope_cache.clear();self._scope_context=context;self._scope_key=key
            if changed:self.invalidate_preview(changed,geometry=False)
            return
        if key==self._scope_key:
            if changed:self.invalidate_preview(changed,geometry=False)
            return
        if self.preview_enabled and self.large_scene:
            if self._vectors is not None and not self._dirty:
                size=self.preview_stats['bytes']
                if size<=64*1024*1024:self._scope_cache[self._scope_key]=(self._vectors,size)
            cached=self._scope_cache.pop(key,None)
            while len(self._scope_cache)>3 or sum(size for _,size in self._scope_cache.values())>64*1024*1024:
                self._scope_cache.popitem(last=False)
            self._vectors=cached[0] if cached else None;self._dirty=set()
            if cached:self.preview_stats['bytes']=cached[1];self.scope_cache_hits+=1
            else:self._build_timer.start(0)
        elif changed:self.invalidate_preview(changed,geometry=False)
        self._scope_key=key;self.viewport().update()

    def prime_vector_records(self,provider):
        if not self.preview_enabled or not self.large_scene or self.owner_ids is None:return
        compiler=VectorCache(self.scene().itemsBoundingRect())
        for uid in self.owner_ids():self._records.rows(uid,provider(uid),compiler)

    def wheel_activity(self):
        # No old image, deferred refinement or per-zoom cache.
        pass

    def prepare_preview(self):
        self._build_timer.stop()
        if self._building or not self.preview_enabled or not self.large_scene:return
        if self._vectors is not None and not self._dirty:return
        if self.owner_ids is None or self.owner_items is None:return
        start=time.perf_counter();self._building=True
        try:
            if self._vectors is None:
                self._vectors=VectorCache(self.scene().itemsBoundingRect());owners=self.owner_ids()
            else:owners=self._dirty
            self._vectors.update(owners,self.owner_items,record_cache=self._records);self._dirty=set()
            self.preview_stats['bytes']=self._vectors.bytes
            self.preview_stats['compiled_batches']=self._vectors.compiled
        finally:self._building=False
        self.preview_stats['build_ms']=(self.preview_stats['build_ms']+[(time.perf_counter()-start)*1000])[-32:]

    def paintEvent(self,event):
        if self.preview_enabled and self.large_scene:self.prepare_preview()
        if not self.preview_enabled or not self.large_scene or self._vectors is None:
            self.preview_stats['vector_frames']+=1;self._set_mode('精细几何')
            super().paintEvent(event)
            painter=QPainter(self.viewport())
            try:self.paint_selection(painter)
            finally:painter.end()
            return
        self._set_mode('实时矢量')
        painter=QPainter(self.viewport())
        try:
            painter.fillRect(event.rect(),QColor(palette(self).background))
            tr=self.viewportTransform();inverse,ok=tr.inverted()
            if not ok:return
            painter.setTransform(tr)
            visible=self.mapToScene(self.viewport().rect()).boundingRect()
            scale=max(abs(tr.m11())+abs(tr.m12()),abs(tr.m21())+abs(tr.m22()))*self.devicePixelRatioF()
            overlays=sorted(self.overlay_items(),key=lambda item:item.zValue()) if self.overlay_items else ()
            self.paint_overlays(painter,foreground=False,items=overlays)
            self.preview_stats['drawn_batches']=self._vectors.paint(painter,visible,scale,inverse)
            if self.drag_visual:self.drag_visual.paint_vectors(painter,visible,scale)
            self.paint_overlays(painter,items=overlays)
            self.paint_selection(painter)
        finally:painter.end()
        self.preview_stats['vector_frames']+=1;self.preview_stats['batch_frames']+=1

    def paint_overlays(self,painter,foreground=True,*,items=None):
        # Local metadata is small and changes independently of native geometry.
        # The batch renderer bypasses Qt scene painting, so draw these items
        # explicitly, including screen-sized labels, without rebuilding its cache.
        if items is None:
            items=sorted(self.overlay_items(),key=lambda item:item.zValue()) if self.overlay_items else ()
        tr=self.viewportTransform()
        viewport=self.viewport().rect()
        for item in items:
            if not item.isVisible():continue
            if (item.zValue()>=0)!=foreground:continue
            bounds=item.boundingRect();transform=item.deviceTransform(tr)
            # Include cosmetic outlines and the caption's small backdrop.
            # Use deviceTransform so ItemIgnoresTransformations labels stay
            # visible even when their world-space anchor is off screen.
            if not transform.mapRect(bounds).adjusted(-6,-6,6,6).intersects(viewport):continue
            option=QStyleOptionGraphicsItem();option.exposedRect=bounds
            painter.save()
            try:
                painter.setTransform(transform)
                painter.setOpacity(item.effectiveOpacity())
                item.paint(painter,option,self.viewport())
            finally:painter.restore()

    def _set_mode(self,mode):
        if mode!=self._mode:self._mode=mode;self.preview_mode.emit(mode)

    def selection_rectangles(self):
        bounds={}
        for item in self.scene().selectedItems():
            uid=item.data(0)
            if uid not in bounds:
                bounds[uid]=(self.owner_selection_rect(uid) if self.owner_selection_rect else None) or item.sceneBoundingRect()
        return [r for r in bounds.values() if r is not None]

    def paint_selection(self,painter):
        if getattr(self,'selection_ui',None):return
        if self.drag_visual:return
        painter.resetTransform();painter.setPen(QPen(QColor('#fff095'),1,Qt.PenStyle.DashLine));painter.setBrush(Qt.BrushStyle.NoBrush)
        for rect in self.selection_rectangles():painter.drawRect(self.viewportTransform().mapRect(rect))

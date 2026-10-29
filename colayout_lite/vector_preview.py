"""Spatial/size buckets of independent vector commands, never stretched pixels.

Pens and screen-anchored stipple brushes are supplied during playback. Original
scene objects still own picking and DBU geometry. Only dirty owners recompile.
"""
import math
from collections import OrderedDict
from dataclasses import dataclass
from PySide6.QtCore import Qt,QRectF,QPointF
from PySide6.QtGui import QPicture,QPainter,QPainterPath,QPen,QBrush,QColor,QFontMetricsF,QTransform
from .render import NativeFigureItem,PreviewRectItem,PreviewTextItem

@dataclass
class Batch:
    picture: QPicture
    rectangles: QPainterPath
    bounds: QRectF
    pen: QPen
    brush: QBrush
    pixel_min: float
    size_max: float
    textured: bool
    count: int
    opacity: float = 1.0
    has_picture: bool = True

class VectorCache:
    def __init__(self,extent):
        self.tile=max(extent.width(),extent.height(),1)/16
        self.owners={};self.records={};self.batches={};self.ordered=[];self.compiled=0

    def _record(self,item,*,include_hidden=False):
        if not include_hidden and not item.isVisible():return None
        text=False;textured=False;pen=QPen(Qt.PenStyle.NoPen);brush=QBrush(Qt.BrushStyle.NoBrush)
        if isinstance(item,NativeFigureItem):
            path=item.path();pen=item.pen();s=item.style;fill=s['fill_style'] or 'outline'
            if item.patterned and 'opaque_type' not in item.figure['geometry']:
                if fill in ('stipple','solid'):pen=QPen(Qt.PenStyle.NoPen)
                if fill not in ('outline','none'):
                    if 'Solid' in fill or fill=='solid':brush=QBrush(QColor(*s['fill_rgb']))
                    elif item.texture is not None:brush=QBrush(item.texture);textured=True
            signature=('native',item.figure['style'],item.patterned,'opaque_type' in item.figure['geometry'])
        elif isinstance(item,PreviewRectItem):
            path=QPainterPath();path.addRect(item.rect());pen=item.pen();brush=item.brush();signature=('border',)
        elif isinstance(item,PreviewTextItem):
            if not item.text():return None
            path=None;brush=item.brush();pen=QPen(brush.color());text=True;signature=('text',brush.color().rgba())
        else:return None
        tr=item.sceneTransform()
        if text:
            bounds=tr.mapRect(item.boundingRect())
            drawing=('text',item.text(),item.font(),tr,QFontMetricsF(item.font()).ascent())
        elif isinstance(item,NativeFigureItem) and item.figure['kind']=='rect' and (
                tr.m12()==0 and tr.m21()==0 or tr.m11()==0 and tr.m22()==0) and tr.isAffine():
            # Exact orthogonal rectangle mapping; avoid constructing a path
            # and five temporary corner elements for every PCell contact.
            bounds=tr.mapRect(path.boundingRect());drawing=('rect',bounds)
        else:
            path=tr.map(path);bounds=path.boundingRect();drawing=('path',path)
            if path.elementCount()==5:
                x,y,xx,yy=bounds.left(),bounds.top(),bounds.right(),bounds.bottom()
                corners={(x,y),(x,yy),(xx,y),(xx,yy)}
                if all((element.x,element.y) in corners for element in (path.elementAt(i) for i in range(5))):
                    drawing=('rect',bounds)
        size=min(bounds.width(),bounds.height()) if text else max(bounds.width(),bounds.height())
        if size<=0:size=max(bounds.width(),bounds.height(),1)
        bucket=math.floor(math.log2(max(size,1e-9)))
        parent=item.parentItem();z=parent.zValue() if parent else item.zValue()
        penkey=(pen.color().rgba(),pen.widthF(),pen.style().value,tuple(pen.dashPattern()),pen.dashOffset())
        key=(z,signature,penkey,brush.style().value,bucket,
             math.floor(bounds.center().x()/self.tile),math.floor(bounds.center().y()/self.tile),item.effectiveOpacity())
        return key,(drawing,bounds,pen,brush,7.0 if text else .65,size,textured)

    def update(self,owner_ids,provider,*,record_cache=None):
        dirty=set()
        for uid in owner_ids:
            for key in self.owners.pop(uid,()):
                self.records[key].pop(uid,None);dirty.add(key)
            grouped={}
            items=provider(uid)
            rows=record_cache.rows(uid,items,self) if record_cache is not None and items else [(item,self._record(item)) for item in items]
            for item,rec in rows:
                if rec is not None and item.isVisible():
                    key,row=rec;bounds=row[1]
                    key=(*key[:5],math.floor(bounds.center().x()/self.tile),math.floor(bounds.center().y()/self.tile),item.effectiveOpacity())
                    grouped.setdefault(key,[]).append(row)
            if grouped:self.owners[uid]=set(grouped)
            for key,records in grouped.items():self.records.setdefault(key,{})[uid]=records;dirty.add(key)
        self._rebuild(dirty)

    def translate_owners(self,translations):
        """Reuse geometry for externally certified, pure scene translations.

        This cache cannot prove a model edit is only a translation. The caller
        must certify unchanged geometry/style/visibility before supplying it.
        Unknown owners remain unsatisfied so the caller can use normal reload.
        Replace complete rows: split views may share their immutable Qt values.
        """
        prepared={}
        for uid,delta in translations.items():
            keys=self.owners.get(uid)
            if not keys:continue
            try:
                dx,dy=delta
                if not all(math.isfinite(v) for v in (dx,dy)):continue
                tr=QTransform.fromTranslate(dx,dy)
            except (TypeError,ValueError,OverflowError):continue
            groups={};supported=True
            for key in keys:
                for drawing,bounds,pen,brush,pixel_min,size,textured in self.records[key][uid]:
                    bounds=bounds.translated(dx,dy)
                    if drawing[0]=='rect':drawing=('rect',drawing[1].translated(dx,dy))
                    elif drawing[0]=='path':drawing=('path',tr.map(drawing[1]))
                    elif drawing[0]=='text':
                        _,text,font,old_transform,ascent=drawing
                        drawing=('text',text,font,old_transform*tr,ascent)
                    else:supported=False;break
                    moved_key=(*key[:5],math.floor(bounds.center().x()/self.tile),
                               math.floor(bounds.center().y()/self.tile),*key[7:])
                    groups.setdefault(moved_key,[]).append((drawing,bounds,pen,brush,pixel_min,size,textured))
                if not supported:break
            if supported:prepared[uid]=groups
        dirty=set()
        for uid,groups in prepared.items():
            for key in self.owners[uid]:
                self.records[key].pop(uid);dirty.add(key)
            self.owners[uid]=set(groups)
            for key,rows in groups.items():
                self.records.setdefault(key,{})[uid]=rows;dirty.add(key)
        if dirty:self._rebuild(dirty)
        return set(prepared)

    def split(self,owner_ids):
        """Read-only gesture views of already compiled geometry.

        Reuse intact batches. Only batches mixing moving and stationary owners
        need regrouping; never walk Qt items or transform their paths again.
        The source remains untouched so cancellation can restore it immediately.
        """
        moving_ids=set(owner_ids)
        stationary=VectorCache(QRectF());moving=VectorCache(QRectF())
        for cache in (stationary,moving):cache.tile=self.tile
        for uid,keys in self.owners.items():
            (moving if uid in moving_ids else stationary).owners[uid]=set(keys)
        mixed=set()
        for key,groups in self.records.items():
            selected={uid:rows for uid,rows in groups.items() if uid in moving_ids}
            remaining={uid:rows for uid,rows in groups.items() if uid not in moving_ids}
            for cache,rows in ((stationary,remaining),(moving,selected)):
                if rows:
                    cache.records[key]=rows
                    if len(rows)==len(groups):cache.batches[key]=self.batches[key]
            if selected and remaining:mixed.add(key)
        for cache in (stationary,moving):cache._rebuild(mixed)
        return stationary,moving

    def _rebuild(self,dirty):
        for key in dirty:
            owner_records=self.records[key]
            if not owner_records:
                self.records.pop(key);self.batches.pop(key,None);continue
            # Independent draw commands preserve overlaps and holes; merging
            # fill paths can cancel opposite-winding/mirrored shapes.
            rows=[r for rs in owner_records.values() for r in rs]
            picture=QPicture();p=QPainter(picture);bounds=QRectF();maxsize=0
            rectangles=QPainterPath();rectangles.setFillRule(Qt.FillRule.WindingFill)
            has_picture=False
            try:
                for drawing,b,pen,brush,pixel_min,size,textured in rows:
                    if drawing[0]=='rect':rectangles.addRect(drawing[1])
                    elif drawing[0]=='text':
                        has_picture=True
                        _,text,font,tr,ascent=drawing
                        p.save();p.setTransform(tr,True);p.setFont(font);p.drawText(QPointF(0,ascent),text);p.restore()
                    else:has_picture=True;p.drawPath(drawing[1])
                    bounds=bounds.united(b);maxsize=max(maxsize,size)
            finally:p.end()
            self.batches[key]=Batch(picture,rectangles,bounds,pen,brush,pixel_min,maxsize,textured,len(rows),
                                   key[-1],has_picture);self.compiled+=1
        self.ordered=[batch for key,batch in sorted(self.batches.items(),key=lambda kv:kv[0])]

    @property
    def bytes(self):
        return sum(b.picture.size()+b.rectangles.elementCount()*32 for b in self.ordered)+sum(
            r[0][1].elementCount()*32 if r[0][0]=='path' else 256
            for groups in self.records.values() for rows in groups.values() for r in rows)

    def paint(self,painter,visible,scale,inverse):
        drawn=0
        for batch in self.ordered:
            if batch.size_max*scale<batch.pixel_min or not batch.bounds.intersects(visible):continue
            painter.setOpacity(batch.opacity)
            painter.setPen(batch.pen);brush=QBrush(batch.brush)
            if batch.textured:brush.setTransform(inverse)
            painter.setBrush(brush)
            if not batch.rectangles.isEmpty():painter.drawPath(batch.rectangles)
            if batch.has_picture:painter.drawPicture(0,0,batch.picture)
            drawn+=1
        painter.setOpacity(1.0)
        return drawn


class VectorRecords:
    """Window-owned exact owner records, independent of visibility/opacity.

    Model/style invalidation removes affected owners before their Qt items die.
    Loading can prepare hidden owners once, instead of stalling the first peek.
    Capacity is bounded; a miss always recompiles from the live scene.
    """
    def __init__(self,budget=64*1024*1024):
        self.budget=budget;self.entries=OrderedDict();self.size=0
    def clear(self,owners=None):
        if owners is None:self.entries.clear();self.size=0
        else:
            for uid in owners:
                found=self.entries.pop(uid,None)
                if found:self.size-=found[1]
    def rows(self,uid,items,compiler):
        found=self.entries.get(uid)
        if found is not None:
            if len(items)==len(found[0]) and all(a is b for a,(b,_) in zip(items,found[0])):
                self.entries.move_to_end(uid);return found[0]
            self.clear([uid])
        rows=[(item,compiler._record(item,include_hidden=True)) for item in items]
        size=sum(512+(r[1][0][1].elementCount()*32 if r and r[1][0][0]=='path' else 0) for _,r in rows)
        if size<=self.budget:
            self.entries[uid]=(rows,size);self.size+=size
            while self.size>self.budget:
                _,(_,cost)=self.entries.popitem(last=False);self.size-=cost
        return rows

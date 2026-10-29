"""Native display cache decoding and Qt geometry rendering (never a write model)."""
from __future__ import annotations

from itertools import groupby
from .display_data import decode_display as decode_display
from .geometry_paths import box_rect as box_rect, figure_path as figure_path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush, QImage, QPixmap, QPainterPath, QPainterPathStroker, QPen, QTransform, QFont
from PySide6.QtWidgets import QGraphicsPathItem,QGraphicsItemGroup,QGraphicsRectItem,QGraphicsSimpleTextItem,QStyleOptionGraphicsItem,QStyle


def unselected_option(item,option):
    if getattr(item.scene(),'preview_capture',False) and option.state & QStyle.StateFlag.State_Selected:
        result=QStyleOptionGraphicsItem(option);result.state &= ~QStyle.StateFlag.State_Selected;return result
    return option


class PreviewGroup(QGraphicsItemGroup):
    def shape(self):
        if getattr(self,'exact_pick_shape',None) is not None:return self.exact_pick_shape
        if getattr(self,'border_only',False):
            path=QPainterPath();path.addRect(self.boundingRect());stroke=QPainterPathStroker();stroke.setWidth(1)
            return stroke.createStroke(path)
        return super().shape()
    def paint(self,painter,option,widget=None):
        # Per-layer groups are picking/stacking containers, not separate
        # instances. The view draws one selection overlay per owner UID.
        pass


class PreviewRectItem(QGraphicsRectItem):
    def paint(self,painter,option,widget=None):super().paint(painter,unselected_option(self,option),widget)


class MissingMasterOutline(PreviewRectItem):
    """A missing full-chip sealring must not intercept every interior click."""
    def shape(self):
        path=QPainterPath();path.addRect(self.rect());stroke=QPainterPathStroker();stroke.setWidth(max(1,self.pen().widthF()))
        return stroke.createStroke(path)


class PreviewTextItem(QGraphicsSimpleTextItem):
    def paint(self,painter,option,widget=None):super().paint(painter,unselected_option(self,option),widget)








def make_texture(style):
    rows=style['stipple']
    if not rows:return None
    image=QImage(len(rows[0]),len(rows),QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    color=QColor(*style['fill_rgb'])
    for y,row in enumerate(rows):
        for x,value in enumerate(row):
            if value:image.setPixelColor(x,y,color)
    return QPixmap.fromImage(image)


class NativeFigureItem(QGraphicsPathItem):
    def __init__(self, figure, style, *, texture=None, patterned=True):
        super().__init__(figure_path(figure))
        self.figure=figure;self.style=style;self.texture=texture;self.patterned=patterned
        pen=QPen(QColor(*style['outline_rgb']))
        pen.setCosmetic(True);pen.setWidthF(max(1,style['line_width']))
        bits=style['line_pattern']
        if bits and not all(bits):
            start=bits.index(1) if 1 in bits else 0
            cycle=bits[start:]+bits[:start]
            runs=[float(len(list(values))) for _,values in groupby(cycle)]
            if len(runs)>1:
                if len(runs)%2:runs.append(1.0)
                pen.setDashPattern(runs);pen.setDashOffset(-start)
        if 'opaque_type' in figure['geometry']:
            pen.setColor(QColor('magenta'));pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setZValue(style['priority'])
        self.setData(0,figure['owner_id']);self.setData(1,'detail')
        self.setToolTip(f"{style['lpp'][0]}/{style['lpp'][1]} · {figure['kind']}\n"
                       f"{figure['id']}\nNative bbox (DBU): {figure['bbox']}")

    def paint(self,painter,option,widget=None):
        painter.save()
        if getattr(self,'snapshot_style',None) is not None:
            pen,brush=self.snapshot_style
            painter.setClipPath(self.path(),Qt.ClipOperation.IntersectClip)
            painter.setPen(pen);painter.setBrush(brush);painter.drawPath(self.path())
            painter.restore();return
        style=self.style
        painter.setPen(self.pen())
        brush=QBrush(Qt.BrushStyle.NoBrush)
        fill=style['fill_style'] or 'outline'
        if self.patterned and fill in ('stipple','solid') and 'opaque_type' not in self.figure['geometry']:
            painter.setPen(Qt.PenStyle.NoPen)
        if self.patterned and fill not in ('outline','none') and 'opaque_type' not in self.figure['geometry']:
            if 'Solid' in fill or fill=='solid':brush=QBrush(QColor(*style['fill_rgb']))
            elif self.texture is not None:
                brush=QBrush(self.texture)
                inv,ok=painter.worldTransform().inverted()
                if ok:brush.setTransform(inv)  # stipple size remains in screen pixels
        painter.setBrush(brush)
        painter.drawPath(self.path())
        painter.restore()


def add_label(scene, figure, style):
    text=figure['geometry'].get('text') or ''
    if not text or figure['geometry'].get('visible') is False:return None
    item=PreviewTextItem(text);item.setFont(QFont('Consolas',100));scene.addItem(item)
    item.setBrush(QColor(*style['outline_rgb']))
    box=box_rect(figure['bbox']);own=item.boundingRect()
    orientation=figure['geometry'].get('orientation','R0')
    rotated=orientation in ('R90','R270','MXR90','MYR90')
    width,height=(box.height(),box.width()) if rotated else (box.width(),box.height())
    matrices={'R0':(1,0,0,1),'R90':(0,-1,1,0),'R180':(-1,0,0,-1),'R270':(0,1,-1,0),
              'MX':(1,0,0,-1),'MY':(-1,0,0,1),'MXR90':(0,-1,-1,0),'MYR90':(0,1,1,0)}
    m=matrices.get(orientation,matrices['R0'])
    transform=QTransform(*m,0,0)
    transform.scale(width/max(own.width(),1),height/max(own.height(),1))
    item.setTransform(transform)
    actual=transform.mapRect(own)
    item.setPos(box.left()-actual.left(),box.top()-actual.top())
    item.setZValue(1000+style['priority'])
    item.setToolTip(f"{text}\n{style['lpp']} · {figure['id']}")
    return item


def geometry_audit(scene):
    """Compare every rendered outline's physical extent to native OA extents."""
    mismatches=[];checked=0
    for f in scene['figures']:
        if f['kind'] not in ('rect','polygon','path','pathSeg','ellipse'):continue
        checked+=1
        actual=figure_path(f).boundingRect();expected=box_rect(f['bbox'])
        err=max(abs(actual.x()-expected.x()),abs(actual.y()-expected.y()),
                abs(actual.right()-expected.right()),abs(actual.bottom()-expected.bottom()))
        if err>0.01:mismatches.append({'id':f['id'],'kind':f['kind'],'error_dbu':err,
            'native_bbox':f['bbox'],'render_bbox':[actual.x(),actual.y(),actual.right(),actual.bottom()]})
    return {'checked_figures':checked,'bbox_mismatches':mismatches,'cut_count':scene['cut_count'],
            'unsupported':scene['unsupported'],
            'missing_display_packets':[k for k,v in scene['styles'].items() if not v['definition_found']]}


def owner_bounds_audit(document):
    """Independent check against top-level instance/via bounds from the edit model."""
    mismatches=[];checked=0
    for e in document.entities:
        if e.kind not in ('inst','stdVia','customVia'):continue
        figures=[f for f in document.display['figures'] if f['owner_id']==e.id]
        if not figures:
            mismatches.append({'owner':e.id,'reason':'no expanded figures'});continue
        checked+=1
        bbox=[[min(f['bbox'][0][i] for f in figures) for i in (0,1)],
              [max(f['bbox'][1][i] for f in figures) for i in (0,1)]]
        error=max(abs(bbox[j][i]-e.bbox[j][i]) for j in (0,1) for i in (0,1))
        if error>.01:mismatches.append({'owner':e.id,'kind':e.kind,'error_dbu':error,'expanded':bbox,'native':e.bbox})
    return {'checked_owners':checked,'owner_bbox_mismatches':mismatches}

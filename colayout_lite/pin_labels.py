"""Zoom-dependent PIN presentation with bounded, collision-free screen labels."""
from PySide6.QtCore import Qt,QRectF,QPointF
from PySide6.QtGui import QColor,QPen,QFont,QFontMetricsF
from .pin_projection import facts


def detail_level(pin,tr,paths,emphasized=False,geometry=None):
    """0: hidden, 1: material/marker, 2: marker and eligible label.

    All PIN kinds use the same pixel thresholds. Selection exposes targets at
    overview scales, but labels still obey collision and density limits.
    """
    if emphasized:return 2
    bounds=pin.get('owner_bbox')
    size=0;minor=0
    if bounds:
        (x,y),(xx,yy)=bounds;r=tr.mapRect(QRectF(x,-yy,xx-x,yy-y))
        size=max(r.width(),r.height());minor=min(r.width(),r.height())
    if geometry is not None and tr.m12()==0 and tr.m21()==0:
        figure_size=max(geometry.max_width*abs(tr.m11()),geometry.max_height*abs(tr.m22()))
    else:
        figures=geometry.figures if geometry is not None else (p.boundingRect() for p in paths)
        figure_size=max((max(r.width(),r.height()) for r in (tr.mapRect(b) for b in figures)),default=0)
    label_visible=(size>=180 and minor>=40) if bounds else figure_size>=28
    if label_visible:return 2
    if figure_size>=4 or size>=40 and minor>=6:return 1
    return 0


def render_pins(painter,tr,viewport,records,color_for,emphasized=lambda pin:False,*,label_background='#090c10',label_style='boxed',outline_only=False):
    """Use one placement/hit-test path for both quiet and boxed presentation.

    Plain labels keep the exact marker and leader, without a colored capsule.
    Presentation cannot change PIN identity, scope or the density thresholds.
    """
    plain=label_style=='plain'
    font=QFont('Microsoft YaHei UI');font.setPixelSize(12);font.setBold(not plain)
    strong_font=QFont(font);strong_font.setBold(True)
    painter.setFont(font);metrics=QFontMetricsF(font);strong_metrics=QFontMetricsF(strong_font);occupied=[];labels=[];hits=[]
    inverse,ok=tr.inverted();visible_world=inverse.mapRect(viewport) if ok else None
    # Cull before sorting/formatting. The exact same visible records retain
    # their original priority; off-screen PINs cannot consume label slots.
    records=sorted(((bool(emphasized(r['pin'])),r) for r in records
        if visible_world is None or facts(r).bounds.intersects(visible_world)),
        key=lambda row:(not row[0],row[1]['pin']['id']))
    label_budget=max(1,int(viewport.width()*viewport.height()/(140*28)*.22))
    for strong,record in records:
        geometry=facts(record)
        pin=record['pin'];visible=[]
        level=detail_level(pin,tr,record['paths'],strong,geometry)
        if not level:continue
        color=QColor(color_for(pin))
        painter.setTransform(tr);pen=QPen(color,1.5);pen.setCosmetic(True)
        if pin.get('directional'):pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        fill=QColor(color);fill.setAlpha(0 if outline_only else 28 if plain and not strong else 70);painter.setBrush(fill)
        layers=[l for l,g in pin.get('figures',[])];ignored=set(pin.get('noninteractive_layers',()))
        for i,(path,bounds,inside) in enumerate(zip(record['paths'],geometry.figures,geometry.center_inside)):
            rect=tr.mapRect(bounds)
            if rect.intersects(viewport):
                if level==2 or pin.get('directional'):painter.drawPath(path)
                center=rect.center()
                if not viewport.contains(center) or not inside:
                    screen_path=tr.map(path)
                    clipped=screen_path.intersected(_rectangle(viewport))
                    center=clipped.pointAtPercent(.25) if not clipped.isEmpty() else screen_path.pointAtPercent(.25)
                visible.append((rect,center,layers[i] if i<len(layers) else None))
        if not visible:continue
        painter.resetTransform();pen.setWidthF(1.5);painter.setPen(pen)
        markers=[]
        for rect,center,layer in visible:
            # Dense finger geometry should not become a bright solid stripe in
            # overview. Intermediate detail gives positional hints only.
            if level==1 and any((center-other).manhattanLength()<9 for other in markers):continue
            markers.append(center)
            if plain and strong:
                painter.save();painter.setPen(QPen(QColor(label_background),2));painter.setBrush(color);painter.drawEllipse(center,4,4);painter.restore()
            elif level==1:painter.drawEllipse(center,2,2)
            elif min(rect.width(),rect.height())<7:painter.drawEllipse(center,3.5,3.5)
            if layer not in ignored:hits.append({'rect':QRectF(center.x()-7,center.y()-7,14,14),'pin':pin,'anchor':center,'label':False,'detail':level,'layer':layer})
        if level<2 or len(labels)>=label_budget:continue
        choices=[r for r in visible if r[2] not in ignored] or visible
        rect,anchor,layer=min(choices,key=lambda row:(row[1]-viewport.center()).manhattanLength())
        title=pin['label']
        if not title:continue
        label_metrics=strong_metrics if plain and strong else metrics
        width=label_metrics.horizontalAdvance(title)+10;height=label_metrics.height()+6
        side='right'
        if pin.get('boundary_bbox'):
            (x,y),(xx,yy)=pin['boundary_bbox'];boundary=tr.mapRect(QRectF(x,-yy,xx-x,yy-y))
            side=min(((abs(anchor.x()-boundary.left()),'left'),(abs(anchor.x()-boundary.right()),'right'),
                      (abs(anchor.y()-boundary.top()),'top'),(abs(anchor.y()-boundary.bottom()),'bottom')))[1]
        preferred={'left':(-width-12,-height/2),'right':(12,-height/2),'top':(-width/2,-height-12),'bottom':(-width/2,12)}[side]
        if rect.width()>width+10 and rect.height()>height+4:preferred=(-width/2,-height/2)
        placed=None
        for attempt in range(5):
            shift=((attempt+1)//2)*(height+3)*(1 if attempt%2 else -1) if attempt else 0
            dx,dy=preferred;candidate=QRectF(anchor.x()+dx,anchor.y()+dy+shift,width,height)
            candidate.moveLeft(max(viewport.left()+2,min(candidate.left(),viewport.right()-width-2)))
            candidate.moveTop(max(viewport.top()+2,min(candidate.top(),viewport.bottom()-height-2)))
            if not any(candidate.intersects(other) for other in occupied):placed=candidate;break
        if placed is None:continue  # Keep exact markers; never pile labels or move them far away.
        occupied.append(placed.adjusted(-2,-1,2,1));labels.append((placed,title,color,anchor,strong))
        if layer not in ignored:hits.append({'rect':placed,'pin':pin,'anchor':anchor,'label':True,'detail':level,'layer':layer})
    painter.resetTransform()
    for rect,title,color,anchor,strong in labels:
        closest=QPointF(max(rect.left(),min(anchor.x(),rect.right())),max(rect.top(),min(anchor.y(),rect.bottom())))
        leader=QColor(color)
        if plain:leader.setAlpha(230 if strong else 160)
        painter.setPen(QPen(leader,1.1));painter.drawLine(anchor,closest)
        painter.drawEllipse(anchor,2,2)  # Position remains explicit even when a label is displaced.
    for rect,title,color,anchor,strong in labels:
        fill=QColor(label_background);fill.setAlpha(245)
        painter.setPen(QPen(color,1));painter.setBrush(fill)
        if plain:painter.fillRect(rect,fill)
        else:painter.drawRoundedRect(rect,3,3)
        painter.setFont(strong_font if plain and strong else font)
        painter.drawText(rect.adjusted(5,2,-5,-2),Qt.AlignmentFlag.AlignCenter,title)
    return hits


def _rectangle(rect):
    from PySide6.QtGui import QPainterPath
    path=QPainterPath();path.addRect(rect);return path

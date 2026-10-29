"""Semantic picking independent of fill alpha, rendered internals and frame strokes."""
from PySide6.QtCore import QPointF,QRectF
from .regions.query import children,owner_map


def local_module_at(window,pixel):
    if not window.editor:return None
    p=window.canvas.mapToScene(pixel.toPoint());x,y=p.x(),-p.y()
    return next((r.id for r in children(window.editor.w,window.editor.scope_id)
        if r.bbox[0][0]<=x<=r.bbox[1][0] and r.bbox[0][1]<=y<=r.bbox[1][1]),None)


def native_module_at(window,pixel):
    if not window.editor or not window.editor.w.layout_connectivity:return None
    w=window.editor.w;owners=owner_map(w)
    uid=editable_at(window,pixel)
    native=w.layout_connectivity.instances.get(uid)
    if native and native.black_box and owners.get(uid)==window.editor.scope_id:return uid
    return None


def foreground_frame_at(window,pixel):
    e=window.editor;local=e.w.local_data
    ids={r.id for r in children(e.w,e.scope_id)}|{r.id for r in (*local.markups.values(),*local.keepouts.values()) if r.scope_id==e.scope_id}
    return next((item.data(0) for item in window.canvas.items(pixel.toPoint()) if item.data(0) in ids and item.zValue()>=100030),None)


def editable_at(window,pixel):
    e=window.editor;owners=owner_map(e.w);local=e.w.local_data
    frame_ids={r.id for r in children(e.w,e.scope_id)}|{r.id for r in (*local.markups.values(),*local.keepouts.values()) if r.scope_id==e.scope_id}
    # Prefer actual current-layer material above frames; a keepout should be
    # easy to select in empty space without preventing picking a route on it.
    for item in window.canvas.items(pixel.toPoint()):
        # Foreground borders/captions are intentional frame targets, unlike
        # the transparent frame body beneath actual layout material.
        if item.data(0) in frame_ids and item.zValue()>=100030:return item.data(0)
        uid=item.data(0)
        while item is not None and uid is None:
            item=item.parentItem();uid=item.data(0) if item else None
        if uid in window.groups and owners.get(e.w.baseline.text_owners.get(uid,uid))==e.scope_id:return uid
    p=window.canvas.mapToScene(pixel.toPoint());x,y=p.x(),-p.y()
    frames=[row for row in (*local.markups.values(),*local.keepouts.values()) if row.scope_id==e.scope_id]
    frames.sort(key=lambda r:(r.bbox[1][0]-r.bbox[0][0])*(r.bbox[1][1]-r.bbox[0][1]))
    for row in frames:
        if row.bbox[0][0]<=x<=row.bbox[1][0] and row.bbox[0][1]<=y<=row.bbox[1][1]:return row.id
    return local_module_at(window,pixel)


def handles(window,ident,bounds=None):
    from .bounds_edit import BoundsEdit
    try:_,row=BoundsEdit(window.editor).record(ident)
    except Exception:return []
    if bounds is None:bounds=row.bbox
    (x,y),(xx,yy)=bounds;cx=(x+xx)/2;cy=(y+yy)/2
    positions={'nw':(x,yy),'n':(cx,yy),'ne':(xx,yy),'e':(xx,cy),'se':(xx,y),'s':(cx,y),'sw':(x,y),'w':(x,cy)}
    tr=window.canvas.viewportTransform();result=[]
    for key,(px,py) in positions.items():
        p=tr.map(QPointF(px,-py));result.append((key,QRectF(p.x()-5,p.y()-5,10,10)))
    return result

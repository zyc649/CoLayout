"""Exact local transforms and standard-via display geometry."""
from .model import Shape, Placement, LiteError

ORIENT={'R0':(1,0,0,1),'R90':(0,-1,1,0),'R180':(-1,0,0,-1),'R270':(0,1,-1,0),
        'MX':(1,0,0,-1),'MY':(-1,0,0,1),'MXR90':(0,1,1,0),'MYR90':(0,-1,-1,0)}


def point(p, tr):
    a,b,c,d,x,y=tr
    return a*p[0]+b*p[1]+x,c*p[0]+d*p[1]+y


def transform(origin, orientation, scale=1):
    return tuple(v*scale for v in ORIENT[orientation])+tuple(origin)


def compose(t, u):
    a,b,c,d,x,y=t;e,f,g,h,i,j=u
    return a*e+b*g,a*f+b*h,c*e+d*g,c*f+d*h,a*i+b*j+x,c*i+d*j+y


def box(b, tr):
    (x,y),(xx,yy)=b
    p=[point(v,tr) for v in [(x,y),(x,yy),(xx,y),(xx,yy)]]
    return ((min(v[0] for v in p),min(v[1] for v in p)),(max(v[0] for v in p),max(v[1] for v in p)))


def orientation_after(old, orientation):
    tr=compose(transform((0,0),orientation),transform((0,0),old))[:4]
    return next(k for k,v in ORIENT.items() if v==tr)


def transform_shape(shape, *, delta=(0,0), orientation='R0', pivot=(0,0)):
    r=transform((0,0),orientation);p=point(pivot,r)
    tr=r[:4]+(pivot[0]+delta[0]-p[0],pivot[1]+delta[1]-p[1])
    data=shape.model_dump()
    if shape.kind=='pathSeg' and r[0]*r[3]-r[1]*r[2]<0:
        from .pathseg import mirror_caps
        mirror_caps(shape,data)
    if shape.bbox:data['bbox']=box(shape.bbox,tr)
    if shape.points:data['points']=[point(p,tr) for p in shape.points]
    if shape.origin is not None:
        data['origin']=point(shape.origin,tr);data['orientation']=orientation_after(shape.orientation,orientation)
    return Shape.model_validate(data)


def via_figures(shape, profile):
    vd=profile.vias[shape.via_definition];p=profile.effective_via(shape)
    w,h=p['cutWidth'],p['cutHeight'];rows,cols=p['cutRows'],p['cutColumns'];sx,sy=p['cutSpacing']
    spanx=w*cols+sx*(cols-1);spany=h*rows+sy*(rows-1)
    dx_origin,dy_origin=p.get('originOffset',(0,0));ox,oy=-dx_origin,-dy_origin
    tr=transform(shape.origin,shape.orientation)
    out=[]
    def add(layer,b):
        out.append({'kind':'rect','lpp':[layer,'drawing'],'bbox':box(b,tr),'geometry':{}})
    for row in range(rows):
        for col in range(cols):
            x=-spanx/2+col*(w+sx)-ox;y=-spany/2+row*(h+sy)-oy
            add(vd['cut_layer'],((x,y),(x+w,y+h)))
    for layer,enc,offset in [(vd['layer1'],p['layer1Enc'],p.get('layer1Offset',(0,0))),
                            (vd['layer2'],p['layer2Enc'],p.get('layer2Offset',(0,0)))]:
        dx,dy=offset;ex,ey=enc
        add(layer,((-spanx/2-ex+dx-ox,-spany/2-ey+dy-oy),(spanx/2+ex+dx-ox,spany/2+ey+dy-oy)))
    for name,layer,index in [('imp1Enc',vd.get('implant1'),1),('imp2Enc',vd.get('implant2'),2)]:
        if layer and name in p:
            ex,ey=p[name];base_x,base_y=p[f'layer{index}Enc'];dx,dy=p.get(f'layer{index}Offset',(0,0))
            ex+=base_x;ey+=base_y
            add(layer,((-spanx/2-ex+dx-ox,-spany/2-ey+dy-oy),(spanx/2+ex+dx-ox,spany/2+ey+dy-oy)))
    return out


def shape_figure(shape):
    if shape.kind=='stdVia':raise LiteError('VIA_REQUIRES_PROFILE')
    if shape.kind=='rect':return dict(kind='rect',bbox=shape.bbox,lpp=shape.lpp,geometry={})
    g=dict(points=shape.points,width=shape.width,style=shape.style,
           begin_extension=shape.begin_extension,end_extension=shape.end_extension,
           begin_style=shape.begin_style,end_style=shape.end_style)
    if shape.kind=='pathSeg' and any(s in ('custom','chamfer') for s in (shape.begin_style,shape.end_style)):
        from .pathseg import outline
        g['boundary']=outline(shape)
    if shape.kind=='pathSeg' and shape.width_basis=='oa_diagonal':
        # OA diagonal units are sqrt(2) times the perpendicular distance.
        from math import sqrt
        g['width']/=sqrt(2);g['begin_extension']/=sqrt(2);g['end_extension']/=sqrt(2)
        g['perpendicular_units']=True
    return dict(kind=shape.kind,bbox=((0,0),(0,0)),lpp=shape.lpp,geometry=g)


def rigid_matrix(delta,orientation,pivot):
    r=transform((0,0),orientation);rp=point(pivot,r)
    return r[:4]+(pivot[0]+delta[0]-rp[0],pivot[1]+delta[1]-rp[1])

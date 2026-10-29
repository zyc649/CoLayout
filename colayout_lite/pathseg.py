"""Native PathSeg caps: exact local geometry and end-parameter transforms.

For diagonal segments u/v are sqrt(2) times physical axial distances. The
custom diagonal cuts then use *orthogonal* DBU; on orthogonal segments they
use diagonal DBU instead. Keep that distinction at the API boundary.
"""
from fractions import Fraction

CUSTOM_FIELDS=('left_diagonal','right_diagonal','right_half_width')


def canonical_boundary(points):
    points=[tuple(p) for p in points]
    changed=True
    while changed and len(points)>3:
        changed=False
        for i,b in enumerate(points):
            a=points[i-1];c=points[(i+1)%len(points)]
            u=(b[0]-a[0],b[1]-a[1]);v=(c[0]-b[0],c[1]-b[1])
            if u[0]*v[1]==u[1]*v[0] and u[0]*v[0]+u[1]*v[1]>=0:
                points.pop(i);changed=True;break
    return min(tuple(p[i:]+p[:i]) for p in (points,list(reversed(points))) for i in range(len(p)))


def outline(shape):
    a,b=shape.points;dx=b[0]-a[0];dy=b[1]-a[1]
    diagonal=bool(dx and dy);ux=(dx>0)-(dx<0);uy=(dy>0)-(dy<0);nx,ny=-uy,ux
    length=abs(dx)+abs(dy);half=shape.width//2
    left=shape.begin_custom.right_half_width if shape.begin_custom else (shape.end_custom.right_half_width if shape.end_custom else half)
    right=shape.end_custom.right_half_width if shape.end_custom else left
    pts=[]
    for side,start in [('begin',True),('end',False)]:
        style=getattr(shape,side+'_style');cap=getattr(shape,side+'_custom')
        extension=half if style in ('extend','chamfer') else getattr(shape,side+'_extension')
        if style in ('custom','chamfer'):
            factor=2 if diagonal else 1
            # IC618 rounds the implicit diagonal cut to nearest DBU, but
            # truncates the orthogonal 3/4 cut. These are distinct rules.
            dl,dr=(cap.left_diagonal,cap.right_diagonal) if cap else (((shape.width+1)//3,)*2 if diagonal else ((3*shape.width//4,)*2))
            dl*=factor;dr*=factor
            if start:pts.extend([(right-dl,-right),(-extension,extension-dl),(-extension,dr-extension),(left-dr,left)])
            else:pts.extend([(length+dl-left,left),(length+extension,dl-extension),(length+extension,extension-dr),(length+dr-right,-right)])
        elif start:pts.extend([(-extension,-right),(-extension,left)])
        else:pts.extend([(length+extension,left),(length+extension,-right)])
    out=[];divisor=2 if diagonal else 1
    for u,v in pts:
        x=Fraction(u*ux+v*nx,divisor)+a[0];y=Fraction(u*uy+v*ny,divisor)+a[1]
        if x.denominator!=1 or y.denominator!=1:raise ValueError('Custom end produces fractional DBU boundary')
        p=(int(x),int(y))
        if not out or p!=out[-1]:out.append(p)
    if out and out[0]==out[-1]:out.pop()
    return tuple(out)


def mirror_caps(shape,data):
    """Reflection reverses left/right at each endpoint, rotation does not."""
    for side in ('begin','end'):
        cap=getattr(shape,side+'_custom')
        if cap:
            data[side+'_custom']=dict(left_diagonal=cap.right_diagonal,right_diagonal=cap.left_diagonal,
                right_half_width=shape.width-cap.right_half_width)


def resize_caps(shape,changes,grid):
    """Preserve cap proportions unless the command explicitly supplies a cap."""
    width=changes.get('width',shape.width)
    def scale(v):return int(Fraction(v*width,shape.width*grid)+Fraction(1,2))*grid
    automatic=[]
    if width!=shape.width:
        for side in ('begin','end'):
            cap=getattr(shape,side+'_custom');style=changes.get(side+'_style',getattr(shape,side+'_style'))
            if cap and style=='custom' and side+'_custom' not in changes:
                changes[side+'_custom']={k:scale(v) for k,v in cap.model_dump().items()}
                automatic.append(side)
                if side+'_extension' not in changes:changes[side+'_extension']=scale(getattr(shape,side+'_extension'))
        active=[side for side in ('begin','end') if changes.get(side+'_style',getattr(shape,side+'_style'))=='custom']
        # Independently rounding both halves can change the total native width.
        if len(active)==2 and automatic==['begin','end']:
            changes['end_custom']['right_half_width']=width-changes['begin_custom']['right_half_width']
    for side in ('begin','end'):
        if changes.get(side+'_style',getattr(shape,side+'_style'))!='custom':changes[side+'_custom']=None

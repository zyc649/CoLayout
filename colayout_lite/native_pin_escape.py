"""Plan axis-aligned access windows from exact public PINs, never native internals."""
from collections import defaultdict
from math import ceil,floor
from shapely.geometry import LineString,box
from shapely.ops import nearest_points,unary_union
from .model import LiteError
from .pin_geometry import pin_geometry
from .regions.query import object_bounds,metals


def plan(workspace,profile,obj,width):
    if type(width) is not int or width<=0:raise LiteError('INVALID_ESCAPE_WIDTH','通道宽度须大于零。')
    bounds=object_bounds(workspace,obj,profile)
    if bounds is None:raise LiteError('OBJECT_BOUNDS_MISSING',obj.uid)
    (x,y),(xx,yy)=bounds;owner=box(x,y,xx,yy);grid=profile.grid
    width=max(grid,ceil(width/grid)*grid);half=width/2
    allowed=set(metals(profile));groups=defaultdict(list);skipped=[]
    for pin in workspace.baseline.pins:
        if pin.get('instance_uid')!=obj.uid:continue
        terminal=pin.get('terminal');lpp=pin.get('lpp') or ()
        if not terminal or len(lpp)<2:
            raise LiteError('NATIVE_PIN_GEOMETRY_MISSING','原生 PIN 缺少端子或图层信息。')
        if lpp[0] not in allowed:
            skipped.append({'terminal':terminal,'layer':lpp[0],'reason':'non_routing_metal'});continue
        try:g=pin_geometry(pin,workspace.baseline.objects[obj.uid].placement,obj.placement)
        except (ValueError,KeyError,TypeError) as exc:
            raise LiteError('NATIVE_PIN_GEOMETRY_MISSING','需要真实 PIN 几何，不能使用估算包围框。',terminal=terminal) from exc
        groups[(terminal,lpp[0])].append(g)
    if not groups:raise LiteError('NO_NATIVE_METAL_PINS','未找到可引出的金属 PIN。',skipped=skipped)
    edges=[('left','左',LineString([(x,y),(x,yy)])),('right','右',LineString([(xx,y),(xx,yy)])),
           ('bottom','下',LineString([(x,y),(xx,y)])),('top','上',LineString([(x,yy),(xx,yy)]))]
    rows=[]
    for (terminal,layer),parts in sorted(groups.items()):
        g=unary_union(parts)
        if not owner.covers(g):
            # A PIN already reaches outside the box: no internal corridor is needed.
            if g.intersection(owner).area>0:
                skipped.append({'terminal':terminal,'layer':layer,'reason':'already_at_boundary'});continue
            raise LiteError('NATIVE_PIN_OUTSIDE_OWNER','PIN 几何与原生模块边界不一致。',terminal=terminal)
        distance,index=min((g.distance(edge),i) for i,(_,_,edge) in enumerate(edges))
        side,label,edge=edges[index]
        if distance<=1e-9:
            skipped.append({'terminal':terminal,'layer':layer,'reason':'already_at_boundary'});continue
        point,_=nearest_points(g,edge);px,py=point.x,point.y
        # Include positive PIN area at the inner end and the full configured
        # width. Outward grid rounding cannot leave a sliver at the box edge.
        if side in ('left','right'):
            lo=floor((py-half)/grid)*grid;hi=ceil((py+half)/grid)*grid
            raw=(x,lo,px+half,hi) if side=='left' else (px-half,lo,xx,hi)
        else:
            lo=floor((px-half)/grid)*grid;hi=ceil((px+half)/grid)*grid
            raw=(lo,y,hi,py+half) if side=='bottom' else (lo,py-half,hi,yy)
        bbox=((floor(raw[0]/grid)*grid,floor(raw[1]/grid)*grid),
              (ceil(raw[2]/grid)*grid,ceil(raw[3]/grid)*grid))
        corridor=box(*bbox[0],*bbox[1])
        if corridor.intersection(g).area<=0:raise LiteError('NATIVE_PIN_ESCAPE_UNRESOLVED',terminal=terminal)
        rows.append({'terminal':terminal,'layer':layer,'side':side,'bbox':bbox,
                     'name':(terminal+' · '+label+'侧引出')[:200]})
    return rows,skipped

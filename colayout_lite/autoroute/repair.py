"""Bounded additive repair of metal area and same-net isolated close pieces.

No waivers, instance edits or rule relaxation. Proposed patches still pass the
host's independent DRC/connectivity gate; rejected patches leave explicit errors.
"""
from math import ceil,floor
from shapely.geometry import box
from shapely.ops import nearest_points,unary_union
from shapely import STRtree
from ..model import Shape
from .geometry import decode,shape_figures,parts
from .maze import Maze


def finish(problem,generated):
    output=list(generated);changes=0
    for net in sorted({p['net'] for p in problem.pins}):
        for rule in problem.layers:
            for iteration in range(3):
                geometry=[decode(r.geometry) for r in problem.materials if r.net==net and r.layer==rule.name]
                geometry += [g for s in output if s.net_intent==net for l,g in shape_figures(s,problem) if l==rule.name]
                if not geometry:break
                material=unary_union(geometry)
                pieces=parts(material);patches=[];grid=problem.grid
                def rectangle(bounds):
                    a,b,c,d=bounds
                    return ((floor(a/grid)*grid,floor(b/grid)*grid),(ceil(c/grid)*grid,ceil(d/grid)*grid))
                for g in pieces:
                    if g.area+1e-6>=rule.minimum_area:continue
                    a,b,c,d=g.bounds;width=c-a;height=d-b
                    for axis in (0,1):
                        extra=max(0,(rule.minimum_area/(height if axis==0 else width)-(width if axis==0 else height))/2)+grid
                        patches.append(rectangle((a-extra,b,c+extra,d) if axis==0 else (a,b-extra,c,d+extra)))
                tree=STRtree(pieces)
                for i,g in enumerate(pieces):
                    for j in tree.query(g,predicate='dwithin',distance=rule.spacing):
                        if j<=i or g.distance(pieces[j])>=rule.spacing-1e-7:continue
                        a,b=nearest_points(g,pieces[j]);r=rule.width/2
                        patches.append(rectangle((min(a.x,b.x)-r,min(a.y,b.y)-r,max(a.x,b.x)+r,max(a.y,b.y)+r)))
                # The built-in generator already legalizes its proposed metal.
                # Include the newly covered notch rule here, before the host's
                # independent gate. Explicit check_region remains read-only.
                from ..drc.notches import orthogonal_notches
                added=unary_union([g for s in output if s.net_intent==net
                    for layer,g in shape_figures(s,problem) if layer==rule.name])
                notch_maze=Maze(problem,net,output)
                for gap,_ in orthogonal_notches(material,rule.spacing,added,box(*problem.bounds[0],*problem.bounds[1])):
                    a,b,c,d=gap.bounds;width=max(c-a,rule.width);height=max(d-b,rule.width)
                    variants={rectangle((x,y,x+width,y+height))
                              for x in (a,c-width,(a+c-width)/2)
                              for y in (b,d-height,(b+d-height)/2)}
                    variants=sorted(variants,key=lambda v:(box(*v[0],*v[1]).difference(material).area,v))
                    for bounds in variants:
                        if not notch_maze.collision(rule.name,box(*bounds[0],*bounds[1]),rule.spacing):
                            patches.append(bounds);break
                maze=Maze(problem,net,output);accepted=[]
                for bounds in dict.fromkeys(patches):
                    patch=box(*bounds[0],*bounds[1])
                    if not maze.collision(rule.name,patch,rule.spacing):accepted.append(Shape(kind='rect',lpp=(rule.name,'drawing'),bbox=bounds,net_intent=net))
                    if len(output)+len(accepted)>=problem.limits['shapes']:break
                if not accepted:break
                output.extend(accepted);changes+=len(accepted)
    return output,changes

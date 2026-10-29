"""Reserve legal native-pin escapes before routing inter-device trunks.

Only additive metal/standard via geometry; no synthesized device contacts.
Every escape passes the same exact collision predicates as maze edges.
"""
from math import ceil,sqrt
from shapely.geometry import box
from shapely import affinity
from .maze import Maze
from .geometry import decode,anchors,shape_figures
from ..model import Shape


def escapes(problem,variant):
    generated=[];access={};diagnostics=[];layers=[r.name for r in problem.layers]
    groups=[g for g in problem.groups if not g.landing]
    groups.sort(key=lambda g:g.id,reverse=bool(variant))
    groups.sort(key=lambda g:min(decode(f.geometry).area for f in g.figures))
    for group in groups:
        figures=[(f.layer,decode(f.geometry)) for f in group.figures]
        level=min(layers.index(l) for l,g in figures)
        if level>=len(layers)-1 or any(layers.index(l)>level for l,g in figures):continue
        maze=Maze(problem,group.net,generated,preference=variant)
        transitions=[(z,v) for z,v in maze.transitions[level] if z>level]
        if not transitions:continue
        z,via=transitions[0];layer=layers[level];width=maze.rules[layer].width;grid=problem.grid
        extent=max(abs(x) for x in maze.footprints[via.name][layer].bounds)
        candidates=[]
        for l,g in figures:
            if l!=layer:continue
            x0,y0,x1,y1=g.bounds
            for start in anchors(g,grid):
                for axis,sign in ((0,-1),(0,1),(1,-1),(1,1)):
                    edge=(x0,x1) if axis==0 else (y0,y1)
                    for reach in (extent+grid,extent+width,extent+2*width,extent+4*width,extent+8*width):
                        end=list(start);end[axis]=(edge[sign==1]+sign*reach)
                        end=tuple(round(v/grid)*grid for v in end)
                        length=abs(start[0]-end[0])+abs(start[1]-end[1]);candidates.append((length,start,end))
                candidates.append((0,start,start))
        chosen=None;pads=[]
        for l,g in maze.footprints[via.name].items():
            if l not in maze.rules or g.area>=maze.rules[l].minimum_area:continue
            half=ceil(sqrt(maze.rules[l].minimum_area)/2/grid)*grid
            a,b,c,d=g.bounds;pads.append((l,box(min(a,-half),min(b,-half),max(c,half),max(d,half))))
        for length,start,end in sorted(set(candidates),key=lambda r:(r[0],r[1],r[2]),reverse=False):
            if not maze.clear(layer,start,end) or not maze.via_clear(end,via):continue
            if any(maze.collision(l,affinity.translate(g,*end),maze.rules[l].spacing) for l,g in pads):continue
            shapes=[]
            if start!=end:shapes.append(Shape(kind='path',lpp=(layer,'drawing'),width=width,points=(start,end),style='extendExtend',net_intent=group.net))
            shapes.append(Shape(kind='stdVia',origin=end,via_definition=via.name,net_intent=group.net))
            for l,g in pads:
                a,b,c,d=affinity.translate(g,*end).bounds
                shapes.append(Shape(kind='rect',lpp=(l,'drawing'),bbox=((round(a),round(b)),(round(c),round(d))),net_intent=group.net))
            chosen=shapes;break
        if chosen:
            generated.extend(chosen);access[group.id]=[(l,g) for s in chosen for l,g in shape_figures(s,problem) if l in layers]
        else:diagnostics.append({'net':group.net,'phase':'fanout','group':group.id,'message':'未找到短引出通道，保留原端口交给主寻路器。'})
    return generated,access,diagnostics

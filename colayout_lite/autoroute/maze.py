"""Bounded multi-layer rectilinear search over exact polygon obstacles.

A* and Dijkstra share the same admissible edges. Pattern routing tries legal
L/Z paths first and falls back to A*. No circuit/instance names are consulted.
"""
from heapq import heappush, heappop
from math import ceil, floor
from shapely.geometry import box, Point, LineString
from shapely import affinity, STRtree
from .geometry import decode, anchors, landing_box
from ..model import LiteError


class Maze:
    def __init__(self, problem, net, generated, *, preference=0, algorithm='astar'):
        from .geometry import shape_figures
        self.problem=problem;self.net=net;self.grid=problem.grid;self.algorithm=algorithm;self.preference=preference
        self.rules={r.name:r for r in problem.layers};self.layers=list(self.rules)
        self.roi=box(*problem.bounds[0],*problem.bounds[1]);self.cuts={v.cut_layer for v in problem.via_rules};self.blockers={l:[] for l in (*self.layers,*self.cuts)}
        self.hard={l:[] for l in self.layers};self.rejected=set();self.cache={};self.via_cache={}
        for row in problem.materials:
            if row.layer in self.blockers and (row.net!=net or row.layer in self.cuts):
                self.blockers[row.layer].append((decode(row.geometry),row.owner))
        # Reserve every fixed interface before routing any net, even when its
        # landing has not yet been generated. A marker is not copper, but it is
        # an obligation that a different net must not occupy.
        for pin in problem.pins:
            if not pin['local'] or pin['net']==net:continue
            for row in pin['figures']:
                layer=row['layer']
                if layer in self.rules:
                    bounds=landing_box(decode(row['geometry']),self.rules[layer].width,problem.grid,problem.bounds)
                    self.blockers[layer].append((box(*bounds[0],*bounds[1]),pin['id']))
        from .port_escape import escapes
        self.escape_tracks=[]
        for pin_net,layer,g,uid,point in escapes(problem):
            if pin_net==net:self.escape_tracks.append(point)
            else:self.blockers[layer].append((g,uid))
        for item in generated:
            for layer,g in shape_figures(item,problem):
                if layer in self.blockers and (item.net_intent!=net or layer in self.cuts):
                    self.blockers[layer].append((g,'candidate:'+str(item.net_intent)))
        for barrier in problem.barriers:
            g=decode(barrier.geometry)
            if net in barrier.access:g=g.difference(decode(barrier.access[net]))
            if not g.is_empty:self.hard[barrier.layer].append((g,barrier.owner))
        # Same-net copper behind a closed module layer is not an available
        # connection target. Exempting its spacing creates unrepairable gaps
        # at outside vias: a repair patch cannot enter the child to join them.
        closed={l:[decode(b.geometry) for b in problem.barriers if b.layer==l and net not in b.access] for l in self.layers}
        closed_trees={l:STRtree(gs) for l,gs in closed.items() if gs}
        for row in problem.materials:
            if row.net!=net or row.layer not in closed_trees:continue
            g=decode(row.geometry)
            for i in closed_trees[row.layer].query(g,predicate='intersects'):
                protected=g.intersection(closed[row.layer][int(i)])
                if protected.area>1e-9:self.blockers[row.layer].append((protected,row.owner))
        self.trees={l:STRtree([g for g,_ in rows]) for l,rows in self.blockers.items()}
        self.footprints={v.name:{f.layer:decode(f.geometry) for f in v.footprints} for v in problem.via_rules}
        from .layers import transition
        self.transitions={i:[(j,v) for j in range(len(self.layers)) if j!=i and (v:=transition(problem,i,j))] for i in range(len(self.layers))}
        self.via_radius={l:max((max(abs(x) for x in fs[l].bounds) for fs in self.footprints.values() if l in fs),default=0) for l in self.blockers}

    def collision(self, layer, geometry, spacing):
        if not self.roi.covers(geometry):return True
        for index in self.trees[layer].query(geometry,predicate='dwithin',distance=spacing):
            obstacle,owner=self.blockers[layer][int(index)]
            if geometry.intersects(obstacle) or geometry.distance(obstacle)<spacing-1e-7:
                self.rejected.add(owner);return True
        for obstacle,owner in self.hard.get(layer,[]):
            if geometry.intersection(obstacle).area>1e-9:
                self.rejected.add(owner);return True
        return False

    def clear(self, layer, a, b):
        key=(layer,tuple(sorted((a,b))))
        if key not in self.cache:
            width=self.rules[layer].width
            g=box(min(a[0],b[0])-width/2,min(a[1],b[1])-width/2,max(a[0],b[0])+width/2,max(a[1],b[1])+width/2)
            self.cache[key]=not self.collision(layer,g,self.rules[layer].spacing)
        return self.cache[key]

    def via_clear(self, point, via):
        key=(point,via.name)
        if key not in self.via_cache:
            self.via_cache[key]=all(not self.collision(layer,affinity.translate(g,*point),
                self.rules[layer].spacing if layer in self.rules else via.cut_spacing)
                for layer,g in self.footprints[via.name].items())
        return self.via_cache[key]

    def access(self, figures, toward):
        return [(x,y,self.layers.index(layer)) for layer,g in figures if layer in self.layers
                for x,y in anchors(g,self.grid,toward) if self.clear(layer,(x,y),(x,y))]

    def search(self, source, target):
        # Most connections are local. Keep the exact collision model, first
        # search nearby access tracks, then widen to the whole region on failure.
        try:return self._search(source,target,local=True)
        except LiteError as exc:
            if exc.code not in ('NO_ROUTE','ROUTE_BUDGET_EXCEEDED'):raise
        return self._search(source,target,local=False)

    def _search(self, source, target,*,local):
        centre=target[0][1].representative_point();toward=(centre.x,centre.y)
        starts=self.access(source,toward)
        centre=source[0][1].representative_point();goals=self.access(target,(centre.x,centre.y))
        if not starts or not goals:
            raise LiteError('PIN_ACCESS_BLOCKED','候选接入点受阻，或未采样到能容纳导线端部的合法网格落点。',net=self.net,blockers=sorted(self.rejected))
        if local and self.algorithm!='dijkstra':
            bridge=self.layer_pattern(starts,goals)
            if bridge:return bridge,{'expanded':0,'method':'layer-transition pattern'}
        if local:
            starts=sorted(starts,key=lambda p:min(abs(p[0]-g[0])+abs(p[1]-g[1]) for g in goals))[:16]
            goals=sorted(goals,key=lambda p:min(abs(p[0]-s[0])+abs(p[1]-s[1]) for s in starts))[:16]
        xs={x for x,y,z in starts+goals};ys={y for x,y,z in starts+goals}
        x0,y0,x1,y1=self.roi.bounds
        if local:
            margin=max(self.problem.dbu_per_micron*2,max(max(xs)-min(xs),max(ys)-min(ys))*.3)
            x0=max(x0,min(xs)-margin);x1=min(x1,max(xs)+margin)
            y0=max(y0,min(ys)-margin);y1=min(y1,max(ys)+margin)
        def add(values, v, lo, hi):
            v=round(v/self.grid)*self.grid
            if lo<=v<=hi:values.add(v)
        for layer in self.layers:
            radius=self.rules[layer].width/2;gap=self.rules[layer].spacing
            for geometry,_ in self.blockers[layer]+self.hard[layer]:
                a,b,c,d=geometry.bounds
                if c<x0 or a>x1 or d<y0 or b>y1:continue
                for extra in (radius+gap+self.grid,self.via_radius[layer]+gap+self.grid):
                    for v in (floor((a-extra)/self.grid)*self.grid,ceil((c+extra)/self.grid)*self.grid):add(xs,v,x0,x1)
                    for v in (floor((b-extra)/self.grid)*self.grid,ceil((d+extra)/self.grid)*self.grid):add(ys,v,y0,y1)
            for _,g in source+target:
                a,b,c,d=g.bounds;extra=max(radius,self.via_radius[layer])+gap+self.grid
                for v in (a-extra,c+extra):add(xs,v,x0,x1)
                for v in (b-extra,d+extra):add(ys,v,y0,y1)
            for v in (x0+radius+self.grid,x1-radius-self.grid):add(xs,v,x0,x1)
            for v in (y0+radius+self.grid,y1-radius-self.grid):add(ys,v,y0,y1)
        from .layers import cut_spacing
        for cut in self.cuts:
            gap=cut_spacing(self.problem,cut)+self.via_radius[cut]+self.grid
            for g,_ in self.blockers[cut]:
                a,b,c,d=g.bounds
                if c<x0 or a>x1 or d<y0 or b>y1:continue
                for v in (a-gap,c+gap):add(xs,v,x0,x1)
                for v in (b-gap,d+gap):add(ys,v,y0,y1)
        for x,y in self.escape_tracks:
            add(xs,x,x0,x1);add(ys,y,y0,y1)
        xs=sorted(xs);ys=sorted(ys)
        if len(xs)*len(ys)*len(self.layers)>self.problem.limits['grid_nodes']:
            raise LiteError('ROUTE_BUDGET_EXCEEDED','稀疏网格超过预算。',net=self.net,grid_nodes=len(xs)*len(ys)*len(self.layers))
        if self.algorithm=='pattern':
            path=self.pattern(starts,goals,xs,ys)
            if path:return path,{'expanded':0,'method':'L/Z pattern'}
        ix={v:i for i,v in enumerate(xs)};iy={v:i for i,v in enumerate(ys)}
        targets={(ix[x],iy[y],z) for x,y,z in goals}
        def heuristic(x,y,z):
            if self.algorithm=='dijkstra':return 0
            via_cost=min(r.width for r in self.rules.values())*6
            return self.problem.limits.get('heuristic_weight',1.4)*min(abs(x-a)+abs(y-b)+abs(z-zz)*via_cost for a,b,zz in goals)
        queue=[];distance={};parent={};counter=0
        for x,y,z in starts:
            state=(ix[x],iy[y],z,0,-1);distance[state]=0
            heappush(queue,(heuristic(x,y,z),0,counter,state));counter+=1
        expanded=0;final=None
        while queue:
            _,cost,_,state=heappop(queue)
            if cost!=distance[state]:continue
            x,y,z,used,direction=state;origin=(xs[x],ys[y]);expanded+=1
            if expanded>min(self.problem.limits['search_states'],100000 if local else self.problem.limits['search_states']):
                raise LiteError('ROUTE_BUDGET_EXCEEDED','寻路状态超过预算。',net=self.net,expanded=expanded)
            if (x,y,z) in targets:final=state;break
            neighbors=[]
            preferred=(z+self.preference)%2
            steps=((x-1,y,0),(x+1,y,0),(x,y-1,1),(x,y+1,1))
            for xx,yy,d in sorted(steps,key=lambda s:s[2]!=preferred):
                if not 0<=xx<len(xs) or not 0<=yy<len(ys):continue
                dest=(xs[xx],ys[yy]);layer=self.layers[z]
                if self.clear(layer,origin,dest):
                    length=abs(dest[0]-origin[0])+abs(dest[1]-origin[1])
                    cost_step=length+(length//5 if d!=preferred else 0)+(self.grid*4 if direction>=0 and direction!=d else 0)
                    neighbors.append(((xx,yy,z,used,d),cost_step))
            if used<self.problem.limits['max_vias_per_branch']:
                for zz,via in self.transitions[z]:
                    if self.via_clear(origin,via):neighbors.append(((x,y,zz,used+1,-1),max(self.rules[self.layers[k]].width for k in (z,zz))*6))
            for nxt,step in neighbors:
                value=cost+step
                if value>=distance.get(nxt,float('inf')):continue
                distance[nxt]=value;parent[nxt]=state;xx,yy,*_=nxt
                heappush(queue,(value+heuristic(xs[xx],ys[yy],nxt[2]),value,counter,nxt));counter+=1
        if final is None:raise LiteError('NO_ROUTE','在当前边界、层和预算内未找到通道。',net=self.net,blockers=sorted(self.rejected),expanded=expanded)
        path=[];node=final
        while node is not None:path.append((xs[node[0]],ys[node[1]],node[2]));node=parent.get(node)
        return list(reversed(path)),{'expanded':expanded,'method':self.algorithm}

    def pattern(self, starts, goals, xs, ys):
        pairs=sorted(((abs(a[0]-b[0])+abs(a[1]-b[1]),a,b) for a in starts for b in goals if a[2]==b[2]))
        for _,a,b in pairs[:80]:
            x,y,z=a;xx,yy,_=b;layer=self.layers[z]
            bends=[[(x,y),(xx,y),(xx,yy)],[(x,y),(x,yy),(xx,yy)]]
            if self.preference:bends.reverse()
            mids=xs if self.preference==0 else ys
            for mid in sorted(mids,key=lambda v:abs(v-((x+xx)/2 if self.preference==0 else (y+yy)/2)))[:12]:
                bends.append([(x,y),(mid,y),(mid,yy),(xx,yy)] if self.preference==0 else [(x,y),(x,mid),(xx,mid),(xx,yy)])
            for points in bends:
                if all(self.clear(layer,c,d) for c,d in zip(points,points[1:])):
                    return [(px,py,z) for px,py in points]
        return None

    def layer_pattern(self,starts,goals):
        """Try short legal upper-layer bridges before expanding a large maze.

        The same geometry/via predicates are used by graph edges and validation.
        This does not add unselected layers or manufacture access contacts.
        """
        def lift(point,start,end):
            queue=[(start,[])];visited={start}
            for z,path in queue:
                if z==end:return path
                for zz,via in self.transitions[z]:
                    if zz not in visited and self.via_clear(point,via):
                        visited.add(zz);queue.append((zz,path+[(point[0],point[1],zz)]))
            return None
        pairs=sorted(((abs(a[0]-b[0])+abs(a[1]-b[1]),a,b) for a in starts for b in goals))[:96]
        for _,a,b in pairs:
            x,y,z=a;xx,yy,zz=b
            for level in sorted(range(len(self.layers)),key=lambda k:(abs(k-z)+abs(k-zz),-k)):
                up=lift((x,y),z,level);down=lift((xx,yy),level,zz)
                if up is None or down is None or len(up)+len(down)>self.problem.limits['max_vias_per_branch']:continue
                for bend in ((xx,y),(x,yy)) if not self.preference else ((x,yy),(xx,y)):
                    layer=self.layers[level]
                    if self.clear(layer,(x,y),bend) and self.clear(layer,bend,(xx,yy)):
                        return [a]+up+[(bend[0],bend[1],level),(xx,yy,level)]+down
        return None

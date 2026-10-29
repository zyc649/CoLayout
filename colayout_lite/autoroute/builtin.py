"""Generic multi-terminal tree construction over the shared maze kernel."""
from math import ceil, floor
from shapely.geometry import box, mapping
from shapely.ops import unary_union
from ..model import Shape, LiteError
from .models import Proposal, PluginResult
from .geometry import decode, shape_figures, layer_union, landing_box
from .maze import Maze

ALGORITHMS = {
    'builtin.astar':('加权 A* 稀疏迷宫','astar','多层正交寻路，逐步接入已有同网树；优先计算速度，不承诺最短路径。'),
    'builtin.pattern':('L/Z 模式＋A*','pattern','先尝试简短正交路径，受阻时转入迷宫搜索。'),
    'builtin.dijkstra':('Dijkstra 波前','dijkstra','无启发式的加权波前搜索，用于比较寻路时间与结果。'),
    'builtin.fanout':('端口引出＋A*','fanout','先用合法标准过孔为窄端口保留引出通道，再连接多层网络。'),
    'builtin.reorder':('拥塞重排＋A*','reorder','根据未布通网络调整次序，最多三轮重布候选；始终保留原有布线。'),
}


def compact(points):
    result=[]
    for pt in points:
        if result and pt==result[-1]:continue
        result.append(pt)
        while len(result)>=3 and (result[-3][0]==result[-2][0]==result[-1][0] or result[-3][1]==result[-2][1]==result[-1][1]):result.pop(-2)
    return result


def path_shapes(path, problem, net):
    output=[];points=[path[0][:2]];z=path[0][2]
    def segment():
        pts=compact(points)
        if len(pts)>1:output.append(Shape(kind='path',lpp=(problem.layers[z].name,'drawing'),width=problem.layers[z].width,
                                       points=tuple(pts),style='extendExtend',net_intent=net))
    for x,y,zz in path[1:]:
        if zz!=z:
            from .layers import transition
            via=transition(problem,z,zz)
            if via is None:raise LiteError('ROUTING_VIA_UNAVAILABLE')
            segment();output.append(Shape(kind='stdVia',origin=(x,y),via_definition=via.name,net_intent=net))
            z=zz;points=[(x,y)]
        else:points.append((x,y))
    segment();return output


def one(problem, algorithm, variant,net_order=None):
    generated=[];diagnostics=[];groups_by_net={}
    access={}
    if algorithm=='fanout':
        from .fanout import escapes
        generated,access,diagnostics=escapes(problem,variant)
        algorithm='astar'
    for group in problem.groups:groups_by_net.setdefault(group.net,[]).append(group)
    # Different generic net orders and preferred directions produce real alternatives.
    nets=net_order or sorted(groups_by_net,key=lambda n:(-len(groups_by_net[n]),n),reverse=bool(variant))
    for net in nets:
        groups=groups_by_net[net];records=[]
        try:
            for group in groups:
                fs=[(f.layer,decode(f.geometry)) for f in group.figures]+access.get(group.id,[])
                if group.landing:
                    pads=[];maze=Maze(problem,net,generated,preference=variant,algorithm=algorithm)
                    for layer,g in fs:
                        a,b,c,d=g.bounds;rule=next(r for r in problem.layers if r.name==layer);grid=problem.grid
                        # Increase landing only if required; never move a canonical PIN.
                        bounds=landing_box(g,rule.width,grid,problem.bounds)
                        pad=box(*bounds[0],*bounds[1])
                        if maze.collision(layer,pad,rule.spacing):
                            if group.alternative_layers:continue
                            raise LiteError('PIN_ACCESS_BLOCKED','接口落点金属受阻。',pin_ids=group.pin_ids,net=net,blockers=sorted(maze.rejected))
                        pads.append(Shape(kind='rect',lpp=(layer,'drawing'),bbox=bounds,net_intent=net))
                        if group.alternative_layers:break
                    if not pads:raise LiteError('PIN_ACCESS_BLOCKED','所有可选金属接入均受阻。',pin_ids=group.pin_ids,net=net,blockers=sorted(maze.rejected))
                    generated.extend(pads);fs=[f for s in pads for f in shape_figures(s,problem)]
                records.append((group.id,fs))
            records.sort(key=lambda row:row[0],reverse=bool(variant))
            if not records:continue
            _,tree=records.pop(0)
            while records:
                union=layer_union(tree)
                attached=[row for row in records if any(l in union and
                    ((touch:=union[l].intersection(g)).area>0 or touch.length>0) for l,g in row[1])]
                for row in attached:tree+=row[1];records.remove(row)
                if not records:break
                def distance(row):return min(g.distance(h) for _,g in tree for _,h in row[1])
                goal=min(records,key=lambda row:(distance(row),row[0]))
                # Union same-layer tree material to keep access enumeration bounded.
                tree=[(l,g) for l,g in layer_union(tree).items()]
                maze=Maze(problem,net,generated,preference=variant,algorithm=algorithm)
                # Escape the small unconnected terminal toward the existing tree.
                # Starting from a large tree explores the whole free plane when
                # a single narrow terminal is trapped behind another net.
                path,stats=maze.search(goal[1],tree);new=path_shapes(path,problem,net)
                generated.extend(new);tree+=goal[1]+[(l,g) for s in new for l,g in shape_figures(s,problem) if l in maze.layers]
                records.remove(goal);diagnostics.append({'net':net,**stats})
                if len(generated)>problem.limits['shapes']:raise LiteError('ROUTE_BUDGET_EXCEEDED','候选图形数量超过预算。')
        except LiteError as exc:
            diagnostics.append({'net':net,'code':exc.code,'message':str(exc),'details':exc.details})
    from .repair import finish
    generated,patches=finish(problem,generated)
    if patches:diagnostics.append({'phase':'local_repair','patches':patches})
    return Proposal(title='横向优先' if variant==0 else '纵向优先 · 逆序接网',shapes=tuple(generated),
                    diagnostics=tuple(diagnostics),parameters={'preferred_direction':variant,'net_order':nets})


def generate(problem, algorithm_id, count=2):
    if algorithm_id not in ALGORITHMS:raise ValueError('Unknown built-in algorithm')
    algorithm=ALGORITHMS[algorithm_id][1]
    if algorithm=='reorder':
        from .reorder import solve
        return solve(problem,min(count,2))
    return PluginResult(request_id=problem.request_id,source_digest=problem.source_digest,
        candidates=tuple(one(problem,algorithm,i%2) for i in range(min(count,2))))

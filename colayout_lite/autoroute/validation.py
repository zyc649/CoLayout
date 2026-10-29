"""Host-owned candidate checks. Plugin metrics/status never establish legality."""
from uuid import uuid4
from math import hypot
from ..model import LiteError, Operation, digest
from ..editor import Editor, projected
from ..drc.local import run as run_drc
from ..drc.models import Region
from .snapshot import scope_graph, connectivity
from .geometry import shape_figures, layer_union
from .maze import Maze


def fingerprint(shapes, problem):
    rows=[]
    for net in sorted({s.net_intent for s in shapes}):
        unions=layer_union([f for s in shapes if s.net_intent==net for f in shape_figures(s,problem)])
        rows.extend((net,layer,g.normalize().wkb_hex) for layer,g in sorted(unions.items()))
    return digest(rows)


def checked_operations(proposal, problem, p):
    operations=[];known={pin['net'] for pin in problem.pins};layers={r.name for r in problem.layers}
    for shape in proposal.shapes:
        if shape.kind not in ('rect','path','stdVia') or shape.net_intent not in known:
            raise LiteError('PLUGIN_SHAPE_NOT_ALLOWED','插件只可新增已知网络的矩形、正交路径和标准过孔。')
        if shape.kind=='stdVia':
            if shape.via_definition not in {v.name for v in problem.via_rules} or shape.orientation!='R0' or shape.via_parameters:
                raise LiteError('PLUGIN_VIA_NOT_ALLOWED','仅支持冻结默认尺寸的 R0 标准过孔。')
        elif shape.lpp not in {(l,'drawing') for l in layers}:
            raise LiteError('PLUGIN_LAYER_NOT_ALLOWED')
        elif shape.kind=='path' and (shape.style!='extendExtend' or shape.begin_extension or shape.end_extension or
                any(a[0]!=b[0] and a[1]!=b[1] for a,b in zip(shape.points,shape.points[1:]))):
            raise LiteError('PLUGIN_PATH_NOT_ALLOWED','仅支持正交 extendExtend 路径。')
        p.check(shape)
        operations.append(Operation(action='create',uid=str(uuid4()),shape=shape))
    return tuple(operations)


def validate(w, p, drc, problem, proposal):
    errors=[];operations=();after=None;drc_report=None;connections=None
    try:
        if problem.source_digest!=digest(w.model_dump(mode='json')):raise LiteError('ROUTING_SOURCE_MISMATCH')
        operations=checked_operations(proposal,problem,p)
        candidate=Editor(w,p,scope_id=problem.region_id)
        candidate.apply(operations,expected_revision=w.revision)
        after=candidate.w
        # Independently check full generated geometry, including square caps,
        # via metal/cut footprints, unowned material, region and policy barriers.
        for i,shape in enumerate(proposal.shapes):
            maze=Maze(problem,shape.net_intent,proposal.shapes[:i]+proposal.shapes[i+1:])
            for layer,g in shape_figures(shape,problem):
                from .layers import cut_spacing
                spacing=maze.rules[layer].spacing if layer in maze.rules else cut_spacing(problem,layer)
                if maze.collision(layer,g,spacing):
                    errors.append({'code':'ROUTING_COLLISION','shape_index':i,'layer':layer,'blockers':sorted(maze.rejected)})
        graph=scope_graph(after,p,problem.region_id);connections=connectivity(graph)
        known={pin['id']:pin['net'] for pin in graph['pins']}
        for op in operations:
            components={n['component_id'] for n in graph['nodes'] if n['owner_uid']==op.uid}
            nets={known[pid] for cid in components for pid in graph['component_pins'].get(cid,())}
            if nets!={op.shape.net_intent}:
                errors.append({'code':'ROUTING_UNPROVEN_NET','object_id':op.uid,'expected_net':op.shape.net_intent,'physical_nets':sorted(nets)})
        drc_report=run_drc(after,p,drc,Region(bbox=problem.bounds),scope_id=problem.region_id)
        from ..drc.design_warnings import blocking
        blockers=[marker for marker in drc_report.markers if blocking(marker)]
        if blockers:errors.append({'code':'ROUTING_DRC_FAILED','count':len(blockers)})
        if not drc_report.coverage['complete_for_configured_subset']:
            errors.append({'code':'ROUTING_DRC_INCOMPLETE','coverage':drc_report.coverage})
        if connections['shorts']:errors.append({'code':'ROUTING_SHORT','shorts':connections['shorts']})
        if connections['warnings']:errors.append({'code':'ROUTING_CONNECTIVITY_INCOMPLETE','warnings':connections['warnings']})
    except (LiteError,ValueError,KeyError,TypeError) as exc:
        errors.append({'code':getattr(exc,'code','PLUGIN_OUTPUT_INVALID'),'message':str(exc),'details':getattr(exc,'details',{})})
    complete=bool(connections and connections['complete'])
    status='ready' if complete and not errors else 'invalid' if errors else 'partial'
    length=sum(sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a,b in zip(s.points,s.points[1:])) for s in proposal.shapes if s.kind=='path')/p.dbu_per_micron
    return {'status':status,'errors':errors,'connectivity':connections,'drc':drc_report.model_dump(mode='json') if drc_report else None,
        'length_um':length,'via_count':sum(s.kind=='stdVia' for s in proposal.shapes),'shape_count':len(proposal.shapes),
        'operations':[op.model_dump(mode='json') for op in operations],
        'geometry_fingerprint':fingerprint(proposal.shapes,problem) if after is not None else None}

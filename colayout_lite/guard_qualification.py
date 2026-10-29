"""Faithful sample reproduction and native roundtrip, without a DRC engine."""
from collections import Counter
from math import ceil
from pathlib import Path
from shapely import affinity
from shapely.ops import unary_union
from .adapter import Adapter
from .editor import Editor
from .model import LiteError,Workspace
from .process_library import write_json
from .transport import NativeTransport


def check_closed_seam(workspace,obj,recipe):
    """Check sampled longitudinal cut gaps at the coincident closing endpoints."""
    from .scene import figures_by_owner
    from .materials import polygon_from_figure
    figures,_=figures_by_owner(workspace.baseline,objects={obj.uid:obj},owner_filter={obj.uid},
                              modes={obj.uid:'full'},include_styles=False)
    start=obj.mpp.master.points[0];parts=[p for p in recipe.parts if p.kind=='rectangle']
    required={p.lpp:min(q.space for q in parts if q.lpp==p.lpp) for p in parts}
    band=recipe.width+max((abs(p.separation)+p.width for p in parts),default=0)
    rows={};checked=[]
    for figure in figures.get(obj.uid,[]):
        lpp=tuple(figure.get('lpp') or figure['style'].split('/'))
        if lpp not in required or figure['kind']!='rect':continue
        x,y,xx,yy=polygon_from_figure(figure).bounds
        if abs((y+yy)/2-start[1])>band:continue
        rows.setdefault((lpp,round(y,6),round(yy,6)),[]).append((x,xx))
    for (lpp,y,yy),cuts in rows.items():
        left=[b for b in cuts if sum(b)/2<start[0]];right=[b for b in cuts if sum(b)/2>=start[0]]
        if not left or not right:continue
        gap=min(b[0] for b in right)-max(b[1] for b in left)
        if gap+1e-5<required[lpp]:raise LiteError('GUARD_CLOSED_SEAM_SPACING',str(lpp),gap_dbu=gap,minimum_dbu=required[lpp])
        checked.append({'lpp':lpp,'gap_dbu':round(gap,6),'sample_space_dbu':required[lpp]})
    if not checked:raise LiteError('GUARD_CLOSED_SEAM_UNVERIFIED')
    return checked


def _materials(workspace,obj):
    from .scene import figures_by_owner
    from .materials import polygon_from_figure
    figures,_=figures_by_owner(workspace.baseline,objects={obj.uid:obj},owner_filter={obj.uid},
                              modes={obj.uid:'full'},include_styles=False)
    layers={};counts=Counter()
    for figure in figures.get(obj.uid,[]):
        if figure['kind'] not in ('rect','polygon','path','pathSeg'):continue
        lpp=tuple(figure.get('lpp') or figure['style'].split('/'))
        layers.setdefault(lpp,[]).append(polygon_from_figure(figure));counts[lpp]+=1
    if not layers:raise LiteError('MPP_GEOMETRY_MISSING')
    return {k:unary_union(v) for k,v in layers.items()},counts


def _require_reproduction(materials,counts,actual,actual_counts,dx,dy):
    if materials.keys()!=actual.keys() or counts!=actual_counts or any(
            not affinity.translate(shape,dx,dy).equals(actual[layer]) for layer,shape in materials.items()):
        raise LiteError('GUARD_SAMPLE_REPRODUCTION_MISMATCH','原生开放路径复现的层/图形数量/实际几何与样例不一致。')


def reproduce(recipe,connection,library,cell,folder):
    from .guard_setup import discover,is_open_corner_sample
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    adapter=Adapter(NativeTransport(connection));before,p=adapter.read(library,cell)
    recipe.check_profile(p)
    samples,_=discover(adapter,library,cell)
    row=next((r for r in samples['paths'] if r['native_id']==recipe.source.get('native_id')),None)
    if row is None or not is_open_corner_sample(row):raise LiteError('GUARD_OPEN_SAMPLE_REQUIRED')
    source=next(o for o in before.objects.values() if o.native_id==row['native_id'])
    source_workspace=Workspace(baseline=before,profile_id=p.id)
    materials,counts=_materials(source_workspace,source)
    from .native_temporary import TemporaryCopies
    with TemporaryCopies(adapter):
        return _reproduce(adapter,recipe,p,library,cell,folder,before,row,materials,counts)


def _reproduce(adapter,recipe,p,library,cell,folder,before,row,materials,counts):
    w,p=adapter.create_validation_workspace(library,cell,label='MPP_REPRODUCTION')
    baseline=w.baseline
    candidate=p.model_copy(update={'guard_recipes':[recipe.model_dump()]})
    scale=p.dbu_per_micron;grid=p.grid
    x=ceil((max((o.bbox[1][0] for o in baseline.objects.values() if o.bbox),default=0)+100*scale)/grid)*grid
    y=ceil(100*scale/grid)*grid
    ox,oy=row['points'][0];dx,dy=x-ox,y-oy
    points=[(px+dx,py+dy) for px,py in row['points']]
    e=Editor(w,candidate)
    uid=adapter.guard_preview(e,points=points,template=recipe.model_dump(),_validation=True,net_intent='MPP_VERIFY')
    w=adapter.commit(e.w)
    if w.state!='clean':raise LiteError('GUARD_ROUNDTRIP_FAILED')
    actual,actual_counts=_materials(w,w.baseline.objects[uid])
    _require_reproduction(materials,counts,actual,actual_counts,dx,dy)
    checks=[{'form':'path','native_roundtrip':True,'sample_geometry_equal':True,
             'members':sum(counts.values()),'uid':uid}]
    # Closing a sampled cross-section uses the existing ring generator. Check
    # native construction/readback; do not infer a foundry minimum from this.
    (sx,sy),(xx,yy)=row['centerline_bbox']
    width=max(recipe.min_side_dbu,xx-sx);height=max(recipe.min_side_dbu,yy-sy)
    bx=x+width+100*scale
    e=Editor(w,candidate)
    ring=adapter.guard_preview(e,bbox=((bx,y),(bx+width,y+height)),template=recipe.model_dump(),
                               _validation=True,net_intent='MPP_VERIFY')
    w=adapter.commit(e.w)
    if w.state!='clean':raise LiteError('GUARD_ROUNDTRIP_FAILED')
    checks.append({'form':'ring','native_roundtrip':True,'uid':ring,'size_dbu':[width,height],
                   'seam':check_closed_seam(w,w.baseline.objects[ring],recipe)})
    e=Editor(w,candidate)
    for ident in (uid,ring):e.delete_guard(ident)
    w=adapter.commit(e.w)
    if w.state!='clean' or w.baseline.semantic()!=baseline.semantic():raise LiteError('GUARD_DELETE_RESTORE_FAILED')
    after,_=adapter.read(library,cell)
    if before.semantic()!=after.semantic() or before.counter!=after.counter or before.dirty!=after.dirty:
        raise LiteError('GUARD_SAMPLE_WAS_CHANGED')
    proof={'status':'passed','kind':'native_reproduction','drc_checked':False,'forms':['ring','path'],
           'geometry_key':recipe.geometry_key(),'report':str((folder/'report.json').resolve()),
           'checks':checks,'source_unchanged':True,'copy_restored':True,
           'scope':'开放样例参数直接采集及逐层几何复现、闭环原生往返、删除恢复；未进行保护环 DRC，实际设计须补齐井区等上下文并检查。'}
    write_json(folder/'report.json',proof)
    result=recipe.model_copy(update={'validation':proof});result.save(folder/'recipe.json')
    return result

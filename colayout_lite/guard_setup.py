"""Collect MPP recipes; retain explicit legacy DRC diagnostics separately."""
import argparse,json,time
from pathlib import Path
from uuid import uuid4
from decimal import Decimal
from .paths import ROOT
from .transport import NativeTransport
from .adapter import Adapter,require_unchanged
from .model import LiteError,digest
from .guard_recipes import GuardPart,GuardRecipe
from .mpp_recipe import open_termination,closed_termination
from .process_library import write_json


def integer(value,scale):
    n=Decimal(str(value))*scale
    if n!=n.to_integral_value():raise LiteError('GUARD_SAMPLE_FRACTIONAL_DBU')
    return int(n)


def discover(adapter,library,cell):
    from .sexpr import parse_native
    snapshot,p=adapter.read(library,cell)
    remote=adapter.native.call('ltGuardSamples',library,cell,uuid4().hex)[0]
    folder=ROOT/'artifacts/guard-recipes/discovery';folder.mkdir(parents=True,exist_ok=True);path=folder/(uuid4().hex+'.sexpr')
    r=adapter.native.client.download_file(remote,str(path))
    if r.errors:raise LiteError('GUARD_SAMPLE_DOWNLOAD_FAILED')
    rings=[];scale=p.dbu_per_micron
    text=path.read_text(encoding='utf8').strip()
    # Cadence prints an empty list as nil. Missing optional guard samples must
    # not prevent collecting the process's layers, vias and devices.
    for row in ([] if text=='nil' else parse_native(text)):
        data=dict(row);points=[tuple(integer(v,scale) for v in pt) for pt in data['points']]
        xs,ys=zip(*points);bbox=((min(xs),min(ys)),(max(xs),max(ys)))
        closed=points[0]==points[-1] and all(a[0]==b[0] or a[1]==b[1] for a,b in zip(points,points[1:]))
        # Accept only a closed rectangular centerline, possibly with its seam
        # at the middle of an edge. Irregular/chopped samples remain inspectable.
        closed=closed and all(x in (bbox[0][0],bbox[1][0]) or y in (bbox[0][1],bbox[1][1]) for x,y in points)
        area=abs(sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(points,points[1:])))
        dx,dy=bbox[1][0]-bbox[0][0],bbox[1][1]-bbox[0][1]
        closed=closed and dx>0 and dy>0 and area==2*dx*dy and sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a,b in zip(points,points[1:]))==2*(dx+dy)
        parts=[]
        for part in data['parts'] or []:
            values=dict(part)
            for key,v in list(values.items()):
                if key in ('choppable','diagonal'):values[key]=v=='yes'
                elif key not in ('kind','lpp','justification','gap'):values[key]=integer(v,scale)
            parts.append(GuardPart.model_validate(values).model_dump())
        rings.append({'native_id':data['native_id'],'centerline_bbox':bbox,'points':points,'closed_rectangle':closed,
            'chopped':data['chopped']=='yes','master_lpp':data['master_lpp'],'width':integer(data['width'],scale),'parts':parts,
            'contact_rows':len([q for q in parts if q['kind']=='rectangle'])})
    current,_=adapter.read(library,cell)
    if current.semantic()!=snapshot.semantic():raise LiteError('GUARD_SOURCE_CHANGED_DURING_DISCOVERY')
    return {'schema_version':'colayout-guard-samples-1','source':{'library':library,'cell':cell},'source_digest':digest(snapshot.semantic()),
        'technology_fingerprint':p.native_fingerprint,'dbu_per_micron':scale,'grid':p.grid,'paths':rings},p


def build(samples,index,ident,name):
    r=samples['paths'][index]
    if r['chopped'] or not r['parts']:raise LiteError('MPP_SAMPLE_UNSUPPORTED')
    if r['contact_rows'] not in (1,2):raise LiteError('MPP_SAMPLE_UNSUPPORTED','当前只支持单排或双排接触孔的原生 MPP 样例。')
    closed=r['points'][0]==r['points'][-1]
    parts=tuple(GuardPart.model_validate(q) for q in r['parts'])
    # End caps have no meaning on the abutted seam of a closed ring.
    ring_parts=closed_termination(parts,samples['grid'])
    open_parts=tuple(parts) if not closed else open_termination(parts,r['width'],samples['grid'])
    kind='double' if r['contact_rows']==2 else 'single'
    segment_lengths=[max(abs(a[0]-b[0]),abs(a[1]-b[1])) for a,b in zip(r['points'],r['points'][1:])]
    minimum_segment=min([r['width']*4,*[v for v in segment_lengths if v>0]]) if not closed else r['width']*4
    return GuardRecipe(id=ident,name=name,library=samples['source']['library'],technology_fingerprint=samples['technology_fingerprint'],
        kind=kind,master_lpp=r['master_lpp'],width=r['width'],parts=ring_parts,open_parts=open_parts,
        min_side_dbu=r['width']*4,min_length_dbu=minimum_segment,
        source={'sample':samples['source'],'source_digest':samples['source_digest'],'path_index':index,
            'native_id':r['native_id'],'sample_form':'closed' if closed else 'open',
            'measurement':'native MPP cross-section; open sample caps copied directly' if not closed else 'native closed MPP; derived open caps'})


def is_open_corner_sample(row):
    points=row['points']
    if row['chopped'] or len(points)<3 or points[0]==points[-1]:return False
    directions=[]
    for a,b in zip(points,points[1:]):
        dx=b[0]-a[0];dy=b[1]-a[1]
        if (dx==0)==(dy==0):return False
        directions.append('x' if dx else 'y')
    return len(set(directions))==2


def validate(recipe,connection,library,source_cell,sizes=None,folder=None,*,drc_profile=None):
    from .mpp_recipe import sampled
    if recipe.kind=='double' and not sampled(recipe):raise LiteError('GUARD_SAMPLE_REQUIRED')
    from .editor import Editor
    from .drc import jobs
    from .drc.config import load
    from .drc.models import Region
    from .drc.waivers import review,WaiverPolicy
    from .guard_context import validation_context
    folder=Path(folder or ROOT/'artifacts/guard-recipes/validation'/uuid4().hex);folder.mkdir(parents=True,exist_ok=True)
    a=Adapter(NativeTransport(connection));before,p=a.read(library,source_cell)
    recipe.check_profile(p);drc=drc_profile or load(p)
    if drc:drc.check_technology(p)
    if drc is None or drc.remote is None:raise LiteError('GUARD_DRC_REQUIRED','先配置此工艺的服务器 DRC。')
    qa_waivers=WaiverPolicy(technology_fingerprint=p.native_fingerprint,configuration_id=p.configuration_id,keywords=('BORDER','density','seal ring'))
    w,p=a.create_validation_workspace(library,source_cell,label='GUARD19')
    original_baseline=w.baseline
    scale=p.dbu_per_micron;side=recipe.min_side_dbu/scale
    sizes=sizes or [(side,side),(max(20,side),max(20,side)),(max(40,side),max(25,side))]
    cases=[{'form':'ring','size_um':size} for size in sizes]
    length=max(20,recipe.min_length_dbu/scale)
    cases += [{'form':'path','relative_points':pts} for pts in [[(0,0),(recipe.min_length_dbu/scale,0)],[(0,0),(0,length)],[(0,0),(length,0),(length,length)]]]
    before,_=a.read(library,source_cell);checks=[]
    candidate=p.model_copy(update={'guard_recipes':[recipe.model_dump()]})
    for i,case in enumerate(cases):
        e=Editor(w,candidate);x=1000000+i*200000;y=1000000
        if case['form']=='ring':
            width,height=case['size_um'];bbox=((x,y),(x+integer(width,scale),y+integer(height,scale)))
            geometry={'bbox':bbox}
        else:
            pts=[(x+integer(px,scale),y+integer(py,scale)) for px,py in case['relative_points']]
            geometry={'points':pts};bbox=((min(p[0] for p in pts),min(p[1] for p in pts)),(max(p[0] for p in pts),max(p[1] for p in pts)))
        uid=a.guard_preview(e,**geometry,template=recipe.model_dump(),_validation=True,net_intent='MPP_TEST')
        context,shapes=validation_context(recipe,p,drc,bbox,closed=case['form']=='ring')
        context_ids=[e.create(shape) for shape in shapes]
        w=a.commit(e.w)
        if w.state!='clean':raise LiteError('GUARD_ROUNDTRIP_FAILED')
        bounds=[bbox,*(shape.bbox for shape in shapes)]
        request_region=Region(bbox=((min(b[0][0] for b in bounds)-5000,min(b[0][1] for b in bounds)-5000),
                                   (max(b[1][0] for b in bounds)+5000,max(b[1][1] for b in bounds)+5000)))
        job=jobs.start(w,p,drc,request_region,'calibre');started=time.monotonic()
        while time.monotonic()-started<drc.remote.timeout_seconds*3+60:
            state=jobs.status(job['job_id'])
            if state['status'] in ('completed','failed','cancelled'):break
            time.sleep(.25)
        else:jobs.cancel(job['job_id']);raise LiteError('GUARD_DRC_TIMEOUT')
        if state['status']!='completed':raise LiteError('GUARD_DRC_FAILED',state.get('message',''))
        result=jobs.result(job['job_id']);reviewed=review(result,qa_waivers);write_json(folder/f'drc-{i}.json',reviewed)
        row={**case,'job_id':job['job_id'],'active':reviewed['active_count'],'waived':reviewed['waived_count'],
            'group_uid':uid,'source_cell':w.baseline.cell,'rule_checks':result.coverage.get('rule_checks_executed'),
            'context':context,'context_shapes':[{'uid':ident,**shape.model_dump(mode='json')} for ident,shape in zip(context_ids,shapes)]}
        checks.append(row);write_json(folder/'report.json',{'recipe':recipe.id,'checks':checks,'geometry_key':recipe.geometry_key(),'context':context})
        if reviewed['active_count'] or result.coverage.get('truncated'):raise LiteError('GUARD_DRC_VIOLATIONS',str(folder/f'drc-{i}.json'))
    # Exercise ordinary whole-MPP deletion for all generated cases.
    e=Editor(w,candidate)
    for row in checks:
        e.delete_guard(row['group_uid'])
        for shape in row['context_shapes']:e.delete(shape['uid'])
    w=a.commit(e.w)
    if w.state!='clean' or w.baseline.semantic()!=original_baseline.semantic():raise LiteError('GUARD_DELETE_RESTORE_FAILED')
    current,_=a.read(library,source_cell)
    if current.semantic()!=before.semantic():raise LiteError('GUARD_SAMPLE_WAS_CHANGED')
    updated=recipe.model_copy(update={'validation':{'status':'passed','forms':['ring','path'],'geometry_key':recipe.geometry_key(),'report':str((folder/'report.json').resolve()),
        'checks':checks,'context':context,'drc_profile_digest':drc.fingerprint(),
        'scope':'样例参数重生成、多个尺寸原生往返及有记录的使用上下文 DRC；包含 N+ / NWell 的配方按完整井区覆盖验证，实际放置仍需完成井区并检查整个设计。'}})
    updated.save(folder/'recipe.json');return updated


def install(recipe,profile_path):
    from .mpp_recipe import sampled
    if recipe.kind=='double' and not sampled(recipe):raise LiteError('GUARD_SAMPLE_REQUIRED')
    from .technology import TechnologyProfile
    path=Path(profile_path);p=TechnologyProfile.model_validate_json(path.read_text(encoding='utf8'));recipe.check_profile(p)
    if not recipe.ready():raise LiteError('GUARD_RECIPE_NOT_VALIDATED')
    report=json.loads(Path(recipe.validation['report']).read_text(encoding='utf8'))
    if report.get('geometry_key')!=recipe.geometry_key() or report.get('checks')!=recipe.validation.get('checks') or len(report.get('checks',[]))<6 or any(c.get('active')!=0 or not c.get('rule_checks') for c in report['checks']):
        raise LiteError('GUARD_VALIDATION_EVIDENCE_MISMATCH')
    p.save(ROOT/'artifacts/guard-recipes/config-backups'/uuid4().hex/'profile.json')
    recipes=[r for r in p.guard_recipes if r['id']!=recipe.id]+[recipe.model_dump()]
    TechnologyProfile.model_validate({**p.model_dump(),'guard_recipes':recipes}).save(path)


def seed(profile,template_name,width_um,ident,name,cut_space_um=None):
    """Retired: double rows must be collected from a user-supplied native sample."""
    raise LiteError('GUARD_SAMPLE_REQUIRED','不再从单排模板生成双排候选；请在样例中提供所需双排 MPP。')


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('schema');p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('discover');p.add_argument('--connection',default=str(ROOT/'config/colayout_lite.json'));p.add_argument('--library',required=True);p.add_argument('--cell',required=True);p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('build');p.add_argument('--samples',type=Path,required=True);p.add_argument('--index',type=int,required=True);p.add_argument('--id',required=True);p.add_argument('--name',required=True);p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('validate');p.add_argument('--recipe',type=Path,required=True);p.add_argument('--connection',default=str(ROOT/'config/colayout_lite.json'));p.add_argument('--library',required=True);p.add_argument('--cell',required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--drc-profile',type=Path)
    p=sub.add_parser('install');p.add_argument('--recipe',type=Path,required=True);p.add_argument('--profile',type=Path,required=True)
    p=sub.add_parser('seed');p.add_argument('--profile',type=Path,required=True);p.add_argument('--template',required=True);p.add_argument('--width-um',type=float,required=True);p.add_argument('--cut-space-um',type=float);p.add_argument('--id',required=True);p.add_argument('--name',required=True);p.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.cmd=='schema':write_json(args.out,GuardRecipe.model_json_schema());print(args.out)
    elif args.cmd=='discover':
        data,p=discover(Adapter(NativeTransport(args.connection)),args.library,args.cell);write_json(args.out,data)
        print(json.dumps({'samples':str(args.out),'paths':[{k:r[k] for k in ('centerline_bbox','closed_rectangle','contact_rows','master_lpp','width')} for r in data['paths']]},ensure_ascii=False))
    elif args.cmd=='build':
        recipe=build(json.loads(args.samples.read_text(encoding='utf8')),args.index,args.id,args.name);recipe.save(args.out);print(args.out)
    elif args.cmd=='validate':
        from .drc.models import DrcProfile
        drc=DrcProfile.model_validate_json(args.drc_profile.read_text(encoding='utf8')) if args.drc_profile else None
        recipe=GuardRecipe.model_validate_json(args.recipe.read_text(encoding='utf8'));validate(recipe,args.connection,args.library,args.cell,folder=args.out,drc_profile=drc);print(args.out/'recipe.json')
    elif args.cmd=='seed':
        from .technology import TechnologyProfile
        p=TechnologyProfile.model_validate_json(args.profile.read_text(encoding='utf8'));r=seed(p,args.template,args.width_um,args.id,args.name,args.cut_space_um);r.save(args.out);print(args.out)
    else:install(GuardRecipe.model_validate_json(args.recipe.read_text(encoding='utf8')),args.profile);print('installed')


if __name__=='__main__':main()

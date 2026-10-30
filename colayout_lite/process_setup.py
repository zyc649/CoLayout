"""Agent preparation and native validation. Human confirmation lives in the UI.

Run --help for inspect / prepare / list. No command silently confirms a profile.
"""
from pathlib import Path,PurePosixPath
from datetime import datetime,timezone
from uuid import uuid4
import argparse,json
from .paths import ROOT
from .transport import NativeTransport, skill
from .model import LiteError,digest
from .technology import TechnologyProfile
from .process_library import ProcessLibrary,write_json
from .onboarding import discover,save_profile
from .adapter import Adapter
from .editor import Editor
from .actions import Actions
from .process_measurements import metal_pair,measure_single_via,settings_profile,policy_key


def inspect_live(env_file):
    if not Path(env_file).resolve().is_file():
        raise LiteError('BRIDGE_ENV_MISSING','Run the repository connection setup before inspecting Virtuoso.')
    from virtuoso_bridge import VirtuosoClient
    from .bridge_environment import select_environment
    from .sexpr import parse_native
    select_environment(env_file);client=VirtuosoClient.from_env()
    code='list(getWorkingDir() foreach(mapcar w hiGetWindowList() if(w!=hiGetCIWindow() && geGetWindowCellView(w) && geGetWindowCellView(w)~>viewName=="layout" then let((cv) cv=geGetWindowCellView(w) list(cv~>libName cv~>cellName dbFullLibPath(cv~>libName) techGetTechFile(cv)~>libName cv~>modifiedButNotSaved)) else nil)))'
    result=client.execute_skill(code)
    if result.errors:raise LiteError('BRIDGE_INSPECT_FAILED',str(result.errors))
    cwd,rows=parse_native(result.output.strip())
    layouts=[dict(zip(('library','cell','library_path','technology','unsaved'),r)) for r in rows or [] if r]
    return client,{'working_directory':cwd,'layouts':layouts}


def make_connection(env_file,library,cell,project_root):
    client,live=inspect_live(env_file)
    rows=[r for r in live['layouts'] if r['library']==library and r['cell']==cell]
    if not rows:raise LiteError('SAMPLE_NOT_OPEN','inspect 未找到指定的已打开 Layout。')
    sample=rows[0];root=PurePosixPath(project_root)
    if not root.is_absolute() or '..' in root.parts or root!=PurePosixPath(sample['library_path']).parent or sample['library']==sample['technology']:
        raise LiteError('SAMPLE_PROJECT_ROOT_MISMATCH','project-root 必须是该业务库目录的直接父目录；不能使用 PDK 库作为样例。')
    # The selected project receives scratch exports, never global startup files.
    scratch=str(root/'.colayout-bridge');r=client.execute_skill('progn(unless(isDir('+skill(scratch)+') createDir('+skill(scratch)+')) t)')
    if r.errors:raise LiteError('SCRATCH_DIRECTORY_FAILED',str(r.errors))
    ident=digest([str(Path(env_file).resolve()),str(root),library])[:12]
    path=ROOT/'config/connections'/('process-'+ident+'.json')
    if path.exists():
        old=json.loads(path.read_text(encoding='utf8'))
        if old['allowed_remote_root']!=str(root) or Path(old['bridge_env'])!=Path(env_file).resolve():raise LiteError('CONNECTION_ID_COLLISION')
        return path
    write_json(path,{'schema_version':'colayout-lite-connection-1','bridge_env':str(Path(env_file).resolve()),
        'allowed_remote_root':str(root),'state_directory':'artifacts/process-library/runtime/'+ident,
        'profiles_directory':'config/technologies','default_library':library,'default_source_cell':cell})
    return path










def load_recipes(profile,paths,source,mode):
    from .guard_recipes import GuardRecipe
    recipes=[]
    for path in paths:
        recipe=GuardRecipe.model_validate_json(Path(path).read_text(encoding='utf8'));recipe.check_profile(profile)
        if not recipe.ready():raise LiteError('GUARD_RECIPE_NOT_VALIDATED')
        if mode=='sample' and recipe.source.get('sample')!=source:raise LiteError('GUARD_SAMPLE_MODE_REQUIRES_THIS_SAMPLE')
        recipes.append(recipe.model_dump())
    return profile.model_copy(update={'guard_recipes':recipes})


def validate(path,profile,progress=lambda s:None):
    """Private config/profile: active defaults are never changed by preparation."""
    path=Path(path);data=json.loads(path.read_text(encoding='utf8'));folder=path.parent/'validation'/uuid4().hex[:10]
    profile.save(folder/'profiles/process.json')
    cfg=json.loads(Path(data['connection']).read_text(encoding='utf8'))
    cfg.update(profiles_directory=str((folder/'profiles').resolve()),preferred_profile=profile.id)
    cp=folder/'connection.json';write_json(cp,cfg)
    a=Adapter(NativeTransport(cp));source=data['source'];progress('复制样例，在独立副本中验证配置…')
    from .native_temporary import TemporaryCopies
    with TemporaryCopies(a):
        w,p=a.create_validation_workspace(source['library'],source['cell'],label='PROCESS16');e=Editor(w,p);act=Actions(e)
        report={'status':'running','target':w.baseline.cell,'checks':[],'policy_key':policy_key(profile)}
        rp=folder/'report.json';write_json(rp,report)
        def check(name,ok):
            report['checks'].append({'name':name,'passed':bool(ok)});write_json(rp,report)
            if not ok:raise LiteError('PROCESS_VALIDATION_FAILED',name)
        try:
            ids=[]
            for i,lpp in enumerate(p.writable_lpps):
                ids.append(act.execute('create_rect',dict(x=100+i*10,y=100,width=4,height=2,lpp=lpp)).uid)
            from .wire_defaults import default_width
            wire_layers=list(p.editor_defaults.get('widths_um',{})) or [p.editor_defaults['layer'][0]]
            for i,layer in enumerate(wire_layers):
                if (layer,'drawing') not in p.writable_lpps:continue
                for action,pts in [('create_path90',[[100,120+i*30],[104,120+i*30],[104,124+i*30]]),('create_path45',[[100,130+i*30],[104,134+i*30],[108,134+i*30]])]:
                    ids.append(act.execute(action,dict(points=pts,width=default_width(p,layer),lpp=[layer,'drawing'])).uid)
            definitions=[v['definition'] for v in data.get('stack_measurement',{}).get('vias',[])] or [p.editor_defaults['via_definition']]
            for i,definition in enumerate(definitions):ids.append(act.execute('create_via',dict(x=130+i*10,y=140,definition=definition,via_parameters={'cutRows':1,'cutColumns':1})).uid)
            e.w=a.commit(e.w);check('所有允许层矩形、默认线宽的90°/45°线、默认单孔写回读回',e.w.state=='clean')
            for uid in ids:act.execute('move',dict(dx=1,dy=2),uid)
            e.w=a.commit(e.w);check('上述对象移动后读回',e.w.state=='clean')
            for uid in ids:e.delete(uid)
            e.w=a.commit(e.w);check('删除恢复原始副本，器件/端子/关联未改变',e.w.baseline.semantic()==w.baseline.semantic())
            report.update(status='passed',scope='配置所选层/默认线宽/标准单孔的往返；不是全部 via 或 DRC/LVS 验证',
                guardring='configured_not_validated_here' if p.guard_templates else 'not_configured')
        except Exception as exc:
            report.update(status='failed',error=str(exc));raise
        finally:write_json(rp,report)
        data.update(profile=profile.model_dump(),status='base_verified' if data.get('schema_version')=='colayout-process-proposal-2' else 'ready_for_confirmation',validation={**report,'report':str(rp.resolve())})
        write_json(path,data);progress('基础工艺往返验证通过。')
        return data


def prepare(connection,library,cell,name=None,*,via_uid=None,explicit_pair=None,explicit_stack=None,via_uids=None,guard_recipes=None,guard_mode='sample',drc_profile=None,root=None,progress=print):
    store=ProcessLibrary(root);a,s,p=discover(Path(connection),library,cell)
    if s.dirty:raise LiteError('SAVE_SAMPLE_FIRST','请先在 Virtuoso 保存 Layout 样例。')
    if not any(o.kind=='inst' for o in s.objects.values()):raise LiteError('SAMPLE_DEVICE_REQUIRED','样例需包含至少一个正常实例化器件，用于验证内部图形和实例保护。')
    if any(o.kind=='inst' and o.read_only_reason=='master_unresolved' for o in s.objects.values()):raise LiteError('SAMPLE_MASTER_UNRESOLVED')
    from .wire_defaults import metal_stack,measure_stack
    order=metal_stack(p,explicit_stack)
    if explicit_pair and tuple(order[:2])!=tuple(explicit_pair):raise LiteError('METAL_STACK_PAIR_MISMATCH')
    choices=dict(via_uids or {})
    if via_uid:choices['/'.join(order[:2])]=via_uid
    stack_measurement=measure_stack(s,p,order,choices);pair=tuple(order[:2]);measurement=stack_measurement['vias'][0]
    p=p.model_copy(update={'editor_defaults':{**p.editor_defaults,'metal_stack':order,'widths_um':stack_measurement['widths_um']}})
    if guard_mode!='sample':raise LiteError('GUARD_SAMPLE_REQUIRED','双排仅支持用户提供的样例，不再生成 Agent 自拟配方。')
    # A new onboarding proposal does not silently inherit unrelated factories.
    p=p.model_copy(update={'guard_recipes':[]})
    if guard_recipes:
        p=load_recipes(p,guard_recipes,{'library':library,'cell':cell},guard_mode)
    from .wire_defaults import default_writable_lpps
    layers=default_writable_lpps(p,order)
    folder=store.folder/'drafts'/uuid4().hex;path=folder/'proposal.json'
    proposal={'schema_version':'colayout-process-proposal-2','status':'preparing','created_at':datetime.now(timezone.utc).isoformat(),
        'connection':str(Path(connection).resolve()),'source':{'library':library,'cell':cell},'profile':p.model_dump(),
        'metal_pair':pair,'measurement':measurement,'stack_measurement':stack_measurement,'limitations':(['GuardRing 未配置，本次不追查模板。'] if not p.guard_templates else []),
        'source_semantic':digest(s.semantic()),'guard_mode':guard_mode}
    candidate=settings_profile(proposal,name or p.label,measurement['suggested_width_um'],layers)
    from .drc.models import DrcProfile
    from .process_bundle import capture_publication,complete
    dp=Path(drc_profile) if drc_profile else store.root/'config/drc'/(p.key+'.json')
    drc=DrcProfile.model_validate_json(dp.read_text(encoding='utf8')) if dp.exists() else None
    proposal['profile']=candidate.model_dump();proposal['publication_base']=capture_publication(proposal,store)
    candidate.save(folder/'technology.json');write_json(path,proposal)
    complete(path,drc,progress=progress)
    return path


def confirm(path,profile,*,store=None,progress=lambda s:None,drc_profile=None):
    """Retained legacy adapter. Current UI/API review uses process_review.approve."""
    from .process_compat import confirm_legacy
    return confirm_legacy(path,profile,store=store,progress=progress,drc_profile=drc_profile)


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('list')
    i=sub.add_parser('inspect');i.add_argument('--env',default=str(ROOT/'.env'))
    c=sub.add_parser('connect');c.add_argument('--env',default=str(ROOT/'.env'));c.add_argument('--library',required=True);c.add_argument('--cell',required=True);c.add_argument('--project-root',required=True)
    p=sub.add_parser('prepare');p.add_argument('--connection',required=True);p.add_argument('--library',required=True);p.add_argument('--cell',required=True)
    p.add_argument('--name');p.add_argument('--via-uid');p.add_argument('--metal1');p.add_argument('--metal2')
    p.add_argument('--metal-stack',nargs='+');p.add_argument('--via-uids',type=Path,help='JSON: {"M1/M2":"uid", ...}')
    p.add_argument('--guard-recipes',type=Path,nargs='+',help='Optional validated GuardRecipe JSON files')
    p.add_argument('--guard-mode',choices=['sample','agent'],default='sample')
    p.add_argument('--drc-profile',type=Path,help='Local+remote DRC candidate; reuse matching saved config if omitted')
    c=sub.add_parser('complete');c.add_argument('--proposal',type=Path,required=True);c.add_argument('--drc-profile',type=Path);c.add_argument('--guard-recipes',type=Path,nargs='+')
    args=parser.parse_args()
    try:
        if args.command=='inspect':print(json.dumps(inspect_live(args.env)[1],ensure_ascii=False,indent=2));return
        if args.command=='connect':print(json.dumps({'connection':str(make_connection(args.env,args.library,args.cell,args.project_root).resolve())},ensure_ascii=False));return
        if args.command=='list':
            s=ProcessLibrary();s.migrate_existing();print(json.dumps({'configured':s.entries(),'pending':[str(p) for p,d in s.drafts()]},ensure_ascii=False,indent=2));return
        if args.command=='complete':
            from .process_bundle import complete
            from .drc.models import DrcProfile
            if args.guard_recipes:
                draft=json.loads(args.proposal.read_text(encoding='utf8'))
                if draft['status'] in ('confirmed','superseded'):raise LiteError('PROPOSAL_NOT_EDITABLE')
                draft['profile']=load_recipes(TechnologyProfile.model_validate(draft['profile']),args.guard_recipes,draft['source'],draft.get('guard_mode','sample')).model_dump(mode='json');write_json(args.proposal,draft)
            d=complete(args.proposal,DrcProfile.model_validate_json(args.drc_profile.read_text(encoding='utf8')) if args.drc_profile else None,progress=print)
            print(json.dumps({'status':d['status'],'proposal':str(args.proposal),'sections':d['sections']},ensure_ascii=False));return
        if bool(args.metal1)!=bool(args.metal2):raise LiteError('BOTH_METAL_LAYERS_REQUIRED')
        path=prepare(args.connection,args.library,args.cell,args.name,via_uid=args.via_uid,explicit_pair=(args.metal1,args.metal2) if args.metal1 else None,
            explicit_stack=args.metal_stack,via_uids=json.loads(args.via_uids.read_text(encoding='utf8')) if args.via_uids else None,guard_recipes=args.guard_recipes,guard_mode=args.guard_mode,drc_profile=args.drc_profile)
        print(json.dumps({'status':'ready_for_confirmation','proposal':str(path.resolve()),'next':'旧格式准备结果已保留；请使用 colayout-pdk / process_agent 通过 API 重新提交待审核配置。'},ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'status':'failed','error':str(exc),'details':getattr(exc,'details',{})},ensure_ascii=False));raise SystemExit(1)


if __name__=='__main__':main()

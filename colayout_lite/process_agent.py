"""Dedicated process-agent helper. Collect/check through Bridge, submit through HTTP."""
import argparse,json
from pathlib import Path,PurePosixPath
from uuid import uuid4
from .paths import ROOT
from .model import LiteError,digest
from .process_library import write_json,ProcessLibrary
from .process_package import ProcessPackage
from .agent_tools.client import AgentClient


def app_client(path=None):
    if path is None:
        installation=json.loads((ROOT/'.colayout/installation.json').read_text(encoding='utf8'))
        path=Path(installation['document']).parent/'agent-connection.json'
    return AgentClient(path)


def binding(client,ident=None):
    data=client.call('process_configuration',{'action':'requirements'},wait_seconds=0)
    rows=data['connections']
    matches=[r for r in rows if r['id']==ident] if ident else [r for r in rows if r['current']]
    if not matches and len(rows)==1:matches=rows
    if len(matches)!=1:raise LiteError('PROCESS_CONNECTION_REQUIRED','先用 requirements 选择本机连接 ID。')
    return matches[0]


def collect(client,folder,*,library=None,cell=None,connection_id=None,project_root=None,
            explicit_stack=None,via_uids=None,name=None,variant='',replace_key=None,skip_guards=False,layer_materials=None):
    from .process_setup import inspect_live
    from .onboarding import discover
    from .wire_defaults import metal_stack,measure_stack,default_writable_lpps
    from .guard_setup import discover as guard_samples,build,is_open_corner_sample
    from .sexpr import parse_native
    row=binding(client,connection_id);cfg=json.loads(Path(row['collection_connection_file']).read_text(encoding='utf8'))
    env=(ROOT/cfg['bridge_env']).resolve()
    _,live=inspect_live(env)
    layouts=live['layouts']
    if bool(library)!=bool(cell):raise LiteError('PROCESS_SAMPLE_REQUIRED')
    if library:
        selected=[s for s in layouts if s['library']==library and s['cell']==cell]
        sample=selected[0] if selected else None
    else:
        if len(layouts)!=1:raise LiteError('PROCESS_SAMPLE_AMBIGUOUS','请明确用户的样例库/cell，不使用历史默认值。',layouts=layouts)
        sample=layouts[0];library=sample['library'];cell=sample['cell']
    if sample and sample['unsaved']:raise LiteError('SAVE_SAMPLE_FIRST')
    remote=project_root or (str(PurePosixPath(sample['library_path']).parent) if sample else cfg['allowed_remote_root'])
    folder=Path(folder)
    if folder.exists():raise LiteError('COLLECTION_DIRECTORY_EXISTS','使用新的输出目录，保留原采集记录。')
    folder.mkdir(parents=True)
    cfg.update(allowed_remote_root=remote,bridge_env=str(env),state_directory=str((folder/'native-runtime').resolve()),
               profiles_directory=str((folder/'profiles').resolve()),default_library=library,default_source_cell=cell)
    cfg.pop('preferred_profile',None);connection=folder/'collection-connection.json';write_json(connection,cfg)
    adapter,snapshot,p=discover(connection,library,cell)
    write_json(folder/'native-technology.json',p.model_dump(mode='json'))
    write_json(folder/'sample-layout.json',snapshot.model_dump(mode='json'))
    if snapshot.dirty:raise LiteError('SAVE_SAMPLE_FIRST')
    if PurePosixPath(snapshot.library_path).parent!=PurePosixPath(remote) or library==p.native_technology_name:
        raise LiteError('SAMPLE_PROJECT_ROOT_MISMATCH')
    if not any(o.kind=='inst' for o in snapshot.objects.values()):raise LiteError('SAMPLE_DEVICE_REQUIRED')
    if any(o.kind=='inst' and o.read_only_reason=='master_unresolved' for o in snapshot.objects.values()):raise LiteError('SAMPLE_MASTER_UNRESOLVED')
    if layer_materials:
        from .technology import with_layer_materials
        p=with_layer_materials(p,layer_materials)
    order=metal_stack(p,explicit_stack);measurement=measure_stack(snapshot,p,order,via_uids)
    key=replace_key or 'pdk-'+digest([p.native_fingerprint,p.native_technology_name,variant])[:24]
    ident='process-'+digest(key)[:16]
    existing=client.call('process_configuration',{'action':'list'},wait_seconds=0)['configured']
    saved=None
    if any(r['key']==key for r in existing):
        saved=ProcessPackage.model_validate(client.call('process_configuration',{'action':'get','technology_key':key},wait_seconds=0)['package'])
        if saved.technology.native_fingerprint!=p.native_fingerprint or (saved.technology.native_technology_name and saved.technology.native_technology_name!=p.native_technology_name):
            raise LiteError('PROCESS_IDENTITY_MISMATCH')
        ident=saved.technology.id
    recipes=[];unsupported=[]
    if not skip_guards:
        samples,_=guard_samples(adapter,library,cell);write_json(folder/'guard-samples.json',samples)
        selected=[i for i,row in enumerate(samples['paths']) if is_open_corner_sample(row)]
        if samples['paths'] and not selected:
            raise LiteError('GUARD_OPEN_SAMPLE_REQUIRED','需要所需 P/N 类型的原生 90° 开放路径样例；仅闭环不能用于新配置。无需保护环时可用 --skip-guards。')
        seen=set()
        for index,item in enumerate(samples['paths']):
            if index not in selected:continue
            try:
                recipe=build(samples,index,'sample-'+str(index+1),'样例 MPP '+str(index+1))
                signature=digest([recipe.kind,recipe.master_lpp,recipe.width,[r.model_dump(mode='json') for r in recipe.parts],[r.model_dump(mode='json') for r in recipe.open_parts]])
                if signature in seen:continue
                seen.add(signature);recipes.append(recipe.model_dump(mode='json'))
            except (LiteError,ValueError) as exc:unsupported.append({'index':index,'native_id':item['native_id'],'reason':str(exc)})
    token=uuid4().hex;remote_cdf=adapter.native.call('ltProcessSample',library,cell,token)[0]
    cdf_file=folder/'device-cdf.sexpr';result=adapter.native.client.download_file(remote_cdf,str(cdf_file))
    if result.errors:raise LiteError('PROCESS_SAMPLE_DOWNLOAD_FAILED')
    rows=parse_native(cdf_file.read_text(encoding='utf8')) or []
    devices=[{'name':r[0],'master':r[1],'terminals':r[2],'cdf_status':r[3][0],
              'parameters':r[3][1] or [],'instance_properties':r[4]} for r in rows]
    write_json(folder/'device-evidence.json',devices)
    names={parameter[0] for device in devices for parameter in device['parameters']}
    summary=tuple(s for s in p.schematic_summary_parameters if s in names)
    p=p.model_copy(update={'id':ident,'label':name or (saved.technology.label if saved else p.label),
        'configuration_id':key,'writable_lpps':tuple(default_writable_lpps(p,order)),
        'guard_templates':[],'guard_recipes':recipes,'schematic_summary_parameters':summary,
        'editor_defaults':{'metal_stack':order,'layer':[order[0],'drawing'],'width_um':measurement['widths_um'][order[0]],
                           'widths_um':measurement['widths_um'],'via_definition':measurement['vias'][0]['definition']}})
    from .drc.models import DrcProfile
    from .drc.waivers import WaiverPolicy
    drc=saved.drc if saved else DrcProfile(id=p.label+' DRC',technology_fingerprint=p.native_fingerprint,configuration_id=key)
    report=saved.report_policy if saved else WaiverPolicy(technology_fingerprint=p.native_fingerprint,configuration_id=key)
    package=ProcessPackage(technology=p,drc=drc,report_policy=report,
        sample_evidence={'source_digest':digest(snapshot.semantic()),'via_uids':via_uids or {},
            'standalone_lpps':sorted({o.shape.lpp for o in snapshot.objects.values() if o.shape and o.shape.kind in ('rect','polygon','path','pathSeg') and o.shape.lpp}),
            'stack_measurement':measurement,'devices':devices,'unconfigured_guards':unsupported,'variant':variant})
    from .drc.onboarding import discover as find_rules
    write_json(folder/'rule-candidates.json',find_rules(connection))
    from .codec import decode as decode_native
    after,_=decode_native(adapter.native.read(library,cell))
    if after.semantic()!=snapshot.semantic() or after.counter!=snapshot.counter or after.dirty!=snapshot.dirty:
        raise LiteError('PDK_SAMPLE_CHANGED')
    write_json(folder/'package.json',package.model_dump(mode='json'))
    meta={'source':{'library':library,'cell':cell},'connection_id':row['id'],'project_root':remote,
          'collection_connection':str(connection.resolve()),'package':str((folder/'package.json').resolve()),
          'status':'collected; fill actual DRC rules and review preferences before check'}
    write_json(folder/'collection.json',meta)
    return {**meta,'native_technology':p.native_technology_name,'configuration_key':p.key,
            'metals':order,'sample_recipes':len(recipes),'unconfigured_guards':unsupported,'devices':len(devices),
            'mim_capacitor':drc.mim_capacitor.model_dump(mode='json'),
            'mim_next':'从 MIM 样例、技术资料及实际提取规则确认图层和上下金属；未知可提交待确认方案，由人审核填写。'}


def check(folder,progress=print):
    from .process_configuration import ProcessConfiguration
    from .process_review import prepare
    folder=Path(folder);meta=json.loads((folder/'collection.json').read_text(encoding='utf8'))
    package=ProcessPackage.model_validate_json((folder/'package.json').read_text(encoding='utf8')).require_complete()
    result=prepare(ProcessConfiguration(ProcessLibrary()),package,meta['source'],meta['collection_connection'],progress)
    write_json(folder/'checked-package.json',result['package'])
    write_json(folder/'verification.json',{k:v for k,v in result.items() if k!='package'})
    return {k:v for k,v in result.items() if k!='package'}


def request(folder):
    folder=Path(folder);path=folder/'submit-request.json'
    if path.exists():raise LiteError('REQUEST_FILE_EXISTS','请求文件已存在；结果未知时保持原文件重试。')
    meta=json.loads((folder/'collection.json').read_text(encoding='utf8'))
    proof=json.loads((folder/'verification.json').read_text(encoding='utf8'))
    package=json.loads((folder/'checked-package.json').read_text(encoding='utf8'))
    data={'tool':'process_configuration','client_id':'pdk-'+uuid4().hex,'request_id':uuid4().hex,
          'arguments':{'action':'submit','package':package,'sample':meta['source'],'connection_id':meta['connection_id'],
                       'project_root':meta['project_root'],'verification_id':proof['verification_id']}}
    write_json(path,data);return {'request_file':str(path.resolve())}


def submit(client,path):
    path=Path(path);data=json.loads(path.read_text(encoding='utf8'))
    if data.get('tool')!='process_configuration' or data.get('arguments',{}).get('action')!='submit':raise LiteError('PROCESS_REQUEST_REQUIRED')
    client.client_id=data['client_id']
    # Never rewrite the request or change its ID on failure/unknown outcomes.
    result=client.call(data['tool'],data['arguments'],request_id=data['request_id'],wait_seconds=0)
    write_json(path.with_name(path.stem+'-response-'+uuid4().hex[:8]+'.json'),result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--api-connection',type=Path)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('requirements','list'):sub.add_parser(name)
    inspect=sub.add_parser('inspect');inspect.add_argument('--connection-id')
    p=sub.add_parser('collect');p.add_argument('--out',type=Path,required=True);p.add_argument('--library');p.add_argument('--cell')
    p.add_argument('--connection-id');p.add_argument('--project-root');p.add_argument('--name');p.add_argument('--variant',default='')
    p.add_argument('--replace-key');p.add_argument('--metal-stack',nargs='+');p.add_argument('--via-uids',type=Path);p.add_argument('--skip-guards',action='store_true')
    p.add_argument('--layer-materials',type=Path,help='仅补充原生 unknown 材质：{层名:{material:角色,source:真实工艺依据}}')
    for name in ('check','request'):
        p=sub.add_parser(name);p.add_argument('folder',type=Path)
    p=sub.add_parser('submit');p.add_argument('request_file',type=Path)
    p=sub.add_parser('status');p.add_argument('proposal_id')
    p=sub.add_parser('export');p.add_argument('technology_key');p.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.command=='check':result=check(args.folder)
        elif args.command=='request':result=request(args.folder)
        else:
            client=app_client(args.api_connection)
            if args.command in ('requirements','list'):result=client.call('process_configuration',{'action':args.command},wait_seconds=0)
            elif args.command=='inspect':
                from .process_setup import inspect_live
                row=binding(client,args.connection_id);cfg=json.loads(Path(row['collection_connection_file']).read_text(encoding='utf8'))
                result=inspect_live(ROOT/cfg['bridge_env'])[1]
            elif args.command=='collect':result=collect(client,args.out,library=args.library,cell=args.cell,connection_id=args.connection_id,
                project_root=args.project_root,name=args.name,variant=args.variant,replace_key=args.replace_key,explicit_stack=args.metal_stack,
                via_uids=json.loads(args.via_uids.read_text(encoding='utf8')) if args.via_uids else None,skip_guards=args.skip_guards,
                layer_materials=json.loads(args.layer_materials.read_text(encoding='utf8')) if args.layer_materials else None)
            elif args.command=='submit':result=submit(client,args.request_file)
            elif args.command=='status':result=client.call('process_configuration',{'action':'status','proposal_id':args.proposal_id},wait_seconds=0)
            else:
                if args.out.exists():raise LiteError('EXPORT_FILE_EXISTS')
                result=client.call('process_configuration',{'action':'export','technology_key':args.technology_key},wait_seconds=0)
                write_json(args.out,result);result={'file':str(args.out.resolve())}
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as exc:
        print(json.dumps({'status':'failed','code':getattr(exc,'code','ERROR'),'message':str(exc),'details':getattr(exc,'details',{})},ensure_ascii=False));raise SystemExit(1)


if __name__=='__main__':main()

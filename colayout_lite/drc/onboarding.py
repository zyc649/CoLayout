"""PDK onboarding checks reuse the production local/remote engines."""
import math,re,shlex,time
from pathlib import Path
from ..model import LiteError,Shape,digest
from ..editor import Editor
from ..adapter import Adapter,require_unchanged
from ..paths import ROOT
from ..transport import NativeTransport
from ..process_library import write_json
from .models import Region
from . import jobs
from .local import run


def settings_key(profile):
    return digest(profile.model_dump(exclude={'id','provenance'}))


def probe(profile,connection):
    if profile.remote is None:raise LiteError('REMOTE_DRC_NOT_CONFIGURED')
    native=NativeTransport(connection);r=profile.remote;hashes={}
    for key in ['deck_path','layer_map','calibre','strmout','environment']:
        path=getattr(r,key);flag='-x' if key in ('calibre','strmout') else '-r'
        check=native.client.ssh_runner.run_command('test '+flag+' '+shlex.quote(path),timeout=15)
        if check.returncode:raise LiteError('DRC_PATH_UNAVAILABLE',path)
        if key in ('deck_path','layer_map'):
            check=native.client.ssh_runner.run_command('sha256sum -- '+shlex.quote(path),timeout=15)
            values=check.stdout.split();value=values[0] if values else ''
            if check.returncode or not re.fullmatch('[0-9a-f]{64}',value):raise LiteError('DRC_INVALID_CHECKSUM')
            field='deck_sha256' if key=='deck_path' else 'layer_map_sha256'
            old=getattr(r,field)
            if old and old!=value:raise LiteError('DRC_SOURCE_CHANGED','规则/映射文件与候选配置校验和不一致：'+path)
            hashes[field]=value
    return profile.model_copy(update={'remote':r.model_copy(update=hashes)})


def discover(connection):
    """Bounded project search. Candidates are evidence, never auto-selected."""
    native=NativeTransport(connection);root=native.config['allowed_remote_root']
    cmd='find '+shlex.quote(root)+" -maxdepth 5 \\( -type d \\( -name '.colayout-*' -o -name 'COLAYOUT_MVP_*' \\) -prune \\) -o -type f \\( -iname '*.drc' -o -iname '*.svrf' -o -iname '*.tvf' -o -iname '*runset*' -o -iname '*strm*map*' \\) -print | head -n 100"
    r=native.client.ssh_runner.run_command(cmd,timeout=30)
    if r.returncode:raise LiteError('DRC_DISCOVERY_FAILED',r.stderr)
    saved=[]
    from .models import DrcProfile
    for path in (ROOT/'config/drc').glob('*.json'):
        p=DrcProfile.model_validate_json(path.read_text(encoding='utf8'))
        if p.remote and p.remote.deck_path.startswith(root.rstrip('/')+'/'):
            saved.append({'profile':str(path.resolve()),'technology_fingerprint':p.technology_fingerprint,
                'deck':p.remote.deck_path,'layer_map':p.remote.layer_map,'provenance':p.provenance})
    return {'project_root':root,'candidates':r.stdout.splitlines(),'saved_candidates':saved,'limit':100,
        'note':'核对工艺版本/金属栈/宏选项；多个候选不可按文件名自动认定正确。未找到时请用户提供规则主文件和层映射路径。'}


def validate(profile,technology,connection,library,cell,folder,progress=lambda s:None):
    """Deliberate width violation and repair, with all raw results preserved.

    This tests the supported local rule and real server execution/coordinates.
    Local rule names do not need to equal foundry deck rule names.
    """
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);profile.check_technology(technology)
    enabled=[r for r in profile.rules if r.enabled]
    if not enabled:raise LiteError('LOCAL_DRC_RULES_REQUIRED','请先从实际工艺规则配置本地 DRC。')
    if any(not r.source.strip() for r in enabled):raise LiteError('DRC_RULE_SOURCE_REQUIRED','启用的规则必须标明真实规则文件和规则编号。')
    widths=[r for r in enabled if r.kind=='width' and (r.layer,'drawing') in technology.writable_lpps]
    if not widths:raise LiteError('DRC_WIDTH_PROBE_REQUIRED','至少需一条可绘图层的基本线宽规则用于本地验证。')
    profile=probe(profile,connection);profile.save(folder/'profile.json')
    a=Adapter(NativeTransport(connection));before,_=a.read(library,cell)
    w,_=a.create_validation_workspace(library,cell,label='PDK_DRC21');scale=technology.dbu_per_micron;g=technology.grid
    rule=widths[0];minimum=math.ceil(rule.value*scale/g)*g;narrow=minimum-g
    if narrow<=0:raise LiteError('DRC_THRESHOLD_BELOW_GRID')
    bounds=[o.bbox for o in w.baseline.objects.values() if o.bbox]
    margin=max(100*scale,math.ceil(profile.remote.halo_um*scale)*4)
    x=math.ceil((max([b[1][0] for b in bounds] or [0])+margin)/g)*g;y=0
    side=math.ceil(max(10*scale,minimum*4,math.sqrt(max([r.value for r in enabled if r.kind=='area' and r.layer==rule.layer] or [0]))*scale*2)/g)*g
    e=Editor(w,technology);uid=e.create(Shape(kind='rect',lpp=(rule.layer,'drawing'),bbox=((x,y),(x+side,y+narrow))))
    region=Region(bbox=((x-g,y-g),(x+side+g,y+side+g)))
    report={'status':'running','settings_key':settings_key(profile),'target':w.baseline.cell,'probe_rule':rule.id,'checks':[],
        'scope':'本地故意窄线/修复、服务器实际执行和可用标记的坐标核对；不匹配本地/服务器规则名，不证明逐条规则等价或样例全规则通过。'}
    write_json(folder/'report.json',report)
    for name,bad in [('bad',True),('fixed',False)]:
        if not bad:e.edit(uid,bbox=((x,y),(x+side,y+side)))
        e.w.save(folder/(name+'-workspace.json'),portable=True)
        progress('DRC 联合验证：'+('故意错误' if bad else '修复后')+'（本地 + 服务器）')
        local=run(e.w,technology,profile,region);local.save(folder/(name+'-local.json'))
        job=jobs.start(e.w,technology,profile,region,'calibre');started=time.monotonic()
        while True:
            state=jobs.status(job['job_id'])
            if state['status'] in ('completed','failed','cancelled'):break
            if time.monotonic()-started>profile.remote.timeout_seconds*3+60:
                jobs.cancel(job['job_id']);raise LiteError('PDK_DRC_TIMEOUT')
            time.sleep(.3)
        if state['status']!='completed':raise LiteError('PDK_REMOTE_DRC_FAILED',state.get('message',''))
        remote=jobs.result(job['job_id']);remote.save(folder/(name+'-remote.json'))
        for engine,result in [('local',local),('remote',remote)]:
            hits=[m for m in result.markers if m.rule_id==rule.id] if engine=='local' else list(result.markers)
            if result.status!='completed' or result.coverage.get('truncated'):raise LiteError('PDK_DRC_INCOMPLETE')
            if engine=='local' and bool(hits)!=bad:raise LiteError('PDK_DRC_PROBE_MISMATCH',engine+' '+name+' '+rule.id)
            if any(m.bbox[1][0]<region.bbox[0][0] or m.bbox[0][0]>region.bbox[1][0] or
                   m.bbox[1][1]<region.bbox[0][1] or m.bbox[0][1]>region.bbox[1][1] for m in hits):
                raise LiteError('PDK_DRC_COORDINATES')
            if engine=='remote' and not result.coverage.get('rule_checks_executed'):raise LiteError('PDK_DRC_NO_RULES_EXECUTED')
            report['checks'].append({'engine':engine,'case':name,'passed':True,'probe_hits':len(hits),
                'coordinate_witness':bool(hits),'rule_name_mapping_required':False,
                'raw_markers':len(result.markers),'report':str((folder/(name+'-'+engine+'.json')).resolve()),
                'rule_checks':result.coverage.get('rule_checks_executed'),'coverage':result.coverage})
        write_json(folder/'report.json',report)
    after,_=a.read(library,cell);require_unchanged(w.model_copy(update={'baseline':before}),after)
    report.update(status='passed',source_unchanged=True);write_json(folder/'report.json',report)
    return profile,{**report,'report':str((folder/'report.json').resolve())}

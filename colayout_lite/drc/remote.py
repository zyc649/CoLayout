from pathlib import Path
from time import sleep,perf_counter
import json,shlex,re
from ..adapter import Adapter,require_unchanged
from ..paths import ROOT
from ..transport import NativeTransport, skill
from ..process_library import write_json
from ..hierarchy import same_dependencies
from ..model import LiteError
from .models import Result,stamp,validate_context
from .rdb import parse
from ..materials import associate,AssociationIndex
from .remote_deck import validate_windows,waiver_receipt
from .scope import SERVER_BOUNDARY_POLICY


def run(w,technology,profile,region,job_id,folder,progress,*,waive_regions_um=(),scope_info=None,result_limit=None):
    from ..native_lane import channel
    validate_windows(waive_regions_um)
    if result_limit is not None and (type(result_limit) is not int or not 1000<=result_limit<=1000000):
        raise LiteError('INVALID_DRC_RESULT_LIMIT')
    with channel(w.connection_config,cancelled=lambda:(folder/'cancel.flag').exists(),
                 progress=lambda message:progress('queued',message,stage='native_channel')):
        return _held_run(w,technology,profile,region,job_id,folder,progress,waive_regions_um,scope_info,result_limit)


def _held_run(w,technology,profile,region,job_id,folder,progress,waive_regions_um,scope_info,result_limit=None):
    context={}
    windows=validate_windows(waive_regions_um)
    try:return _run(w,technology,profile,region,job_id,folder,progress,context,windows,scope_info,result_limit)
    finally:
        native=context.get('native');remote=context.get('remote');private=context.get('private')
        if native and remote and not context.get('terminal'):
            try:native.client.ssh_runner.run_command('touch -- '+shlex.quote(remote+'/cancel.flag'),timeout=10)
            except Exception:pass # Server export handshake and phase timeouts remain bounded.
        temporary=context.get('temporary')
        if temporary:
            try:temporary.finish(bool(context.get('terminal')))
            except Exception:pass # Completed job evidence remains authoritative.
        if native and private:
            try:
                # ltRelease has saved/no-window/root checks. Keep every other
                # open view, including concurrent jobs, in this atomic call.
                key=private.baseline.library+'/'+private.baseline.cell
                expression='let((keep) foreach(cv dbGetOpenCellViews() unless(strcat(cv~>libName "/" cv~>cellName)=='+skill(key)+' keep=cons(strcat(cv~>libName "/" cv~>cellName) keep))) ltRelease(keep))'
                native.client.execute_skill(expression,timeout=15)
            except Exception:pass # Disk snapshots/logs are intentionally retained.


def _run(w,technology,profile,region,job_id,folder,progress,context,waive_regions_um,scope_info,result_limit=None):
    from virtuoso_bridge.virtuoso.layout import parse_xstream_log
    from shapely import make_valid
    def checkpoint():
        if (folder/'cancel.flag').exists():raise LiteError('DRC_CANCELLED')
    checkpoint()
    validate_context(w,technology,profile)
    if profile.remote is None:raise LiteError('REMOTE_DRC_NOT_CONFIGURED')
    per_rule=result_limit if result_limit is not None else profile.remote.max_results_per_rule
    retained=result_limit if result_limit is not None else profile.max_markers
    progress('preparing','正在核对服务器源版图…',stage='source_verification')
    started=perf_counter();a=Adapter(NativeTransport(w.connection_config));source=w.baseline
    from ..native_temporary import TemporaryCopies
    context['temporary']=TemporaryCopies(a).__enter__()
    context['native']=a.native
    current,_=a.read(source.library,source.cell);require_unchanged(w,current)
    progress('preparing','正在复制检查快照，包含本地未同步修改…',stage='snapshot_preparation')
    factory=a.create_validation_workspace if w.validation_only else a.create_workspace
    private,p=factory(source.library,source.cell,label='PREVIEW_DRC')
    context['private']=private;checkpoint()
    if w.operations:
        progress('preparing','正在应用并核对检查副本的本地修改…',stage='snapshot_commit')
        from ..clone_draft import bind
        private=a.commit(bind(w,private))
    if private.state!='clean':raise LiteError('DRC_SNAPSHOT_NOT_CLEAN')
    if private.baseline.dirty:
        raise LiteError('DRC_SNAPSHOT_NOT_SAVED','检查副本仍有未保存变化，未导出或执行 DRC。',stage='snapshot_save')
    remote=a.native.config['allowed_remote_root']+'/.colayout-drc/drc-'+job_id
    mkdir=a.native.client.ssh_runner.run_command('mkdir -p -- '+shlex.quote(remote),timeout=15)
    if mkdir.returncode:raise LiteError('DRC_REMOTE_DIRECTORY_FAILED',mkdir.stderr)
    context['remote']=remote;checkpoint()
    scale=technology.dbu_per_micron;h=profile.remote.halo_um
    x,y=region.bbox[0];xx,yy=region.bbox[1];window=[x/scale-h,y/scale-h,xx/scale+h,yy/scale+h]
    manifest={'job_id':job_id,'job_directory':remote,'allowed_root':a.native.config['allowed_remote_root'],
        'library':source.library,'cell':private.baseline.cell,'window_um':window,'remote':{**profile.remote.model_dump(),'max_results_per_rule':per_rule},
        'waive_regions_um':waive_regions_um}
    write_json(folder/'manifest.json',manifest)
    for local,name in [(Path(__file__).with_name('remote_runner.py'),'runner.py'),
                       (Path(__file__).with_name('remote_deck.py'),'remote_deck.py'),(folder/'manifest.json','manifest.json')]:
        response=a.native.client.upload_file(str(local),remote+'/'+name)
        if response.errors:raise LiteError('DRC_UPLOAD_FAILED',str(response.errors))
    progress('preparing','正在启动服务器检查…',stage='remote_launch')
    command='source '+shlex.quote(profile.remote.environment)+' >/dev/null 2>&1; cd '+shlex.quote(a.native.config['allowed_remote_root'])+'; nohup python3 '+shlex.quote(remote+'/runner.py')+' '+shlex.quote(remote)+' >'+shlex.quote(remote+'/launcher.log')+' 2>&1 </dev/null &'
    launch=a.native.client.ssh_runner.run_command('bash -lc '+shlex.quote(command),timeout=15)
    if launch.returncode:raise LiteError('DRC_LAUNCH_FAILED',launch.stderr)
    approved=False;last_phase=None;state={};cancel_sent=False
    deadline=perf_counter()+profile.remote.timeout_seconds*3+30
    while perf_counter()<deadline:
        if (folder/'cancel.flag').exists() and not cancel_sent:
            a.native.client.ssh_runner.run_command('touch -- '+shlex.quote(remote+'/cancel.flag'),timeout=10);cancel_sent=True
        fetched=a.native.client.ssh_runner.run_command('cat -- '+shlex.quote(remote+'/state.json'),timeout=15)
        if not fetched.returncode:
            state=json.loads(fetched.stdout)
            if (state.get('phase'),state['status'])!=last_phase:
                last_phase=(state.get('phase'),state['status'])
                terminal=state['status'] in ('completed','failed','cancelled')
                progress('processing' if terminal else state['status'],'正在接收并解析服务器报告…' if terminal else {'export':'后台导出版图快照…','calibre':'Calibre 正在执行区域全规则检查…','waiting_for_export_verification':'正在核对导出快照…'}.get(last_phase[0],last_phase[0]),
                         stage='report_download' if terminal else state.get('phase','remote_running'),
                         drc_completed=state['status']=='completed')
            if state['status']=='exported' and not approved and not cancel_sent:
                a.native.client.download_file(remote+'/xstream.log',str(folder/'xstream.log'))
                log=parse_xstream_log((folder/'xstream.log').read_text(encoding='utf8',errors='replace'))
                if not log.completed or log.error_count:
                    a.native.client.ssh_runner.run_command('touch -- '+shlex.quote(remote+'/cancel.flag'),timeout=10)
                    raise LiteError('DRC_XSTREAM_FAILED')
                refreshed,_=a.read(source.library,source.cell);require_unchanged(w,refreshed)
                if not same_dependencies(source,refreshed):raise LiteError('DRC_SOURCE_CHANGED_DURING_EXPORT')
                a.native.client.ssh_runner.run_command('touch -- '+shlex.quote(remote+'/export.ok'),timeout=10);approved=True
            if state['status'] in ('completed','failed','cancelled'):
                context['terminal']=True;break
        sleep(.5)
    else:
        a.native.client.ssh_runner.run_command('touch -- '+shlex.quote(remote+'/cancel.flag'),timeout=10)
        raise LiteError('DRC_JOB_TIMEOUT')
    artifacts={'remote_directory':remote,'private_cell':private.baseline.cell}
    for name in ['state.json','export.log','xstream.log','calibre.log','drc.summary','drc.results','region.drc']:
        destination=folder/('remote-state.json' if name=='state.json' else name)
        result=a.native.client.download_file(remote+'/'+name,str(destination))
        if not result.errors:artifacts[name]=str(destination.resolve())
    write_json(folder/'remote-state.json',state)
    if state['status']!='completed':raise LiteError('DRC_CANCELLED' if state['status']=='cancelled' else 'DRC_ENGINE_FAILED',state.get('error',''))
    if state.get('waiver_application')!=waiver_receipt(waive_regions_um):
        raise LiteError('DRC_WAIVER_RECEIPT_MISMATCH','服务器未确认按本次黑盒范围执行检查。')
    progress('processing','正在解析并核对服务器报告…',stage='report_validation',drc_completed=True)
    raw=(folder/'drc.results').read_bytes()
    try:raw=raw.decode('utf8')
    except UnicodeDecodeError:raw=raw.decode('latin-1')
    geometries=[]
    markers,counts=parse(raw,region,scale,max_markers=retained,geometries=geometries)
    if counts['native_top']!=private.baseline.cell:raise LiteError('DRC_RESULT_CELL_MISMATCH',counts['native_top'])
    summary=(folder/'drc.summary').read_text(encoding='latin-1')
    def summary_count(label):
        match=re.search(re.escape(label)+r':\s*(\d+)',summary)
        if not match:raise LiteError('DRC_SUMMARY_INCOMPLETE',label)
        return int(match.group(1))
    executed=summary_count('TOTAL DRC RuleChecks Executed');generated=summary_count('TOTAL DRC Results Generated')
    if executed<1:raise LiteError('DRC_NO_RULES_EXECUTED')
    from .blackboxes import association_materials
    physical,objects,warnings,roi,context_geometry=association_materials(w,technology,region,profile.remote.halo_um*scale,scope_info)
    index=AssociationIndex(physical)
    associated=[]
    for marker,g in zip(markers,geometries,strict=True):
        refs=associate(index,objects,make_valid(g).buffer(1))
        associated.append(marker.model_copy(update={'objects':refs,'association':'geometric_candidates' if refs else 'none'}))
    del geometries
    coverage={'mode':'region_with_context','layout_window_clip':False,'halo_um':h,'rule_deck':'all enabled rules in configured main deck',
        'warnings':warnings,'truncated':counts['truncated'] or generated>counts['total_context_markers'] or any(r['stored']>=per_rule for r in counts['rules'].values()),
        'result_limits':{'per_rule':per_rule,'retained_markers':retained},
        'limitations':['区域窗口可能影响全局密度、长距离连接和依赖远处图形的规则；不是整芯片签核','对象关联为几何候选，不是 Calibre 原生对象身份'],
        'rule_counts':counts['rules'],'context_markers':counts['total_context_markers'],'rule_checks_executed':executed,
        'summary_results_generated':generated,'effective_deck_sha256':state.get('effective_deck_sha256'),
        'source_deck_sha256':state.get('source_deck_sha256'),
        'waiver_application':state['waiver_application'],'waive_regions_um':waive_regions_um,
        'boundary_policy':SERVER_BOUNDARY_POLICY}
    if scope_info is not None:coverage['scope']=scope_info
    if waive_regions_um:
        coverage['limitations'].append('黑盒为服务器输入几何排除：完整位于排除区的图形不检查；跨界图形完整保留。原生 PIN 内部几何也随范围排除，接口附近规则与本地 PIN 上下文检查不等价。')
    return Result(job_id=job_id,engine='calibre',**stamp(w),profile_digest=profile.fingerprint(),technology_fingerprint=technology.native_fingerprint,configuration_id=technology.configuration_id,
        dbu_per_micron=scale,region=region,context_bbox=((window[0]*scale,window[1]*scale),(window[2]*scale,window[3]*scale)),
        markers=tuple(associated),coverage=coverage,artifacts=artifacts,metrics={'seconds':perf_counter()-started,'markers':len(associated),'engine_exit':'completed'})

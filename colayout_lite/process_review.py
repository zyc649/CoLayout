"""Native checks on copies, reusable local verification receipts, UI-only approval."""
import json
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4
from .model import LiteError,digest
from .process_library import write_json
from .process_package import ProcessPackage
from .technology import TechnologyProfile
from .drc.models import DrcProfile
from .process_transaction import file_key

VALIDATION_VERSION='colayout-process-native-validation-v1'


def verify_native_facts(candidate,actual):
    for key in ('native_fingerprint','dbu_per_micron','grid','native_layers','vias'):
        if getattr(candidate,key)!=getattr(actual,key):raise LiteError('CONNECTED_PDK_MISMATCH',key)
    if candidate.native_technology_name and candidate.native_technology_name!=actual.native_technology_name:
        raise LiteError('CONNECTED_PDK_MISMATCH','native technology library')
    if any(t not in actual.guard_templates for t in candidate.guard_templates):raise LiteError('GUARD_NATIVE_TEMPLATE_MISMATCH')


def validation_key(package):
    from .process_measurements import policy_key
    from .drc.onboarding import settings_key
    return digest([VALIDATION_VERSION,policy_key(package.technology),settings_key(package.drc)])


def binding_key(connection):
    from .paths import ROOT
    cfg=json.loads(Path(connection).read_text(encoding='utf8'))
    return digest([str((ROOT/cfg['bridge_env']).resolve()),cfg['allowed_remote_root']])


def verify_source(package,connection,source,expected=None):
    from .adapter import Adapter
    from .transport import NativeTransport
    from .codec import decode
    from pathlib import PurePosixPath
    adapter=Adapter(NativeTransport(connection))
    snapshot,actual=decode(adapter.native.read(source['library'],source['cell']))
    if snapshot.dirty:raise LiteError('SAVE_SAMPLE_FIRST')
    if PurePosixPath(snapshot.library_path).parent!=PurePosixPath(adapter.native.config['allowed_remote_root']) or source['library']==actual.label:
        raise LiteError('SAMPLE_PROJECT_ROOT_MISMATCH')
    verify_native_facts(package.technology,actual)
    proof={'semantic':digest(snapshot.semantic()),'session':snapshot.session,'counter':snapshot.counter,
           'native_technology_name':actual.native_technology_name,'native_fingerprint':actual.native_fingerprint}
    if expected and proof!=expected:raise LiteError('PDK_SAMPLE_CHANGED')
    return adapter,snapshot,actual,proof


def validate(package,connection,source,folder,progress=lambda s:None):
    """Used by the configuration helper and UI; never publishes active settings."""
    package=ProcessPackage.model_validate(package).require_complete();p=package.technology;folder=Path(folder)
    from .process_measurements import policy_key
    from .wire_defaults import metal_stack,measure_stack
    from .guard_setup import discover,build,is_open_corner_sample
    from .mpp_recipe import GuardRecipe
    p.save(folder/'profiles/process.json')
    cfg=json.loads(Path(connection).read_text(encoding='utf8'))
    cfg.update(preferred_profile=p.id,profiles_directory=str((folder/'profiles').resolve()),
               state_directory=str((folder/'native-runtime').resolve()))
    native_connection=folder/'connection.json';write_json(native_connection,cfg)
    adapter,snapshot,actual,source_proof=verify_source(package,native_connection,source)
    p=p.model_copy(update={'native_technology_name':actual.native_technology_name})
    package=package.model_copy(update={'technology':p});p.save(folder/'profiles/process.json')
    order=metal_stack(p,p.editor_defaults.get('metal_stack'))
    measurements=measure_stack(snapshot,p,order,package.sample_evidence.get('via_uids',{}))
    source_key=package.sample_evidence.get('source_digest')
    if source_key and source_key!=source_proof['semantic']:raise LiteError('PDK_SAMPLE_CHANGED')
    if p.guard_templates:
        raise LiteError('GUARD_OPEN_SAMPLE_REQUIRED','新采集配置仅启用开放样例配方，不直接启用未采样的原生模板；旧配置导入保持兼容。')
    if p.guard_recipes:
        samples,_=discover(adapter,source['library'],source['cell'])
        for raw in p.guard_recipes:
            recipe=GuardRecipe.model_validate(raw)
            hits=[i for i,row in enumerate(samples['paths']) if row['native_id']==recipe.source.get('native_id')]
            if len(hits)!=1:
                raise LiteError('GUARD_SAMPLE_REQUIRED',f'保护环“{recipe.name}”记录的原生样例对象标识无法匹配，请重新采集当前样例；现有配置保留。')
            if not is_open_corner_sample(samples['paths'][hits[0]]):raise LiteError('GUARD_OPEN_SAMPLE_REQUIRED')
            observed=build(samples,hits[0],recipe.id,recipe.name)
            if any(getattr(recipe,k)!=getattr(observed,k) for k in ('kind','master_lpp','width','parts')):
                raise LiteError('GUARD_SAMPLE_GEOMETRY_MISMATCH')
            if recipe.open_parts!=observed.open_parts:
                raise LiteError('GUARD_SAMPLE_GEOMETRY_MISMATCH','开放路径端头和截面必须直接保留样例参数。')
    p=p.model_copy(update={'guard_recipes':[{**r,'validation':{}} for r in p.guard_recipes]})
    stage=folder/'proposal.json'
    proposal={'schema_version':'colayout-process-proposal-2','status':'preparing',
              'connection':str(native_connection),'source':source,'profile':p.model_dump(mode='json'),
              'metal_pair':order[:2],'measurement':measurements['vias'][0],
              'stack_measurement':measurements,'source_semantic':source_proof['semantic'],
              'drc_profile':package.drc.model_dump(mode='json')}
    write_json(stage,proposal)
    from .process_bundle import verify_samples
    checked=verify_samples(stage,package.drc,progress=progress)
    from .codec import decode
    after,_=decode(adapter.native.read(source['library'],source['cell']))
    if after.semantic()!=snapshot.semantic() or after.counter!=snapshot.counter or after.dirty!=snapshot.dirty:raise LiteError('PDK_SAMPLE_CHANGED')
    p=TechnologyProfile.model_validate(checked['profile'])
    final=package.model_copy(update={'technology':p,'drc':DrcProfile.model_validate(checked['drc_profile'])})
    proof={'version':VALIDATION_VERSION,'status':'passed','report':str(stage),'source':source,
           'source_proof':source_proof,'binding_key':binding_key(connection),'validation_key':validation_key(final),
           'policy_key':policy_key(p),'kind':'sample_qualification','drc_checked':False,
           'scope':'原生图形/默认尺寸往返、开放 MPP 样例几何复现、配置数据和服务器路径核对；未运行 DRC/LVS。'}
    return final,proof


def prepare(service,package,source,connection,progress=lambda s:None):
    """Configuration agent's check-only helper: receipts cannot activate a process."""
    ident=uuid4().hex;folder=service.store.folder/'prepared'/ident
    final,proof=validate(package,connection,source,folder,progress)
    record={'package':final.model_dump(mode='json'),'proof':proof}
    write_json(folder/'receipt.json',{'sha256':digest(record),**record})
    return {'verification_id':ident,'package':record['package'],'source':source,'status':'ready_to_submit'}


def verification(service,ident,package,source,connection):
    if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise LiteError('PROCESS_VERIFICATION_UNKNOWN')
    path=service.store.folder/'prepared'/ident/'receipt.json'
    if not path.is_file():raise LiteError('PROCESS_VERIFICATION_UNKNOWN')
    record=json.loads(path.read_text(encoding='utf8'));sha=record.pop('sha256',None)
    if digest(record)!=sha:raise LiteError('PROCESS_VERIFICATION_DAMAGED')
    proof=record['proof']
    if proof.get('version')!=VALIDATION_VERSION or proof.get('status')!='passed':raise LiteError('PROCESS_VERIFICATION_CHANGED')
    if proof.get('source')!=source or proof.get('binding_key')!=binding_key(connection) or proof.get('validation_key')!=validation_key(package):
        raise LiteError('PROCESS_VERIFICATION_CHANGED')
    return proof


def local_settings_review(service,package,source,connection):
    """Reuse saved native qualification only for an exact, unchanged binding."""
    entry=service.store.entries().get(package.technology.key)
    if not entry or entry.get('confirmed') is not True:return None
    if Path(entry['connection']).resolve()!=Path(connection).resolve():return None
    if source!=(entry.get('sample') or {}):return None
    current=service.load(package.technology.key)
    if package.sample_evidence!=current.sample_evidence:return None
    # This deliberately includes factory definitions, evidence, permissions,
    # native data and default geometry. No native input may hitchhike here.
    if package.technology!=current.technology or not current.drc or not package.drc:return None
    local_fields={'mim_capacitor','design_warnings','max_markers','local_halo_um'}
    if current.drc.model_dump(exclude=local_fields)!=package.drc.model_dump(exclude=local_fields):return None
    changed=sorted(name for name in local_fields if getattr(current.drc,name)!=getattr(package.drc,name))
    changed+=['report_policy'] if current.report_policy!=package.report_policy else []
    changed+=['notes'] if current.notes!=package.notes else []
    changed+=['agent_autoroute_enabled'] if current.agent_autoroute_enabled!=package.agent_autoroute_enabled else []
    if not changed:return None # An explicit unchanged requalification still checks its sample.
    return {'version':VALIDATION_VERSION,'status':'passed','kind':'reviewed_local_settings',
            'configuration_key':package.technology.key,'previous_configuration_digest':current.fingerprint(),
            'changed_fields':changed,'native_roundtrip_on_this_host':False,'drc_checked':False,
            'scope':'仅审核本地设置；原生工艺、保护环、默认几何、规则阈值、服务器配置、连接和样例引用与已批准配置完全相同。'}


def approve(service,ident,expected_digest,package,progress=lambda s:None):
    """Only the reviewed UI invokes publication. HTTP provides no approve action."""
    path,data=service.proposal(ident)
    if data['status'] not in ('pending_review','needs_attention') or data['review_digest']!=expected_digest:raise LiteError('PROCESS_PROPOSAL_CHANGED')
    package=ProcessPackage.model_validate(package).require_complete().require_mim_review();p=package.technology;connection=data['connection']
    if p.native_fingerprint!=data['profile']['native_fingerprint']:raise LiteError('PROPOSAL_PROCESS_MISMATCH')
    if service.base(package,connection)!=data['publication_base']:raise LiteError('PROCESS_CONFIGURATION_CHANGED')
    data.update(status='validating',error=None);write_json(path,data)
    publication_base={**data['publication_base'],str(path.resolve()):file_key(path)}
    try:
        from .drc.onboarding import probe
        local_proof=local_settings_review(service,package,data['source'],connection)
        if local_proof:
            progress('核对本地设置；保留已审核的原生工艺与保护环配置…')
            final=package;proof=local_proof
        elif data.get('imported'):
            drc=probe(package.drc,connection)
            proof={'status':'passed','kind':'reviewed_configuration_and_server_paths','native_roundtrip_on_this_host':False}
            final=package.model_copy(update={'drc':drc})
        else:
            proof=None
            if data.get('verification_id'):
                try:proof=verification(service,data['verification_id'],package,data['source'],connection)
                except LiteError as exc:
                    if exc.code!='PROCESS_VERIFICATION_CHANGED':raise
            if proof:
                progress('核对已验证方案、原生样例和服务器文件…')
                # Bypass any old preferred profile while comparing raw native facts.
                verify_source(package,connection,data['source'],proof['source_proof'])
                final=package.model_copy(update={'drc':probe(package.drc,connection)})
            else:final,proof=validate(package,connection,data['source'],path.parent/'verification'/uuid4().hex,progress)
        if not local_proof:
            p=final.technology.model_copy(update={'validation':{'status':'human-confirmed',
                'confirmed_at':datetime.now(timezone.utc).isoformat(),'verification':proof}})
            final=final.model_copy(update={'technology':p})
        # Keep the existing native qualification; the local review has its own receipt.
        data['verification']=proof
        return service.publish(final,connection,publication_base,proposal_path=path,proposal=data)
    except Exception as exc:
        if file_key(path)==publication_base[str(path.resolve())]:
            data.update(status='needs_attention',error=str(exc));write_json(path,data)
        else:write_json(path.parent/('validation-error-'+uuid4().hex+'.json'),{'error':str(exc)})
        raise

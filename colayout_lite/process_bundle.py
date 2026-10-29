"""Sample qualification; older full-DRC diagnostics remain explicit helpers."""
import json
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4
from .model import LiteError,digest
from .technology import TechnologyProfile
from .process_library import ProcessLibrary,write_json
from .drc.models import DrcProfile
from .drc.onboarding import settings_key,probe
from .process_transaction import file_key


def targets(data,store):
    p=TechnologyProfile.model_validate(data['profile']);connection=Path(data['connection'])
    cfg=json.loads(connection.read_text(encoding='utf8'));folder=store.root/cfg.get('profiles_directory','config/technologies')
    matches=[]
    for path in folder.glob('*.json'):
        other=TechnologyProfile.model_validate_json(path.read_text(encoding='utf8'))
        if other.id==p.id and other.key!=p.key:raise LiteError('PROFILE_NAME_IN_USE')
        if other.key==p.key:matches.append(path)
    if len(matches)>1:raise LiteError('AMBIGUOUS_TECHNOLOGY_PROFILE')
    return {'technology':matches[0] if matches else folder/('process-'+digest(p.key)[:12]+'.json'),
        'drc':store.root/'config/drc'/(p.key+'.json'),'registry':store.path,'connection':connection}


def capture_publication(data,store):
    return {str(path.resolve()):file_key(path) for path in targets(data,store).values()}


def verify_samples(path,drc,*,progress=lambda s:None):
    """Default onboarding: native reproduction and file checks, no DRC run."""
    from . import process_setup
    from .guard_qualification import reproduce
    from .mpp_recipe import GuardRecipe
    path=Path(path);data=json.loads(path.read_text(encoding='utf8'))
    if data['status'] in ('confirmed','superseded'):raise LiteError('PROPOSAL_NOT_EDITABLE')
    p=TechnologyProfile.model_validate(data['profile']);drc.check_technology(p)
    drc=probe(drc,data['connection'])
    data.update(drc_profile=drc.model_dump(mode='json'),status='preparing',error=None);write_json(path,data)
    try:
        data=process_setup.validate(path,p,progress)
        recipes=[]
        for raw in p.guard_recipes:
            recipe=GuardRecipe.model_validate(raw)
            progress('核对开放样例的原生几何复现：'+recipe.name)
            recipe=reproduce(recipe,data['connection'],data['source']['library'],data['source']['cell'],
                             path.parent/'guard-reproduction'/uuid4().hex[:10])
            recipes.append(recipe.model_dump(mode='json'))
        p=p.model_copy(update={'guard_recipes':recipes})
        data.update(profile=p.model_dump(mode='json'),status='ready_for_confirmation',
            validation={**data['validation'],'policy_key':process_setup.policy_key(p)},
            drc_validation={'status':'not_run','reason':'配置阶段只校验规则数据及服务器文件路径；设计 DRC 单独运行。'},
            sections={'technology':'native_roundtrip_passed','guards':'native_reproduction',
                      'local_drc':'configured','remote_drc':'paths_verified'})
        write_json(path,data);progress('样例复现及配置核对完成；没有运行 DRC。')
        return data
    except Exception as exc:
        data=json.loads(path.read_text(encoding='utf8'));data.update(status='needs_attention',error=str(exc))
        write_json(path,data);raise


def complete(path,drc=None,*,progress=lambda s:None):
    """Prepare only. No active configuration file is written here."""
    from . import process_setup
    from .drc.onboarding import validate
    path=Path(path);data=json.loads(path.read_text(encoding='utf8'))
    if data['status'] in ('confirmed','superseded'):raise LiteError('PROPOSAL_NOT_EDITABLE')
    if data.get('schema_version')!='colayout-process-proposal-2':raise LiteError('UNIFIED_PROPOSAL_REQUIRED','请重新 prepare 生成三部分提案。')
    if drc is None and data.get('drc_profile'):drc=DrcProfile.model_validate(data['drc_profile'])
    data.update(status='preparing',error=None);write_json(path,data)
    try:
        if drc is None:raise LiteError('DRC_CONFIGURATION_REQUIRED','未找到匹配的 DRC 配置。Agent 需读取真实规则并填写候选配置，再用 complete 继续。',proposal=str(path.resolve()))
        p=TechnologyProfile.model_validate(data['profile']);drc.check_technology(p)
        drc=probe(drc,data['connection']);data['drc_profile']=drc.model_dump(mode='json');write_json(path,data)
        if data.get('validation',{}).get('policy_key')!=process_setup.policy_key(p) or data.get('validation',{}).get('status')!='passed':
            data=process_setup.validate(path,p,progress)
        proof=data.get('drc_validation',{})
        if proof.get('status')!='passed' or proof.get('settings_key')!=settings_key(drc):
            drc,proof=validate(drc,p,data['connection'],data['source']['library'],data['source']['cell'],path.parent/'drc-validation'/uuid4().hex[:10],progress)
        # A changed server deck/runner requires the MPP factory to be qualified
        # against that configuration too. Old local-rule-only changes do not
        # establish a different server deck but may conservatively requalify.
        recipes=[]
        from .mpp_recipe import GuardRecipe
        from .guard_setup import validate as validate_guard
        for raw in p.guard_recipes:
            recipe=GuardRecipe.model_validate(raw)
            if not recipe.ready() or recipe.validation.get('drc_profile_digest')!=drc.fingerprint():
                progress('重新核对 MPP 配方与本次 DRC：'+recipe.name)
                recipe=validate_guard(recipe,data['connection'],data['source']['library'],data['source']['cell'],
                    folder=path.parent/'guard-validation'/uuid4().hex[:10],drc_profile=drc)
            recipes.append(recipe.model_dump(mode='json'))
        p=p.model_copy(update={'guard_recipes':recipes})
        # Updating only proof metadata doesn't change generated geometry.
        validation={**data['validation'],'policy_key':process_setup.policy_key(p)}
        data.update(profile=p.model_dump(mode='json'),drc_profile=drc.model_dump(mode='json'),validation=validation,
            drc_validation=proof,status='ready_for_confirmation',sections={'technology':'passed','local_drc':'passed','remote_drc':'passed'})
        write_json(path,data);progress('三部分验证完成，等待人统一确认。');return data
    except Exception as exc:
        data=json.loads(path.read_text(encoding='utf8'));data.update(status='needs_attention',error=str(exc));write_json(path,data);raise


def publish(path,data,profile,drc,store):
    """Compatibility adapter; preserves old receipt paths and atomic rollback."""
    from .process_compat import publish_legacy
    return publish_legacy(path,data,profile,drc,store,writer=write_json)

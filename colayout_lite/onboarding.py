"""Process onboarding: discovery, editable policy, atomic saving and smoke test."""
from pathlib import Path
from datetime import datetime
from uuid import uuid4
import json,shutil
from .paths import ROOT
from .transport import NativeTransport
from .adapter import Adapter
from .codec import decode
from .technology import TechnologyProfile
from .editor import Editor
from .actions import Actions
from .model import LiteError


def discover(connection_path,library,cell):
    adapter=Adapter(NativeTransport(connection_path))
    snapshot,profile=decode(adapter.native.read(library,cell))
    candidates=[]
    for path in (ROOT/adapter.native.config.get('profiles_directory','config/technologies')).glob('*.json'):
        existing=TechnologyProfile.model_validate_json(path.read_text(encoding='utf-8'))
        if existing.native_fingerprint==profile.native_fingerprint and existing.native_layers==profile.native_layers and existing.vias==profile.vias and (not existing.native_technology_name or existing.native_technology_name==profile.native_technology_name):
            candidates.append(existing)
    if len(candidates)==1:profile=candidates[0]
    return adapter,snapshot,profile


def save_profile(adapter,profile,*,name,writable_lpps,defaults):
    if not name.strip():raise LiteError('PROFILE_NAME_REQUIRED','请填写工艺名称')
    data=profile.model_dump();data.update(id=name.strip(),label=name.strip(),writable_lpps=writable_lpps,editor_defaults=defaults,
        validation={'status':'configured_not_validated','note':'需要执行连接与写回验证'})
    result=TechnologyProfile.model_validate(data)
    if result.id==profile.id and result.writable_lpps==profile.writable_lpps and result.editor_defaults==profile.editor_defaults:
        result=result.model_copy(update={'validation':profile.validation})
    folder=ROOT/adapter.native.config.get('profiles_directory','config/technologies');folder.mkdir(parents=True,exist_ok=True)
    matching=[]
    for path in folder.glob('*.json'):
        existing=TechnologyProfile.model_validate_json(path.read_text(encoding='utf-8'))
        if existing.id==result.id and existing.key!=result.key:
            raise LiteError('PROFILE_NAME_IN_USE','该名称对应另一个实际工艺，请换名称')
        if existing.key==result.key:matching.append(path)
    if len(matching)>1:raise LiteError('AMBIGUOUS_TECHNOLOGY_PROFILE','同一工艺存在多份配置，请先整理；不自动覆盖多份文件。')
    path=matching[0] if matching else folder/('process-'+uuid4().hex[:10]+'.json')
    backup=ROOT/'artifacts/lite-02/config-backups'/uuid4().hex[:10];backup.mkdir(parents=True,exist_ok=True)
    if path.exists():shutil.copyfile(path,backup/path.name)
    config_path=adapter.native.config_path
    if config_path.exists():shutil.copyfile(config_path,backup/'connection.json')
    result.save(path)
    config={**adapter.native.config,'preferred_profile':result.id}
    temp=config_path.with_name(config_path.name+'.tmp');temp.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(config_path)
    adapter.native.config=config
    return result,path


def validate_sample(adapter,library,cell,profile,progress=lambda message:None):
    """Validate the actual connection+profile on a newly cloned sample."""
    progress('复制 Layout 样例，原版图不修改…')
    w,p=adapter.create_workspace(library,cell,label='ONBOARD')
    if p.native_fingerprint!=profile.native_fingerprint:raise LiteError('CONNECTED_PDK_MISMATCH')
    e=Editor(w,p);actions=Actions(e);layer=list(p.editor_defaults.get('layer',p.writable_lpps[0]));checks=[]
    def run(name,params):
        result=actions.execute(name,params);checks.append({'operation':name,'uid':result.uid});return result.uid
    run('create_rect',dict(x=100,y=100,width=4,height=2,lpp=layer))
    run('create_path90',dict(points=[[100,110],[104,110],[104,114]],width=p.editor_defaults.get('width_um',.8),lpp=layer))
    run('create_path45',dict(points=[[100,120],[104,124],[108,124]],width=p.editor_defaults.get('width_um',.8),lpp=layer))
    via=profile.editor_defaults.get('via_definition') or next((k for k,v in p.vias.items() if v['kind']=='stdViaDef' and not v.get('cut_pattern')),None)
    if via:run('create_via',dict(x=110,y=100,definition=via,via_parameters={'cutRows':2,'cutColumns':3}))
    progress('写回并核对矩形、90°/45°线和过孔…')
    after=adapter.commit(e.w)
    if after.state!='clean':raise LiteError('VALIDATION_COMMIT_FAILED',str(after.last_result))
    records={o['uid']:after.baseline.objects[o['uid']].shape.model_dump() for o in checks}
    e=Editor(after,p)
    for row in checks:e.delete(row['uid'])
    restored=adapter.commit(e.w)
    if restored.baseline.semantic()!=w.baseline.semantic():raise LiteError('VALIDATION_RESTORE_MISMATCH')
    report={'status':'passed','source':{'library':library,'cell':cell},'target':after.baseline.cell,
            'profile':profile.id,'fingerprint':profile.native_fingerprint,'operations':checks,'native_readback':records,
            'scope':'连接/配置/基本几何写回核对；不等于全部via、全部操作或DRC/LVS签核'}
    path=ROOT/'artifacts/lite-02/onboarding'/f'{uuid4().hex}.json';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    progress('连接与基本写回验证通过。')
    return report,path

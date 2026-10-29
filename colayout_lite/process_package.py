"""Portable process data shared by UI, HTTP proposals and file import/export."""
from typing import Literal
import re
from pydantic import Field,model_validator
from .model import Record,LiteError,digest
from .technology import TechnologyProfile
from .drc.models import DrcProfile
from .drc.waivers import WaiverPolicy


class ProcessPackage(Record):
    schema_version:Literal['colayout-process-package-1']='colayout-process-package-1'
    technology:TechnologyProfile
    drc:DrcProfile|None=None
    report_policy:WaiverPolicy|None=None
    notes:str=Field(default='',max_length=20000)
    sample_evidence:dict=Field(default_factory=dict)

    @model_validator(mode='after')
    def consistent(self):
        p=self.technology
        if not p.id.strip() or not p.label.strip():raise ValueError('Process name is required')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',p.native_fingerprint):raise ValueError('Invalid process fingerprint')
        if p.configuration_id:
            if self.drc and self.drc.configuration_id is None:object.__setattr__(self,'drc',self.drc.model_copy(update={'configuration_id':p.key}))
            if self.report_policy and self.report_policy.configuration_id is None:object.__setattr__(self,'report_policy',self.report_policy.model_copy(update={'configuration_id':p.key}))
        if self.drc:self.drc.check_technology(p)
        if self.report_policy and self.report_policy.technology_fingerprint!=p.native_fingerprint:
            raise ValueError('Report policy belongs to another process')
        if self.report_policy and (self.report_policy.configuration_id or p.native_fingerprint)!=p.key:
            raise ValueError('Report policy belongs to another process configuration')
        return self

    def require_complete(self):
        p=self.technology;d=self.drc
        from .wire_defaults import metal_stack,default_width
        stack=metal_stack(p,p.editor_defaults.get('metal_stack'))
        if not p.editor_defaults.get('layer') or not p.editor_defaults.get('via_definition'):
            raise LiteError('PROCESS_DRAWING_DEFAULTS_REQUIRED')
        if tuple(p.editor_defaults['layer'])!=(stack[0],'drawing'):
            raise LiteError('PROCESS_DEFAULT_LAYER_MISMATCH')
        if set(stack)-set(p.editor_defaults.get('widths_um',{})):
            raise LiteError('PROCESS_LAYER_WIDTHS_REQUIRED','请提供各金属层的默认线宽。')
        for layer in stack:default_width(p,layer)
        via=p.vias[p.editor_defaults['via_definition']]
        if via.get('kind')!='stdViaDef' or via.get('cut_pattern') or (via.get('layer1'),via.get('layer2'))!=tuple(stack[:2]):
            raise LiteError('PROCESS_DEFAULT_VIA_MISMATCH')
        if not d or not d.remote or not any(r.enabled for r in d.rules):
            raise LiteError('PROCESS_DRC_REQUIRED','统一配置需包含本地规则和服务器 DRC。')
        if any(r.enabled and not r.source.strip() for r in d.rules):
            raise LiteError('DRC_RULE_SOURCE_REQUIRED','本地规则阈值需标明实际来源，不能从样例尺寸推断。')
        from .mpp_recipe import GuardRecipe,sampled
        for raw in p.guard_recipes:
            recipe=GuardRecipe.model_validate(raw)
            if recipe.kind=='double' and not sampled(recipe):
                raise LiteError('GUARD_SAMPLE_REQUIRED','双排保护环与开放路径必须来自样例。')
        return self

    def fingerprint(self):return digest(self.model_dump(mode='json'))

    def require_mim_review(self):
        if not self.drc:raise LiteError('PROCESS_DRC_REQUIRED')
        self.drc.mim_capacitor.require_reviewed()
        self.drc.check_technology(self.technology)
        return self


def portable(package):
    """Do not export host connections, workspace state or local validation paths."""
    p=package.technology
    recipes=[]
    from .mpp_recipe import available,native_templates
    for raw in available(p):
        row=dict(raw)
        proof=row.get('validation',{})
        row['validation']={k:proof[k] for k in ('status','geometry_key','forms','kind','drc_checked') if k in proof}
        if proof.get('context'):
            row['validation']['context']={k:proof['context'][k] for k in
                ('kind','layers','ring','path','fixture_open_depth_um') if k in proof['context']}
        source=row.get('source',{})
        row['source']={k:source[k] for k in ('sample','source_digest','native_id','path_index','measurement') if k in source}
        recipes.append(row)
    templates=[]
    candidates=native_templates(p)
    for item in candidates:
        # Prefer the actual technology-library definition over an identical
        # inherited entry named after the source user's business library.
        item=next((t for t in candidates if t['library']==p.native_technology_name and
                   (t['name'],t['definition'])==(item['name'],item['definition'])),item)
        if item not in templates:templates.append(item)
    p=p.model_copy(update={'guard_recipes':recipes,'guard_templates':templates,'validation':{'status':'shared_configuration'}})
    d=package.drc
    if d:d=d.model_copy(update={'provenance':{'configuration':'shared; verify server paths on this host'}})
    return package.model_copy(update={'technology':p,'drc':d,'sample_evidence':{},'notes':package.notes})


def encode(package):
    data=portable(package).model_dump(mode='json')
    return {'format':'colayout-process-file-1','sha256':digest(data),'configuration':data}


def decode(data):
    if data.get('format')!='colayout-process-file-1':raise LiteError('PROCESS_FILE_FORMAT')
    if digest(data.get('configuration'))!=data.get('sha256'):raise LiteError('PROCESS_FILE_CHECKSUM')
    return ProcessPackage.model_validate(data['configuration'])


def changes(before,after):
    """Small review summary; full editable values remain in the section tabs."""
    old=before.technology;new=after.technology
    sections=[]
    if (old.writable_lpps,old.editor_defaults,old.material_evidence)!=(new.writable_lpps,new.editor_defaults,new.material_evidence):sections.append('绘图与图层')
    if before.drc!=after.drc:sections.append('DRC 与设计提醒')
    if (old.guard_templates,old.guard_recipes)!=(new.guard_templates,new.guard_recipes):sections.append('保护环')
    if before.report_policy!=after.report_policy or old.schematic_summary_parameters!=new.schematic_summary_parameters:sections.append('摘要与报告')
    text='变更：'+('、'.join(sections) if sections else '名称、说明或验证信息')
    from .mpp_recipe import available,native_templates
    def capabilities(profile):
        return {str(r['id']) for r in available(profile)}|{str(t['name']) for t in native_templates(profile)}
    removed=capabilities(old)-capabilities(new)
    if removed:text+='；停用保护环：'+'、'.join(sorted(removed))
    return text

from __future__ import annotations
from typing import Literal,Any
from math import isfinite
from pydantic import Field,model_validator
from ..model import Record,Box,digest,LiteError
from ..technology import TechnologyProfile
from .warning_models import DesignWarnings
from .mim_config import MimCapacitor

DRC_IMPLEMENTATION = 'local-geometry-v1'


class Rule(Record):
    id:str=Field(description='Local rule identifier, not a selector for a foundry rule or its conditions.')
    kind:Literal['width','spacing','area','enclosure']=Field(description='Geometric check. spacing does not distinguish same-net/different-net geometry or compare net names. Enabled spacing rules on the same layer all apply; different thresholds are not conditional branches.')
    layer:str
    other_layer:str|None=None
    value:float
    enabled:bool=True
    severity:Literal['error','warning']='error'
    note:str=Field(default='',description='Description only: state the actual local check, omitted conditions and possible false positives/missed cases. Does not execute conditions or exclusions.')
    source:str=Field(default='',description='Evidence from the selected PDK/rule deck; does not execute or import the referenced rule.')
    @model_validator(mode='after')
    def valid(self):
        if not isfinite(self.value) or self.value<=0:raise ValueError('Rule threshold must be finite and positive')
        if self.kind=='enclosure' and not self.other_layer:raise ValueError('Enclosure requires enclosing metal layer')
        if self.kind!='enclosure' and self.other_layer:raise ValueError('other_layer applies only to enclosure')
        return self


class RemoteConfig(Record):
    deck_path:str
    deck_sha256:str=''
    layer_map:str
    layer_map_sha256:str=''
    calibre:str='/path/to/calibre'
    strmout:str='/path/to/strmout'
    environment:str='/path/to/eda-environment.sh'
    halo_um:float=10
    timeout_seconds:int=600
    max_results_per_rule:int=10000
    @model_validator(mode='after')
    def valid(self):
        if not isfinite(self.halo_um) or self.halo_um<=0 or self.timeout_seconds<1 or self.max_results_per_rule<1:raise ValueError('Invalid remote DRC limits')
        for path in [self.deck_path,self.layer_map,self.calibre,self.strmout,self.environment]:
            if not path.startswith('/') or any(c in path for c in ('\n','\r','\x00','"')):raise ValueError('Remote paths must be absolute and contain no quotes or newlines')
        return self


class DrcProfile(Record):
    schema_version:Literal['colayout-drc-profile-1']='colayout-drc-profile-1'
    id:str
    technology_fingerprint:str
    configuration_id:str|None=Field(default=None,exclude_if=lambda v:v is None)
    rules:tuple[Rule,...]=()
    local_halo_um:float=2
    max_markers:int=10000
    remote:RemoteConfig|None=None
    provenance:dict[str,Any]=Field(default_factory=dict)
    design_warnings:DesignWarnings=Field(default_factory=DesignWarnings)
    mim_capacitor:MimCapacitor=Field(default_factory=MimCapacitor,exclude_if=lambda v:v==MimCapacitor())
    @model_validator(mode='after')
    def valid(self):
        if not isfinite(self.local_halo_um) or self.local_halo_um<0 or self.max_markers<1:raise ValueError('Invalid DRC limits')
        if len({r.id for r in self.rules})!=len(self.rules):raise ValueError('Duplicate rule IDs')
        return self
    def check_technology(self,p:TechnologyProfile):
        if p.native_fingerprint!=self.technology_fingerprint:raise LiteError('DRC_TECHNOLOGY_MISMATCH')
        if self.configuration_id is not None and self.configuration_id!=p.key:raise LiteError('DRC_CONFIGURATION_MISMATCH')
        self.mim_capacitor.check_technology(p)
        layers={r['layer'] for r in p.layers if r['purpose']=='drawing'}
        metals={r['layer'] for r in p.layers if r['purpose']=='drawing' and r.get('material')=='metal'}
        if set(self.design_warnings.directions)-metals:raise LiteError('DRC_DIRECTION_LAYER_UNKNOWN')
        for rule in self.rules:
            if rule.layer not in layers or (rule.other_layer and rule.other_layer not in layers):raise LiteError('DRC_LAYER_UNKNOWN',rule.id)
    def fingerprint(self):return digest([DRC_IMPLEMENTATION,self.model_dump(mode='json')])


class Region(Record):
    bbox:Box
    @model_validator(mode='after')
    def valid(self):
        (x,y),(xx,yy)=self.bbox
        if x>=xx or y>=yy:raise ValueError('检查区域必须有正的宽度和高度')
        return self
    @classmethod
    def from_um(cls,values,scale):
        from decimal import Decimal
        coords=[]
        if len(values)!=4:raise ValueError('ROI requires xmin ymin xmax ymax')
        for v in values:
            n=Decimal(str(v))*scale
            if not n.is_finite() or n!=n.to_integral_value():raise ValueError('区域坐标精度超出 1 DBU')
            coords.append(int(n))
        return cls(bbox=((coords[0],coords[1]),(coords[2],coords[3])))


class Marker(Record):
    id:str
    rule_id:str
    message:str
    severity:Literal['error','warning']='error'
    kind:Literal['polygon','edges','box']='box'
    points:tuple[tuple[float,float],...]=()
    edges:tuple[tuple[float,float,float,float],...]=()
    bbox:tuple[tuple[float,float],tuple[float,float]]
    layers:tuple[str,...]=()
    objects:tuple[dict[str,Any],...]=()
    association:Literal['local_geometry','geometric_candidates','none']='none'
    measured_um:float|None=None
    required_um:float|None=None
    details:dict[str,Any]=Field(default_factory=dict)


class Result(Record):
    schema_version:Literal['colayout-drc-result-1']='colayout-drc-result-1'
    job_id:str
    engine:Literal['local','calibre']
    status:Literal['completed','failed','cancelled']='completed'
    document_id:str
    document_revision:int
    baseline_session:str
    baseline_counter:str
    snapshot_digest:str
    profile_digest:str
    technology_fingerprint:str
    configuration_id:str|None=Field(default=None,exclude_if=lambda v:v is None)
    dbu_per_micron:int
    region:Region
    context_bbox:tuple[tuple[float,float],tuple[float,float]]
    markers:tuple[Marker,...]=()
    coverage:dict[str,Any]=Field(default_factory=dict)
    artifacts:dict[str,str]=Field(default_factory=dict)
    metrics:dict[str,Any]=Field(default_factory=dict)
    def is_current(self,w,profile=None):
        from .scope import HIERARCHY_POLICY, SERVER_BOUNDARY_POLICY
        if self.engine=='calibre' and self.coverage.get('boundary_policy')!=SERVER_BOUNDARY_POLICY:return False
        scope=self.coverage.get('scope',{})
        if scope and scope.get('selection_policy')!=HIERARCHY_POLICY:return False
        if scope.get('fingerprint'):
            from ..scope_state import fingerprint
            current=fingerprint(w,scope.get('region_id'))==scope['fingerprint']
        else:current=w.revision==self.document_revision
        return (w.id==self.document_id and current and w.baseline.session==self.baseline_session
            and w.baseline.counter==self.baseline_counter and (profile is None or profile.fingerprint()==self.profile_digest))


def stamp(w):
    return {'document_id':w.id,'document_revision':w.revision,'baseline_session':w.baseline.session,'baseline_counter':w.baseline.counter,
        'snapshot_digest':digest({'baseline':w.baseline.semantic(),'operations':[o.model_dump() for o in w.operations],
                                  'guards':w.guard_previews})}


def validate_context(w,technology,profile):
    profile.check_technology(technology)
    if w.baseline.technology_fingerprint!=technology.native_fingerprint:raise LiteError('DRC_WORKSPACE_TECHNOLOGY_MISMATCH')
    if w.baseline.dbu_per_micron!=technology.dbu_per_micron:raise LiteError('DRC_DBU_MISMATCH')

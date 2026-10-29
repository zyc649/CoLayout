from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,StrictInt,model_validator

Point=tuple[StrictInt,StrictInt]


class BoxRecord(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    id:str
    bbox:tuple[Point,Point]

    @model_validator(mode='after')
    def valid_box(self):
        if any(a>=b for a,b in zip(*self.bbox)) or any(abs(v)>2**31-1 for p in self.bbox for v in p):
            raise ValueError('Invalid local region bounds')
        return self


class InterfacePin(BoxRecord):
    name:str
    net:str
    lpp:tuple[str,str]
    layer_mode:Literal['single','any_metal']='single'  # Legacy file default; new UI ports explicitly use any_metal.
    evidence:tuple[str,...]=()
    fixed:bool=True
    access_group:str|None=None  # Explicit copied-port identity, never inferred from net names.
    @model_validator(mode='before')
    @classmethod
    def legacy_edge_flag(cls,value):
        # Read old documents, but no longer store or expose an interior mode.
        return {k:v for k,v in value.items() if k!='on_edge'} if isinstance(value,dict) else value


class OperationRegion(BoxRecord):
    name:str=Field(min_length=1)
    parent_id:str|None=None
    object_uids:tuple[str,...]=()  # Direct owners only; never duplicate child geometry.
    pins:dict[str,InterfacePin]=Field(default_factory=dict)
    state:Literal['sealed']='sealed'  # Legacy field; all regions are active immediately.
    revision:int=0
    interface_revision:int=0
    blocked_layers:tuple[str,...]=()
    note:str=''
    pin_mode:Literal['fixed','directional']='fixed'
    interface_policy:Literal['layout_v1','reference_v2']='layout_v1'


    @model_validator(mode='before')
    @classmethod
    def upgrade_active_region(cls,value):
        if isinstance(value,dict):
            value=dict(value)
            if value.get('state')=='draft':value['state']='sealed'
            pins=value.get('pins',{})
            if isinstance(pins,dict):
                value['pins']={k:({**p,'fixed':True} if isinstance(p,dict)
                    else p.model_copy(update={'fixed':True}) if isinstance(p,InterfacePin) else p) for k,p in pins.items()}
        return value


class MarkupBox(BoxRecord):
    text:str=''
    scope_id:str|None=None


class RoutingKeepout(BoxRecord):
    layers:tuple[str,...]=()
    note:str=''
    scope_id:str|None=None


class NativeRoutingWindow(BoxRecord):
    """Rectangle in its native owner's placement coordinates, not OA geometry."""
    owner_uid:str=Field(min_length=1)
    name:str=Field(default='布线豁免',min_length=1,max_length=200)
    layers:tuple[str,...]=Field(min_length=1)
    note:str=Field(default='',max_length=20000)
    enabled:bool=True


def contains(outer,inner):
    return all(outer[0][i]<=inner[0][i] and inner[1][i]<=outer[1][i] for i in range(2))


def overlaps(a,b):
    return all(a[0][i]<b[1][i] and b[0][i]<a[1][i] for i in range(2))


def enclosing_scope(regions,bbox):
    """Deepest containing construction region; crossing boxes stay at an ancestor."""
    candidates=[r for r in regions.values() if contains(r.bbox,bbox)]
    def depth(region):
        seen=set();current=region
        while current.parent_id in regions and current.parent_id not in seen:
            seen.add(current.parent_id);current=regions[current.parent_id]
        return len(seen)
    return max(candidates,key=depth).id if candidates else None


def validate_hierarchy(regions):
    owners=set()
    for ident,region in regions.items():
        if ident!=region.id:raise ValueError('Region ID mismatch')
        if len(region.object_uids)!=len(set(region.object_uids)) or owners.intersection(region.object_uids):
            raise ValueError('Layout object belongs to more than one local region')
        owners.update(region.object_uids)
        seen={ident};parent=region.parent_id
        while parent:
            if parent not in regions or parent in seen:raise ValueError('Missing parent or region cycle')
            if not contains(regions[parent].bbox,region.bbox):raise ValueError('Child region outside parent')
            seen.add(parent);parent=regions[parent].parent_id
        access_nets={}
        for key,pin in region.pins.items():
            group=pin.access_group or pin.id
            if group in access_nets and access_nets[group]!=pin.net:raise ValueError('Copied PIN group has different nets')
            access_nets[group]=pin.net
            if key!=pin.id:raise ValueError('Region PIN ID mismatch')
            center=tuple((a+b)/2 for a,b in zip(*pin.bbox))
            if any(not region.bbox[0][i]<=center[i]<=region.bbox[1][i] for i in range(2)):
                raise ValueError('Interface PIN center is outside region')
            if not pin.fixed:raise ValueError('Region interface must be active')
    rows=list(regions.values())
    for i,a in enumerate(rows):
        for b in rows[i+1:]:
            if a.parent_id==b.parent_id and overlaps(a.bbox,b.bbox):raise ValueError('Sibling regions overlap')

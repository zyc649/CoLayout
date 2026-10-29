"""Workspace-only user content. References geometry by UID; owns no layout copy."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator
from .regions.models import OperationRegion,MarkupBox,RoutingKeepout,NativeRoutingWindow,validate_hierarchy,enclosing_scope


class LocalRecord(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)


class LocalGroup(LocalRecord):
    id: str
    name: str = Field(min_length=1)
    object_uids: tuple[str,...] = Field(min_length=1)


class LocalPin(LocalRecord):
    id: str
    name: str = Field(min_length=1)
    net: str = Field(min_length=1)
    lpp: tuple[str,str]
    bbox: tuple[tuple[StrictInt,StrictInt],tuple[StrictInt,StrictInt]]
    group_id: str | None = None
    object_uids: tuple[str,...] = ()

    @model_validator(mode='after')
    def valid_box(self):
        if any(a>=b for a,b in zip(*self.bbox)) or any(abs(v)>2**31-1 for p in self.bbox for v in p):
            raise ValueError('Invalid local PIN bounds')
        return self


class LocalAnnotation(LocalRecord):
    id: str
    kind: Literal['note','requirement'] = 'note'
    text: str
    object_uids: tuple[str,...] = ()
    group_id: str | None = None


class RoutingRecord(LocalRecord):
    """Historical provenance, not a live ownership/reference that blocks deletion."""
    id: str
    region_id: str
    source_revision: int
    candidate_id: str
    algorithms: tuple[dict, ...]
    object_uids: tuple[str, ...]
    metrics: dict


class LocalData(LocalRecord):
    schema_version: Literal['colayout-local-data-1'] = 'colayout-local-data-1'
    groups: dict[str,LocalGroup] = Field(default_factory=dict)
    pins: dict[str,LocalPin] = Field(default_factory=dict)
    annotations: dict[str,LocalAnnotation] = Field(default_factory=dict)
    instructions: str | None = None
    regions:dict[str,OperationRegion]=Field(default_factory=dict)
    markups:dict[str,MarkupBox]=Field(default_factory=dict)
    keepouts:dict[str,RoutingKeepout]=Field(default_factory=dict)
    native_blocked_layers:dict[str,tuple[str,...]]=Field(default_factory=dict)
    native_routing_windows:dict[str,NativeRoutingWindow]=Field(default_factory=dict)
    # Explicit human associations for otherwise ambiguous reference top nets.
    reference_net_map:dict[str,str]=Field(default_factory=dict)
    routing_records:dict[str,RoutingRecord]=Field(default_factory=dict)

    @model_validator(mode='after')
    def identities(self):
        for records in (self.groups,self.pins,self.annotations,self.routing_records,self.native_routing_windows):
            if any(key!=record.id for key,record in records.items()):
                raise ValueError('Local object ID mismatch')
        if len({p.name for p in self.pins.values()})!=len(self.pins):
            raise ValueError('Local PIN names must be unique')
        for item in (*self.pins.values(),*self.annotations.values()):
            if item.group_id and item.group_id not in self.groups:
                raise ValueError('Local group reference is missing')
        validate_hierarchy(self.regions)
        # Repair older documents that placed all boxes at root. Geometry and
        # stable IDs remain unchanged; grouping does not limit keepout coverage.
        for field in ('markups','keepouts'):
            records=getattr(self,field)
            object.__setattr__(self,field,{key:row.model_copy(update={'scope_id':enclosing_scope(self.regions,row.bbox)}) for key,row in records.items()})
        for records in (self.markups,self.keepouts):
            if any(key!=row.id for key,row in records.items()):raise ValueError('Local box ID mismatch')
        if any(m.scope_id and m.scope_id not in self.regions for m in (*self.markups.values(),*self.keepouts.values())):
            raise ValueError('Markup scope is missing')
        return self


def require_references(local,known_uids):
    from .model import LiteError
    missing={uid for item in (*local.groups.values(),*local.pins.values(),*local.annotations.values(),*local.regions.values())
             for uid in item.object_uids if uid not in known_uids}
    missing.update(set(local.native_blocked_layers)-set(known_uids))
    missing.update(row.owner_uid for row in local.native_routing_windows.values() if row.owner_uid not in known_uids)
    if missing:raise LiteError('LOCAL_REFERENCES_MISSING','本地内容引用的版图对象已不存在；内容未丢弃。',uids=sorted(missing))

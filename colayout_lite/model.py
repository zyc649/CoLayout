"""Strict wire model. No Qt, bridge, schematic or PDK-specific device logic."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator, field_validator
from .circuit.models import CircuitContext, LayoutConnectivity
from .local_models import LocalData

MAX_DBU = 2**31 - 1
Point = tuple[StrictInt, StrictInt]
Box = tuple[Point, Point]
Orientation = Literal['R0', 'R90', 'R180', 'R270', 'MX', 'MY', 'MXR90', 'MYR90']
PATH_STYLES = {'truncateExtend', 'extendExtend', 'roundRound', 'varExtendExtend'}
VIA_COUNTS = {'cutRows', 'cutColumns'}
VIA_LENGTHS = {'cutWidth', 'cutHeight'}
VIA_PAIRS = {'cutSpacing', 'layer1Enc', 'layer2Enc', 'layer1Offset', 'layer2Offset',
             'originOffset', 'imp1Enc', 'imp2Enc'}


def digest(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)

    def save(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_text(self.model_dump_json(indent=2), encoding='utf-8')
        temporary.replace(path)


class LiteError(RuntimeError):
    def __init__(self, code: str, message: str = '', **details):
        self.code, self.details = code, details
        super().__init__(code + (': ' + message if message else ''))


def checked_int(value, label='coordinate'):
    if type(value) is not int or abs(value) > MAX_DBU:
        raise ValueError(f'{label} must be integer DBU in supported range')


def segments_intersect(a, b, c, d):
    def cross(p, q, r):
        return (q[0]-p[0])*(r[1]-p[1]) - (q[1]-p[1])*(r[0]-p[0])
    def on(p, q, r):
        return min(p[0], q[0]) <= r[0] <= max(p[0], q[0]) and min(p[1], q[1]) <= r[1] <= max(p[1], q[1])
    x, y, z, w = cross(a,b,c), cross(a,b,d), cross(c,d,a), cross(c,d,b)
    return (x*y < 0 and z*w < 0) or any(v == 0 and on(p,q,r) for v,p,q,r in
        [(x,a,b,c), (y,a,b,d), (z,c,d,a), (w,c,d,b)])


class CustomEnd(Record):
    """OA custom cap lengths in native DBU (not all share the width basis)."""
    left_diagonal: StrictInt
    right_diagonal: StrictInt
    right_half_width: StrictInt

    @model_validator(mode='after')
    def valid(self):
        for key,value in self.model_dump().items():
            checked_int(value,key)
            if value<0:raise ValueError('Negative custom end length')
        if self.right_half_width<=0:raise ValueError('Custom half width must be positive')
        return self


class Shape(Record):
    kind: Literal['rect', 'polygon', 'path', 'pathSeg', 'stdVia']
    lpp: tuple[str, str] | None = None
    bbox: Box | None = None
    points: tuple[Point, ...] = ()
    width: StrictInt | None = None
    style: Literal['truncateExtend','extendExtend','roundRound','varExtendExtend'] = 'truncateExtend'
    begin_style: Literal['truncate', 'extend', 'variable', 'chamfer', 'custom'] = 'truncate'
    end_style: Literal['truncate', 'extend', 'variable', 'chamfer', 'custom'] = 'truncate'
    begin_custom: CustomEnd|None=None
    end_custom: CustomEnd|None=None
    begin_extension: StrictInt = 0
    end_extension: StrictInt = 0
    # OA diagonal PathSeg width/extensions use native diagonal units. Never
    # silently reinterpret an imported native width as perpendicular width.
    width_basis: Literal['perpendicular', 'oa_diagonal'] = 'perpendicular'
    origin: Point | None = None
    orientation: Orientation = 'R0'
    via_definition: str | None = None
    via_parameters: dict[str, Any] = Field(default_factory=dict)
    net_intent: str | None = None

    @field_validator('net_intent',mode='before')
    @classmethod
    def empty_intent(cls,value):return None if value=='' else value

    @model_validator(mode='after')
    def valid(self):
        if self.kind!='path' and self.style!='truncateExtend':raise ValueError('style belongs only to Path')
        if self.kind!='pathSeg' and (self.begin_style!='truncate' or self.end_style!='truncate'):
            raise ValueError('Separate end styles belong only to PathSeg')
        if self.kind not in ('path','pathSeg') and (self.begin_extension or self.end_extension):
            raise ValueError('Extensions belong only to paths')
        if self.kind!='pathSeg' and self.width_basis!='perpendicular':raise ValueError('Diagonal units belong only to native PathSeg')
        for side in ('begin','end'):
            cap=getattr(self,side+'_custom');style=getattr(self,side+'_style')
            if (cap is not None)!=(self.kind=='pathSeg' and style=='custom'):
                raise ValueError('Custom end parameters must agree with PathSeg end style')
        if self.kind!='stdVia' and self.orientation!='R0':raise ValueError('Non-via transforms must update actual coordinates')
        for p in self.points + tuple(self.bbox or ()) + ((self.origin,) if self.origin else ()):
            for v in p: checked_int(v)
        if self.kind == 'stdVia':
            if self.lpp or self.bbox or self.points or self.width is not None:
                raise ValueError('Via geometry is defined by its technology definition')
            if self.origin is None or not self.via_definition:
                raise ValueError('Via needs origin and definition')
            for name, value in self.via_parameters.items():
                if name in VIA_COUNTS:
                    if type(value) is not int or not 1 <= value <= 64: raise ValueError('Invalid via count')
                elif name in VIA_LENGTHS:
                    checked_int(value, name)
                    if value <= 0: raise ValueError('Invalid cut dimension')
                elif name in VIA_PAIRS:
                    if not isinstance(value, (list, tuple)) or len(value) != 2: raise ValueError('Via pair needs x/y')
                    for v in value: checked_int(v, name)
                    if name.endswith('Enc') or name == 'cutSpacing':
                        if min(value) < 0: raise ValueError('Negative via enclosure/spacing')
                else: raise ValueError('Unsupported via parameter: ' + name)
            return self
        if not self.lpp or not all(self.lpp): raise ValueError('Shape needs layer/purpose')
        if self.origin is not None or self.via_definition or self.via_parameters:
            raise ValueError('Non-via shape cannot have via fields')
        if self.kind == 'rect':
            if not self.bbox or any(a >= b for a,b in zip(*self.bbox)): raise ValueError('Rectangle needs positive area')
            if self.points or self.width is not None: raise ValueError('Rectangle has only two corners')
        elif self.kind == 'polygon':
            if self.bbox or self.width is not None or len(self.points) < 3: raise ValueError('Polygon needs vertices')
            pts = self.points
            if len(set(pts)) != len(pts): raise ValueError('Duplicate polygon vertex; do not repeat closing vertex')
            area = sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(pts, pts[1:]+pts[:1]))
            if not area: raise ValueError('Degenerate polygon')
            edges = list(zip(pts, pts[1:]+pts[:1]))
            for i,(a,b) in enumerate(edges):
                for j,(c,d) in enumerate(edges):
                    if j <= i+1 or (i == 0 and j == len(edges)-1): continue
                    if segments_intersect(a,b,c,d): raise ValueError('Self-intersecting polygon')
        else:
            if self.bbox or len(self.points) < 2 or (self.kind == 'pathSeg' and len(self.points) != 2):
                raise ValueError('Invalid path vertices')
            if self.width is None or self.width <= 0 or self.width % 2: raise ValueError('Path needs positive even DBU width')
            checked_int(self.width, 'width')
            for a,b in zip(self.points, self.points[1:]):
                dx,dy = abs(a[0]-b[0]), abs(a[1]-b[1])
                if not (dx or dy) or (dx and dy and dx != dy): raise ValueError('Only nonzero 90/45 degree segments')
            if self.kind == 'path' and self.style not in PATH_STYLES: raise ValueError('Unsupported native path style')
            if self.kind == 'path' and self.style!='varExtendExtend' and (self.begin_extension or self.end_extension):
                raise ValueError('Explicit Path extensions require varExtendExtend')
            diagonal = self.kind == 'pathSeg' and all(a != b for a,b in zip(*self.points))
            if self.width_basis != ('oa_diagonal' if diagonal else 'perpendicular'):
                raise ValueError('PathSeg width basis must match native orientation')
            for style, ext in [(self.begin_style,self.begin_extension), (self.end_style,self.end_extension)]:
                checked_int(ext, 'extension')
                if ext < 0: raise ValueError('Negative extension not supported')
                if self.kind == 'pathSeg' and style not in ('variable','custom') and ext != 0:
                    raise ValueError('Extension must agree with end style')
            if self.kind=='pathSeg' and (self.begin_custom or self.end_custom):
                caps=[c.right_half_width for c in (self.begin_custom,self.end_custom) if c]
                if (sum(caps) if len(caps)==2 else 2*caps[0])!=self.width:
                    raise ValueError('Native custom half widths must agree with width')
            if self.kind=='pathSeg' and any(s in ('custom','chamfer') for s in (self.begin_style,self.end_style)):
                from .pathseg import outline
                boundary=outline(self)
                # Invalid imported custom caps stay read-only; never silently
                # clip a malformed native contour into a different polygon.
                Shape(kind='polygon',lpp=self.lpp,points=boundary)
        return self


class Placement(Record):
    origin: Point
    orientation: Orientation = 'R0'

    @model_validator(mode='after')
    def valid(self):
        for v in self.origin: checked_int(v)
        return self


class MultipartPath(Record):
    """One native parametric MPP. Subfigures are a derived, read-only cache."""
    master: Shape | None = None
    opaque_master:dict[str,Any]=Field(default_factory=dict)
    name:str=''
    parts:list[Any]=Field(default_factory=list)
    choppable:bool=True
    chopped:bool=False
    member_counts:dict[str,int]=Field(default_factory=dict)
    member_native_ids:tuple[str,...]=()
    member_uids:tuple[str,...]=()
    member_routes:dict[str,str]=Field(default_factory=dict)
    native_definition:str|list[Any]=''
    def semantic(self):
        return self.model_dump(exclude={'member_native_ids','member_uids','member_routes','native_definition'})


class Object(Record):
    uid: str
    native_id: str
    native_row: list[Any] = Field(default_factory=list)
    kind: str
    bbox: tuple[tuple[float, float], tuple[float, float]] | None = None
    shape: Shape | None = None
    placement: Placement | None = None
    mpp:MultipartPath|None=None
    attributes: dict[str, Any] = Field(default_factory=dict)
    properties: list[Any] = Field(default_factory=list)
    observed_net: str | None = None
    group_uid: str | None = None
    route_uid: str | None = None
    read_only_reason: str | None = None
    # Native action-specific permission. Does not unlock parameter edits.
    deletion_allowed: bool = False

    def semantic(self):
        d = self.model_dump(exclude={'native_id','native_row','bbox','observed_net','deletion_allowed','mpp'})
        d['mpp']=self.mpp.semantic() if self.mpp else None
        d['attributes'].pop('master_counter', None)
        d['attributes'].pop('master_key', None)
        d['properties'] = sorted(d['properties'], key=lambda p:p[0])
        if self.mpp:
            d.pop('placement',None)
        elif self.shape is None and self.kind not in ('inst','mosaic'):d['opaque_bbox']=self.bbox
        return d


class NativeRoute(Record):
    uid: str
    members: tuple[str,...]=()
    status: str
    net: str|None=None
    properties: list[Any]=Field(default_factory=list)
    start: str|None=None
    end: str|None=None
    restrictions: list[Any]=Field(default_factory=list)
    contiguous: bool=False
    # Native connection objects are immutable context, not editable geometry.
    # None also denotes pre-0.10 snapshots without connection detail.
    endpoint_details: list[Any]|None=None

    def semantic(self):
        d=self.model_dump(exclude={'contiguous'})
        d['properties']=sorted(d['properties'],key=lambda row:row[0])
        return d


class FigureGroup(Record):
    uid: str
    name: str|None=None
    kind: str
    origin: Point
    orientation: Orientation
    ordered: bool
    properties: list[Any]=Field(default_factory=list)
    members: tuple[str,...]=()
    relationships: list[Any]=Field(default_factory=list)

    def semantic(self):
        d=self.model_dump();d['properties']=sorted(d['properties'],key=lambda p:p[0])
        if not self.ordered:d['members']=tuple(sorted(d['members']))
        return d


class Snapshot(Record):
    schema_version: Literal['colayout-lite-layout-1','colayout-lite-layout-2','colayout-lite-layout-3','colayout-lite-layout-4','colayout-lite-layout-5','colayout-lite-layout-6'] = 'colayout-lite-layout-6'
    library: str
    cell: str
    library_path: str
    session: str
    counter: str
    dirty: bool
    dbu_per_micron: StrictInt
    grid: StrictInt
    objects: dict[str, Object]
    dependencies: list[Any] = Field(default_factory=list)
    dependency_digest: str = ''
    pins: list[dict[str, Any]] = Field(default_factory=list)
    terminals: list[Any] = Field(default_factory=list)
    opaque_counts: dict[str, int] = Field(default_factory=dict)
    display: dict[str, Any] = Field(default_factory=dict)
    technology_fingerprint: str = ''
    text_owners: dict[str,str] = Field(default_factory=dict)
    routes: dict[str, NativeRoute] | None = None
    fig_groups: dict[str, FigureGroup] | None = None
    dependency_scheme: Literal['geometry','native_versions'] = 'geometry'
    protected_dependencies: list[Any] | None = None

    def semantic(self):
        from .routing import route_semantics
        return dict(objects={k:v.semantic() for k,v in self.objects.items()},
                    dependencies=self.dependency_digest, terminals=self.terminals,
                    opaque_counts=self.opaque_counts, technology=self.technology_fingerprint,routes=route_semantics(self.routes),
                    fig_groups=None if self.fig_groups is None else {k:v.semantic() for k,v in self.fig_groups.items()})

    @model_validator(mode='after')
    def valid(self):
        if self.dbu_per_micron <= 0 or self.grid <= 0: raise ValueError('Invalid units')
        if any(k != v.uid for k,v in self.objects.items()): raise ValueError('UID map mismatch')
        from .routing import validate_membership
        validate_membership(self)
        return self


class Operation(Record):
    action: Literal['create', 'update', 'delete', 'transform', 'guard', 'delete_guard']
    uid: str = Field(default_factory=lambda: str(uuid4()))
    before: str | None = None
    shape: Shape | None = None
    placement: Placement | None = None
    guard: dict[str, Any] | None = None

    @model_validator(mode='after')
    def valid(self):
        if self.action in ('create','update'):
            if self.shape is None or self.placement or self.guard: raise ValueError('Expected shape payload')
        elif self.action == 'transform':
            if self.placement is None or self.shape or self.guard: raise ValueError('Expected placement payload')
        elif self.action == 'guard':
            if not self.guard or self.shape: raise ValueError('Expected guard payload')
        elif self.shape or self.placement or self.guard: raise ValueError('Delete takes no payload')
        if self.action in ('update','delete','transform') and not self.before:
            raise ValueError('Existing object change requires baseline fingerprint')
        return self


class Workspace(Record):
    @model_validator(mode='after')
    def validation_scope(self):
        if self.validation_only:
            import re
            if not re.fullmatch(r'COLAYOUT_MVP_LITE_[A-Z0-9_]+_[0-9a-f]{10}',self.baseline.cell):
                raise ValueError('Layout-only validation must target an isolated generated cell')
        return self
    @model_validator(mode='before')
    @classmethod
    def baseline_reference(cls,value):
        if isinstance(value,dict) and 'baseline_ref' in value:
            from .storage import load_baseline
            if 'baseline' in value:raise ValueError('Ambiguous baseline')
            value=dict(value)
            if value.pop('storage_version',None) not in (None,'colayout-lite-storage-1'):raise ValueError('Unsupported storage version')
            value['baseline']=load_baseline(value.pop('baseline_ref'))
        return value

    def save(self,path,*,portable=False):
        if portable:return super().save(path)
        from .storage import save_workspace
        save_workspace(self,path)

    schema_version: Literal['colayout-lite-workspace-1'] = 'colayout-lite-workspace-1'
    id: str = Field(default_factory=lambda: str(uuid4()))
    revision: int = 0
    validation_only: bool = Field(default=False,exclude_if=lambda v:not v)
    baseline: Snapshot
    circuit: CircuitContext | None = None
    layout_connectivity: LayoutConnectivity | None = None
    local_data: LocalData = Field(default_factory=LocalData)
    profile_id: str
    connection_config: str | None = None
    operations: tuple[Operation, ...] = ()
    instance_display: dict[str,Literal['auto','full','box_pins']] = Field(default_factory=dict)
    guard_previews: dict[str, Any] = Field(default_factory=dict)
    state: Literal['clean', 'editing', 'submitting', 'conflict', 'indeterminate'] = 'clean'
    last_result: dict[str, Any] = Field(default_factory=dict)

"""A single native MPP factory, with independently validated open-path caps."""
from typing import Literal
from pydantic import Field,StrictInt,model_validator
from .model import Record,LiteError,digest,Shape

class GuardPart(Record):
    kind:Literal['offsetPath','enclosurePath','rectangle']
    lpp:tuple[str,str]
    choppable:bool=True
    width:StrictInt|None=None
    length:StrictInt|None=None
    enclosure:StrictInt|None=None
    separation:StrictInt=0
    justification:Literal['center','left','right']='center'
    beginOffset:StrictInt=0
    endOffset:StrictInt=0
    beginSegOffset:StrictInt=0
    endSegOffset:StrictInt=0
    space:StrictInt|None=None
    gap:Literal['distribute','minimum']='distribute'
    diagonal:bool=False
    @model_validator(mode='after')
    def valid(self):
        if self.kind!='enclosurePath' and (self.width is None or self.width<=0):raise ValueError('Part requires positive width')
        if self.kind=='rectangle' and (self.length is None or self.length<=0 or self.space is None or self.space<=0):raise ValueError('Cut requires positive length/space')
        if self.kind=='enclosurePath' and self.enclosure is None:raise ValueError('Missing enclosure')
        return self

def open_termination(parts,master_width,grid):
    """Candidate cap extensions from enclosure geometry, requiring Calibre QA."""
    from math import ceil
    result=[]
    for part in parts:
        distance=max(0,-part.enclosure) if part.kind=='enclosurePath' else max(0,(part.width-master_width)/2) if part.kind=='offsetPath' else None
        result.append(part if distance is None else part.model_copy(update={'beginOffset':ceil(distance/grid)*grid,'endOffset':ceil(distance/grid)*grid}))
    return tuple(result)


def closed_termination(parts,grid):
    """Keep contact rows separated across a closed path's coincident endpoints.

    ROD's negative offsets retract each endpoint. Open caps only need contact
    enclosure; the two ends of a ring together need one full sampled cut gap.
    Round outward on the native grid, and retain larger explicit retractions.
    """
    from math import ceil
    result=[]
    for part in parts:
        if part.kind=='rectangle':
            retreat=ceil(part.space/(2*grid))*grid
            result.append(part.model_copy(update={'beginOffset':min(part.beginOffset,-retreat),
                                                  'endOffset':min(part.endOffset,-retreat)}))
        else:result.append(part.model_copy(update={'beginOffset':0,'endOffset':0}))
    return tuple(result)

class GuardRecipe(Record):
    schema_version:Literal['colayout-mpp-recipe-2']='colayout-mpp-recipe-2'
    id:str
    name:str
    library:str
    technology_fingerprint:str
    kind:Literal['single','double']
    master_lpp:tuple[str,str]
    width:StrictInt
    parts:tuple[GuardPart,...]
    open_parts:tuple[GuardPart,...]
    min_side_dbu:StrictInt
    min_length_dbu:StrictInt
    source:dict=Field(default_factory=dict)
    validation:dict=Field(default_factory=dict)
    @model_validator(mode='after')
    def valid(self):
        if min(self.width,self.min_side_dbu,self.min_length_dbu)<=0 or not self.parts or not self.open_parts:raise ValueError('Invalid MPP recipe')
        if self.kind=='double':
            for parts in (self.parts,self.open_parts):
                cuts=[p for p in parts if p.kind=='rectangle']
                if len(cuts)!=2 or cuts[0].lpp!=cuts[1].lpp or (cuts[0].justification,cuts[0].separation)==(cuts[1].justification,cuts[1].separation):raise ValueError('Double requires two distinct contact rows')
        return self
    def geometry_key(self):return digest(self.model_dump(exclude={'name','source','validation'}))
    def check_profile(self,p):
        if self.technology_fingerprint!=p.native_fingerprint:raise LiteError('GUARD_PROCESS_MISMATCH')
        known={(r['layer'],r['purpose']) for r in p.layers}
        if self.master_lpp not in known or any(part.lpp not in known for part in (*self.parts,*self.open_parts)):raise LiteError('GUARD_LAYER_UNKNOWN')
        values=[self.width,self.min_side_dbu,self.min_length_dbu]+[v for part in (*self.parts,*self.open_parts) for v in part.model_dump().values() if type(v) is int]
        if any(v%p.grid for v in values):raise LiteError('GUARD_RECIPE_OFF_GRID')
    def ready(self):
        # Generation qualification is not a DRC/LVS signoff of a placed guard.
        return self.validation.get('status')=='passed' and self.validation.get('geometry_key')==self.geometry_key() and set(self.validation.get('forms',[]))=={'ring','path'}
    def payload(self,bbox,grid,net_intent=None,*,points=None):
        if net_intent is not None and not isinstance(net_intent,str):raise LiteError('INVALID_GUARD_NET_INTENT')
        closed=points is None
        if closed:
            (x,y),(xx,yy)=bbox
            if min(xx-x,yy-y)<self.min_side_dbu:raise LiteError('GUARD_TOO_SMALL')
            mid=((x+xx)//(2*grid))*grid;points=[(mid,y),(xx,y),(xx,yy),(x,yy),(x,y),(mid,y)]
        else:
            points=[tuple(p) for p in points]
            Shape(kind='path',lpp=self.master_lpp,points=points,width=self.width)
            if points[0]==points[-1]:raise LiteError('OPEN_MPP_REQUIRED')
            if any(a[0]!=b[0] and a[1]!=b[1] for a,b in zip(points,points[1:])):raise LiteError('MPP_ORTHOGONAL_REQUIRED','当前生成配方支持水平、竖直及90°转角；斜向MPP需要另行验证孔阵列。')
            if any(max(abs(a[0]-b[0]),abs(a[1]-b[1]))<self.min_length_dbu for a,b in zip(points,points[1:])):raise LiteError('MPP_SEGMENT_TOO_SHORT')
        if any(type(v) is not int or v%grid for point in points for v in point):raise LiteError('OFF_GRID')
        def native(v):return ('yes' if v else 'no') if isinstance(v,bool) else str(v) if type(v) is int else v
        return {'version':'mpp-generation-2','recipe_id':self.id,'recipe_key':self.geometry_key(),
            'master_lpp':self.master_lpp,'width':str(self.width),'points':[[str(v) for v in p] for p in points],
            'parts':[{k:native(v) for k,v in part.model_dump(exclude_none=True).items()} for part in (closed_termination(self.parts,grid) if closed else self.open_parts)],'net_intent':net_intent}

def migrate_recipes(rows,grid):
    """Read old configuration only; never remove existing layout geometry."""
    result=[]
    for raw in rows or []:
        if raw.get('kind')=='nested':continue
        if raw.get('schema_version')=='colayout-guard-recipe-1':
            if len(raw.get('components',[]))!=1:continue
            c=raw['components'][0];parts=tuple(GuardPart.model_validate(p) for p in c['parts'])
            raw={k:v for k,v in raw.items() if k not in ('schema_version','components','validation')}
            raw.update(schema_version='colayout-mpp-recipe-2',master_lpp=c['master_lpp'],width=c['width'],parts=parts,
                open_parts=open_termination(parts,c['width'],grid),min_length_dbu=raw['min_side_dbu'],validation={'status':'requires_path_validation'})
        result.append(GuardRecipe.model_validate(raw).model_dump(mode='json'))
    return result

def sampled(recipe):
    source=recipe.source
    return bool(source.get('sample',{}).get('library') and source.get('sample',{}).get('cell')
                and source.get('source_digest') and source.get('native_id'))

def native_templates(profile):
    # Double rows require a sampled recipe, including when the PDK happens to
    # ship a double-row template. No sample means neither ring nor path support.
    from .sexpr import parse_native
    result=[]
    for template in profile.guard_templates:
        try:
            definition=parse_native(template['definition'])
            if isinstance(definition,list) and len((definition+[None]*4)[3] or [])<=1:result.append(template)
        except (ValueError,TypeError,KeyError):continue
    return result

def available(profile,kind=None):return [r.model_dump() for raw in profile.guard_recipes if (r:=GuardRecipe.model_validate(raw)).ready() and (r.kind!='double' or sampled(r)) and (kind is None or r.kind==kind)]
def configured(profile,raw,*,validation=False):
    recipe=GuardRecipe.model_validate(raw);recipe.check_profile(profile)
    if not any(GuardRecipe.model_validate(saved)==recipe for saved in profile.guard_recipes) or (not validation and not recipe.ready()):raise LiteError('GUARD_RECIPE_NOT_CONFIGURED')
    if recipe.kind=='double' and not sampled(recipe):raise LiteError('GUARD_SAMPLE_REQUIRED','双排保护环和开放路径需先提供样例并完成工艺审核。')
    return recipe
def summary(profile):return '；'.join(label+'：'+('已配置' if (bool(native_templates(profile)) if kind=='single' else False) or available(profile,kind) else '未配置') for kind,label in [('single','单排 MPP'),('double','双排 MPP')])

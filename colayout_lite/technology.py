"""Declarative, discovered process settings; no device-name assumptions."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import Field, model_validator
from .model import Record, Shape, LiteError, digest

# Candidate native names only; absent fields stay absent and profiles may override.
DEFAULT_SCHEMATIC_SUMMARY_PARAMETERS = ('w','l','fw','fingers','nf','m','r','c')


class MaterialEvidence(Record):
    native:Literal['unknown']|None='unknown'
    source:str=Field(min_length=1,max_length=4000)


class TechnologyProfile(Record):
    schema_version: Literal['colayout-lite-technology-1'] = 'colayout-lite-technology-1'
    id: str
    label: str
    native_fingerprint: str
    native_technology_name: str|None = Field(default=None,exclude_if=lambda v:v is None)
    configuration_id: str|None = Field(default=None,exclude_if=lambda v:v is None)
    dbu_per_micron: int
    grid: int
    writable_lpps: tuple[tuple[str,str], ...]
    layers: list[dict[str,Any]]
    # layers holds the reviewed effective material. For legacy PDK omissions,
    # retain each replaced native value and its evidence without altering OA.
    material_evidence:dict[str,MaterialEvidence]=Field(default_factory=dict,exclude_if=lambda v:not v)
    vias: dict[str,dict[str,Any]]
    guard_templates: list[dict[str,Any]] = Field(default_factory=list)
    guard_recipes:list[dict[str,Any]]=Field(default_factory=list)
    validation: dict[str,Any] = Field(default_factory=dict)
    editor_defaults: dict[str,Any] = Field(default_factory=dict)
    # Display preferences only: never part of native matching or extraction.
    schematic_summary_parameters: tuple[str,...] = DEFAULT_SCHEMATIC_SUMMARY_PARAMETERS

    @model_validator(mode='before')
    @classmethod
    def upgrade_mpp_recipes(cls,data):
        if isinstance(data,dict) and data.get('guard_recipes'):
            from .mpp_recipe import migrate_recipes
            data={**data,'guard_recipes':migrate_recipes(data['guard_recipes'],data.get('grid',1))}
        return data

    @model_validator(mode='after')
    def valid(self):
        for name,evidence in self.material_evidence.items():
            rows=[r for r in self.layers if r['layer']==name]
            if not rows or len({r.get('material') for r in rows})!=1:
                raise ValueError('Material evidence needs one consistent existing layer')
            if rows[0].get('material') not in ('metal','cut','poly','diff','nwell','pwell','nplus','pplus') or not evidence.source.strip():
                raise ValueError('Supplemental material requires a supported role and actual source')
        if self.configuration_id:
            import re
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',self.configuration_id):raise ValueError('Invalid process configuration ID')
        names=self.schematic_summary_parameters
        if len(set(names))!=len(names) or any(not n.strip() or n!=n.strip() for n in names):
            raise ValueError('Schematic summary parameter names must be nonempty, trimmed and unique')
        if self.dbu_per_micron <= 0 or self.grid <= 0: raise ValueError('Invalid technology scale')
        known={(p['layer'],p['purpose']) for p in self.layers}
        if set(self.writable_lpps)-known: raise ValueError('Configured writable LPP absent from technology')
        if set(self.editor_defaults)-{'layer','width_um','widths_um','metal_stack','via_definition'}:raise ValueError('Unknown editor default')
        if self.editor_defaults.get('layer') and tuple(self.editor_defaults['layer']) not in self.writable_lpps:raise ValueError('Default layer must be writable')
        if self.editor_defaults.get('via_definition') and self.editor_defaults['via_definition'] not in self.vias:raise ValueError('Unknown default via')
        widths=dict(self.editor_defaults.get('widths_um',{}))
        if set(widths)-{r['layer'] for r in self.layers if r['purpose']=='drawing' and r.get('material')=='metal'}:raise ValueError('Unknown routing metal for width')
        if 'width_um' in self.editor_defaults:widths['__legacy__']=self.editor_defaults['width_um']
        for value in widths.values():
            from decimal import Decimal
            width=Decimal(str(value))*self.dbu_per_micron
            if not width.is_finite() or width<=0 or width!=width.to_integral_value() or int(width)%self.grid or int(width)%2:
                raise ValueError('Default wire width must be positive even DBU on grid')
        if self.editor_defaults.get('metal_stack'):
            from .wire_defaults import metal_stack
            metal_stack(self,self.editor_defaults['metal_stack'])
        from .guard_recipes import GuardRecipe
        recipes=[GuardRecipe.model_validate(raw) for raw in self.guard_recipes]
        if len({r.id for r in recipes})!=len(recipes):raise ValueError('Duplicate guard recipe ID')
        for recipe in recipes:recipe.check_profile(self)
        return self

    @property
    def key(self):
        return self.configuration_id or self.native_fingerprint

    @property
    def native_layers(self):
        if not self.material_evidence:return self.layers
        return [{**row,'material':self.material_evidence[row['layer']].native} if row['layer'] in self.material_evidence else row for row in self.layers]

    def check(self, shape: Shape):
        if shape.kind in ('path', 'pathSeg'):
            from .path_validation import validate_path_points
            validate_path_points(shape.points)
        if shape.kind == 'stdVia':
            vd=self.vias.get(shape.via_definition)
            if not vd or vd['kind']!='stdViaDef': raise LiteError('UNSUPPORTED_VIA',shape.via_definition or '')
            if vd.get('cut_pattern'):raise LiteError('PATTERNED_VIA_READ_ONLY')
            if set(shape.via_parameters)-set(vd['defaults']): raise LiteError('UNSUPPORTED_VIA_PARAMETER')
            if ('imp1Enc' in shape.via_parameters and not vd.get('implant1')) or ('imp2Enc' in shape.via_parameters and not vd.get('implant2')):
                raise LiteError('VIA_IMPLANT_NOT_DEFINED')
        elif shape.lpp not in self.writable_lpps: raise LiteError('LAYER_NOT_WRITABLE',str(shape.lpp))
        coords=list(shape.points)+list(shape.bbox or [])+([shape.origin] if shape.origin else [])
        if any(v % self.grid for p in coords for v in p): raise LiteError('OFF_GRID')
        if shape.width is not None and shape.width % self.grid: raise LiteError('OFF_GRID_WIDTH')
        if shape.kind=='pathSeg' and any(v%self.grid for v in [shape.begin_extension,shape.end_extension]): raise LiteError('OFF_GRID_EXTENSION')
        for cap in (shape.begin_custom,shape.end_custom):
            if cap and any(v%self.grid for v in cap.model_dump().values()):raise LiteError('OFF_GRID_CUSTOM_END')
        for name,value in shape.via_parameters.items():
            if name in ('cutRows','cutColumns'):continue
            values=value if isinstance(value,(list,tuple)) else [value]
            if any(v%self.grid for v in values):raise LiteError('OFF_GRID_VIA_PARAMETER',name)

    def effective_via(self, shape: Shape):
        return {**self.vias[shape.via_definition]['defaults'], **shape.via_parameters}


def native_fingerprint(raw):
    return digest(raw)


def with_layer_materials(profile,declarations):
    """Fill only missing native roles from explicit, reviewable process evidence."""
    native={r['layer']:r.get('material') for r in profile.native_layers}
    evidence=dict(profile.material_evidence)
    for name,row in declarations.items():
        if name not in native or native[name] not in (None,'unknown'):
            raise LiteError('NATIVE_MATERIAL_CANNOT_OVERRIDE',name)
        if set(row)!={'material','source'}:raise LiteError('MATERIAL_DECLARATION_INVALID',name)
        evidence[name]=MaterialEvidence(native=native[name],source=row['source'])
    layers=[{**r,'material':declarations[r['layer']]['material']} if r['layer'] in declarations else r for r in profile.layers]
    return TechnologyProfile.model_validate({**profile.model_dump(mode='json'),'layers':layers,'material_evidence':evidence})

"""Reviewed MIM contact location; layer names are native PDK data."""
from typing import Literal
from pydantic import model_validator
from ..model import Record,LiteError


class MimCapacitor(Record):
    status:Literal['unconfigured','unsupported','configured']='unconfigured'
    lpp:tuple[str,str]|None=None
    lower_metal:str|None=None
    upper_metal:str|None=None
    source:str=''

    @model_validator(mode='after')
    def valid(self):
        if self.lpp and any(not v.strip() for v in self.lpp):raise ValueError('MIM layer/purpose cannot be empty')
        if self.lower_metal and self.upper_metal and self.lower_metal==self.upper_metal:raise ValueError('MIM requires two different metal layers')
        if self.status=='configured' and not all((self.lpp,self.lower_metal,self.upper_metal,self.source.strip())):
            raise ValueError('配置 MIM 需填写图层/用途、上下金属及来源；无法确认时保持待确认。')
        if self.status=='unsupported' and any((self.lpp,self.lower_metal,self.upper_metal)):
            raise ValueError('不支持 MIM 时不要填写层位')
        return self

    def require_reviewed(self):
        if self.status=='unconfigured':
            raise LiteError('MIM_CONFIRMATION_REQUIRED','请在“本地 DRC → MIM 电容”确认层位，或明确选择此工艺不支持 MIM。')

    def check_technology(self,p):
        if self.lpp and tuple(self.lpp) not in {(r['layer'],r['purpose']) for r in p.layers}:
            raise LiteError('MIM_LAYER_UNKNOWN','MIM 图层/用途不在本工艺中。')
        metals={r['layer'] for r in p.layers if r.get('material')=='metal'}
        if any(layer and layer not in metals for layer in (self.lower_metal,self.upper_metal)):
            raise LiteError('MIM_METAL_UNKNOWN','上下层需选择本工艺已确认的金属层。')
        if self.status!='configured':return
        pair={self.lower_metal,self.upper_metal}
        if not any(v.get('kind')=='stdViaDef' and {v.get('layer1'),v.get('layer2')}==pair for v in p.vias.values()):
            raise LiteError('MIM_VIA_PAIR_UNKNOWN','本工艺中没有连接所选两层的标准过孔。')
        stack=p.editor_defaults.get('metal_stack',[])
        if self.lower_metal in stack and self.upper_metal in stack:
            if stack.index(self.upper_metal)!=stack.index(self.lower_metal)+1:
                raise LiteError('MIM_METAL_ORDER','MIM 的上下金属应按实际金属栈相邻排序。')

"""Shared routing width policy; process defaults and DRC limits are distinct."""
from decimal import Decimal,ROUND_CEILING
from math import lcm
from .actions import dbu
from .model import LiteError

_UNSET=object()

def default_width_um(technology,layer,minimum_um):
    defaults=technology.editor_defaults
    if layer in defaults.get('widths_um',{}):return defaults['widths_um'][layer]
    if 'width_um' in defaults:return defaults['width_um']  # Legacy confirmed profile.
    # Old profiles without a default retain a legal, on-grid minimum fallback.
    quantum=lcm(2,technology.grid)
    steps=(Decimal(str(minimum_um))*technology.dbu_per_micron/quantum).to_integral_value(rounding=ROUND_CEILING)
    return float(steps*quantum/technology.dbu_per_micron)


def width_dbu(technology,layer,minimum_um,width_um=_UNSET):
    width=default_width_um(technology,layer,minimum_um) if width_um is _UNSET else width_um
    value=dbu(width,technology)
    if value<=0 or value%2 or value%technology.grid or Decimal(str(width))<Decimal(str(minimum_um)):
        raise LiteError('ROUTE_WIDTH_BELOW_RULE',
            f'{layer} 布线宽度 {width} µm 不符合规则；请配置不小于 {minimum_um} µm 的网格线宽。',
            layer=layer,width_um=width,minimum_um=minimum_um)
    return value

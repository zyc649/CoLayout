"""Layer-ordered defaults measured from the preceding adjacent standard via."""
from decimal import Decimal
from math import lcm,ceil
from .model import LiteError


def metal_stack(profile,explicit=None):
    metals={r['layer'] for r in profile.layers if r.get('material')=='metal' and r['purpose']=='drawing'}
    if not metals:raise LiteError('PROCESS_LAYER_MATERIALS_REQUIRED','原生技术库未声明金属材质。配置 Agent 需依据真实工艺资料补充 --layer-materials，再提交人端审核；不能按层名猜测。')
    edges={(v['layer1'],v['layer2']) for v in profile.vias.values() if v.get('layer1') in metals and v.get('layer2') in metals}
    if explicit:
        order=list(explicit)
        if len(order)<2 or len(set(order))!=len(order) or any((a,b) not in edges for a,b in zip(order,order[1:])):raise LiteError('INVALID_METAL_STACK')
        return order
    # Only connected routing metals; unrelated metal-purpose markers are not
    # sorted into a fictitious stack. Branches still require explicit mapping.
    connected={v for pair in edges for v in pair};bottom=connected-{b for a,b in edges}
    if len(bottom)!=1:raise LiteError('METAL_STACK_AMBIGUOUS','请由 Agent 核对后提供 --metal-stack。')
    order=[next(iter(bottom))]
    while True:
        nexts={b for a,b in edges if a==order[-1]}
        if not nexts:break
        if len(nexts)!=1 or next(iter(nexts)) in order:raise LiteError('METAL_STACK_AMBIGUOUS')
        order.append(next(iter(nexts)))
    if set(order)!=connected:raise LiteError('METAL_STACK_AMBIGUOUS')
    return order


def default_width(profile,layer=None):
    defaults=profile.editor_defaults
    layer=layer or defaults.get('layer',(None,))[0]
    if isinstance(layer,(tuple,list)):layer=layer[0]
    return defaults.get('widths_um',{}).get(layer,defaults.get('width_um',.8))


def default_writable_lpps(profile,stack):
    return [(r['layer'],r['purpose']) for r in profile.layers if r['purpose']=='drawing' and
            (r.get('material')=='nwell' or r.get('material')=='metal' and r['layer'] in stack)]


def measure_stack(snapshot,profile,order,via_uids=None):
    from .process_measurements import measure_single_via
    vias=[];widths={};evidence={};via_uids=via_uids or {}
    for i,(lower,upper) in enumerate(zip(order,order[1:])):
        pair=(lower,upper);key=lower+'/'+upper
        try:measurement=measure_single_via(snapshot,profile,pair,via_uids.get(key))
        except LiteError as exc:
            raise LiteError(exc.code,f'{lower}–{upper}：'+str(exc),**exc.details) from exc
        vias.append({'pair':list(pair),**measurement})
        for layer in ([lower,upper] if i==0 else [upper]):
            raw=measurement['metal_rectangles'][layer]['side_dbu'];quantum=lcm(profile.grid,2)
            rounded=ceil(raw/quantum)*quantum
            widths[layer]=rounded/profile.dbu_per_micron
            evidence[layer]={'via_pair':list(pair),'via_uid':measurement['uid'],'definition':measurement['definition'],
                'metal_layer':layer,'raw_width_dbu':raw,'suggested_width_um':widths[layer],'rounded':rounded!=raw}
    return {'metal_stack':list(order),'vias':vias,'widths_um':widths,'per_layer':evidence,
        'basis':'首层取首对过孔下层金属短边；其余层取前一级过孔上层金属短边。'}

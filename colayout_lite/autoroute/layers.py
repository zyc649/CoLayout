"""Technology-driven metal selection and frozen standard-via graph."""
from ..model import LiteError
from ..routing_widths import width_dbu
from ..routing_rules import routing_capabilities,_via_template,_threshold
from .models import LayerRule,ViaRule
from .geometry import figure


def capabilities(technology,drc):
    caps=routing_capabilities(technology,drc)
    return {'layers':caps['layers'],'layer_pairs':caps['layer_pairs'],
            'default_layers':[r['layer'] for r in caps['layers'] if r['supported']][:2]}


def resolve(technology,drc,selected=None):
    caps=capabilities(technology,drc);selected=tuple(caps['default_layers'] if selected is None else selected)
    supported={r['layer'] for r in caps['layers'] if r['supported']}
    if not selected or len(set(selected))!=len(selected) or not set(selected)<=supported:
        raise LiteError('ROUTING_LAYER_SCOPE','请选择至少一个规则完整的可布线金属层。',selected=selected,capabilities=caps)
    names=tuple(r['layer'] for r in caps['layers'] if r['layer'] in selected)
    scale=technology.dbu_per_micron
    rules=tuple(LayerRule(name=n,width=width_dbu(technology,n,_threshold(drc,'width',n)),
        spacing=_threshold(drc,'spacing',n)*scale,minimum_area=(_threshold(drc,'area',n) or 0)*scale*scale) for n in names)
    vias=[];edges={n:set() for n in names};checked=[]
    for row in caps['layer_pairs']:
        if not row['supported'] or not set(row['layers'])<=set(names):continue
        definition,footprints=_via_template(technology,drc,row['via_definition'])
        # Every generated metal enclosure must be on an explicitly chosen layer.
        if any(l not in names and l!=definition['cut_layer'] for l in footprints):continue
        vias.append(ViaRule(name=row['via_definition'],cut_layer=definition['cut_layer'],
            footprints=tuple(figure(l,g) for l,g in footprints.items()),cut_spacing=_threshold(drc,'spacing',definition['cut_layer'])*scale))
        a,b=row['layers'];edges[a].add(b);edges[b].add(a);checked.append(row['cut_width_rule_checked'])
    reached={names[0]}
    while True:
        more=reached|set().union(*(edges[n] for n in reached))
        if more==reached:break
        reached=more
    if reached!=set(names):raise LiteError('ROUTING_LAYER_DISCONNECTED','所选层之间没有完整的已验证标准过孔通道；请选择连续且规则完整的金属层。',selected=names,reachable=sorted(reached))
    return rules,tuple(vias),all(checked)


def transition(problem,a,b):
    pair={problem.layers[a].name,problem.layers[b].name}
    return next((v for v in problem.via_rules if pair<={f.layer for f in v.footprints}),None)


def cut_spacing(problem,layer):
    return max(v.cut_spacing for v in problem.via_rules if v.cut_layer==layer)

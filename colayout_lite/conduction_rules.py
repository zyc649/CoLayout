"""Read-only electrical roles derived from the imported technology definitions.

This is not a write-layer policy. Diffusion/implants prove a contact signature;
they never become lateral conducting nodes or transistor channels.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ContactRule:
    names: tuple[str,...]
    cut: str
    layers: tuple[str,str]
    required: frozenset[str]
    trigger: frozenset[str]
    forbidden: frozenset[str]
    kind: str


class ConductionRules:
    def __init__(self,technology):
        self.definitions=technology.vias
        roles={r['layer']:r.get('material') for r in technology.layers if r['purpose']=='drawing'}
        self.metals=frozenset(k for k,v in roles.items() if v=='metal')
        self.gates=frozenset(k for k,v in roles.items() if v=='poly')
        self.wells=frozenset(k for k,v in roles.items() if v=='nwell')
        self.diffusions=frozenset(k for k,v in roles.items() if v=='diff')
        self.conductors=self.metals|self.gates|self.wells
        self.clickable=self.metals|self.gates
        rules={}
        for name,d in technology.vias.items():
            if d.get('kind')!='stdViaDef' or d.get('cut_pattern'):continue
            a,b,cut=(d.get(k) for k in ('layer1','layer2','cut_layer'))
            if not a or not b or not cut:continue
            kind=None;required=frozenset((a,b));forbidden=frozenset()
            if a in self.metals and b in self.metals:
                layers=tuple(sorted((a,b)));trigger=required;kind='metal_via'
            # Local policy deliberately does not connect poly/Gate to metal.
            # Keep same-layer poly geometry/query and native write capabilities;
            # only the cross-layer electrical edge is disabled. N-well taps
            # below retain their existing material proof.
            elif (roles.get(a)=='diff' and b in self.metals) or (roles.get(b)=='diff' and a in self.metals):
                implants={d.get('implant1'),d.get('implant2')}-{None}
                wells=implants & self.wells;nplus={k for k in implants if roles.get(k)=='nplus'}
                if len(wells)==1 and nplus:
                    well=next(iter(wells));metal=b if b in self.metals else a
                    layers=(well,metal);required=required|implants;trigger=frozenset(wells|nplus);kind='well_contact'
                    forbidden=frozenset(k for k,v in roles.items() if v in ('pplus','pwell','poly'))
            if kind:
                key=(cut,layers,required,trigger,forbidden,kind)
                rules.setdefault(key,[]).append(name)
        self.contacts=tuple(ContactRule(tuple(names),*key) for key,names in rules.items())
        self.contact_cuts=frozenset(r.cut for r in self.contacts)
        self.access_rules=tuple(r for r in self.contacts if r.kind!='metal_via')
        self.access_layers=self.gates|self.wells|frozenset(l for r in self.access_rules for l in (*r.required,*r.forbidden,r.cut) if l not in self.metals)

    def accepts_definition(self,rule,name):
        if name is None or name in rule.names:return True
        definition=self.definitions.get(name,{})
        if definition.get('kind')!='stdViaDef' or definition.get('cut_pattern'):return False
        ends={definition.get('layer1'),definition.get('layer2')}
        # A diffusion contact can land in pre-existing N+ / N-well material.
        # It need not generate that well itself (e.g. M1_SN inside NW). The
        # complete well-contact signature must still be proved geometrically.
        return (rule.kind=='well_contact' and definition.get('cut_layer')==rule.cut and
                ends<=rule.required and bool(ends & self.diffusions) and rule.layers[1] in ends)

    def describe(self):
        return {'conductive_layers':sorted(self.conductors),'metal_layers':sorted(self.metals),
                'gate_layers':sorted(self.gates),'well_layers':sorted(self.wells),
                'contacts':[{'definitions':list(r.names),'cut':r.cut,'layers':list(r.layers),'required_layers':sorted(r.required),'kind':r.kind} for r in self.contacts],
                'unsupported_conduction':['gate-to-metal contact','lateral diffusion','pwell / substrate propagation','device channels']}

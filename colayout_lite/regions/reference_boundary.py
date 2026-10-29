"""Reference obligations for region planning, separate from physical connectivity."""
from collections import defaultdict
from copy import deepcopy
from ..circuit.hierarchy import instance_for, reference_net, net_key, path_label
from ..geometry_memo import GeometryMemo

_reference_facts = GeometryMemo(sources=3, entries=4)


def legacy_obligations(w,selected):
    """Keep existing region contracts loadable until explicit PIN recompute.

    Old saved regions may lack new reference-only obligations. Loading a file
    must neither reject it for new requirements nor silently move its PINs.
    """
    bound=defaultdict(set);owners=defaultdict(set)
    for binding in w.circuit.bindings:
        for path in binding.schematic_paths:bound[path[0].instance].add(binding.layout_uid)
    for inst in w.circuit.instances.values():
        for term in inst.terminals.values():
            for net in (term.members or {term.name:term.net}).values():
                if net is not None:owners[net].update(bound[inst.name])
    rows=[]
    for port in w.circuit.ports.values():
        for member,net in (port.members or {port.name:port.net}).items():
            if not owners[net]&selected:continue
            basis='人工关联' if net in w.local_data.reference_net_map else '原理图顶层同名参考'
            rows.append({'reference_net':net,'scope':'','target':w.local_data.reference_net_map.get(net,net),
                'missing_terminals':[],'has_native_member':True,'evidence':f'原理图顶层 {member}（{basis}）'})
    return rows


def _facts(context, layout):
    """Immutable circuit/Layout binding facts; no placement or local policy."""
    owners=defaultdict(set);entries=defaultdict(list);native=defaultdict(set);identities={}
    for binding in context.bindings:
        inst=layout.instances.get(binding.layout_uid)
        if inst is None:continue
        actual={member:net for t in inst.terminals.values() for member,net in (t.members or {t.name:t.net}).items()}
        for path in binding.schematic_paths:
            ref=instance_for(context,path)
            if ref is None:continue  # Legacy hierarchical snapshots remain explicitly incomplete elsewhere.
            for term in ref.terminals.values():
                for member,net in (term.members or {term.name:term.net}).items():
                    if net is None:continue
                    prefix,net=reference_net(context,path[:-1],net);key=net_key(prefix,net)
                    identities[key]=(prefix,net);owners[key].add(inst.uid)
                    entries[key].append({'uid':inst.uid,'endpoint':path_label(path)+'.'+member,
                        'missing':member not in actual,'reference_path':[p.model_dump(mode='json') for p in path],
                        'terminal':term.name,'member':member,'reference_net':net})
                    if actual.get(member) is not None:native[key].add(actual[member])
    external={net_key((),n) for p in context.ports.values() for n in (p.members or {p.name:p.net}).values() if n is not None}
    return owners,entries,native,identities,external


def obligations(w, selected):
    # A rigid move does not change native binding facts. Retain both sources
    # with the entry and evaluate membership/reference-map policy anew below.
    _,facts=_reference_facts.get(w.circuit,id(w.layout_connectivity),
        lambda:(w.layout_connectivity,_facts(w.circuit,w.layout_connectivity)))
    owners,entries,native,identities,external=facts
    result=[]
    for key,uids in owners.items():
        if not uids&selected or not (uids-selected or key in external):continue
        prefix,net=identities[key];inside=[e for e in entries[key] if e['uid'] in selected]
        missing=[{k:deepcopy(v) for k,v in e.items() if k!='missing'} for e in inside if e['missing']]
        # Root reference names are intentional interface labels, not evidence of
        # native terminals. Internal occurrence nets need an unambiguous actual
        # target; never flatten same-named nets from different subcircuits.
        target=(w.local_data.reference_net_map.get(net,net) if not prefix else
                next(iter(native[key])) if len(native[key])==1 else None)
        result.append({'reference_net':net,'scope':path_label(prefix),'target':target,
            'missing_terminals':missing,'has_native_member':any(not e['missing'] for e in inside),
            'evidence':('原理图接口要求：'+(path_label(prefix)+'/' if prefix else '')+net+
                        ('（人工关联）' if not prefix and net in w.local_data.reference_net_map else ''))})
    return result

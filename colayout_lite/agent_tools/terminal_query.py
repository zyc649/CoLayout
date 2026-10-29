"""Join authorized native identity, reference bindings and physical PIN evidence."""
from collections import defaultdict
from .inspection import direct_ids
from ..editor import projected
from ..region_analysis import scope_graph
from ..circuit.net_names import signal_names
from ..circuit.hierarchy import instance_for, path_label


def matches_reference(path, name):
    return bool(path) and (path[0].instance==name or path_label(path)==name)


def reference_gaps(circuit, inst, paths, terminal, reference_name=None):
    """Describe reference coverage, without creating native terminals or PINs.

    A binding identifies an instance, not equivalent terminal names or nets.
    Resolve the exact bound occurrence; a descendant never borrows its
    ancestor's interface, including in legacy snapshots without hierarchy.
    """
    if circuit is None:
        return [], []
    native_members = {member for t in inst.terminals.values()
                      for member in (t.members or {t.name: t.net})}
    missing, warnings = {}, []
    for path in paths:
        if not path or (reference_name is not None and not matches_reference(path,reference_name)):
            continue
        ref = instance_for(circuit,path)
        native_path = [part.model_dump(mode='json') for part in path]
        if ref is None:
            warnings.append({'kind': 'reference_interface_unavailable', 'uid': inst.uid,
                             'schematic_path': native_path,
                             'reason': 'bound instance interface was not exported'})
            continue
        for t in ref.terminals.values():
            for member, net in (t.members or {t.name: t.net}).items():
                if member in native_members or (terminal is not None and terminal not in (t.name, member)):
                    continue
                references = missing.setdefault((t.name, member), [])
                evidence = {'instance': ref.name, 'terminal': t.name, 'member': member,
                            'net': net, 'signal': t.member_signals.get(member),
                            'schematic_path': native_path}
                if evidence not in references:
                    references.append(evidence)
    rows = []
    for (name, member), references in sorted(missing.items()):
        rows.append({'terminal': name, 'member': member, 'net': None, 'signal': None,
                     'pin_ids': [], 'component_ids': [], 'other_nets': [], 'query': None,
                     'contact_state': 'geometry_unavailable',
                     'evidence_source': 'schematic_reference_only',
                     'reason': 'layout_terminal_unavailable',
                     'reference_terminals': references})
        warnings.append({'kind': 'layout_terminal_unavailable', 'uid': inst.uid,
                         'terminal': name, 'member': member,
                         'reason': 'reference terminal has no same-named native terminal member; physical connection is unknown'})
    return rows, warnings


def query(w,p,rid,name,terminal=None,name_source='layout'):
    allowed=direct_ids(w,rid);objects=projected(w);layout=w.layout_connectivity
    bindings=defaultdict(list)
    if w.circuit:
        for binding in w.circuit.bindings:
            if binding.layout_uid in allowed:
                bindings[binding.layout_uid].extend(binding.schematic_paths)
    if name_source=='schematic':
        ids=sorted(uid for uid,paths in bindings.items() if any(matches_reference(path,name) for path in paths))
    else:
        ids=sorted(uid for uid in allowed if (objects[uid].attributes.get('name')==name or
            layout and uid in layout.instances and layout.instances[uid].name==name))
    result={'document_id':w.id,'revision':w.revision,'region_id':rid,'name_source':name_source,'instance_name':name,
        'status':'found' if ids else 'not_found_in_current_scope','ambiguous':name_source=='layout' and len(ids)>1,
        'candidates':[],'meaning':'Native Layout nets define identity. Schematic bindings are references; missing geometry is unknown, not disconnected.'}
    if name_source=='schematic' and w.circuit is None:
        result.update(status='reference_unavailable',required_evidence='verified native schematic bindings')
        return result
    if layout is None:
        result['status']='native_interface_unavailable'
        result['candidates']=[{'uid':uid,'layout_name':objects[uid].attributes.get('name',uid),
            'status':'native_interface_unavailable','terminals':[],
            'schematic_paths':[[part.model_dump(mode='json') for part in path] for path in bindings[uid]]} for uid in ids]
        result['coverage_warnings']=[{'kind':'layout_connectivity_missing'}]
        return result
    if not ids:return result
    graph=scope_graph(w,p,rid);signals=signal_names(layout);pins=defaultdict(list)
    for pin in graph['pins']:
        if pin['owner'] in ids:pins[pin['owner']].append(pin)
    from ..connection_diagnostics import pin_issues
    issues={r['pin_id']:r for r in pin_issues(graph,limit=0)['preparation_issues']}
    net_sets=defaultdict(set);warnings=list(graph['warnings'])
    for uid in ids:
        inst=layout.instances.get(uid) if layout else None
        candidate={'uid':uid,'layout_name':objects[uid].attributes.get('name',inst.name if inst else uid),
            'schematic_paths':[[part.model_dump(mode='json') for part in path] for path in bindings[uid]],
            'terminals':[],'status':'native_interface_unavailable' if inst is None else 'found'}
        result['candidates'].append(candidate)
        if inst is None:continue
        for t in inst.terminals.values():
            members=t.members or {t.name:t.net}
            for member,net in members.items():
                if terminal is not None and terminal not in (t.name,member):continue
                matching=[pin for pin in pins[uid] if pin['name']==member]
                components=set().union(*(graph['pin_components'].get(pin['id'],set()) for pin in matching))
                partial=any(pin['id'] in graph.get('partial_pin_ids',set()) for pin in matching)
                other_nets={pin['net'] for pin in graph['pins'] if any(cid in graph['pin_components'].get(pin['id'],set()) for cid in components)}-{net,None}
                unsupported=any(issues.get(pin['id'],{}).get('reason')=='gate_requires_metal' for pin in matching)
                state=('unsupported_access' if unsupported else 'geometry_unavailable' if not matching or not any(pin['figures'] for pin in matching) else
                    'unresolved_net' if net is None else 'shorted' if other_nets else 'partial' if partial else 'attached' if components else 'unattached')
                signal=t.member_signals.get(member) or signals.get(net)
                if signal and net is not None:net_sets[signal].add(net)
                candidate['terminals'].append({'terminal':t.name,'member':member,'net':net,'signal':signal,
                    'pin_ids':[pin['id'] for pin in matching],'component_ids':sorted(components),'contact_state':state,
                    'evidence_source':'layout',
                    'other_nets':sorted(other_nets),'query':{'kind':'net','target':{'kind':'pin','id':matching[0]['id']}} if len(matching)==1 else None})
        missing,reference_warnings=reference_gaps(w.circuit,inst,bindings[uid],terminal,
            name if name_source=='schematic' else None)
        candidate['terminals'].extend(missing)
        warnings.extend(reference_warnings)
        if not candidate['terminals']:candidate['status']='terminal_not_found'
    result.update(query_ref=graph['query_ref'],coverage_warnings=warnings,
        same_signal_distinct_nets=[{'signal':s,'nets':sorted(nets)} for s,nets in sorted(net_sets.items()) if len(nets)>1],
        connection_scope='contacts within current layer only; attached does not assert whole-net completion, seam continuity or LVS')
    return result

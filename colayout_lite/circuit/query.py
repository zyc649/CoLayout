"""Local projections. Layout targets and schematic reference stay separate."""
from ..model import LiteError


def require_context(workspace):
    if workspace.circuit is None or workspace.layout_connectivity is None:
        raise LiteError('NATIVE_CONTEXT_REQUIRED', '请从 Virtuoso 重新导入原生对应关系与 Layout 网络。')
    layout = workspace.layout_connectivity
    if workspace.circuit.pair_id != layout.pair_id:
        raise LiteError('PAIRED_SOURCE_MISMATCH', '原理图参考与 Layout 网络不是同一次导入。')
    s = workspace.baseline
    if (layout.source.library,layout.source.cell,layout.source.session,layout.source.counter) != (s.library,s.cell,s.session,s.counter):
        raise LiteError('NATIVE_CONTEXT_STALE')
    return workspace.circuit


def rebind_layout(connectivity, snapshot):
    if connectivity is None:
        return None
    return connectivity.model_copy(update={'source':connectivity.source.model_copy(update={
        'library':snapshot.library,'cell':snapshot.cell,'session':snapshot.session,'counter':snapshot.counter})})


def layout_intent(connectivity):
    """Index only native Layout terminals. Schematic is deliberately absent."""
    mapping, nets, missing = {}, {}, []
    def add(endpoint, net):
        if net is None:
            missing.append(endpoint)
        else:
            nets.setdefault(net,[]).append(endpoint)
    for uid, inst in connectivity.instances.items():
        mapping[inst.name] = uid
        for term in inst.terminals.values():
            for name, net in (term.members or {term.name:term.net}).items():
                add(inst.name+'.'+name,net)
    for term in connectivity.ports.values():
        for name, net in (term.members or {term.name:term.net}).items():
            add('$'+name,net)
    if missing:
        raise LiteError('LAYOUT_NET_DATA_INCOMPLETE', 'Layout 端口未分配网络；不会从原理图补推。', endpoints=missing)
    return {'schema_version':'colayout-agent-intent-1','instance_map':mapping,
            'nets':{net:sorted(ends) for net,ends in nets.items()}}


def inspect_circuit(workspace, device=None):
    context = require_context(workspace)
    if device is None:
        return context.model_dump(mode='json')
    if device not in context.instances:
        raise LiteError('UNKNOWN_LOGICAL_DEVICE', device)
    return {'instance':context.instances[device].model_dump(mode='json'),
            'bindings':[row.model_dump(mode='json') for row in context.bindings
                        if any(path[0].instance==device for path in row.schematic_paths)]}


def selection_boundary(workspace, layout_uids):
    if workspace.layout_connectivity is None:
        raise LiteError('LAYOUT_CONNECTIVITY_REQUIRED')
    selected=set(layout_uids)
    intent=layout_intent(workspace.layout_connectivity)
    known=set(intent['instance_map'].values())
    if not selected or selected-known:
        raise LiteError('INVALID_LAYOUT_SELECTION', unknown=sorted(selected-known))
    rows=[]
    for net,endpoints in intent['nets'].items():
        inside=[e for e in endpoints if not e.startswith('$') and intent['instance_map'][e.rsplit('.',1)[0]] in selected]
        outside=[e for e in endpoints if e not in inside]
        if inside and outside:
            rows.append({'net':net,'inside_endpoints':inside,'outside_endpoints':outside})
    return {'boundary_nets':rows,'scope':'native Layout pin/net boundary; schematic not used'}

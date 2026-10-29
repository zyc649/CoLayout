"""Occurrence-aware reference queries. Never derive Layout identity from names."""
import json


def path_key(path):
    return tuple((p.library,p.cell,p.view,p.instance,p.member,p.row,p.column) for p in path)


def path_label(path):
    return '/'.join(p.instance+(f'[{p.member},{p.row},{p.column}]' if (p.member,p.row,p.column)!=(0,0,0) else '') for p in path)


def scope_for(context, path):
    if not path:return context
    key=path_key(path)
    return next((scope for scope in context.hierarchy if path_key(scope.path)==key),None)


def instance_for(context, path):
    if not path:return None
    scope=scope_for(context,path[:-1])
    if scope is None:return None
    p=path[-1];s=scope.source
    if (p.library,p.cell,p.view)!=(s.library,s.cell,s.view):return None
    return scope.instances.get(p.instance)


def validate_capture(context):
    expected={path_key(path[:i]) for b in context.bindings for path in b.schematic_paths for i in range(1,len(path))}
    actual=[path_key(scope.path) for scope in context.hierarchy]
    if set(actual)!=expected or len(actual)!=len(set(actual)):
        raise ValueError('Incomplete or unexpected schematic hierarchy capture')
    for scope in context.hierarchy:
        if scope.source.session!=context.source.session or instance_for(context,scope.path) is None:
            raise ValueError('Invalid schematic occurrence source')
    for binding in context.bindings:
        for path in binding.schematic_paths:
            if any(instance_for(context,path[:i]) is None for i in range(1,len(path)+1)):
                raise ValueError('Bound schematic instance was not captured')


def reference_net(context, path, net):
    """Canonical reference net across scalar hierarchy ports, never a Layout net.

    Retain occurrence-local identity when a bus/array relation is ambiguous.
    No parsing of device/net naming conventions or vector expressions.
    """
    path=tuple(path)
    if net is None:return path,None
    while path:
        scope=scope_for(context,path);parent=instance_for(context,path)
        if scope is None or parent is None:break
        if parent.member_count!=1:break
        if any((p.member,p.row,p.column)!=(0,0,0) for p in path):break
        targets=set()
        for port in scope.ports.values():
            for member,n in (port.members or {port.name:port.net}).items():
                if n!=net:continue
                for term in parent.terminals.values():
                    values=term.members or {term.name:term.net}
                    if member in values and values[member] is not None:targets.add(values[member])
        if len(targets)!=1:break
        net=targets.pop();path=path[:-1]
    return path,net


def net_key(path,net):
    return json.dumps([path_key(path),net],ensure_ascii=False,separators=(',',':'))


def reference_rows(context, bindings):
    """Only bound leaves of authorized Layout objects, with exact scope identity."""
    rows={}
    for binding in bindings:
        for path in binding.schematic_paths:
            inst=instance_for(context,path)
            if inst is None:continue
            key=path_key(path)
            rows[key]={**inst.model_dump(mode='json'),'reference_path':[p.model_dump(mode='json') for p in path],
                       'qualified_name':path_label(path)}
            segment=path[-1]
            if inst.member_count!=1 or (segment.member,segment.row,segment.column)!=(0,0,0):
                # The snapshot contains instance-wide terminal aggregates, not
                # occurrence-indexed array connectivity. Repeating terminal bit
                # zero for every bound member is false reference information.
                # Keep the native aggregate expression; never parse bus names
                # or substitute Layout nets to invent a schematic member net.
                for terminal in rows[key]['terminals'].values():
                    terminal['members']={};terminal['member_signals']={}
                rows[key].update(reference_nets=[],reference_nets_status='aggregate_only',
                    terminals_scope='instance_aggregate')
                continue
            nets=[]
            for term in inst.terminals.values():
                for member,net in (term.members or {term.name:term.net}).items():
                    owner,canonical=reference_net(context,path[:-1],net)
                    nets.append({'terminal':term.name,'member':member,'net':canonical,
                                 'scope_path':[p.model_dump(mode='json') for p in owner]})
            rows[key]['reference_nets']=nets
            rows[key]['reference_nets_status']='resolved'
    return [rows[key] for key in sorted(rows)]

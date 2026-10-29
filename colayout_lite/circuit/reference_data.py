"""UI-only reference projection; preserve native paths, values and binding identities."""
from collections import defaultdict
from .hierarchy import path_key,path_label


def endpoint_rows(terminals,connections=None):
    result=[];connections=connections or {}
    for port in terminals.values():
        name=port['name'];net=port['net'];direction=port.get('direction') or '未提供'
        def row(label,value):
            return (label,direction,value if value is not None else '未连接',
                    ', '.join(connections.get(value,())) if value is not None else '')
        result.append(row(name,net))
        members=port.get('members') or {}
        if members and (len(members)>1 or next(iter(members))!=name):
            result.extend(row(name+' / '+member,value) for member,value in members.items())
    return result


def instance_records(workspace,data):
    # Index each binding once. Two paths reaching the same occurrence do not
    # duplicate a physical instance; separate layout UIDs remain separate.
    targets=defaultdict(dict)
    for binding in workspace.circuit.bindings:
        layout=workspace.layout_connectivity.instances[binding.layout_uid]
        for path in binding.schematic_paths:
            for depth,segment in enumerate(path):
                key=(path_key(path[:depth]),segment.instance)
                targets[key][layout.uid]=(layout.name+(' [黑盒]' if layout.black_box else ''),layout.uid)
    records=[]
    def add(instances,prefix,source,ports):
        for name,instance in instances.items():
            records.append({'label':(path_label(prefix)+'/' if prefix else '')+name,
                'instance':instance,'path':prefix,'source':source,'ports':ports,
                'targets':tuple(targets.get((path_key(prefix),name),{}).values())})
    add(data['instances'],(),data['source'],data['ports'])
    for scope in sorted(workspace.circuit.hierarchy,key=lambda s:len(s.path)):
        add({name:inst.model_dump(mode='json') for name,inst in scope.instances.items()},scope.path,
            scope.source.model_dump(mode='json'),{name:port.model_dump(mode='json') for name,port in scope.ports.items()})
    return records

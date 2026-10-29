"""Display heuristics and version guards; never edit device internals."""
from copy import deepcopy
from .model import digest

def node_info(node):return dict(node[11] or []) if len(node)>11 else {}

def child_count(node):
    info=node_info(node)
    return int(info['child_count']) if 'child_count' in info else sum(c[2] in ('inst','mosaic') for c in node[10] or [])

def effective_mode(node,requested='auto'):
    return ('box_pins' if child_count(node)>0 else 'full') if requested=='auto' else requested

def is_hierarchical_instance(workspace, obj):
    """Use the imported hierarchy behind the canvas's automatic box/PIN view.

    A leaf PCell is an ordinary device. Display overrides and temporary peeking
    are presentation choices, never permission to waive ordinary geometry.
    Missing hierarchy evidence must not silently exclude an instance.
    """
    if obj.kind not in ('inst', 'mosaic'):
        return False
    node = workspace.baseline.display.get('nodes', {}).get(obj.attributes.get('master_key'))
    if node is not None:
        return child_count(node) > 0
    layout = workspace.layout_connectivity
    instance = layout.instances.get(obj.uid) if layout else None
    return bool(instance and instance.black_box)

def protected_rows(snapshot):
    if snapshot.protected_dependencies is not None:return snapshot.protected_dependencies
    nodes=snapshot.display.get('nodes',{});keys=set()
    def walk(key):
        if key in keys:return
        keys.add(key)
        for child in nodes.get(key,[None]*10+[[]])[10] or []:walk(child[1])
    for obj in snapshot.objects.values():
        if obj.kind in ('inst','mosaic') and obj.attributes.get('master_key'):walk(obj.attributes['master_key'])
    rows=[d for d in snapshot.dependencies if d[0] in keys]
    return rows if {d[0] for d in rows}==keys else None

def same_dependencies(a,b):
    if a.dependency_scheme==b.dependency_scheme=='geometry':return a.dependency_digest==b.dependency_digest
    ra,rb=protected_rows(a),protected_rows(b)
    if ra is None or rb is None:return False
    return digest(sorted(ra))==digest(sorted(rb))

def merge_fragment(display,fragment):
    result={**display,'nodes':{**display['nodes'],**{n[0]:n for n in fragment[4]}},
            'expanded_roots':list(dict.fromkeys(display.get('expanded_roots',[])+[fragment[3]]))}
    styles=dict(display['styles']);styles.update(dict(fragment[5]));result['styles']=list(styles.items())
    result['unsupported']=display.get('unsupported',[])+([u for u in fragment[6] or [] if u not in display.get('unsupported',[])] if len(fragment)>6 else [])
    return result

def retain_display(old,new):
    if not same_dependencies(old,new):return new
    roots=[k for k in old.display.get('expanded_roots',[]) if k in new.display['nodes']]
    if not roots:return new
    selected={}
    def walk(key):
        if key in selected:return
        node=old.display['nodes'][key];selected[key]=node
        for child in node[10] or []:walk(child[1])
    for key in roots:walk(key)
    selected.pop(new.display['root'],None)
    styles=dict(old.display['styles']);styles.update(dict(new.display['styles']))
    display={**new.display,'nodes':{**new.display['nodes'],**selected},'styles':list(styles.items()),'expanded_roots':roots,
             'unsupported':new.display.get('unsupported',[])+[u for u in old.display.get('unsupported',[]) if u not in new.display.get('unsupported',[])]}
    return new.model_copy(update={'display':display})

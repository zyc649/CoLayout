"""Expose only leaf gate/well access material; native modules stay opaque.

Metals enter through real PINs or a geometrically proven N-well contact
landing, not arbitrary device-internal routing. AA/implant/cut rows are evidence.
"""
from .conduction_rules import ConductionRules
from .materials import Physical,polygon_from_figure,placement_delta,apply_delta
from .scene import figures_by_owner
from .editor import projected
from shapely.geometry import box
from .hierarchy import node_info,child_count
from collections import defaultdict


def default_access_projection(workspace,profile,physical):
    """Apply the same native GT/NW boundary to the legacy whole-document check."""
    rules=ConductionRules(profile)
    if not rules.gates and not rules.wells:return physical,[]
    from .inspection_data import pins_for_view
    objects=projected(workspace);uids={u for u,o in objects.items() if o.kind in ('inst','mosaic')}
    pins,warnings=pins_for_view(workspace,profile,uids,[],include_top=False)
    access,problems=leaf_access_material(workspace,profile,uids,pins)
    rows=[r for r in physical if not r.inside_instance or r.layer not in rules.access_layers]
    rows+=access
    for pin in pins:
        rows.extend(Physical(pin['owner'],layer,g,True) for layer,g in pin['figures'] if layer in rules.gates|rules.wells)
    return rows,warnings+problems


def leaf_access_material(workspace,profile,uids,pins):
    rules=ConductionRules(profile)
    if not rules.gates and not rules.wells:return [],[]
    # NW follows a proved tap. GT only extends an actual GT PIN on its own
    # layer; a metal PIN never acquires GT material via a Gate contact.
    candidates={pin['owner'] for pin in pins if not pin['local']}
    selected=set();warnings=[]
    for uid in candidates & set(uids):
        obj=workspace.baseline.objects.get(uid)
        if not obj or obj.kind not in ('inst','mosaic'):continue
        inst=workspace.layout_connectivity.instances.get(uid) if workspace.layout_connectivity else None
        node=workspace.baseline.display.get('nodes',{}).get(obj.attributes.get('master_key'))
        if inst and inst.black_box or node and child_count(node)>0:continue
        if node is None or node_info(node).get('collapsed'):
            warnings.append({'kind':'access_geometry_missing','uid':uid,'message':'GT/NW 接入检查缺少器件几何缓存，请显式刷新。'});continue
        selected.add(uid)
    if not selected:return [],warnings
    # Connectivity does not need DRC widths/skeletons. Decode only contact
    # evidence and conductors, using the same exact native geometry decoder.
    figures,_=figures_by_owner(workspace.baseline,owner_filter=selected,modes={u:'full' for u in selected})
    objects=projected(workspace);rows=[];problems=[]
    for uid in selected:
        delta=placement_delta(workspace.baseline.objects[uid].placement,objects[uid].placement)
        if not figures.get(uid):problems.append({'kind':'access_geometry_missing','uid':uid,'message':'器件内部几何缓存为空。'})
        for f in figures.get(uid,[]):
            layer=(f.get('lpp') or [f.get('style','').split('/')[0]])[0]
            if layer not in rules.access_layers|rules.metals:continue
            if f.get('geometry',{}).get('opaque_type') or f.get('interface'):
                problems.append({'kind':'access_geometry_missing','uid':uid,'layer':layer});continue
            if f['kind'] not in ('rect','polygon','path','pathSeg'):
                if f['kind'] not in ('label','textDisplay'):problems.append({'kind':'access_geometry_unsupported','uid':uid,'layer':layer,'figure_kind':f['kind']})
                continue
            g=box(*f['bbox'][0],*f['bbox'][1]) if f['kind']=='rect' else polygon_from_figure(f)
            if delta!=(1,0,0,1,0,0):g=apply_delta(g,delta)
            if not g.is_empty:rows.append(Physical(uid,layer,g,True))
    from .conduction_contacts import contact_links
    by_owner=defaultdict(list);landings=[];cuts=set();domains={};retained=set()
    for row in rows:by_owner[row.owner].append(row)
    for uid,owner_rows in by_owner.items():
        conductive=[r for r in owner_rows if r.layer in rules.conductors]
        nodes=[{'owner':r.owner,'layer':r.layer,'geometry':r.geometry} for r in conductive]
        links,_,_=contact_links(owner_rows,nodes,rules,{},contacts=rules.access_rules,evidence_cuts=cuts)
        used={i for a,b,g,details in links for i in (a,b) if nodes[i]['layer'] in rules.metals}
        from .conduction_domains import access_domains
        master=workspace.baseline.display['nodes'][workspace.baseline.objects[uid].attributes['master_key']]
        allowed,domains[uid]=access_domains(nodes,links,used,[pin for pin in pins if pin['owner']==uid],master,rules)
        retained.update(id(conductive[i]) for i in allowed)
        landings.extend(conductive[i] for i in sorted(used & allowed))
    cut_layers={r.cut for r in rules.access_rules}
    def relevant_cut(row):
        parts=[row.geometry] if row.geometry.geom_type=='Polygon' else row.geometry.geoms
        return any((row.owner,row.layer,g.wkb) in cuts and domains[row.owner](g) for g in parts)
    return [r for r in rows if r.layer in rules.access_layers and
            (r.layer not in rules.conductors or id(r) in retained) and
            (r.layer not in cut_layers or relevant_cut(r))]+landings,warnings+problems

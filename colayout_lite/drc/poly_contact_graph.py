"""Temporary Poly-contact evidence. Never changes the normal connectivity graph."""
from collections import defaultdict
from shapely import STRtree
from .models import Region
from ..model import MAX_DBU
from ..materials import extract,Physical
from ..editor import projected
from ..conduction_rules import ConductionRules,ContactRule
from ..conduction_contacts import contact_links
from ..physical_connectivity import _UnionFind,_touches_conductively
from ..inspection_data import pins_for_view
from ..regions.query import children


class PatchRules(ConductionRules):
    def __init__(self,technology):
        super().__init__(technology)
        grouped=defaultdict(list)
        for name,d in technology.vias.items():
            a,b,cut=(d.get(k) for k in ('layer1','layer2','cut_layer'))
            if d.get('kind')!='stdViaDef' or d.get('cut_pattern') or not cut:continue
            if a in self.gates and b in self.metals:pair=(a,b)
            elif b in self.gates and a in self.metals:pair=(b,a)
            else:continue
            required=frozenset(pair)|frozenset(d.get(k) for k in ('implant1','implant2') if d.get(k))
            grouped[(pair,cut,required)].append(name)
        self.contacts=tuple(r for r in self.contacts if r.kind=='metal_via')+tuple(
            ContactRule(tuple(names),cut,pair,required,frozenset((pair[0],)),frozenset(),'poly_contact')
            for (pair,cut,required),names in grouped.items())
        self.conductors=self.metals|self.gates
        self.cut_layers={r['layer'] for r in technology.layers if r.get('material')=='cut'}


def nodes_from(rows,rules):
    return [{'owner':r.owner,'layer':r.layer,'geometry':g} for r in rows if r.layer in rules.conductors
            for g in ([r.geometry] if r.geometry.geom_type=='Polygon' else getattr(r.geometry,'geoms',()))
            if g.geom_type=='Polygon' and not g.is_empty]


class Index:
    def __init__(self,nodes):
        self.nodes=nodes;self.layers=defaultdict(list)
        for i,n in enumerate(nodes):self.layers[n['layer']].append(i)
        self.trees={l:STRtree([nodes[i]['geometry'] for i in ids]) for l,ids in self.layers.items()}

    def hits(self,layer,geometry):
        if layer not in self.trees:return ()
        return (self.layers[layer][int(i)] for i in self.trees[layer].query(geometry,predicate='intersects'))


def join(nodes,rows,rules,objects,checkpoint,*,cross_poly=True):
    index=Index(nodes);uf=_UnionFind(len(nodes))
    for i,n in enumerate(nodes):
        checkpoint()
        for j in index.hits(n['layer'],n['geometry']):
            if not cross_poly and n['layer'] in rules.gates and n['owner']!=nodes[j]['owner']:continue
            if j>i and _touches_conductively(n['geometry'],nodes[j]['geometry']):uf.join(i,j)
    links,warnings,_=contact_links(rows,nodes,rules,objects)
    for a,b,g,detail in links:uf.join(a,b)
    cuts={d.get('cut_layer') for d in rules.definitions.values()}|getattr(rules,'cut_layers',set())
    for row in rows:
        if row.layer not in cuts:continue
        gates={l for l in rules.gates if any(nodes[i]['geometry'].intersection(row.geometry).area>0 for i in index.hits(l,row.geometry))}
        metals={l for l in rules.metals if any(nodes[i]['geometry'].intersection(row.geometry).area>0 for i in index.hits(l,row.geometry))}
        # An unrelated upper metal may overlap the same XY footprint. Once
        # this cut has a declared Poly-to-present-metal pair, those other
        # layers do not imply an additional missing contact definition.
        if metals and any(not any(r.cut==row.layer and g in r.layers and (set(r.layers)-{g})<=metals
                                 for r in rules.contacts) for g in gates):
            warnings.append({'kind':'unknown_poly_contact_mapping','owner_uid':row.owner,'cut_layer':row.layer,'bbox':row.geometry.bounds})
    return uf,index,warnings


def build(w,p,allowed,scope,checkpoint):
    rules=PatchRules(p);objects=projected(w)
    rows,_,warnings,_,_=extract(w,p,Region(bbox=((-MAX_DBU,-MAX_DBU),(MAX_DBU,MAX_DBU))),0,
                              checkpoint,owner_filter=allowed)
    leaf={u for u in allowed if objects[u].kind in ('inst','mosaic')}
    region_ids=[r.id for r in children(w,scope)]+([scope] if scope else [])
    visible=set(allowed)|set(scope_native(w,scope))
    pins,pin_warnings=pins_for_view(w,p,visible,region_ids,include_top=scope is None)
    by_owner=defaultdict(list)
    for row in rows:by_owner[row.owner].append(row)
    retained=[];domains={};problems=defaultdict(list)
    for uid in sorted(leaf):
        checkpoint()
        material=by_owner[uid];nodes=nodes_from(material,rules)
        uf,index,contact_warnings=join(nodes,material,rules,objects,checkpoint)
        master=w.baseline.display.get('nodes',{}).get(objects[uid].attributes.get('master_key'))
        intrinsic={r[0]:r[2] for r in master[8] or []} if master and len(master)>8 else {}
        labels=defaultdict(set);pin_ids=defaultdict(set)
        for pin in pins:
            if pin['owner']!=uid:continue
            terminal=intrinsic.get(pin['name']) or pin['name']
            for layer,g in pin['figures']:
                for i in index.hits(layer,g):
                    if nodes[i]['geometry'].intersection(g).area>0:
                        root=uf.find(i);labels[root].add(terminal);pin_ids[root].add(pin['id'])
        owner_domains=[]
        for i,node in enumerate(nodes):
            root=uf.find(i)
            safe=len(labels[root])==1 and objects[uid].kind!='mosaic'
            if safe:retained.append(node)
            if node['layer'] in rules.gates:
                owner_domains.append((node['layer'],node['geometry'],safe,sorted(labels[root]),sorted(pin_ids[root])))
        domains[uid]=owner_domains
        problems[uid].extend(contact_warnings)
    for row in rows:
        if row.owner not in leaf:retained.extend(nodes_from([row],rules))
    # PIN figures are real material boundaries; never bridge an intrinsic
    # multi-terminal element through its body. Local markers only label material.
    for pin in pins:
        if pin['local']:continue
        for layer,g in pin['figures']:
            if layer in rules.conductors:
                retained.extend(nodes_from([Physical(pin['owner'] or pin['id'],layer,g)],rules))
    # Prove contacts again over only retained material, so removed intrinsic
    # regions cannot supply a hidden bridge between PIN islands.
    evidence=[r for r in rows if r.layer not in rules.conductors]
    evidence += [Physical(n['owner'],n['layer'],n['geometry']) for n in retained]
    # Keep candidate cross-device Poly edges out while locating conflicts.
    # Otherwise one true short contaminates every legal shared gate on its net.
    # Every allowed device island has one native terminal domain; comparing
    # each candidate's two incident components also checks longer Poly chains.
    uf,index,contact_warnings=join(retained,evidence,rules,objects,checkpoint,cross_poly=False)
    labels=defaultdict(set);attached=defaultdict(dict);unknown=defaultdict(list)
    for pin in pins:
        for layer,g in pin['figures']:
            for i in index.hits(layer,g):
                if retained[i]['geometry'].intersection(g).area<=0:continue
                root=uf.find(i)
                attached[root][pin['id']]={'id':pin['id'],'owner':pin['owner'],'name':pin['name'],
                    'display_name':pin.get('display_name',pin['label']),'net':pin['net']}
                if pin['net'] is None:unknown[root].append({'kind':'unassigned_pin','pin_id':pin['id']})
                else:labels[root].add(pin['net'])
    for warning in warnings+pin_warnings:
        uid=warning.get('uid') or warning.get('owner') or warning.get('owner_uid')
        if uid:problems[uid].append(warning)
    for warning in contact_warnings:
        uid=warning.get('owner') or warning.get('owner_uid')
        if uid:problems[uid].append(warning)
    return {'nodes':retained,'uf':uf,'index':index,'nets':labels,'pins':attached,
            'unknown':unknown,'domains':domains,'problems':problems}


def scope_native(w,scope):
    from ..regions.query import owner_map
    from ..hierarchy import is_hierarchical_instance
    owners=owner_map(w)
    return [u for u,o in projected(w).items() if owners.get(u)==scope and is_hierarchical_instance(w,o)]

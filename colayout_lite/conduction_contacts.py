"""Prove contact edges from actual geometry and imported standard definitions."""
from collections import defaultdict
from shapely import STRtree
from shapely.ops import unary_union


def contact_links(rows,nodes,rules,objects,*,contacts=None,evidence_cuts=None):
    """Return node-index edges; no net names participate in physical proofs."""
    by_layer=defaultdict(list)
    for row in rows:by_layer[row.layer].append(row.geometry)
    trees={layer:STRtree(gs) for layer,gs in by_layer.items()};unions={}
    indexes=defaultdict(list)
    for i,n in enumerate(nodes):indexes[n['layer']].append(i)
    node_trees={l:STRtree([nodes[i]['geometry'] for i in ids]) for l,ids in indexes.items()}
    cut_hits={}
    def hits(layer,g):
        if layer in cut_hits:return cut_hits[layer]
        if layer not in trees:return ()
        cut_hits[layer]=tuple(sorted(int(i) for i in trees[layer].query(g,predicate='intersects') if by_layer[layer][int(i)].intersection(g).area>0))
        return cut_hits[layer]
    def covers(layer,g):
        ids=hits(layer,g)
        if not ids:return False
        key=(layer,ids)
        if key not in unions:unions[key]=by_layer[layer][ids[0]] if len(ids)==1 else unary_union([by_layer[layer][i] for i in ids])
        return unions[key].covers(g)
    def node_hits(layer,g):
        if layer not in node_trees:return []
        return [indexes[layer][int(i)] for i in node_trees[layer].query(g,predicate='intersects') if nodes[indexes[layer][int(i)]]['geometry'].intersection(g).area>0]
    links=[];warnings=[];count=0;by_cut=defaultdict(list)
    for r in rules.contacts if contacts is None else contacts:by_cut[r.cut].append(r)
    seen=set()
    for row in rows:
        if row.layer not in by_cut:continue
        for g in ([row.geometry] if row.geometry.geom_type=='Polygon' else row.geometry.geoms):
            if g.geom_type!='Polygon' or g.is_empty:continue
            cut_hits={}
            key=(row.owner,row.layer,g.wkb)
            if key in seen:continue
            seen.add(key);obj=objects.get(row.owner)
            explicit=obj.shape.via_definition if obj and obj.kind=='stdVia' else None
            candidates=[r for r in by_cut[row.layer] if rules.accepts_definition(r,explicit)]
            active=[];matched=[]
            # Keep ambiguous metal-only cut mappings fail-closed, as before.
            if explicit is None and len({r.layers for r in candidates if r.kind=='metal_via'})>1:
                warnings.append({'kind':'ambiguous_via_cut_layer','layer':row.layer,'owner':row.owner});continue
            for r in candidates:
                if r.kind!='metal_via' and explicit not in r.names and not all(hits(l,g) for l in r.trigger):continue
                if evidence_cuts is not None:evidence_cuts.add(key)
                blocked=[l for l in r.forbidden if hits(l,g)] if r.kind!='metal_via' else []
                if blocked:
                    warnings.append({'kind':'unsupported_contact_environment','owner_uid':row.owner,'cut_layer':row.layer,
                        'bbox':g.bounds,'conflicting_layers':sorted(blocked),'definitions':list(r.names)})
                    continue
                active.append(r)
                if all(covers(l,g) for l in r.required):matched.append(r)
            endpoints={r.layers for r in matched}
            if len(endpoints)>1:
                warnings.append({'kind':'ambiguous_contact','owner_uid':row.owner,'cut_layer':row.layer,'bbox':g.bounds,'pairs':sorted(endpoints)});continue
            if not matched:
                if active:
                    warnings.append({'kind':'uncovered_via_cut' if all(r.kind=='metal_via' for r in active) else 'incomplete_access_contact',
                        'owner_uid':row.owner,'cut_layer':row.layer,'bbox':g.bounds,
                        'required_layers':sorted(set().union(*(r.required for r in active))),
                        'missing_layers':sorted({l for r in active for l in r.required if not covers(l,g)})})
                continue
            r=matched[0];a,b=r.layers
            for i in node_hits(a,g):
                for j in node_hits(b,g):links.append((i,j,g,{'layers':[a,b],'cut_layer':row.layer,'via_owner_uid':row.owner,'contact_kind':r.kind,'definitions':list(r.names),'definition_name':explicit}))
            count+=1
    return links,warnings,count

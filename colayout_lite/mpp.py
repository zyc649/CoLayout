"""Native MPP boundary: collapse only true ROD membership, never spatial guesses."""
from collections import Counter
from .model import MultipartPath,Placement,LiteError
from .geometry import transform,compose,box,transform_shape,ORIENT

PART_KEYS=('name','kind','lpp','choppable','net_name','terminal_name','width_um','length_um','enclosure_um','separation_um','justification','begin_offset_um','end_offset_um','begin_segment_offset_um','end_segment_offset_um','space_um','gap','diagonal')

def part_records(rows):
    result=[]
    for row in rows or []:
        p=dict(zip(PART_KEYS,row))
        for key,value in p.items():
            if key.endswith('_um') and value is not None:p[key]=float(value)
        result.append(p)
    return result


def collapse(objects,rows):
    physical=dict(objects);owners={o.native_id:uid for uid,o in physical.items()};result=dict(objects)
    for row in rows or []:
        data=dict(row);master_id=data['master'];uid=owners[master_id];o=physical[uid]
        members=[owners[n] for n in data['members']];children=[physical[k] for k in members]
        # Geometry/counts are checked independently from ephemeral child DB IDs.
        counts=Counter('/'.join([v.kind,*(v.native_row[3] or [])]) for v in children)
        reason=data['restriction'] or ('missing_persistent_identity' if uid.startswith('session:') else None)
        if o.shape is None:reason=reason or 'mpp_unsupported_master'
        body=MultipartPath(master=o.shape,opaque_master=o.attributes if o.shape is None else {},name=data['name'] or '',parts=part_records(data['parts']),choppable=bool(data['choppable']),
            chopped=bool(data['chopped']),member_counts=dict(counts),member_native_ids=data['members'],member_uids=members,
            member_routes={v.uid:v.route_uid for v in children if v.route_uid},native_definition=data['definition'])
        bounds=[v.bbox for v in children if v.bbox]
        bbox=((min(b[0][0] for b in bounds),min(b[0][1] for b in bounds)),(max(b[1][0] for b in bounds),max(b[1][1] for b in bounds))) if bounds else o.bbox
        anchor=o.shape.points[0] if o.shape and o.shape.points else (0,0)
        for k in members:result.pop(k,None)
        result[uid]=o.model_copy(update={'kind':'mpp','shape':None,'mpp':body,'bbox':bbox,'group_uid':None,
            'placement':Placement(origin=anchor),'read_only_reason':reason,'deletion_allowed':bool(data['delete_allowed']) and not uid.startswith('session:'),
            'route_uid':None,'attributes':{'name':data['name'] or 'MPP','form':'guardring' if o.shape and o.shape.points[0]==o.shape.points[-1] else 'multipart_path'}})
    return result


def delta(before,after):
    a,b,c,d=ORIENT[before.orientation];x,y=before.origin
    return compose(transform(after.origin,after.orientation),(a,c,b,d,-a*x-c*y,-b*x-d*y))


def placed(obj,placement):
    tr=delta(obj.placement,placement);orient=next(k for k,v in ORIENT.items() if v==tr[:4])
    if obj.mpp.master is None:raise LiteError('MPP_MASTER_UNSUPPORTED')
    body=obj.mpp.model_copy(update={'master':transform_shape(obj.mpp.master,orientation=orient,delta=tr[4:])})
    return obj.model_copy(update={'placement':placement,'mpp':body,'bbox':box(obj.bbox,tr) if obj.bbox else None})

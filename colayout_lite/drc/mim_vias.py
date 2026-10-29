"""Block ordinary independent vias whose cuts land on a configured MIM plate."""
from shapely.geometry import box
from shapely.ops import unary_union
from shapely.strtree import STRtree
from ..geometry import via_figures
from ..model import digest
from .models import Marker


def run(w,technology,settings,physical,objects,allowed,roi,*,checkpoint=lambda:None,limit=10000):
    coverage={'status':settings.status,'checked_vias':0,'truncated':False}
    if settings.status!='configured':return [],coverage
    masks=[r for r in physical if (r.layer,r.purpose)==settings.lpp]
    if not masks:return [],coverage
    tree=STRtree([r.geometry for r in masks]);markers=[]
    pair={settings.lower_metal,settings.upper_metal}
    for uid in sorted(allowed):
        checkpoint();obj=objects[uid]
        # Only top-level native/editor stdVia objects, never figures inside PCells.
        shape=obj.shape
        if not shape or shape.kind!='stdVia':continue
        via=technology.vias[shape.via_definition]
        if {via.get('layer1'),via.get('layer2')}!=pair:continue
        figures=via_figures(shape,technology)
        cuts=[box(*f['bbox'][0],*f['bbox'][1]) for f in figures if f['lpp'][0]==via['cut_layer']]
        if not any(c.intersects(roi) for c in cuts):continue
        coverage['checked_vias']+=1;overlaps=[];owners=set();hit_cuts=0
        for cut in cuts:
            checkpoint();hit=False
            for i in tree.query(cut):
                mask=masks[int(i)];overlap=cut.intersection(mask.geometry).intersection(roi)
                # Boundary touching and metal enclosure overlap alone are not a hit.
                if overlap.area>1e-6:
                    hit=True;overlaps.append(overlap);owners.add(mask.owner)
            hit_cuts+=hit
        if not overlaps:continue
        if len(markers)>=limit:coverage['truncated']=True;continue
        overlap=unary_union(overlaps);x,y,xx,yy=overlap.bounds
        refs=[{'uid':uid,'kind':obj.kind,'name':obj.attributes.get('name'),'inside_instance':False}]
        refs.extend({'uid':owner,'kind':objects[owner].kind,'name':objects[owner].attributes.get('name'),
                     'inside_instance':objects[owner].kind in ('inst','mosaic')} for owner in sorted(owners))
        message=(f'该 {settings.lower_metal}–{settings.upper_metal} 过孔位于 MIM 区域（{settings.lpp[0]}/{settings.lpp[1]}），'
                 '不能按普通层间导通使用。请将过孔移至 MIM 区外，或采用工艺允许的下层接入方式。')
        markers.append(Marker(id=digest(['mim_via',uid,settings.model_dump(),overlap.wkb_hex])[:24],
            rule_id='MIM_VIA_BLOCKED',message=message,severity='error',kind='box',bbox=((x,y),(xx,yy)),
            layers=(settings.lpp[0],settings.lower_metal,settings.upper_metal,via['cut_layer']),
            objects=tuple(refs),association='local_geometry',
            details={'category':'mim_via_contact','via_uid':uid,'via_definition':shape.via_definition,
                     'mim_lpp':settings.lpp,'metal_pair':[settings.lower_metal,settings.upper_metal],
                     'overlapping_cuts':hit_cuts,'mim_owners':sorted(owners),'source':settings.source}))
    return markers,coverage

"""Project shared native master caches to a local, selectable display scene."""
from copy import deepcopy
from collections import defaultdict
import math
from .display_data import decode_display
from .geometry_memo import GeometryMemo
_decoded_nodes=GeometryMemo(sources=4,entries=128)
from .geometry import transform,compose,point,box,ORIENT
from .hierarchy import effective_mode,node_info


def figures_by_owner(snapshot, *, display=None, objects=None, modes=None, limit=500000, owner_filter=None,include_styles=True):
    display=display or snapshot.display;objects=objects or snapshot.objects
    nodes=display['nodes'];root=display['root'];owners={o.native_id:uid for uid,o in objects.items()}
    for uid,obj in objects.items():
        if obj.mpp:owners.update({ident:uid for ident in obj.mpp.member_native_ids})
    decoded={}
    if include_styles:
        styles=deepcopy(_decoded_nodes.get(display,('styles',),lambda:decode_display(['colayout-display-0.1',snapshot.session,'',snapshot.counter,[[0,0],[0,0]],[],display['styles'],[]])['styles']))
    else:
        # Physical extraction needs layer identity/cut role, not thousands of
        # copied stipple cells and display colors. Figure decoding is identical.
        styles={key:{'lpp':tuple(row[0]),'is_cut':row[4]=='cut'} for key,row in (display['styles'] or [])}
    def node_figures(key):
        if key not in decoded:
            node=nodes[key]
            raw=['colayout-display-0.1',snapshot.session,key,snapshot.counter,node[5] or [[0,0],[0,0]],node[9] or [],[],[]]
            decoded[key]=_decoded_nodes.get(display,('figures',key),lambda:decode_display(raw,known_styles=styles)['figures'])
        return decoded[key]
    out=defaultdict(list);count=0
    modes=modes or {}
    def special(key,color,priority):
        styles[key]=dict(lpp=['Colayout',key],priority=priority,outline_rgb=color,fill_rgb=color,fill_style='outline',stipple=[],line_width=1,line_pattern=[1],is_cut=False,definition_found=True)
    special('__module_frame__',[111,157,202],100000)
    special('__pin_name__',[255,235,150],100010)
    def emit(f,uid):
        nonlocal count
        count+=1
        if count>limit:raise ValueError('显示超过500000图元，请收起部分模块；不会返回残缺画面。')
        out[uid].append(f)
    def interface(key,tr,uid,path):
        node=nodes[key];bounds=box([[float(v) for v in p] for p in node[5]],tr) if node[5] else None
        if bounds:
            emit(dict(id=uid+':frame:'+str(len(out[uid])),owner_id=uid,inside_instance=False,interface=True,kind='rect',style='__module_frame__',bbox=bounds,geometry={}),uid)
            height=max(50,min(24*snapshot.dbu_per_micron,min(bounds[1][0]-bounds[0][0],bounds[1][1]-bounds[0][1])*.06))
            title=objects[uid].attributes.get('name',node[2])+' · Virtuoso';width=max(height,len(title)*height*.6)
            bb=[[bounds[0][0],bounds[1][1]-height],[bounds[0][0]+width,bounds[1][1]]]
            emit(dict(id=uid+':title:'+str(len(out[uid])),owner_id=uid,interface=True,inside_instance=False,kind='label',style='__module_frame__',bbox=bb,geometry={'text':title,'orientation':'R0','height':height}),uid)
        source=node_figures(key);labelled=set()
        for name,direction,net,groups in node[8] or []:
            for group in groups or []:
                for raw in group:
                    found=[f for f in source if f['owner_id']==raw[0] and f['kind'] not in ('label','textDisplay')]
                    for original in found:
                        f=project(original,tr,uid,path);f['interface']=True;f['inside_instance']=False;f['pin_name']=name;emit(f,uid)
                    if raw[2]:
                        bb=box([[float(v) for v in p] for p in raw[2]],tr)
                        if not found:
                            key_style='/'.join(raw[3]) if raw[3] else '__module_frame__'
                            if key_style not in styles:key_style='__module_frame__'
                            emit(dict(id=uid+':pin:'+str(len(out[uid])),owner_id=uid,interface=True,inside_instance=False,kind='rect',style=key_style,bbox=bb,geometry={},pin_name=name),uid)
                        if name in labelled:continue
                        labelled.add(name)
                        size=max(50,min(6*snapshot.dbu_per_micron,(min(bounds[1][0]-bounds[0][0],bounds[1][1]-bounds[0][1])*.025 if bounds else 100)))
                        x=(bb[0][0]+bb[1][0])/2;y=(bb[0][1]+bb[1][1])/2
                        emit(dict(id=uid+':pin-label:'+str(len(out[uid])),owner_id=uid,interface=True,inside_instance=False,kind='label',style='__pin_name__',bbox=[[x,y],[x+size*.6*len(name),y+size]],geometry={'text':name,'orientation':'R0','height':size}),uid)
    def project(original,tr,uid,path):
        scale=math.hypot(tr[0],tr[2]);f=dict(original);f['geometry']=dict(original['geometry']);f['owner_id']=uid;f['occurrence_path']=list(path)
        f['inside_instance']=objects[uid].kind in ('inst','mosaic')
        f['bbox']=box(f['bbox'],tr);g=f['geometry']
        if 'points' in g:g['points']=[point(p,tr) for p in g['points']]
        if 'boundary' in g:g['boundary']=[point(p,tr) for p in g['boundary']]
        if 'xy' in g:g['xy']=point(g['xy'],tr)
        for name in ('width','height','begin_extension','end_extension'):
            if name in g:g[name]*=scale
        if 'orientation' in g:
            parent=tuple(round(v/scale) for v in tr[:4]);local=ORIENT[g['orientation']]
            combined=compose(parent+(0,0),local+(0,0))[:4]
            g['orientation']=next(k for k,v in ORIENT.items() if v==combined)
        return f
    def walk(key,tr,owner=None,path=(),depth=0):
        nonlocal count
        if depth>24:raise ValueError('Display hierarchy depth exceeded')
        node=nodes[key];scale=math.hypot(tr[0],tr[2])
        for original in node_figures(key):
            uid=owner or owners.get(original['owner_id'])
            if uid is None or (owner_filter is not None and uid not in owner_filter):continue
            emit(project(original,tr,uid,path),uid)
        if owner is not None:
            children_ids={c[0] for c in node[10] or []}
            for row in node[6] or []:
                if row[1] in ('inst','mosaic') and row[0] not in children_ids and row[2]:
                    emit(dict(id=row[0]+':unavailable',owner_id=owner,inside_instance=True,kind='rect',style='__module_frame__',bbox=box([[float(v) for v in p] for p in row[2]],tr),geometry={'opaque_type':'missing/unsupported master'}),owner)
        for child in node[10] or []:
            uid=owner or owners.get(child[0])
            if uid is None or (owner_filter is not None and uid not in owner_filter):continue
            child_node=nodes[child[1]]
            local=transform(tuple(map(float,child[3])),child[4],float(child[5])*float(node[4])/float(child_node[4]))
            occurrence={'native_instance':child[0],'master':child[1],'kind':child[2],
                        'origin':child[3],'orientation':child[4]}
            if len(child)>6:occurrence['array_index']=child[6]
            combined=compose(tr,local);newpath=path+(occurrence,)
            if owner is None and child[2] in ('inst','mosaic') and (effective_mode(child_node,modes.get(uid,'auto'))=='box_pins' or node_info(child_node).get('collapsed')):
                interface(child[1],combined,uid,newpath)
            else:walk(child[1],combined,uid,newpath,depth+1)
    walk(root,(1,0,0,1,0,0))
    return dict(out),styles or {}

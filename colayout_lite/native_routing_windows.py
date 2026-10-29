"""Object-scoped metal corridors. Native geometry and PINs remain opaque/read-only."""
from uuid import uuid4
from shapely.geometry import box as polygon_box
from shapely.ops import unary_union
from .geometry import transform,box,ORIENT
from .editor import projected
from .hierarchy import is_hierarchical_instance
from .regions.models import NativeRoutingWindow
from .regions.query import owner_map,object_bounds,metals
from .model import LiteError


def world_bounds(workspace,row,objects=None):
    obj=(projected(workspace) if objects is None else objects)[row.owner_uid]
    return box(row.bbox,transform(obj.placement.origin,obj.placement.orientation))


def local_bounds(obj,bounds):
    a,b,c,d=ORIENT[obj.placement.orientation];x,y=obj.placement.origin
    return box(bounds,(a,c,b,d,-a*x-c*y,-b*x-d*y))


def windows_for(workspace,uid):
    return [row for row in workspace.local_data.native_routing_windows.values() if row.owner_uid==uid]


def blocked_geometry(workspace,uid,layer,bounds,objects=None):
    """Subtract only this owner's enabled windows; other obstacles are untouched."""
    obstacle=polygon_box(*bounds[0],*bounds[1])
    openings=[polygon_box(*b[0],*b[1]) for row in windows_for(workspace,uid)
              if row.enabled and layer in row.layers
              for b in [world_bounds(workspace,row,objects)]]
    return obstacle.difference(unary_union(openings)) if openings else obstacle


def describe(workspace,row,profile,objects=None):
    objects=projected(workspace) if objects is None else objects
    bounds=world_bounds(workspace,row,objects);scale=profile.dbu_per_micron
    owner=object_bounds(workspace,objects[row.owner_uid],profile)
    effective=polygon_box(*bounds[0],*bounds[1]).intersection(polygon_box(*owner[0],*owner[1]))
    return {'id':row.id,'owner_uid':row.owner_uid,'name':row.name,'layers':list(row.layers),
            'note':row.note,'enabled':row.enabled,'bounds_um':[v/scale for pt in bounds for v in pt],
            'effective_bounds_um':[v/scale for v in effective.bounds] if not effective.is_empty else None,
            'coordinates':'workspace_um','follows_owner':True,
            'actions':['set_native_routing_window','delete_native_routing_window']}


def validate(workspace,profile):
    if not workspace.local_data.native_routing_windows:return
    objects=projected(workspace);allowed=set(metals(profile))
    for row in workspace.local_data.native_routing_windows.values():
        obj=objects.get(row.owner_uid)
        if (obj is None or obj.placement is None or not is_hierarchical_instance(workspace,obj)
                or workspace.layout_connectivity is None or row.owner_uid not in workspace.layout_connectivity.instances):
            raise LiteError('NATIVE_WINDOW_OWNER_INVALID','豁免区所属对象必须仍是原生层次模块。',id=row.id,owner_uid=row.owner_uid)
        if not row.layers or set(row.layers)-allowed:
            raise LiteError('UNKNOWN_ROUTING_METAL',id=row.id)
        owner=object_bounds(workspace,obj,profile)
        if owner is None:raise LiteError('OBJECT_BOUNDS_MISSING',row.owner_uid)
        bounds=world_bounds(workspace,row,objects)
        if polygon_box(*bounds[0],*bounds[1]).intersection(polygon_box(*owner[0],*owner[1])).area<=1e-9:
            raise LiteError('NATIVE_WINDOW_OUTSIDE_OWNER','豁免区须覆盖所属原生模块的部分范围。',id=row.id,owner_uid=row.owner_uid)


class NativeRoutingWindows:
    def __init__(self,editor):self.editor=editor

    def target(self,uid):
        e=self.editor;w=e.w;obj=projected(w).get(uid)
        if (obj is None or obj.placement is None or not is_hierarchical_instance(w,obj)
                or w.layout_connectivity is None or uid not in w.layout_connectivity.instances):
            raise LiteError('EXPECTED_NATIVE_MODULE','仅支持 Virtuoso 原生层次模块；普通器件和本地操作区不适用。')
        if owner_map(w).get(uid)!=e.scope_id:raise LiteError('OBJECT_OUTSIDE_REGION','只能设置当前层直属原生模块。')
        e.work_sessions.assert_editable(uid)
        return obj

    def record(self,ident):
        row=self.editor.w.local_data.native_routing_windows.get(ident)
        if row is None:raise LiteError('NATIVE_WINDOW_MISSING',ident)
        self.target(row.owner_uid)
        return row

    def _publish(self,rows):
        from .regions.actions import RegionActions
        RegionActions(self.editor)._publish(native_routing_windows=rows)

    def create(self,uid,bounds,layers,*,name='布线豁免',note='',enabled=True):
        obj=self.target(uid)
        from .regions.actions import RegionActions
        bbox=RegionActions(self.editor).snap_box(bounds)
        row=NativeRoutingWindow(id='native-window-'+uuid4().hex,owner_uid=uid,
            bbox=local_bounds(obj,bbox),layers=tuple(dict.fromkeys(layers)),
            name=name.strip(),note=note,enabled=enabled)
        self._publish({**self.editor.w.local_data.native_routing_windows,row.id:row})
        return row.id

    def update(self,ident,*,bounds=None,layers=None,name=None,note=None,enabled=None):
        row=self.record(ident);changes={}
        if bounds is not None:
            from .regions.actions import RegionActions
            changes['bbox']=local_bounds(self.target(row.owner_uid),RegionActions(self.editor).snap_box(bounds))
        if layers is not None:changes['layers']=tuple(dict.fromkeys(layers))
        if name is not None:changes['name']=name.strip()
        if note is not None:changes['note']=note
        if enabled is not None:changes['enabled']=enabled
        updated=NativeRoutingWindow.model_validate(row.model_copy(update=changes).model_dump())
        self._publish({**self.editor.w.local_data.native_routing_windows,ident:updated})

    def delete(self,ident):
        self.record(ident)
        self._publish({key:row for key,row in self.editor.w.local_data.native_routing_windows.items() if key!=ident})

    def auto_escape(self,uid,width):
        """One publication/undo for all corridors; repeat calls reuse coverage."""
        obj=self.target(uid);e=self.editor
        from .native_pin_escape import plan
        planned,skipped=plan(e.w,e.profile,obj,width)
        rows=dict(e.w.local_data.native_routing_windows);created=[];reused=[];channels=[]
        for channel in planned:
            geometry=polygon_box(*channel['bbox'][0],*channel['bbox'][1])
            existing=next((r for r in rows.values() if r.owner_uid==uid and r.enabled and channel['layer'] in r.layers
                           and polygon_box(*world_bounds(e.w,r)[0],*world_bounds(e.w,r)[1]).covers(geometry)),None)
            if existing is None:
                existing=NativeRoutingWindow(id='native-window-'+uuid4().hex,owner_uid=uid,
                    bbox=local_bounds(obj,channel['bbox']),layers=(channel['layer'],),name=channel['name'])
                rows[existing.id]=existing;created.append(existing.id)
            else:reused.append(existing.id)
            channels.append({'id':existing.id,'terminal':channel['terminal'],'layer':channel['layer'],'side':channel['side']})
        self._publish(rows)
        return {'owner_uid':uid,'created_uids':created,'reused_uids':list(dict.fromkeys(reused)),
                'channels':channels,'skipped':skipped,'native_geometry_changed':False}

    def auto_escape_um(self,uid,width_um):
        from decimal import ROUND_CEILING
        from .actions import number
        value=number(width_um)
        if value<=0:raise LiteError('INVALID_ESCAPE_WIDTH','通道宽度须大于零。')
        p=self.editor.profile
        width=int((value*p.dbu_per_micron/p.grid).to_integral_value(rounding=ROUND_CEILING))*p.grid
        return self.auto_escape(uid,width)

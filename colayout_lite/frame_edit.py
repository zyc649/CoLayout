"""Shared human/Agent frame geometry commands. Membership never changes on resize."""
from .model import LiteError
from .local_models import LocalData
from .editor import projected
from .regions.models import contains,overlaps
from .regions.query import children,owner_map,object_bounds
from .regions.constraints import validate_workspace
from .pin_placement import resized_pins


class FrameEdit:
    def __init__(self,editor):self.editor=editor

    def record(self,ident):
        e=self.editor;local=e.w.local_data
        for field in ('regions','markups','keepouts'):
            row=getattr(local,field).get(ident)
            if row is None:continue
            scope=row.parent_id if field=='regions' else row.scope_id
            if scope!=e.scope_id and not (field=='regions' and ident==e.scope_id):
                raise LiteError('REGION_SCOPE_VIOLATION','只能调整自身操作区、直接子区或当前层的框。')
            e.work_sessions.assert_editable(ident)
            return field,row
        raise LiteError('LOCAL_BOX_MISSING',ident)

    def limits(self,ident):
        """A region cannot shrink past contents; note/keepout boxes have no contents."""
        field,row=self.record(ident)
        if field!='regions':return None
        w=self.editor.w;objects=projected(w);bounds=[]
        for uid in row.object_uids:
            b=object_bounds(w,objects[uid],self.editor.profile)
            if b is None:raise LiteError('OBJECT_BOUNDS_MISSING',uid)
            bounds.append(b)
        bounds += [child.bbox for child in children(w,row.id)]
        bounds += [b.bbox for b in (*w.local_data.markups.values(),*w.local_data.keepouts.values()) if b.scope_id==row.id]
        if not bounds:return None
        return (tuple(min(b[0][i] for b in bounds) for i in (0,1)),tuple(max(b[1][i] for b in bounds) for i in (0,1)))

    def candidate(self,ident,bounds,*,reflow_pins=False):
        field,row=self.record(ident);w=self.editor.w;grid=self.editor.profile.grid
        bbox=tuple(tuple(round(v/grid)*grid for v in p) for p in bounds)
        if any(a>=b for a,b in zip(*bbox)):raise LiteError('FRAME_TOO_SMALL','框必须有正的宽度和高度。')
        changes={'bbox':bbox}
        if field=='regions':
            if row.parent_id and not contains(w.local_data.regions[row.parent_id].bbox,bbox):
                raise LiteError('REGION_OUTSIDE_PARENT','区域不能超出上层边界。')
            if any(other.id!=ident and overlaps(other.bbox,bbox) for other in children(w,row.parent_id)):
                raise LiteError('REGION_PARTIAL_OVERLAP','区域不能与同层模块重叠。')
            limits=self.limits(ident)
            if limits and not contains(bbox,limits):raise LiteError('RESIZE_EXCLUDES_CONTENT','不能把已有成员或内部框裁到区域外。')
            changes.update(pins=resized_pins(row,bbox,grid),revision=row.revision+1,interface_revision=row.interface_revision+1)
            if reflow_pins:
                from .regions.pin_layout import fit_resized_pins
                changes['pins']=fit_resized_pins(row.model_copy(update=changes),self.editor.profile,w.local_data.keepouts.values())
            # Resizing is not another marquee import. Keep outsiders outside.
            owners=owner_map(w)
            for uid,obj in projected(w).items():
                if owners.get(uid)!=row.parent_id or obj.kind not in ('inst','mosaic'):continue
                b=object_bounds(w,obj,self.editor.profile)
                if b and overlaps(bbox,b):raise LiteError('RESIZE_OVERLAPS_OBJECT','扩框不能吞入其他器件。',uid=uid)
        updated=row.model_copy(update=changes)
        values={**getattr(w.local_data,field),ident:updated}
        if field=='regions' and row.parent_id:
            parent=values[row.parent_id];values[parent.id]=parent.model_copy(update={'revision':parent.revision+1})
        local=LocalData.model_validate(w.local_data.model_copy(update={field:values}).model_dump())
        # A geometric box moved into another region follows that region's ID;
        # region membership itself is deliberately unchanged.
        for r in local.regions.values():
            pins=list(r.pins.values())
            if r.id==ident:
                for i,p in enumerate(pins):
                    for other in pins[i+1:]:
                        from .interface_layers import overlaps_layers
                        if overlaps_layers(p,other,self.editor.profile) and overlaps(p.bbox,other.bbox):raise LiteError('INTERFACE_PINS_OVERLAP',p.name+' / '+other.name)
            for p in pins:
                for keep in local.keepouts.values():
                    from .interface_layers import fully_blocked
                    if (r.id==ident or keep.id==ident) and fully_blocked(p,keep.layers,self.editor.profile) and overlaps(p.bbox,keep.bbox):
                        raise LiteError('KEEPOUT_COVERS_FIXED_PIN',p.id)
        candidate=w.model_copy(update={'local_data':local})
        if field=='regions':validate_workspace(candidate,self.editor.profile)
        return candidate

    def resize(self,ident,bounds,*,expected_revision=None):
        e=self.editor;e.check_revision(expected_revision)
        candidate=self.candidate(ident,bounds)
        field,row=self.record(ident)
        if getattr(candidate.local_data,field)[ident].bbox==row.bbox:return e.w
        e.publish(candidate);return e.w

    def tighten(self,ident,*,padding=0,expected_revision=None):
        """Shrink the frame only; preserve membership, mode and native geometry."""
        from math import floor,ceil
        e=self.editor;e.check_revision(expected_revision)
        field,row=self.record(ident)
        if field!='regions':raise LiteError('REGION_REQUIRED','请选择操作区。')
        if type(padding) is not int or padding<0:raise LiteError('INVALID_PADDING')
        limits=self.limits(ident)
        if limits is None:raise LiteError('REGION_EMPTY','没有可用于收紧边界的内容。')
        # Direct-child PINs are public access geometry at this level. Keep
        # their outer halves reachable; own boundary PINs move with this box.
        contents=[limits,*[pin.bbox for child in children(e.w,ident) for pin in child.pins.values()]]
        limits=(tuple(min(b[0][i] for b in contents) for i in (0,1)),
                tuple(max(b[1][i] for b in contents) for i in (0,1)))
        grid=e.profile.grid
        bounds=(tuple(max(row.bbox[0][i],floor((limits[0][i]-padding)/grid)*grid) for i in (0,1)),
                tuple(min(row.bbox[1][i],ceil((limits[1][i]+padding)/grid)*grid) for i in (0,1)))
        if bounds!=row.bbox:
            e.publish(self.candidate(ident,bounds,reflow_pins=True))
        updated=e.w.local_data.regions[ident];scale=e.profile.dbu_per_micron
        return {'region_id':ident,'changed':updated!=row,
                'previous_bounds_um':[v/scale for p in row.bbox for v in p],
                'bounds_um':[v/scale for p in updated.bbox for v in p],
                'changed_pin_ids':[pid for pid,p in row.pins.items() if updated.pins[pid]!=p],
                'native_geometry_changed':False,'pin_mode':updated.pin_mode}

    def move(self,ident,delta,*,expected_revision=None):
        field,row=self.record(ident)
        if field=='regions':raise LiteError('REGION_MOVE_REQUIRES_RIGID_TRANSFORM')
        return self.resize(ident,tuple(tuple(v+d for v,d in zip(p,delta)) for p in row.bbox),expected_revision=expected_revision)


def resized_bounds(bounds,handle,point,grid,limits=None,outer=None):
    """Handle coordinates used by both on-screen feedback and release."""
    (x,y),(xx,yy)=bounds;px,py=(round(v/grid)*grid for v in point)
    if 'w' in handle:x=min(px,xx-grid,limits[0][0] if limits else xx-grid)
    if 'e' in handle:xx=max(px,x+grid,limits[1][0] if limits else x+grid)
    if 's' in handle:y=min(py,yy-grid,limits[0][1] if limits else yy-grid)
    if 'n' in handle:yy=max(py,y+grid,limits[1][1] if limits else y+grid)
    if outer:
        x=max(x,outer[0][0]);y=max(y,outer[0][1]);xx=min(xx,outer[1][0]);yy=min(yy,outer[1][1])
    return ((x,y),(xx,yy))

"""Small human editing contract. No creation, net rewrites or device internals."""
from .editor import Editor,projected
from .model import LiteError,Placement,Operation,digest
from .geometry import point,orientation_after,transform_shape,rigid_matrix as rigid_matrix
from .local_models import LocalData
from .regions.transforms import transform_local as transform_local, verify_transforms as verify_transforms
from .regions.query import owner_map,members,descendants,object_bounds,metals
from .regions.models import contains,overlaps

SHAPES={'rect','polygon','path','pathSeg','stdVia'}


class HumanEdit:
    def __init__(self,editor):self.editor=editor

    def kind(self,ident):
        e=self.editor;w=e.w
        if ident in w.local_data.regions:
            if w.local_data.regions[ident].parent_id!=e.scope_id:raise LiteError('REGION_SCOPE_VIOLATION','只能操作当层的黑盒整体。')
            e.work_sessions.assert_editable(ident,action='transform')
            return 'area'
        e.work_sessions.assert_editable(ident)
        for field,kind in [('markups','markup'),('keepouts','keepout')]:
            if ident in getattr(w.local_data,field):
                from .frame_edit import FrameEdit
                FrameEdit(e).record(ident);return kind
        obj=projected(w).get(ident)
        if obj is None:raise LiteError('OBJECT_NOT_EDITABLE')
        if owner_map(w).get(ident)!=e.scope_id:raise LiteError('REGION_SCOPE_VIOLATION','不能操作黑盒内部或上层参考对象。')
        if obj.read_only_reason:raise LiteError('OBJECT_READ_ONLY',obj.read_only_reason)
        if obj.kind=='inst':return 'instance'
        if obj.mpp:return 'mpp'
        if obj.shape and obj.kind in SHAPES:return 'shape'
        raise LiteError('OBJECT_NOT_EDITABLE','此类对象不支持鼠标编辑。')

    def bounds(self,ident):
        w=self.editor.w
        if ident in w.local_data.regions:return w.local_data.regions[ident].bbox
        for field in ('markups','keepouts'):
            if ident in getattr(w.local_data,field):return getattr(w.local_data,field)[ident].bbox
        return object_bounds(w,self.editor.object(ident),self.editor.profile)

    def transform(self,idents,*,delta=(0,0),orientation='R0',expected_revision=None):
        e=self.editor;e.check_revision(expected_revision);idents=tuple(dict.fromkeys(idents))
        if not idents:raise LiteError('SELECT_OBJECTS')
        kinds={uid:self.kind(uid) for uid in idents}
        if any(k in ('markup','keepout') for k in kinds.values()):
            if len(idents)!=1 or orientation!='R0':raise LiteError('FRAME_MOVE_SEPARATELY','定位/禁布框请单独移动或调整大小。')
            from .frame_edit import FrameEdit
            return FrameEdit(e).move(idents[0],delta,expected_revision=expected_revision)
        if orientation!='R0' and any(k=='shape' for k in kinds.values()):raise LiteError('GUI_TRANSFORM_NOT_ALLOWED','导线、矩形、过孔仅允许移动或删除。')
        if orientation not in ('R0','R90','R180','R270','MX','MY','MXR90','MYR90'):raise LiteError('GUI_TRANSFORM_NOT_ALLOWED')
        grid=e.profile.grid;delta=tuple(round(v/grid)*grid for v in delta)
        if orientation=='R0' and delta==(0,0):return e.w
        bounds=[self.bounds(uid) for uid in idents]
        if any(b is None for b in bounds):raise LiteError('OBJECT_BOUNDS_MISSING')
        pivot=tuple(round((min(b[0][i] for b in bounds)+max(b[1][i] for b in bounds))/(2*grid))*grid for i in (0,1))
        matrix=rigid_matrix(delta,orientation,pivot)
        # The temporary Editor retains native permissions. Region pose checks
        # are performed once on the final atomic geometry + metadata update.
        staging=e.w.model_copy(update={'local_data':LocalData(),'layout_connectivity':None})
        temp=Editor(staging,e.profile);local=e.w.local_data;proofs={};uids=[]
        for ident,kind in kinds.items():
            if kind=='area':
                proofs[ident]=(delta,orientation,pivot);local=transform_local(local,ident,matrix)
                uids.extend(members(e.w,ident))
            else:uids.append(ident)
        objects=projected(staging);operations=[]
        for uid in dict.fromkeys(uids):
            if uid in e.w.baseline.text_owners:continue
            obj=objects[uid]
            if obj.read_only_reason:raise LiteError('OBJECT_READ_ONLY',uid+' · '+obj.read_only_reason)
            if obj.kind in ('inst','mpp'):
                operations.append(Operation(action='transform',uid=uid,before=digest(obj.semantic()),placement=Placement(
                    origin=point(obj.placement.origin,matrix),orientation=orientation_after(obj.placement.orientation,orientation))))
            elif obj.shape and obj.kind in SHAPES:
                operations.append(Operation(action='update',uid=uid,before=digest(obj.semantic()),shape=transform_shape(obj.shape,delta=delta,orientation=orientation,pivot=pivot)))
            else:raise LiteError('UNSUPPORTED_REGION_MEMBER',uid)
        temp.apply(operations)
        try:local=LocalData.model_validate(local.model_dump())
        except ValueError as exc:
            from .regions.transform_diagnostics import failure
            raise failure(local,set(proofs),e.profile.dbu_per_micron) from exc
        candidate=e.w.model_copy(update={'operations':temp.w.operations,'local_data':local})
        e.publish(candidate,region_transforms=proofs)
        return e.w

    def delete(self,idents,*,expected_revision=None):
        e=self.editor;e.check_revision(expected_revision);idents=tuple(dict.fromkeys(idents))
        if not idents:raise LiteError('SELECT_OBJECTS')
        kinds={uid:self.deletion_kind(uid) for uid in idents}
        temp=Editor(e.w,e.profile,scope_id=e.scope_id)
        for uid,kind in kinds.items():
            if kind=='geometry':temp.delete(uid)
        local=temp.w.local_data
        local=LocalData.model_validate(local.model_copy(update={field:{uid:row for uid,row in getattr(local,field).items() if uid not in kinds}
            for field in ('markups','keepouts')}).model_dump())
        e.publish(temp.w.model_copy(update={'local_data':local}))

    def deletion_kind(self,ident):
        e=self.editor;w=e.w
        if ident in w.local_data.regions:raise LiteError('GUI_DELETE_NOT_ALLOWED','操作区只能使用“解散操作区”，Delete / Backspace 不会解散或删除它。')
        if ident in w.local_data.markups or ident in w.local_data.keepouts:
            from .frame_edit import FrameEdit
            FrameEdit(e).record(ident);return 'frame'
        e.work_sessions.assert_editable(ident)
        if owner_map(w).get(ident)!=e.scope_id:raise LiteError('REGION_SCOPE_VIOLATION','只能删除当前层对象。')
        obj=e.object(ident)
        if obj.kind=='inst' or not (obj.shape or obj.mpp):raise LiteError('GUI_DELETE_NOT_ALLOWED','器件和原生模块不能删除。')
        from .actions import availability
        allowed,reason=availability('delete',obj)
        if not allowed:raise LiteError('GUI_DELETE_NOT_ALLOWED',reason)
        return 'geometry'

    def adjust_pin(self,region_id,pin_id,x,y,*,layer=None,name=None,size=None,expected_revision=None):
        e=self.editor;e.check_revision(expected_revision);w=e.w;r=w.local_data.regions.get(region_id)
        if r is None or not (r.id==e.scope_id or r.parent_id==e.scope_id):raise LiteError('REGION_SCOPE_VIOLATION','只能调整本层边界或本层子模块的本地 PIN。')
        e.work_sessions.assert_editable(region_id)
        pin=r.pins.get(pin_id)
        if pin is None:raise LiteError('LOCAL_PIN_REQUIRED','Virtuoso PIN 不可单独移动。')
        original=pin
        if name is not None:
            if not name.strip():raise LiteError('PIN_NAME_REQUIRED')
            pin=pin.model_copy(update={'name':name.strip()})
        if size is not None:
            if len(size)!=2 or any(type(v) is not int or v<=0 or v%(2*e.profile.grid) for v in size):
                raise LiteError('PIN_SIZE_GRID','PIN 宽高须为正的两倍网格整数。')
            if any(v>r.bbox[1][i]-r.bbox[0][i] for i,v in enumerate(size)):
                raise LiteError('PIN_SIZE_EXCEEDS_REGION','接口标记不能大于子操作区。')
            from .pin_placement import center
            cx,cy=center(pin);hx,hy=(v//2 for v in size)
            pin=pin.model_copy(update={'bbox':((int(cx)-hx,int(cy)-hy),(int(cx)+hx,int(cy)+hy))})
        from .interface_layers import ANY_METAL,ANY_METAL_LABEL,layers,overlaps_layers,fully_blocked
        if layer==ANY_METAL_LABEL:layer=ANY_METAL
        if layer is not None and layer!=ANY_METAL and layer not in metals(e.profile):raise LiteError('PIN_LAYER_NOT_WRITABLE_METAL')
        from .pin_placement import candidate
        updated=candidate(r,pin,x,y,e.profile.grid,layer=layer)
        if not layers(updated,e.profile):raise LiteError('PIN_LAYER_NOT_WRITABLE_METAL')
        for keep in w.local_data.keepouts.values():
            if fully_blocked(updated,keep.layers,e.profile) and overlaps(updated.bbox,keep.bbox):raise LiteError('PIN_IN_KEEPOUT',keep.id)
        for other in r.pins.values():
            if other.id!=pin.id and overlaps_layers(other,updated,e.profile) and overlaps(other.bbox,updated.bbox):raise LiteError('INTERFACE_PINS_OVERLAP',other.name)
        if updated==original:return
        regions={**w.local_data.regions,r.id:r.model_copy(update={'pins':{**r.pins,pin.id:updated},'revision':r.revision+1,'interface_revision':r.interface_revision+1})}
        if r.parent_id:
            parent=regions[r.parent_id];regions[parent.id]=parent.model_copy(update={'revision':parent.revision+1})
        local=LocalData.model_validate(w.local_data.model_copy(update={'regions':regions}).model_dump())
        e.publish(w.model_copy(update={'local_data':local}))

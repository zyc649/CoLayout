"""Transactional local region commands. GUI is a thin adapter to this service."""
from uuid import uuid4
from math import lcm,floor,ceil
from .models import OperationRegion,InterfacePin,MarkupBox,RoutingKeepout,contains,overlaps
from .query import object_bounds,owner_map,children,members,metals,boundary
from ..local_models import LocalData
from ..editor import projected
from ..model import LiteError
from ..interface_layers import overlaps_layers,fully_blocked


class RegionActions:
    def __init__(self,editor):self.editor=editor

    def _publish(self,**changes):
        self.editor.check_revision(None)
        local=LocalData.model_validate(self.editor.w.local_data.model_copy(update=changes).model_dump())
        if local!=self.editor.w.local_data:
            candidate=self.editor.w.model_copy(update={'local_data':local})
            from .constraints import validate_workspace
            validate_workspace(candidate,self.editor.profile)
            self.editor.publish(candidate)

    def _region(self,ident):
        region=self.editor.w.local_data.regions.get(ident)
        if region is None:raise LiteError('REGION_MISSING',ident)
        return region

    def set_pin_mode(self, ident, mode):
        if mode not in ('fixed', 'directional'):
            raise LiteError('INVALID_PIN_MODE')
        region = self._region(ident)
        self.editor.work_sessions.assert_editable(ident)
        if mode != region.pin_mode:
            self._update(region, pin_mode=mode, interface_revision=region.interface_revision+1)

    def _update(self,region,**changes):
        updated=region.model_copy(update={**changes,'revision':region.revision+1})
        self._publish(regions={**self.editor.w.local_data.regions,region.id:updated})

    def snap_box(self,bounds):
        grid=self.editor.profile.grid
        values=[round(v) if abs(v-round(v))<1e-6 else v for v in bounds]
        if values[0]==values[2] or values[1]==values[3]:raise LiteError('INVALID_BOUNDS','框须有正面积。')
        bbox=((floor(min(values[0],values[2])/grid)*grid,floor(min(values[1],values[3])/grid)*grid),
              (ceil(max(values[0],values[2])/grid)*grid,ceil(max(values[1],values[3])/grid)*grid))
        # Also validate finite integer bounds, nonzero area and native range.
        MarkupBox(id='validation',bbox=bbox)
        return bbox

    def create(self,bounds,name='',*,parent_id=None):
        w=self.editor.w;bbox=self.snap_box(bounds);regions=dict(w.local_data.regions);owners=owner_map(w)
        if parent_id and not contains(self._region(parent_id).bbox,bbox):raise LiteError('REGION_OUTSIDE_PARENT')
        adopted=[]
        for child in children(w,parent_id):
            if overlaps(bbox,child.bbox):
                if not contains(bbox,child.bbox):raise LiteError('REGION_PARTIAL_OVERLAP','操作区不能部分交叠；请完整包住子区域。',region=child.id)
                adopted.append(child.id)
        direct=[];partial=[]
        for uid,obj in projected(w).items():
            if uid in w.baseline.text_owners or owners.get(uid)!=parent_id:continue
            bounds=object_bounds(w,obj,self.editor.profile)
            if bounds is None:
                if obj.kind in ('inst','mosaic'):raise LiteError('OBJECT_BOUNDS_MISSING',uid)
                continue
            if contains(bbox,bounds):direct.append(uid)
            elif overlaps(bbox,bounds):partial.append(uid)
        if partial:raise LiteError('REGION_CUTS_OBJECTS','框边穿过已有对象，请调整框；不会拆开原生对象或导线。',uids=partial)
        if not direct and not adopted:raise LiteError('REGION_EMPTY','请框住器件、导线或已封装子区域。')
        ident='area-'+uuid4().hex
        region=OperationRegion(id=ident,name=name.strip() or f'操作区 {len(regions)+1}',bbox=bbox,parent_id=parent_id,
            object_uids=tuple(direct),blocked_layers=metals(self.editor.profile),interface_policy='reference_v2')
        regions[ident]=region
        for child in adopted:regions[child]=regions[child].model_copy(update={'parent_id':ident})
        if parent_id:
            parent=regions[parent_id]
            regions[parent_id]=parent.model_copy(update={'object_uids':tuple(u for u in parent.object_uids if u not in direct),'revision':parent.revision+1})
        candidate=w.model_copy(update={'local_data':w.local_data.model_copy(update={'regions':regions})})
        report=boundary(candidate,ident)
        if report['unresolved']:raise LiteError('BOUNDARY_UNRESOLVED','缺少可靠的本地接口数据，操作区尚未创建。',issues=report['unresolved'])
        regions[ident]=region.model_copy(update={'pins':self._suggested_pins(region,report)})
        self._validate_pins(regions[ident])
        self._publish(regions=regions)
        return ident

    def _suggested_pins(self,region,report):
        p=self.editor.profile;grid=p.grid;size=max(2*grid,int(round(.6*p.dbu_per_micron/(2*grid)))*2*grid)
        layer=metals(p)
        if report['nets'] and not layer:raise LiteError('NO_ROUTING_METAL')
        from collections import defaultdict
        from .pin_layout import available_position
        old=defaultdict(list)
        for pin in region.pins.values():old[pin.net].append(pin)
        wanted={row['net'] for row in report['nets']}
        result={pin.id:pin for pin in region.pins.values() if pin.net in wanted or '人工补充' in pin.evidence}
        rows=report['nets'];(x,y),(xx,yy)=region.bbox
        for index,row in enumerate(rows):
            existing=old.get(row['net'],[])
            if not existing:
                # Initial GUI placement only. The human can place each fixed
                # interface on an edge or inside, independent of layout strategy.
                cx=x;cy=y
                pin=InterfacePin(id='pin-'+uuid4().hex,name=row['net'],net=row['net'],lpp=(layer[0],'drawing'),layer_mode='any_metal',
                    bbox=((cx-size//2,cy-size//2),(cx+size//2,cy+size//2)))
                pin=available_position(region,pin,result.values(),p,
                    keepouts=self.editor.w.local_data.keepouts.values(),total=len(rows))
                existing=[pin]
            for pin in existing:
                pin=pin.model_copy(update={'evidence':tuple(row['evidence'])});result[pin.id]=pin
        for pin in region.pins.values():
            if '人工补充' in pin.evidence:result.setdefault(pin.id,pin)
        return result

    def copy_pin(self,ident,pin_id,*,x=None,y=None):
        region=self._region(ident);e=self.editor
        if region.id!=e.scope_id and region.parent_id!=e.scope_id:
            raise LiteError('REGION_SCOPE_VIOLATION','只能复制本层边界或直接子模块的本地 PIN。')
        e.work_sessions.assert_editable(ident)
        original=region.pins.get(pin_id)
        if original is None:raise LiteError('LOCAL_PIN_REQUIRED','只支持本地接口 PIN。')
        from .pin_layout import available_position
        from ..pin_placement import candidate,center
        copied=original.model_copy(update={'id':'pin-'+uuid4().hex,'access_group':original.access_group or original.id})
        if x is None and y is None:
            copied=available_position(region,copied,region.pins.values(),e.profile,
                keepouts=e.w.local_data.keepouts.values(),preferred=center(original),total=len(region.pins)+1)
        elif x is None or y is None:raise LiteError('INVALID_ARGUMENTS','x/y 必须同时提供。')
        else:copied=candidate(region,copied,x,y,e.profile.grid)
        updated=region.model_copy(update={'pins':{**region.pins,copied.id:copied}})
        self._validate_pins(updated)
        self._update(region,pins=updated.pins,interface_revision=region.interface_revision+1)
        return copied.id

    def recompute(self,ident):
        region=self._region(ident)
        candidate=self.editor.w.model_copy(update={'local_data':self.editor.w.local_data.model_copy(update={
            'regions':{**self.editor.w.local_data.regions,ident:region.model_copy(update={'interface_policy':'reference_v2'})}})})
        self._update(region,pins=self._suggested_pins(region,boundary(candidate,ident)),interface_policy='reference_v2')

    def associate_reference(self,reference_net,layout_net,*,region_id=None):
        w=self.editor.w
        refs={n for p in w.circuit.ports.values() for n in (p.members or {p.name:p.net}).values()} if w.circuit else set()
        nets={n for i in w.layout_connectivity.instances.values() for t in i.terminals.values() for n in (t.members or {t.name:t.net}).values()} if w.layout_connectivity else set()
        if reference_net not in refs or layout_net not in nets:raise LiteError('INVALID_REFERENCE_NET_ASSOCIATION')
        mapping={**w.local_data.reference_net_map,reference_net:layout_net};changes={'reference_net_map':mapping}
        if region_id:
            region=self._region(region_id)
            candidate=w.model_copy(update={'local_data':w.local_data.model_copy(update=changes)})
            updated=region.model_copy(update={'pins':self._suggested_pins(region,boundary(candidate,region_id)),'revision':region.revision+1})
            changes['regions']={**w.local_data.regions,region_id:updated}
        self._publish(**changes)

    def place_pin(self,ident,pin_id,x,y,layer):
        # Compatibility entry; human placement has one implementation.
        from ..human_edit import HumanEdit
        return HumanEdit(self.editor).adjust_pin(ident,pin_id,x,y,layer=layer)

    def _validate_pins(self,region):
        pins=list(region.pins.values())
        for i,pin in enumerate(pins):
            for other in pins[i+1:]:
                if overlaps_layers(pin,other,self.editor.profile) and overlaps(pin.bbox,other.bbox):raise LiteError('INTERFACE_PINS_OVERLAP',pin.name+' / '+other.name)
            for keep in self.editor.w.local_data.keepouts.values():
                if fully_blocked(pin,keep.layers,self.editor.profile) and overlaps(pin.bbox,keep.bbox):raise LiteError('PIN_IN_KEEPOUT',keep.id)

    def seal(self,ident):
        """Legacy call is now a read-only validation, with no extra undo entry."""
        region=self._region(ident);report=boundary(self.editor.w,ident)
        if report['unresolved']:raise LiteError('BOUNDARY_UNRESOLVED',issues=report['unresolved'])
        missing={row['net'] for row in report['nets']}-{p.net for p in region.pins.values()}
        if missing:raise LiteError('INTERFACE_INCOMPLETE',nets=sorted(missing))
        self._validate_pins(region)

    def unseal(self,ident):
        self._region(ident)
        raise LiteError('REGION_ALWAYS_ACTIVE','操作区始终有效；可直接调整本地 PIN。')

    def update_details(self,ident,name,note,blocked_layers):
        region=self._region(ident)
        if set(blocked_layers)-set(metals(self.editor.profile)):raise LiteError('UNKNOWN_ROUTING_METAL')
        self._update(region,name=name.strip(),note=note,blocked_layers=tuple(blocked_layers))

    def dissolve(self,ident):
        region=self._region(ident)
        self.editor.work_sessions.assert_editable(ident,action='dissolve')
        if region.parent_id!=self.editor.scope_id:raise LiteError('REGION_SCOPE_VIOLATION','请返回上层后选择要解散的操作区。')
        local=self.editor.w.local_data;regions=dict(local.regions);regions.pop(ident)
        for child in children(self.editor.w,ident):regions[child.id]=child.model_copy(update={'parent_id':region.parent_id})
        if region.parent_id:
            p=regions[region.parent_id];regions[p.id]=p.model_copy(update={'object_uids':p.object_uids+region.object_uids,'revision':p.revision+1})
        self._publish(regions=regions,
            markups={k:m.model_copy(update={'scope_id':region.parent_id}) if m.scope_id==ident else m for k,m in local.markups.items()},
            keepouts={k:m.model_copy(update={'scope_id':region.parent_id}) if m.scope_id==ident else m for k,m in local.keepouts.items()})

    def add_markup(self,bounds,text='',scope_id=None):
        ident='note-'+uuid4().hex
        self._publish(markups={**self.editor.w.local_data.markups,ident:MarkupBox(id=ident,bbox=self.snap_box(bounds),text=text,scope_id=scope_id)})
        return ident

    def add_keepout(self,bounds,layers=None,note=''):
        layers=metals(self.editor.profile) if layers is None else layers
        if set(layers)-set(metals(self.editor.profile)):raise LiteError('KEEPOUT_LAYERS_REQUIRED','请选择允许布线的金属层。')
        ident='keepout-'+uuid4().hex;item=RoutingKeepout(id=ident,bbox=self.snap_box(bounds),layers=tuple(layers),note=note)
        for r in self.editor.w.local_data.regions.values():
            for p in r.pins.values():
                if fully_blocked(p,layers,self.editor.profile) and overlaps(p.bbox,item.bbox):raise LiteError('KEEPOUT_COVERS_FIXED_PIN',p.id)
        self._publish(keepouts={**self.editor.w.local_data.keepouts,ident:item});return ident

    def remove_box(self,ident):
        if ident not in self.editor.w.local_data.markups and ident not in self.editor.w.local_data.keepouts:raise LiteError('LOCAL_BOX_MISSING')
        from ..human_edit import HumanEdit
        HumanEdit(self.editor).delete([ident])

    def update_box(self,ident,text,layers=()):
        local=self.editor.w.local_data
        if ident in local.markups:
            self._publish(markups={**local.markups,ident:local.markups[ident].model_copy(update={'text':text})})
        elif ident in local.keepouts:
            if set(layers)-set(metals(self.editor.profile)):raise LiteError('KEEPOUT_LAYERS_REQUIRED')
            keep=local.keepouts[ident]
            for r in local.regions.values():
                for p in r.pins.values():
                    if fully_blocked(p,layers,self.editor.profile) and overlaps(p.bbox,keep.bbox):raise LiteError('KEEPOUT_COVERS_FIXED_PIN',p.id)
            self._publish(keepouts={**local.keepouts,ident:keep.model_copy(update={'note':text,'layers':tuple(layers)})})
        else:raise LiteError('LOCAL_BOX_MISSING')

    def native_policy(self,uid,layers):
        w=self.editor.w
        if not w.layout_connectivity or uid not in w.layout_connectivity.instances or not w.layout_connectivity.instances[uid].black_box:
            raise LiteError('EXPECTED_NATIVE_MODULE','请选择 Virtuoso 原生黑盒模块。')
        if set(layers)-set(metals(self.editor.profile)):raise LiteError('UNKNOWN_ROUTING_METAL')
        self._publish(native_blocked_layers={**w.local_data.native_blocked_layers,uid:tuple(layers)})

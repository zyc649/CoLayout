"""L1 semantic editing commands. UI and scripts use this layer, not presets.

Lengths in public command parameters are micrometres. L0 Shape/Operation
payloads remain integer DBU. Ordinary commands never access Virtuoso.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from dataclasses import dataclass
from typing import Any
from .editor import Editor, projected
from .geometry import transform, point, orientation_after, ORIENT
from .model import Shape, Placement, Operation, LiteError, digest

from .commands import COMMANDS,TITLES,FIELDS,allowed_fields,wire_kind
from .permissions import delete_exception

KIND_NAMES={'inst':'器件/模块实例','rect':'矩形','path':'走线','pathSeg':'独立线段',
            'polygon':'多边形','stdVia':'标准过孔','mosaic':'原生数组','mpp':'MPP / 保护环整体'}
READ_ONLY={'pin_geometry':'这是端口图形，当前接口保护端口定义','protected_group':'原生保护环/组内部不能单独修改，可整组删除',
 'layer_not_writable':'当前工艺配置未开放此图层的创建/修改',
 'native_parent_child_requires_adapter':'对象带原生父子附属图形，当前保护整个关联结构，请在 Virtuoso 中编辑',
 'master_unresolved':'源Layout引用的master缺失，仅显示已有外框；不能修改或猜测Pin',
 'shared_diffusion':'与邻居共享扩散，不能单独移动','unsupported_magnification':'该实例带缩放，暂时只读',
 'native_relationship_requires_adapter':'带有尚未适配的原生关联关系','missing_persistent_identity':'尚无可编辑身份，请导入测试副本',
 'native_route_locked':'Virtuoso 中的 route 为 fixed/locked，需先在 Virtuoso 解锁',
 'native_route_topology_requires_adapter':'原生 route 的分组、连接端点或其他关联尚未开放完整编辑',
 'unsupported_object':'该原生对象类型暂时只读'}


def number(value):
    if isinstance(value,bool):raise LiteError('INVALID_NUMBER','数值不能是布尔值')
    try:result=Decimal(str(value))
    except InvalidOperation:raise LiteError('INVALID_NUMBER','请输入有效数字')
    if not result.is_finite():raise LiteError('INVALID_NUMBER','数值必须有限')
    return result


def dbu(value,profile):
    scaled=number(value)*profile.dbu_per_micron
    if scaled!=scaled.to_integral_value():raise LiteError('OFF_GRID',f'坐标精度超出 1 DBU = {1/profile.dbu_per_micron:g} µm')
    result=int(scaled)
    if result%profile.grid:raise LiteError('OFF_GRID',f'请使用 {profile.grid/profile.dbu_per_micron:g} µm 网格')
    return result


def microns(value,profile):return float(Decimal(value)/profile.dbu_per_micron)


def anchor(obj):
    if obj.placement:return obj.placement.origin
    s=obj.shape
    if s.origin is not None:return s.origin
    if s.bbox:return s.bbox[0]
    return s.points[0]


def width_um(shape,profile):
    value=Decimal(shape.width)/profile.dbu_per_micron
    if shape.width_basis=='oa_diagonal':value/=Decimal(2).sqrt()
    return float(value)


def extension_um(shape,side,profile):
    value=Decimal(getattr(shape,side+'_extension'))/profile.dbu_per_micron
    if shape.kind=='pathSeg' and shape.width_basis=='oa_diagonal':value/=Decimal(2).sqrt()
    return float(value)


def custom_um(shape,side,key,profile):
    value=Decimal(getattr(getattr(shape,side+'_custom'),key))/profile.dbu_per_micron
    diagonal=(shape.width_basis=='oa_diagonal') if key=='right_half_width' else (shape.width_basis!='oa_diagonal')
    return float(value/Decimal(2).sqrt() if diagonal else value)


def wire_distance(value,profile,*,diagonal=False,width=False,quantize=False):
    requested=number(value)
    if diagonal or quantize:
        from math import lcm
        quantum=lcm(profile.grid,2) if width else profile.grid
        factor=Decimal(2).sqrt() if diagonal else 1
        result=int((requested*profile.dbu_per_micron*factor/quantum).to_integral_value(rounding=ROUND_HALF_UP))*quantum
    else:result=dbu(requested,profile)
    if result<0 or (width and (result<=0 or result%2)):
        raise LiteError('INVALID_WIDTH' if width else 'INVALID_EXTENSION','线宽须为正偶数 DBU，延伸量须非负。')
    return result


def wire_ends(kind,params,profile,*,shape=None,points=None):
    """Convert only the applicable end fields, preserving physical extensions."""
    changes={}
    diagonal=kind=='pathSeg' and all(a!=b for a,b in zip(*(points or shape.points)))
    if kind=='path':changes['style']=params.get('style',shape.style if shape else 'truncateExtend')
    else:
        changes['width_basis']='oa_diagonal' if diagonal else 'perpendicular'
        for side in ('begin','end'):changes[side+'_style']=params.get(side+'_style',getattr(shape,side+'_style') if shape else 'truncate')
    for side in ('begin','end'):
        key=side+'_extension'
        active=(changes['style']=='varExtendExtend') if kind=='path' else changes[side+'_style'] in ('variable','custom')
        if not active:
            if key in params and number(params[key])!=0:raise LiteError('INACTIVE_EXTENSION','只有自定义延伸端头才能设置非零延伸量。')
            changes[key]=0
        elif key in params:changes[key]=wire_distance(params[key],profile,diagonal=diagonal,quantize=kind=='pathSeg' and changes[side+'_style']=='custom')
        elif shape:
            if kind=='pathSeg' and diagonal!=(shape.width_basis=='oa_diagonal'):
                changes[key]=wire_distance(extension_um(shape,side,profile),profile,diagonal=diagonal,quantize=True)
            elif kind=='pathSeg' and changes[side+'_style']=='custom' and getattr(shape,side+'_custom'):
                pass # Omitted custom extensions scale with width in Editor.
            else:changes[key]=getattr(shape,key)
        else:changes[key]=0
    if kind=='pathSeg':
        from .pathseg import CUSTOM_FIELDS
        converted=[]
        for side in ('begin','end'):
            key=side+'_custom';cap=getattr(shape,key) if shape else None
            if changes[side+'_style']!='custom':
                if params.get(key) is not None:raise LiteError('INACTIVE_CUSTOM_END')
                changes[key]=None;continue
            if key in params:
                values=params[key]
                if not isinstance(values,dict) or set(values)!=set(CUSTOM_FIELDS):raise LiteError('INVALID_CUSTOM_END','倒角参数需要左斜向延伸、右斜向延伸和右半宽。')
                changes[key]={k:wire_distance(v,profile,diagonal=diagonal if k=='right_half_width' else not diagonal,quantize=True) for k,v in values.items()}
            elif cap and diagonal!=(shape.width_basis=='oa_diagonal'):
                # A 90/45 switch changes the basis of all six native cap values.
                target_width=wire_distance(params.get('width',width_um(shape,profile)),profile,diagonal=diagonal,width=True)
                ratio=number(params.get('width',width_um(shape,profile)))/number(width_um(shape,profile))
                def convert(v,d):
                    native=number(v)*ratio*profile.dbu_per_micron*(Decimal(2).sqrt() if d else 1)
                    return int((native/profile.grid).to_integral_value(rounding=ROUND_HALF_UP))*profile.grid
                changes[key]={k:convert(custom_um(shape,side,k,profile),diagonal if k=='right_half_width' else not diagonal) for k in CUSTOM_FIELDS}
                converted.append(side)
                if side+'_extension' not in params:changes[side+'_extension']=convert(extension_um(shape,side,profile),diagonal)
            elif cap:pass # Editor scales native values if width changes.
            else:raise LiteError('CUSTOM_END_PARAMETERS_REQUIRED','原生自定义倒角需要完整的三项端头参数。')
        if converted==['begin','end']:
            changes['end_custom']['right_half_width']=target_width-changes['begin_custom']['right_half_width']
    return changes


def availability(action,obj):
    if action.startswith('create_'):return True,''
    if obj is None:return False,'先在画布或“操作对象”列表选择对象。'
    if obj.mpp:
        if action in ('delete','delete_guard'):return (True,'删除整个原生 MPP') if obj.deletion_allowed else (False,'MPP 有外部约束，不能删除')
        if action in ('move','rotate','mirror'):return (False,'MPP 有未支持的原生约束：'+obj.read_only_reason) if obj.read_only_reason else (True,'整体变换，内部参数保持原生定义')
        return False,'MPP 作为整体操作，不编辑内部单层图形；需要改结构时删除后重新生成。'
    if action=='delete' and delete_exception(obj):
        return True,'可单独删除；分组内其他对象受同步核对保护。'
    if action=='delete_guard':
        return (True,'') if obj.group_uid else (False,'当前对象不属于 GuardRing；不能按保护环删除。')
    if obj.read_only_reason:return False,f'当前对象只读：{READ_ONLY.get(obj.read_only_reason,"包含暂不支持的原生字段")}。'
    if action in ('move','rotate','mirror'):
        return (True,'') if obj.placement or obj.shape else (False,'此对象暂不支持变换。')
    allowed=COMMANDS[action].kinds
    if obj.kind not in allowed:
        names='、'.join(KIND_NAMES[k] for k in sorted(allowed))
        return False,f'当前选中的是{KIND_NAMES.get(obj.kind,obj.kind)}；此操作仅适用于{names}。'
    return True,''


def short_uid(uid):
    return uid[:8]+(':'+uid.rsplit(':',1)[1] if ':' in uid else '')


def describe(obj,profile):
    if obj is None:return '无'
    kind=KIND_NAMES.get(obj.kind,obj.kind);name=obj.attributes.get('name') or short_uid(obj.uid)
    parts=[f'{kind} {name}']
    if obj.placement or obj.shape:
        x,y=anchor(obj);parts.append(f'基点=({microns(x,profile):g}, {microns(y,profile):g}) µm')
    if obj.placement and not obj.mpp:parts.append('方向='+obj.placement.orientation)
    if obj.mpp:
        parts.append(('闭合保护环' if obj.attributes.get('form')=='guardring' else '开放 Multipart Path')+f' · {sum(obj.mpp.member_counts.values())} 个内部图形')
    if obj.shape:
        s=obj.shape
        if s.width is not None:parts.append(f'物理线宽={width_um(s,profile):.6g} µm / 原生 {s.width} DBU')
        if s.bbox:parts.append(f'尺寸={microns(s.bbox[1][0]-s.bbox[0][0],profile):g} × {microns(s.bbox[1][1]-s.bbox[0][1],profile):g} µm')
        if s.lpp:parts.append('/'.join(s.lpp))
        if s.kind=='stdVia':parts.append(f"{s.via_definition} · {s.via_parameters.get('cutRows',1)}行×{s.via_parameters.get('cutColumns',1)}列 · {s.orientation}")
    if obj.group_uid:parts.append('GuardRing成员')
    if obj.route_uid:parts.append('原生 route 成员；当前操作只作用于本对象')
    if obj.read_only_reason:parts.append(('可单独删除，其他编辑受保护：' if obj.deletion_allowed else '只读：')+READ_ONLY.get(obj.read_only_reason,'包含暂不支持的原生字段'))
    return '；'.join(parts)


@dataclass
class ActionResult:
    action:str
    uid:str|None
    changed_uids:set[str]
    before:str
    after:str
    changed:bool
    operations:list[dict[str,Any]]

    @property
    def message(self):
        status='已在本地执行，尚未同步' if self.changed else '数值与原值相同，没有产生修改'
        if self.changed and not self.operations:status='已在本地执行；没有待同步操作'
        return f'{TITLES[self.action]}：{status}\n之前：{self.before}\n之后：{self.after}'


class Actions:
    def __init__(self,editor:Editor):self.editor=editor

    def execute(self,action,params,uid=None,*,adapter=None,progress=None):
        if action not in FIELDS:raise LiteError('UNKNOWN_ACTION')
        e=self.editor;p=e.profile;objects=projected(e.w);obj=objects.get(uid)
        accepted=allowed_fields(action,obj)
        if set(params)-accepted:raise LiteError('UNKNOWN_ARGUMENT','不适用于当前操作/类型的参数：'+','.join(sorted(set(params)-accepted)))
        if action in ('create_path90','create_path45','create_pathseg90','create_pathseg45') and 'width' not in params:
            from .wire_defaults import default_width
            params={**params,'width':default_width(p,params.get('lpp'))}
        required=COMMANDS[action].required
        if required-set(params):raise LiteError('MISSING_ARGUMENT','缺少参数：'+','.join(sorted(required-set(params))))
        allowed,reason=availability(action,obj)
        if not allowed:raise LiteError('ACTION_NOT_APPLICABLE',reason)
        before=describe(obj,p) if not action.startswith('create_') else '无（创建新对象）'
        start_revision=e.w.revision;old_ops={o.uid:o for o in e.w.operations}
        def length(key):
            if key not in params:raise LiteError('MISSING_ARGUMENT',key)
            return dbu(params[key],p)
        def xy():return (length('x'),length('y'))
        def pts():
            values=params.get('points')
            if not isinstance(values,(list,tuple)):raise LiteError('INVALID_POINTS','请填写顶点表')
            out=tuple((dbu(v[0],p),dbu(v[1],p)) for v in values if isinstance(v,(tuple,list)) and len(v)==2)
            if len(out)!=len(values):raise LiteError('INVALID_POINTS','每个顶点需要 X/Y')
            if 'polygon' not in action and len(out)<2:raise LiteError('INVALID_POINTS','线至少需要两个不同端点。')
            if wire_kind(action,obj)=='pathSeg' and len(out)!=2:raise LiteError('PATHSEG_TWO_POINTS','PathSeg 必须恰好有两个端点。')
            if action.startswith(('create_path','edit_path')):
                from .path_validation import validate_path_points
                validate_path_points(out)
            if 'polygon' in action:
                from .model import segments_intersect
                if len(out)>1 and out[-1]==out[0]:out=out[:-1]
                if len(out)<3:raise LiteError('INVALID_POLYGON','多边形至少需要3个不同顶点。')
                if len(set(out))!=len(out):raise LiteError('INVALID_POLYGON','有重复顶点，请按边界顺序填写。')
                edges=list(zip(out,out[1:]+out[:1]))
                for i,(a,b) in enumerate(edges):
                    for j,(c,d) in enumerate(edges):
                        if j<=i+1 or (i==0 and j==len(edges)-1):continue
                        if segments_intersect(a,b,c,d):raise LiteError('INVALID_POLYGON',f'边 {i+1}→{(i+1)%len(out)+1} 与边 {j+1}→{(j+1)%len(out)+1} 相交。请按顺时针或逆时针沿边界填写；图形未修改。')
                if not sum(a[0]*b[1]-b[0]*a[1] for a,b in edges):raise LiteError('INVALID_POLYGON','顶点围成的面积为零，请检查坐标。')
            if action.endswith('90'):
                for index,(a,b) in enumerate(zip(out,out[1:])):
                    if a[0]!=b[0] and a[1]!=b[1]:raise LiteError('ORTHOGONAL_REQUIRED',f'第{index+1}→{index+2}个顶点同时改变了X和Y。90°线必须水平或竖直；可打开联动选项，或选择45°/90°折线。')
            return out
        def native_width(shape=None,points=None):
            kind=shape.kind if shape else wire_kind(action,obj)
            diagonal=kind=='pathSeg' and all(a!=b for a,b in zip(*(points or shape.points)))
            return wire_distance(params['width'],p,diagonal=diagonal,width=True)
        if action=='create_rect':
            x,y=xy();uid=e.create(Shape(kind='rect',lpp=params['lpp'],bbox=((x,y),(x+length('width'),y+length('height'))),net_intent=params.get('net_intent')))
        elif action in ('create_path90','create_path45','create_pathseg90','create_pathseg45'):
            points=pts();kind=wire_kind(action)
            uid=e.create(Shape(kind=kind,lpp=params['lpp'],points=points,width=native_width(points=points),
                net_intent=params.get('net_intent'),**wire_ends(kind,params,p,points=points)))
        elif action=='create_polygon':uid=e.create(Shape(kind='polygon',lpp=params['lpp'],points=pts(),net_intent=params.get('net_intent')))
        elif action in ('create_via','edit_via'):
            values={}
            for key,value in params.get('via_parameters',{}).items():
                if key in ('cutRows','cutColumns'):
                    if type(value) is not int:raise LiteError('INVALID_VIA_COUNT','过孔行列数必须是整数')
                    values[key]=value
                elif isinstance(value,(tuple,list)):values[key]=[dbu(v,p) for v in value]
                else:values[key]=dbu(value,p)
            old=obj.shape if action=='edit_via' else None
            definition=params.get('definition',old.via_definition if old else None)
            if old and definition==old.via_definition:values={**old.via_parameters,**values}
            origin=tuple(length(key) if key in params else old.origin[i] for i,key in enumerate(('x','y')))
            spec=Shape(kind='stdVia',origin=origin,orientation=params.get('orientation',old.orientation if old else 'R0'),
                via_definition=definition,via_parameters=values,net_intent=params.get('net_intent',old.net_intent if old else None))
            if action=='create_via':uid=e.create(spec)
            else:e.apply([Operation(action='update',uid=uid,before=digest(obj.semantic()),shape=spec)])
        elif action=='move':
            delta=(length('dx'),length('dy'))
            if obj.placement:e.place(uid,tuple(a+b for a,b in zip(obj.placement.origin,delta)))
            else:e.transform_shape(uid,delta=delta)
        elif action in ('rotate','mirror'):
            if action=='rotate':
                angle=params.get('degrees',90)
                if type(angle) is not int or angle not in (-90,90,180,270):raise LiteError('INVALID_ROTATION','仅支持相对 ±90°、180°、270°')
                orientation={-90:'R270',90:'R90',180:'R180',270:'R270'}[angle]
            else:
                if params.get('axis') not in ('X','Y'):raise LiteError('INVALID_MIRROR_AXIS')
                orientation='M'+params['axis']
            pivot=tuple(dbu(v,p) for v in params['pivot']) if params.get('pivot') is not None else anchor(obj)
            if obj.placement:
                offset=tuple(v-b for v,b in zip(obj.placement.origin,pivot));rotated=point(offset,transform((0,0),orientation))
                e.place(uid,tuple(v+b for v,b in zip(rotated,pivot)),orientation_after(obj.placement.orientation,orientation))
            else:e.transform_shape(uid,orientation=orientation,pivot=pivot)
        elif action=='set_width':e.edit(uid,width=native_width(obj.shape))
        elif action=='edit_rect':
            x,y=xy();e.edit(uid,bbox=((x,y),(x+length('width'),y+length('height'))),lpp=params.get('lpp',obj.shape.lpp),net_intent=params.get('net_intent',obj.shape.net_intent))
        elif action in ('edit_path90','edit_path45'):
            points=pts();changes={'points':points,'width':native_width(obj.shape,points),'lpp':params.get('lpp',obj.shape.lpp)}
            changes.update(wire_ends(obj.kind,params,p,shape=obj.shape,points=points))
            if 'net_intent' in params:changes['net_intent']=params['net_intent']
            e.edit(uid,**changes)
        elif action=='edit_path_ends':e.edit(uid,**wire_ends(obj.kind,params,p,shape=obj.shape))
        elif action=='edit_polygon':e.edit(uid,points=pts(),lpp=params.get('lpp',obj.shape.lpp),net_intent=params.get('net_intent',obj.shape.net_intent))
        elif action=='place_instance':e.place(uid,xy(),params.get('orientation',obj.placement.orientation))
        elif action=='set_net_intent':e.edit(uid,net_intent=params['net_intent'])
        elif action=='reset_via':
            names=params['names'];defaults=p.vias[obj.shape.via_definition]['defaults']
            if not isinstance(names,(list,tuple)) or not names or any(not isinstance(n,str) or n not in defaults for n in names):
                raise LiteError('INVALID_VIA_PARAMETER_NAMES','请选择该过孔定义实际存在的参数。')
            e.reset_via_parameters(uid,names)
        elif action=='copy':
            if params.get('orientation','R0') not in ORIENT:raise LiteError('INVALID_ORIENTATION')
            pivot=tuple(dbu(v,p) for v in params['pivot']) if params.get('pivot') is not None else anchor(obj)
            uid=e.copy_shape(uid,delta=(length('dx'),length('dy')),orientation=params.get('orientation','R0'),pivot=pivot)
        elif action=='delete':e.delete(uid)
        elif action=='delete_guard':e.delete_guard(obj.uid if obj.mpp else obj.group_uid)
        elif action=='create_guard':
            if adapter is None:raise LiteError('NATIVE_GENERATOR_REQUIRED')
            from .guard_ports import required_net
            x,y=xy();uid=adapter.guard_preview(e,bbox=((x,y),(x+length('width'),y+length('height'))),template=params['template'],net_intent=required_net(params.get('net_intent')),**({'progress':progress} if progress else {}))
        elif action=='create_mpp':
            if adapter is None:raise LiteError('NATIVE_ADAPTER_REQUIRED')
            from .guard_ports import required_net
            uid=adapter.guard_preview(e,points=pts(),template=params['template'],net_intent=required_net(params.get('net_intent')),**({'progress':progress} if progress else {}))
        else:raise LiteError('UNIMPLEMENTED_ACTION',action)
        after_obj=projected(e.w).get(uid)
        new_ops={o.uid:o for o in e.w.operations}
        changed={key for key in old_ops.keys()|new_ops.keys() if old_ops.get(key)!=new_ops.get(key)}|({uid} if uid else set())
        if action=='delete_guard':changed.add(obj.uid if obj.mpp else obj.group_uid)
        return ActionResult(action,uid,changed,before,describe(after_obj,p) if action!='create_guard' else f'已生成原生保护环 {uid}',
                            e.w.revision!=start_revision,[o.model_dump() for o in e.w.operations])

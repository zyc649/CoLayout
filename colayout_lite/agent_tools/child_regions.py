"""Own-frame and direct-child management through shared commands; no recursive access."""

from typing import Literal
from pydantic import Field, model_validator, ValidationError
from ..layout_helpers.contracts import Parameters
from ..model import LiteError
from ..actions import dbu
from ..regions.actions import RegionActions
from ..regions.query import metals
from ..frame_edit import FrameEdit
from ..human_edit import HumanEdit
from ..pin_placement import center


class CreateRegion(Parameters):
    bounds_um: tuple[float, float, float, float]
    name: str = Field(default='', max_length=200)
    note: str = Field(default='', max_length=20000)
    pin_mode: Literal['fixed', 'directional'] = 'fixed'
    blocked_layers: list[str] | None = None


class RegionProperties(Parameters):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=20000)
    pin_mode: Literal['fixed', 'directional'] | None = None
    blocked_layers: list[str] | None = None


class Bounds(Parameters):
    bounds_um: tuple[float, float, float, float]


class Tighten(Parameters):
    padding_um: float = Field(default=0,ge=0,description='Extra margin in µm, added to automatic PIN clearance: half the largest own/direct-child PIN dimension per axis plus 10% (at least one grid step), rounded outward. Only shrinks within the original frame. Native geometry and PIN mode are preserved.')


class PinEscapes(Parameters):
    width_um: float = Field(gt=0,description='Requested corridor width in µm, rounded outward to the manufacturing grid; PIN metal layers are preserved.')


class PinProperties(Parameters):
    pin_id: str
    x: float | None = None
    y: float | None = None
    layer: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)

    @model_validator(mode='after')
    def pairs(self):
        if (self.x is None) != (self.y is None) or (self.width is None) != (self.height is None):
            raise ValueError('x/y and width/height must each be supplied together')
        return self


class Keepout(Bounds):
    layers: list[str] | None = None
    note: str = ''


class CopyPin(Parameters):
    pin_id: str
    x: float | None = None
    y: float | None = None

    @model_validator(mode='after')
    def pairs(self):
        if (self.x is None)!=(self.y is None):raise ValueError('x/y must be supplied together')
        return self


class KeepoutProperties(Parameters):
    layers: list[str] | None = None
    note: str | None = None


class Empty(Parameters):
    pass


class NativePolicy(Parameters):
    layers: list[str]


class CreateNativeWindow(Bounds):
    layers:list[str]=Field(min_length=1,max_length=128)
    name:str=Field(default='布线豁免',min_length=1,max_length=200)
    note:str=Field(default='',max_length=20000)
    enabled:bool=True


class SetNativeWindow(Parameters):
    bounds_um:tuple[float,float,float,float]|None=None
    layers:list[str]|None=Field(default=None,min_length=1,max_length=128)
    name:str|None=Field(default=None,min_length=1,max_length=200)
    note:str|None=Field(default=None,max_length=20000)
    enabled:bool|None=None


MODELS = {
    'create_native_pin_escapes': PinEscapes,
    'create_native_routing_window': CreateNativeWindow,
    'set_native_routing_window': SetNativeWindow,
    'delete_native_routing_window': Empty,
    'set_native_blocked_layers': NativePolicy,
    'create_child_region': CreateRegion,
    'set_child_region': RegionProperties,
    'resize_child_region': Bounds,
    'tighten_child_region': Tighten,
    'set_child_pin': PinProperties,
    'copy_child_pin': CopyPin,
    'dissolve_child_region': Empty,
    'create_keepout': Keepout,
    'resize_keepout': Bounds,
    'set_keepout': KeepoutProperties,
    'delete_keepout': Empty,
}

OWN_ACTIONS = {
    'set_region':'set_child_region',
    'resize_region':'resize_child_region',
    'tighten_region':'tighten_child_region',
    'set_region_pin':'set_child_pin',
    'copy_region_pin':'copy_child_pin',
}
MODELS.update({name:MODELS[target] for name,target in OWN_ACTIONS.items()})


def execute(editor, action, params, uid):
    try:
        args = MODELS[action].model_validate(params)
    except ValidationError as exc:
        raise LiteError('INVALID_ARGUMENTS', str(exc), edit_applied=False) from exc
    if action=='create_native_pin_escapes':
        from ..native_routing_windows import NativeRoutingWindows
        if not uid:raise LiteError('OBJECT_ID_REQUIRED')
        return NativeRoutingWindows(editor).auto_escape_um(uid,args.width_um)
    if action.endswith('_native_routing_window'):
        from ..native_routing_windows import NativeRoutingWindows,describe
        service=NativeRoutingWindows(editor)
        if not uid:raise LiteError('OBJECT_ID_REQUIRED')
        b=None
        if getattr(args,'bounds_um',None) is not None:
            b=tuple(dbu(v,editor.profile) for v in args.bounds_um)
            if b[0]>=b[2] or b[1]>=b[3]:raise LiteError('INVALID_BOUNDS')
        if action=='create_native_routing_window':
            ident=service.create(uid,b,args.layers,name=args.name,note=args.note,enabled=args.enabled)
        elif action=='set_native_routing_window':
            ident=uid;service.update(ident,bounds=b,layers=args.layers,name=args.name,note=args.note,enabled=args.enabled)
        else:
            service.delete(uid)
            return {'created_uids':[],'deleted_uids':[uid],'native_geometry_changed':False}
        row=editor.w.local_data.native_routing_windows[ident]
        return {'created_uids':[ident] if action.startswith('create_') else [],
                'changed_uids':[row.owner_uid,ident],'native_geometry_changed':False,
                'routing_window':describe(editor.w,row,editor.profile)}
    local = editor.w.local_data
    scope = editor.scope_id
    actions = RegionActions(editor)
    own = action in OWN_ACTIONS
    if own:
        if uid not in (None,scope):
            raise LiteError('OWN_REGION_REQUIRED','此动作只能作用于当前接入操作区。',uid=uid)
        uid = scope
        action = OWN_ACTIONS[action]
    if action == 'set_native_blocked_layers':
        from .inspection import direct_ids

        if uid not in direct_ids(editor.w, scope):
            raise LiteError('OBJECT_OUTSIDE_REGION', uid=uid)
        actions.native_policy(uid, args.layers)
        return {
            'created_uids': [],
            'changed_uids': [uid],
            'blocked_layers': list(args.layers),
            'native_geometry_changed': False,
        }

    def bounds(values):
        b = tuple(dbu(v, editor.profile) for v in values)
        if b[0] >= b[2] or b[1] >= b[3]:
            raise LiteError('INVALID_BOUNDS', '范围须按左下、右上顺序且面积为正。')
        parent_id = local.regions[scope].parent_id if own else scope
        parent = local.regions.get(parent_id)
        from ..regions.models import contains

        if parent is not None and not contains(parent.bbox, (b[:2], b[2:])):
            raise LiteError('REGION_OUTSIDE_PARENT', region_id=parent_id, bounds_um=list(values))
        return b

    if action.startswith('create_'):
        if uid is not None:
            raise LiteError('CREATE_UID_ASSIGNED_BY_APP')
        b = bounds(args.bounds_um)
        if action == 'create_child_region':
            uid = actions.create(b, args.name, parent_id=scope)
            actions.update_details(
                uid,
                args.name or editor.w.local_data.regions[uid].name,
                args.note,
                args.blocked_layers if args.blocked_layers is not None else metals(editor.profile),
            )
            actions.set_pin_mode(uid, args.pin_mode)
            return {
                'created_uids': [uid],
                'region_id': uid,
                'claimable': True,
                'scope': 'direct child only',
                'bounds_um':[v/editor.profile.dbu_per_micron for point in editor.w.local_data.regions[uid].bbox for v in point],
                'frame_snap':'outward_to_manufacturing_grid',
            }
        uid = actions.add_keepout(b, args.layers, args.note)
        if editor.w.local_data.keepouts[uid].scope_id != scope:
            raise LiteError('KEEP_OUTSIDE_EDIT_LEVEL', '禁布框不能作为本层编辑写入子模块内部。')
        return {'created_uids': [uid]}
    if action.endswith('keepout'):
        row = local.keepouts.get(uid)
        if row is None or row.scope_id != scope:
            raise LiteError('OBJECT_OUTSIDE_REGION', uid=uid)
        if action == 'resize_keepout':
            b = bounds(args.bounds_um)
            FrameEdit(editor).resize(uid, (b[:2], b[2:]))
            if editor.w.local_data.keepouts[uid].scope_id != scope:
                raise LiteError('KEEP_OUTSIDE_EDIT_LEVEL')
        elif action == 'set_keepout':
            actions.update_box(
                uid,
                row.note if args.note is None else args.note,
                row.layers if args.layers is None else args.layers,
            )
        else:
            actions.remove_box(uid)
        return {'changed_uids': [uid], 'created_uids': []}
    row = local.regions.get(uid)
    if row is None or (not own and row.parent_id != scope):
        raise LiteError(
            'CHILD_REGION_REQUIRED', '只能管理当前层的直接子操作区，不能改自身或再下一层。', uid=uid
        )
    if action=='copy_child_pin':
        pin_id=actions.copy_pin(uid,args.pin_id,
            x=dbu(args.x,editor.profile) if args.x is not None else None,
            y=dbu(args.y,editor.profile) if args.y is not None else None)
        actual=editor.w.local_data.regions[uid].pins[pin_id]
        return {'created_uids':[],'created_pin_ids':[pin_id],'region_id':uid,'pin_id':pin_id,
                'copied_from':args.pin_id,'net':actual.net,'center_um':[v/editor.profile.dbu_per_micron for v in center(actual)]}
    if action == 'tighten_child_region':
        return {'created_uids':[],**FrameEdit(editor).tighten(uid,padding=dbu(args.padding_um,editor.profile))}
    if action == 'resize_child_region':
        b = bounds(args.bounds_um)
        FrameEdit(editor).resize(uid, (b[:2], b[2:]))
    elif action == 'set_child_region':
        actions.update_details(
            uid,
            row.name if args.name is None else args.name,
            row.note if args.note is None else args.note,
            row.blocked_layers if args.blocked_layers is None else args.blocked_layers,
        )
        if args.pin_mode is not None:
            actions.set_pin_mode(uid, args.pin_mode)
    elif action == 'set_child_pin':
        pin = row.pins.get(args.pin_id)
        if pin is None:
            raise LiteError('CHILD_PIN_REQUIRED', pin_id=args.pin_id, region_id=uid)
        x, y = (
            center(pin)
            if args.x is None
            else (dbu(args.x, editor.profile), dbu(args.y, editor.profile))
        )
        size = (
            None
            if args.width is None
            else (dbu(args.width, editor.profile), dbu(args.height, editor.profile))
        )
        HumanEdit(editor).adjust_pin(
            uid, args.pin_id, x, y, layer=args.layer, name=args.name, size=size
        )
        actual = editor.w.local_data.regions[uid].pins[pin.id]
        return {
            'created_uids': [],
            'region_id': uid,
            'pin_id': pin.id,
            'center_um': [v / editor.profile.dbu_per_micron for v in center(actual)],
            'layer_mode': actual.layer_mode,
            'net': actual.net,
        }
    else:
        actions.dissolve(uid)
    return {'created_uids': [], 'region_id': uid}


def contracts():
    return {
        name: {
            'uid': 'required; direct native blackbox instance' if name=='create_native_pin_escapes' else ('required; direct native blackbox instance' if name=='create_native_routing_window' else 'required; routing window ID')
            if name.endswith('_native_routing_window') else 'omitted or current region ID' if name in OWN_ACTIONS else 'required; direct native blackbox instance'
            if name == 'set_native_blocked_layers'
            else 'omitted; APP assigns ID'
            if name.startswith('create_')
            else 'required; direct child region or current-level keepout',
            'input_schema': model.model_json_schema(),
            'scope': 'assigned region frame/interfaces' if name in OWN_ACTIONS else 'current level only; child internals opaque',
        }
        for name, model in MODELS.items()
    }

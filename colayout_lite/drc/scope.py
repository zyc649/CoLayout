"""One construction level: child regions and hierarchical native modules are opaque."""

from ..editor import projected
from ..hierarchy import is_hierarchical_instance
from ..model import LiteError
from ..regions.models import enclosing_scope
from ..regions.query import owner_map, children
from .models import Region

HIERARCHY_POLICY = 'hierarchical_modules_only_v2'
SERVER_BOUNDARY_POLICY = 'server_input_exclusion_v2'


def authorized_region(workspace, profile, region_id, bounds_um=None):
    area = workspace.local_data.regions[region_id]
    try:
        roi = (
            Region(bbox=area.bbox)
            if bounds_um is None
            else Region.from_um(bounds_um, profile.dbu_per_micron)
        )
    except (ValueError, TypeError) as exc:
        raise LiteError(
            'INVALID_DRC_BOUNDS', '范围须为正面积、顺序正确且落在 DBU 的 [xmin,ymin,xmax,ymax]。'
        ) from exc
    (a, b), (c, d) = area.bbox
    (x, y), (xx, yy) = roi.bbox
    if not (a <= x < xx <= c and b <= y < yy <= d):
        raise LiteError('DRC_OUTSIDE_REGION', '检查范围必须完全位于已接入操作区内。')
    return roi


def selection(workspace, region, scope_id=...):
    if scope_id is ...:
        scope_id = enclosing_scope(workspace.local_data.regions, region.bbox)
    if scope_id is not None and scope_id not in workspace.local_data.regions:
        raise LiteError('REGION_MISSING', str(scope_id))
    owners = owner_map(workspace)
    objects = projected(workspace)
    direct = {uid for uid in objects if owners.get(uid) == scope_id}
    native = {uid for uid in direct if is_hierarchical_instance(workspace, objects[uid])}
    devices = {uid for uid in direct - native if objects[uid].kind in ('inst', 'mosaic')}
    allowed = direct - native
    return allowed, {
        'region_id': scope_id,
        'hierarchy': 'current_level_only',
        'selection_policy': HIERARCHY_POLICY,
        'native_instances_excluded': len(native),
        'native_instance_ids': sorted(native),
        'ordinary_instances_included': len(devices),
        'child_regions_excluded': len(children(workspace, scope_id)),
        'meaning': '本层普通器件与直接几何参与检查；仅直接子操作区和原生嵌套模块内部为黑盒。原生黑盒公开 PIN 仅作为接入上下文；连通性仍核对真实接口。',
    }


def pin_context(workspace, ids, context, checkpoint):
    """Expose cached native interfaces without expanding or checking masters."""
    from ..pin_geometry import pin_geometry
    from ..materials import Physical

    objects = projected(workspace)
    ids = set(ids)
    rows = []
    for pin in workspace.baseline.pins:
        uid = pin.get('instance_uid')
        if uid not in ids:
            continue
        checkpoint()
        try:
            geometry = pin_geometry(
                pin, workspace.baseline.objects[uid].placement, objects[uid].placement
            )
        except (KeyError, ValueError, TypeError):
            continue
        if not geometry.is_empty and geometry.intersects(context):
            rows.append(Physical(uid, pin['lpp'][0], geometry, True))
    return rows

"""Freeze the shared construction-level hierarchy as server exclusion windows."""

from ..editor import projected
from ..model import LiteError
from ..regions.query import children, object_bounds
from .scope import selection
from .remote_deck import validate_windows


def server_scope(workspace, technology, region, scope_id=...):
    _, scope = selection(workspace, region, scope_id)
    from ..scope_state import fingerprint
    scope['fingerprint']=fingerprint(workspace,scope['region_id'])
    objects = projected(workspace)
    rows = []
    for child in sorted(children(workspace, scope['region_id']), key=lambda r: r.id):
        rows.append({'kind': 'child_region', 'id': child.id, 'bbox': child.bbox})
    for uid in scope['native_instance_ids']:
        bounds = object_bounds(workspace, objects[uid], technology)
        if bounds is None:
            raise LiteError('DRC_BLACKBOX_BOUNDS_MISSING', '无法确定原生层次模块黑盒范围。', uid=uid)
        rows.append({'kind': 'native_instance', 'id': uid, 'bbox': bounds})
    for row in rows:
        row['bounds_um'] = [
            value / technology.dbu_per_micron for pt in row.pop('bbox') for value in pt
        ]
    try:
        windows = validate_windows([row['bounds_um'] for row in rows])
    except ValueError as exc:
        raise LiteError('INVALID_DRC_BLACKBOX_BOUNDS', str(exc)) from exc
    # Do not clip to ROI/halo: that would admit internal shapes crossing a crop.
    return windows, {
        **scope,
        'meaning': '本层普通器件参与服务器检查；仅直接子操作区与原生嵌套模块按范围排除内部输入图形。跨黑盒边界的图形保留完整参与检查。',
        'blackboxes': rows,
    }


def association_materials(workspace, technology, region, halo, scope_info=None):
    """Candidate association must not reopen opaque internals or report cache gaps."""
    from ..materials import extract

    allowed = None
    if scope_info is not None:
        allowed, _ = selection(workspace, region, scope_info['region_id'])
    return extract(workspace, technology, region, halo, owner_filter=allowed)

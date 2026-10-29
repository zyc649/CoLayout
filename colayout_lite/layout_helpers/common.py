"""Bounds and scope checks shared by helper commands and UI consumers."""

from ..editor import projected
from ..regions.query import owner_map, object_bounds
from ..model import LiteError


def direct_objects(editor, uids):
    if len(set(uids)) != len(uids):
        raise LiteError('DUPLICATE_OBJECT_ID')
    owners = owner_map(editor.w)
    objects = projected(editor.w)
    for uid in uids:
        region=editor.w.local_data.regions.get(uid)
        if region and region.parent_id==editor.scope_id:
            raise LiteError('HELPER_TARGET_TYPE_UNSUPPORTED','此辅助动作处理本层原生对象；子操作区请用 transform 整体移动/旋转/镜像。',uid=uid,kind='child_region',supported_action='transform')
        if uid not in objects or owners.get(uid) != editor.scope_id:
            raise LiteError('OBJECT_OUTSIDE_REGION', uid=uid)
    return {uid: objects[uid] for uid in uids}


def report_bounds(editor, uids):
    result = []
    scale = editor.profile.dbu_per_micron
    for uid in uids:
        bounds = object_bounds(editor.w, editor.object(uid), editor.profile)
        if bounds:
            result.append((uid, bounds))
    if not result:
        return {'bounds_um': None, 'objects': []}
    return {
        'bounds_um': [
            min(b[0][0] for _, b in result) / scale,
            min(b[0][1] for _, b in result) / scale,
            max(b[1][0] for _, b in result) / scale,
            max(b[1][1] for _, b in result) / scale,
        ],
        'objects': [
            {'uid': uid, 'bounds_um': [v / scale for point in bounds for v in point]}
            for uid, bounds in result
        ],
    }


def reference_bounds(editor, uid):
    local = editor.w.local_data
    region = local.regions.get(uid)
    if region and (uid == editor.scope_id or region.parent_id == editor.scope_id):
        return region.bbox
    markup = local.markups.get(uid)
    if markup and markup.scope_id == editor.scope_id:
        return markup.bbox
    obj = direct_objects(editor, [uid])[uid]
    bounds = object_bounds(editor.w, obj, editor.profile)
    if bounds is None:
        raise LiteError('OBJECT_BOUNDS_MISSING', uid=uid)
    return bounds

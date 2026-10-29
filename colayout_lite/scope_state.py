"""Construction-level identity shared by API requests, jobs and DRC history.

Child contents are deliberately absent. Their frame, public ports and routing
policy are inputs to this level; a native instance exposes its exact public PINs.
"""

from .editor import projected
from .model import digest
from .hierarchy import is_hierarchical_instance
from .regions.query import owner_map, children
from .regions.models import overlaps
from collections import OrderedDict
from threading import RLock
from weakref import ref

_cache = OrderedDict()
_lock = RLock()


def fingerprint(workspace, region_id):
    key = (id(workspace), region_id)
    with _lock:
        entry = _cache.get(key)
        if entry is not None and entry[0]() is workspace:
            _cache.move_to_end(key)
            return entry[1]
    value = _fingerprint(workspace, region_id)
    with _lock:
        _cache[key] = (ref(workspace), value)
        while len(_cache) > 512:
            _cache.popitem(last=False)
    return value


def _fingerprint(workspace, region_id):
    regions = workspace.local_data.regions
    if region_id is not None and region_id not in regions:
        return None
    region = regions.get(region_id)
    objects = projected(workspace)
    owners = owner_map(workspace)
    direct = {
        uid
        for uid in objects
        if owners.get(workspace.baseline.text_owners.get(uid, uid)) == region_id
    }

    def external(row):
        return row.model_dump(exclude={'revision', 'interface_revision', 'object_uids', 'pin_mode'})

    keepouts = {
        key: row.model_dump()
        for key, row in workspace.local_data.keepouts.items()
        if row.scope_id == region_id
        or (
            row.scope_id in ancestors(workspace, region_id)
            and (region is None or overlaps(region.bbox, row.bbox))
        )
    }
    layout = workspace.layout_connectivity
    return digest(
        {
            'workspace': workspace.id,
            'recovery_required': workspace.state in ('submitting', 'indeterminate', 'conflict'),
            'baseline': [
                workspace.baseline.library,
                workspace.baseline.cell,
                workspace.baseline.session,
                workspace.baseline.counter,
            ],
            'region': region.model_dump(exclude={'revision', 'interface_revision'})
            if region
            else None,
            'objects': {uid: objects[uid].model_dump() for uid in sorted(direct)},
            'native_hierarchy': {
                uid: is_hierarchical_instance(workspace, objects[uid])
                for uid in sorted(direct) if objects[uid].kind in ('inst', 'mosaic')
            },
            'children': {r.id: external(r) for r in children(workspace, region_id)},
            'native_pins': [p for p in workspace.baseline.pins if p.get('instance_uid') in direct],
            'native_connections': {
                uid: i.model_dump() for uid, i in layout.instances.items() if uid in direct
            }
            if layout
            else {},
            'markups': {
                key: row.model_dump()
                for key, row in workspace.local_data.markups.items()
                if row.scope_id == region_id
            },
            'keepouts': keepouts,
            'native_policies': {
                uid: layers
                for uid, layers in workspace.local_data.native_blocked_layers.items()
                if uid in direct
            },
            'native_routing_windows': {key:row.model_dump() for key,row in workspace.local_data.native_routing_windows.items()
                                       if row.owner_uid in direct},
        }
    )


def ancestors(workspace, region_id):
    result = {None}
    current = workspace.local_data.regions.get(region_id)
    while current and current.parent_id is not None:
        result.add(current.parent_id)
        current = workspace.local_data.regions.get(current.parent_id)
    return result

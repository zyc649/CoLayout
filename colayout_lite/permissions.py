"""Action-specific exceptions to geometry editing restrictions.

These describe native-verified capabilities; the SKILL writer independently
checks actual database ownership, relationships and locks on every command.
"""
def delete_exception(obj):
    return bool(obj and obj.deletion_allowed and obj.kind in ('rect','polygon','path','pathSeg','stdVia')
        and not obj.group_uid and obj.read_only_reason not in ('pin_geometry','protected_group','native_route_locked','native_parent_child_requires_adapter'))


def apply_profile_permissions(snapshot,profile):
    """Expose the same layer restriction already enforced by Editor.check.

    Standard vias are governed by their definitions. Stronger native ownership
    or lock restrictions remain authoritative. Deletion is a separate native
    capability, as before; this does not broaden the process write-layer list.
    """
    objects=dict(snapshot.objects);changed=False
    for uid,obj in objects.items():
        if obj.read_only_reason not in (None,'layer_not_writable'):continue
        blocked=bool(obj.shape and obj.kind!='stdVia' and obj.shape.lpp not in profile.writable_lpps)
        reason='layer_not_writable' if blocked else None
        if reason!=obj.read_only_reason:
            objects[uid]=obj.model_copy(update={'read_only_reason':reason});changed=True
    return snapshot.model_copy(update={'objects':objects}) if changed else snapshot

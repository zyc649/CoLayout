"""Resolve command/group changes to actual canvas owners, including restorations."""


def affected_owners(requested,rendered,next_objects,*,sources=(),text_owners=None):
    changed=set(requested)
    # Compare to what is actually on the canvas, not just two native baselines.
    # A fresh pull can restore an unchanged server group after a local delete.
    changed.update(set(rendered)^next_objects.keys())
    group_changes=set(changed)
    for objects in (*sources,next_objects):
        changed.update(uid for uid,obj in objects.items() if obj.group_uid in group_changes)
    changed.update(uid for uid,parent in (text_owners or {}).items() if parent in changed)
    return changed

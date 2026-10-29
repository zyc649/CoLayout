"""One display/query boundary for local boxes. Transparency never changes ownership."""
from dataclasses import dataclass
from .regions.query import children,owner_map


@dataclass(frozen=True)
class ViewScope:
    direct_regions:tuple
    nested_regions:tuple
    owners:dict
    open_scopes:frozenset

    def visible(self,uid,text_owners=None):
        return self.owners.get((text_owners or {}).get(uid,uid)) in self.open_scopes


def view_scope(w,scope,peek=False):
    direct=tuple(children(w,scope))
    nested=tuple(c for r in direct for c in children(w,r.id)) if peek else ()
    return ViewScope(direct,nested,owner_map(w),frozenset([scope]+([r.id for r in direct] if peek else [])))


def visible_geometry(w,p,scope,peek=False,*,uids=None,objects=None):
    """One rendering rule for visible owners and ancestor overflight context."""
    from .editor import projected
    from .regions.query import object_bounds
    from .regions.models import overlaps
    objects=projected(w) if objects is None else objects
    view=view_scope(w,scope,peek)
    visible={uid for uid in (objects if uids is None else uids) if view.visible(uid,w.baseline.text_owners)}
    context=set()
    if scope:
        ancestors={None};parent=w.local_data.regions[scope].parent_id
        while parent:ancestors.add(parent);parent=w.local_data.regions[parent].parent_id
        for uid,obj in objects.items():
            if obj.shape and view.owners.get(uid) in ancestors:
                bounds=object_bounds(w,obj,p)
                if bounds and overlaps(bounds,w.local_data.regions[scope].bbox):context.add(uid)
        visible.update(context)
    return view,visible,context

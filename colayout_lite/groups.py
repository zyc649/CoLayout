"""Protected native figGroup metadata and deletion projection."""
from .model import FigureGroup,LiteError


def decode_groups(rows):
    out={}
    for uid,name,kind,origin,orient,ordered,props,members,relations in rows or []:
        if uid in out:raise LiteError('DUPLICATE_FIGGROUP_ID',uid)
        out[uid]=FigureGroup(uid=uid,name=name,kind=kind,origin=tuple(map(int,origin)),orientation=orient,
            ordered=bool(ordered),properties=props or [],members=members or (),relationships=relations or [])
    return out


def projected_groups(w):
    if w.baseline.fig_groups is None:return None
    deleted={op.uid for op in w.operations if op.action=='delete'}
    guards={op.uid for op in w.operations if op.action=='delete_guard'}
    deleted.update(u for u,o in w.baseline.objects.items() if o.group_uid in guards)
    return {k:g.model_copy(update={'members':tuple(u for u in g.members if u not in deleted)}).semantic() for k,g in w.baseline.fig_groups.items()}


def require_groups(snapshot):
    def temporary(value):
        if isinstance(value,str):return value.startswith('session:')
        return isinstance(value,(list,tuple)) and any(temporary(v) for v in value)
    if snapshot.fig_groups is None:raise LiteError('METADATA_UPGRADE_REQUIRED','旧快照缺少 figGroup 信息，请先备份并升级/拉取。')
    for g in snapshot.fig_groups.values():
        if temporary((g.uid,g.members,g.relationships)):raise LiteError('FIGGROUP_IDENTITY_NOT_PREPARED')

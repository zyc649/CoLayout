"""Explicit migration of legacy display/edit metadata, never of geometry.

Legacy snapshots did not carry the route table. Upgrade adopts a fresh native
table only after checking all previously represented source data and preserving
validated pending commands. Normal commit never invokes this migration.
"""
from .model import Workspace,LiteError,digest
from .editor import Editor
from .hierarchy import retain_display


def rebase_mpp(workspace, flat_current, current, profile):
    """Explicit v5→v6 upgrade, checked against the old physical representation.

    Native ROD membership may hide old child identities. Never drop a pending
    child command or reinterpret an old composite-generation payload.
    """
    from .adapter import require_unchanged
    if workspace.state in ('submitting','indeterminate','conflict'):raise LiteError('RECOVERY_REQUIRED')
    if (flat_current.session,flat_current.counter)!=(current.session,current.counter):raise LiteError('SOURCE_CHANGED_DURING_MIGRATION')
    require_unchanged(workspace,flat_current)
    operations=[]
    for op in workspace.operations:
        if op.action in ('guard','delete_guard'):raise LiteError('MPP_LEGACY_DRAFT_REQUIRES_REVIEW','旧保护环草稿已保留，请先备份并核对后重新生成。')
        if op.action!='create':
            before=workspace.baseline.objects[op.uid];after=current.objects.get(op.uid)
            if after is None or after.kind!=before.kind:raise LiteError('MPP_LEGACY_CHILD_COMMAND','旧草稿涉及 MPP 内部对象，不能自动改成整体操作。')
            semantic=before.semantic();legacy={k:v for k,v in semantic.items() if k!='mpp'}
            if op.before not in (digest(semantic),digest(legacy)):raise LiteError('OBJECT_CONFLICT',op.uid)
            op=op.model_copy(update={'before':digest(after.semantic())})
        operations.append(op)
    candidate=workspace.model_copy(update={'baseline':retain_display(workspace.baseline,current),'operations':tuple(operations)})
    Editor(Workspace(baseline=current,profile_id=profile.id),profile).apply(operations)
    return candidate


def rebase_fig_groups(workspace,current,profile):
    """Explicit adoption of previously unrepresented native group context."""
    from .adapter import require_unchanged
    from .groups import require_groups
    if workspace.state in ('submitting','indeterminate','conflict'):raise LiteError('RECOVERY_REQUIRED')
    require_groups(current)
    expected=workspace.baseline if workspace.baseline.fig_groups is not None else workspace.baseline.model_copy(update={'fig_groups':current.fig_groups})
    require_unchanged(workspace.model_copy(update={'baseline':expected}),current)
    candidate=workspace.model_copy(update={'baseline':retain_display(workspace.baseline,current)})
    validator=Editor(Workspace(baseline=current,profile_id=profile.id),profile)
    validator.apply([op for op in candidate.operations if op.action not in ('guard','delete_guard')])
    return candidate


def rebase_custom_caps(workspace,current,profile):
    """Explicit 0.10→0.11 capability migration; preserve all pending edits.

    Formerly opaque caps may become Shapes only if their complete previously
    exported native geometry (including boundary) and both end styles agree.
    All other objects, route relations and dependencies use normal conflict
    validation. No silent adoption of concurrent native edits.
    """
    from copy import deepcopy
    from .adapter import require_unchanged
    if workspace.state in ('submitting','indeterminate','conflict'):raise LiteError('RECOVERY_REQUIRED')
    old=workspace.baseline;objects=dict(old.objects)
    root=old.display.get('nodes',{}).get(old.display.get('root'))
    figures={f[1]:dict(f[7] or []) for f in root[9] or []} if root else {}
    def native_geometry(obj):
        row=deepcopy(obj.native_row)
        if not row:raise LiteError('MIGRATION_NATIVE_ROW_MISSING',obj.uid)
        row[0]=None;row[4]=None
        row[5]=sorted(row[5] or [],key=lambda p:p[0])
        row[6]=sorted((k,v) for k,v in row[6] or [] if k not in ('begin_custom','end_custom'))
        return row
    for uid,before in old.objects.items():
        after=current.objects.get(uid)
        if before.kind=='pathSeg' and before.shape is None and after and after.shape:
            if not any(s in ('custom','chamfer') for s in (after.shape.begin_style,after.shape.end_style)):continue
            if native_geometry(before)!=native_geometry(after):raise LiteError('SOURCE_CONFLICT','倒角线段的原生几何已变化：'+uid)
            styles=figures.get(before.native_id,{})
            if (styles.get('begin_style'),styles.get('end_style'))!=(after.shape.begin_style,after.shape.end_style):
                raise LiteError('SOURCE_CONFLICT','原生端头样式不一致：'+uid)
            if before.read_only_reason!=after.read_only_reason and not (before.read_only_reason or '').startswith('unsupported_geometry:'):
                raise LiteError('SOURCE_CONFLICT','对象权限关系已变化：'+uid)
            objects[uid]=before.model_copy(update={'shape':after.shape,'attributes':{},'read_only_reason':after.read_only_reason})
    expected=old.model_copy(update={'objects':objects})
    require_unchanged(workspace.model_copy(update={'baseline':expected}),current)
    operations=[]
    for op in workspace.operations:
        if op.action in ('update','delete','transform'):
            before=old.objects[op.uid];semantic=before.semantic();legacy=deepcopy(semantic)
            if legacy.get('shape'):
                for field in ('begin_custom','end_custom'):legacy['shape'].pop(field,None)
            if op.before not in (digest(semantic),digest(legacy)):raise LiteError('OBJECT_CONFLICT',op.uid)
            op=op.model_copy(update={'before':digest(current.objects[op.uid].semantic())})
        operations.append(op)
    candidate=workspace.model_copy(update={'baseline':retain_display(old,current),'operations':tuple(operations)})
    validator=Editor(Workspace(baseline=current,profile_id=profile.id),profile)
    validator.apply([op for op in operations if op.action not in ('guard','delete_guard')])
    return candidate

def rebase_metadata(workspace,current,profile):
    from .adapter import require_unchanged
    if workspace.state in ('submitting','indeterminate','conflict'):raise LiteError('RECOVERY_REQUIRED')
    if workspace.baseline.routes is not None:
        require_unchanged(workspace,current)
        return workspace.model_copy(update={'baseline':retain_display(workspace.baseline,current)})
    route_reasons={'native_relationship_requires_adapter','native_route_topology_requires_adapter','native_route_locked'}
    def represented(snapshot):
        objects={}
        for uid,obj in snapshot.objects.items():
            attrs={k:v for k,v in obj.attributes.items() if k!='native_route'}
            old=workspace.baseline.objects.get(uid)
            # Capability changes may reveal an existing unsupported geometry;
            # the actual shape/attributes/properties still must match exactly.
            reason=obj.read_only_reason
            if old and old.read_only_reason in route_reasons:reason=None
            objects[uid]=obj.model_copy(update={'route_uid':None,'attributes':attrs,'read_only_reason':reason})
        return snapshot.model_copy(update={'objects':objects,'routes':None})
    require_unchanged(workspace.model_copy(update={'baseline':represented(workspace.baseline)}),represented(current))
    operations=[]
    for op in workspace.operations:
        if op.action in ('update','delete','transform'):
            old=workspace.baseline.objects[op.uid]
            if old.read_only_reason:raise LiteError('UNSAFE_CAPABILITY_MIGRATION')
            legacy=old.semantic();legacy.pop('route_uid',None)
            if op.before not in (digest(old.semantic()),digest(legacy)):raise LiteError('OBJECT_CONFLICT',op.uid)
            op=op.model_copy(update={'before':digest(current.objects[op.uid].semantic())})
        operations.append(op)
    candidate=workspace.model_copy(update={'baseline':retain_display(workspace.baseline,current),'operations':tuple(operations)})
    validator=Editor(Workspace(baseline=current,profile_id=profile.id),profile)
    validator.apply([o for o in operations if o.action not in ('guard','delete_guard')])
    return candidate

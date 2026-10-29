"""Semantic preconditions and native readback verification; no I/O."""

from .model import LiteError
from .editor import projected
from .hierarchy import same_dependencies


def normalized_vertices(points, closed=False):
    """OA drops interior vertices on a straight run. Preserve bends/reversals."""

    def redundant(a, b, c):
        u = (b[0] - a[0], b[1] - a[1])
        v = (c[0] - b[0], c[1] - b[1])
        return u[0] * v[1] == u[1] * v[0] and u[0] * v[0] + u[1] * v[1] > 0

    result = []
    for point in points:
        result.append(tuple(point))
        while len(result) >= 3 and redundant(*result[-3:]):
            result.pop(-2)
    if closed:
        changed = True
        while changed and len(result) > 3:
            changed = False
            for i in range(len(result)):
                if redundant(result[i - 1], result[i], result[(i + 1) % len(result)]):
                    result.pop(i)
                    changed = True
                    break
    return result


def canonical_object(o):
    data = o.semantic()
    if "connections" in data["attributes"]:
        data["attributes"]["connections"] = sorted(
            data["attributes"]["connections"] or [],
            key=lambda row: tuple("" if v is None else str(v) for v in row),
        )
    if o.shape and o.kind == "polygon":
        p = normalized_vertices(data["shape"]["points"], closed=True)
        data["shape"]["points"] = min(
            tuple(p[i:] + p[:i]) for p in (p, list(reversed(p))) for i in range(len(p))
        )
    elif o.shape and o.kind == "path":
        data["shape"]["points"] = tuple(normalized_vertices(data["shape"]["points"]))
    return data


def require_unchanged(w, current):
    current_semantic = current.semantic()
    baseline_semantic = w.baseline.semantic()
    if current_semantic == baseline_semantic:
        return
    old = w.baseline.objects
    new = current.objects
    changed = [
        uid
        for uid in old.keys() | new.keys()
        if uid not in old
        or uid not in new
        or canonical_object(old[uid]) != canonical_object(new[uid])
    ]
    meta = [
        key
        for key, value in baseline_semantic.items()
        if key != "objects" and value != current_semantic[key]
    ]
    if "dependencies" in meta and same_dependencies(w.baseline, current):
        meta.remove("dependencies")
    if not changed and not meta:
        return
    lines = []
    for uid in changed[:8]:
        a = old.get(uid)
        b = new.get(uid)
        label = (a or b).attributes.get("name", uid[:8])
        detail = (
            "服务器新增" if a is None else "服务器删除" if b is None else "服务器修改"
        )
        if a and b and a.shape and b.shape and a.shape.origin != b.shape.origin:
            scale = w.baseline.dbu_per_micron
            detail += f"：原点 {tuple(v / scale for v in a.shape.origin)} → {tuple(v / scale for v in b.shape.origin)} µm"
        lines.append(f"{label} [{(a or b).kind}] {detail}")
    if meta:
        lines.append("版图结构状态也有变化：" + ", ".join(meta))
    raise LiteError(
        "SOURCE_CONFLICT",
        f"服务器版图与导入基准不同（{len(changed)}个对象）。\n"
        + "\n".join(lines)
        + "\n草稿未丢失。可先备份并拉取，或点击“保留草稿另建副本”；原服务器版图不覆盖。",
        changed=changed,
    )


def verify(w, actual, *, profile=None, require_saved=True):
    if require_saved and actual.dirty:
        raise LiteError('READBACK_NOT_SAVED',
            '原生读回仍有未保存变化，磁盘快照尚未与当前几何一致；不能报告同步成功或启动服务器检查。',
            stage='readback', retryable=False)
    from .routing import projected_routes, route_semantics
    from .groups import projected_groups

    if projected_groups(w) != (
        None
        if actual.fig_groups is None
        else {k: g.semantic() for k, g in actual.fig_groups.items()}
    ):
        raise LiteError("READBACK_FIGGROUPS_CHANGED")
    if projected_routes(w) != route_semantics(actual.routes):
        raise LiteError("READBACK_ROUTES_CHANGED")
    if w.baseline.text_owners and w.baseline.text_owners != actual.text_owners:
        raise LiteError("READBACK_TEXT_ASSOCIATION_CHANGED")
    expected = projected(w, text_owners=w.baseline.text_owners or actual.text_owners)
    if set(expected) != set(actual.objects):
        raise LiteError(
            "READBACK_OBJECT_SET", expected=len(expected), actual=len(actual.objects),
            objects=sorted(set(expected)^set(actual.objects))[:20]
        )
    errors = []
    guard_graphs = {}
    created_guards={op.uid for op in w.operations if op.action=='guard'}
    for uid, obj in expected.items():
        want=canonical_object(obj);got=canonical_object(actual.objects[uid])
        if uid in created_guards:
            want=guard_readback_semantic(obj,actual.objects[uid],want)
        elif want != got and profile is not None and obj.mpp:
            from copy import deepcopy
            enriched=guard_readback_semantic(obj,actual.objects[uid],deepcopy(want))
            # First prove that only previously absent native part net names changed.
            # Geometry, definitions, existing assignments and properties remain exact.
            if enriched==got and guard_net_enrichment_proven(w,obj,actual.objects[uid],profile,guard_graphs):
                want=enriched
        if want != got:
            errors.append(uid)
    if errors:
        raise LiteError(
            "READBACK_OBJECT_MISMATCH",
            "服务器读回有差异："
            + ", ".join(f"{uid} [{expected[uid].kind}]" for uid in errors[:5]),
            objects=errors[:20],
        )
    if not same_dependencies(w.baseline, actual):
        raise LiteError(
            "READBACK_CHILD_MASTER_CHANGED",
            "隐藏模块的内部版本或服务器会话已变化，需要备份草稿并重新拉取。",
        )
    if w.baseline.terminals != actual.terminals:
        raise LiteError("READBACK_TERMINALS_CHANGED")
    if w.baseline.opaque_counts != actual.opaque_counts:
        raise LiteError("READBACK_OPAQUE_COLLECTION_CHANGED")
    if w.baseline.technology_fingerprint != actual.technology_fingerprint:
        raise LiteError("READBACK_TECHNOLOGY_CHANGED")
    return True


def guard_readback_semantic(expected,actual,want):
    """Native ROD may resolve a newly-created unassigned part to the master net.

    Permit only absent -> observed-master-net enrichment after guard creation.
    Existing assignments, terminals, geometry and all definition parameters
    remain strict. Preconditions still use canonical_object without this rule.
    """
    if not expected.mpp or not actual.mpp or not actual.observed_net:return want
    parts=want['mpp']['parts'];actual_parts=actual.mpp.parts
    if len(parts)!=len(actual_parts):return want
    for before,after in zip(parts,actual_parts):
        if (before.get('net_name') is None and after.get('net_name')==actual.observed_net
                and before.get('terminal_name') is None):
            before['net_name']=after['net_name']
    return want


def guard_net_enrichment_proven(workspace, expected, actual, profile, graphs):
    """A saved batch can cause native ROD to annotate an existing connected guard.

    Verify that annotation against Layout PINs in the intended physical snapshot.
    Neither route intent nor the returned annotation is used as connectivity proof.
    This rule is never used by source preconditions or by an empty batch.
    """
    if (not workspace.operations or not expected.mpp or not actual.mpp
            or not actual.observed_net or expected.observed_net not in (None,actual.observed_net)
            or profile.native_fingerprint!=workspace.baseline.technology_fingerprint
            or profile.dbu_per_micron!=workspace.baseline.dbu_per_micron):
        return False
    metals={row['layer'] for row in profile.layers if row.get('material')=='metal'}
    cuts={row['layer'] for row in profile.layers if row.get('material')=='cut'}
    changed=[a for a,b in zip(expected.mpp.parts,actual.mpp.parts)
             if a.get('net_name')!=b.get('net_name')]
    if not changed or any(not p.get('lpp') or p['lpp'][0] not in metals|cuts for p in changed):
        return False
    required_layers={p['lpp'][0] for p in changed if p['lpp'][0] in metals}
    if not required_layers:
        required_layers={p['lpp'][0] for p in expected.mpp.parts if p.get('lpp') and p['lpp'][0] in metals}
    if not required_layers:return False
    from .regions.query import owner_map
    from .region_analysis import scope_graph
    scope=owner_map(workspace).get(expected.uid)
    if scope not in graphs:
        graphs[scope]=scope_graph(workspace,profile,scope)
    graph=graphs[scope]
    if graph['warnings']:return False
    nodes=[n for n in graph['nodes'] if n['owner_uid']==expected.uid and n['layer'] in required_layers]
    if {n['layer'] for n in nodes}!=required_layers:return False
    pins={pin['id']:pin for pin in graph['pins']}
    edited={op.uid for op in workspace.operations if op.action in ('create','update','transform','guard')}
    for component in {node['component_id'] for node in nodes}:
        contacts=[pins[pid] for pid in graph['component_pins'].get(component,())]
        if any(p['net'] is None for p in contacts):return False
        nets={p['net'] for p in contacts if p['net'] is not None}
        native_nets={p['net'] for p in contacts if not p['local'] and p['owner']!=expected.uid and p['net'] is not None}
        if nets!={actual.observed_net} or native_nets!={actual.observed_net}:return False
        if not any(n['component_id']==component and n['owner_uid'] in edited for n in graph['nodes']):
            return False
    return True

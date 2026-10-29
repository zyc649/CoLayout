"""Native route membership is topology metadata, independent of connectivity.

Physical edits may disconnect a route. They must preserve its ordered surviving
members and metadata; physical contiguity is observation, never a sync gate.
"""
from .model import NativeRoute,LiteError

def decode_routes(rows):
    result={}
    for row in rows or []:
        uid,members,status,net,props,start,end,restrictions,contiguous=row[:9]
        if uid in result:raise LiteError('DUPLICATE_ROUTE_ID',uid)
        result[uid]=NativeRoute(uid=uid,members=members or [],status=status,net=net,properties=props or [],
            start=start,end=end,restrictions=restrictions or [],contiguous=bool(contiguous),
            endpoint_details=row[9] if len(row)>9 else None)
    return result

def route_semantics(routes):
    return None if routes is None else {k:NativeRoute.model_validate(v).semantic() for k,v in routes.items()}

def projected_routes(workspace):
    routes=route_semantics(workspace.baseline.routes)
    if routes is None:return None
    deleted={op.uid for op in workspace.operations if op.action=='delete'}
    groups={op.uid for op in workspace.operations if op.action=='delete_guard'}
    deleted.update(uid for uid,o in workspace.baseline.objects.items() if o.group_uid in groups)
    return {key:{**value,'members':tuple(u for u in value['members'] if u not in deleted)} for key,value in routes.items()}

def validate_membership(snapshot):
    if snapshot.routes is None:return
    seen={};internal={uid:route for obj in snapshot.objects.values() if obj.mpp for uid,route in obj.mpp.member_routes.items()}
    for key,value in snapshot.routes.items():
        route=NativeRoute.model_validate(value)
        if route.uid!=key:raise LiteError('ROUTE_UID_MISMATCH',key)
        for uid in route.members:
            if uid in seen:raise LiteError('DUPLICATE_ROUTE_MEMBERSHIP',uid)
            seen[uid]=key
            if uid not in snapshot.objects:
                if internal.get(uid)!=key:raise LiteError('ROUTE_MEMBER_MISMATCH',uid)
            elif snapshot.objects[uid].route_uid!=key:raise LiteError('ROUTE_MEMBER_MISMATCH',uid)
    for uid,obj in snapshot.objects.items():
        if obj.route_uid and seen.get(uid)!=obj.route_uid:raise LiteError('ROUTE_OWNER_MISMATCH',uid)

def require_persistent_routes(snapshot):
    def temporary(value):
        if isinstance(value,str):return value.startswith('session:')
        return isinstance(value,(list,tuple)) and any(temporary(v) for v in value)
    if snapshot.routes is None:raise LiteError('METADATA_UPGRADE_REQUIRED','此工作区尚无原生 route 数据。请先备份草稿并拉取新版数据，或显式迁移元数据。')
    for route in snapshot.routes.values():
        route=NativeRoute.model_validate(route)
        if temporary((route.uid,route.members,route.start,route.end,route.restrictions)):
            raise LiteError('ROUTE_IDENTITY_NOT_PREPARED','原生 route 引用尚未建立持久身份，需先准备测试副本并重新拉取。')
        if (route.start or route.end) and route.endpoint_details is None:
            raise LiteError('METADATA_UPGRADE_REQUIRED','此快照缺少原生分支连接点信息；请先备份草稿并重新拉取。')

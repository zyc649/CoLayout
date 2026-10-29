"""Versioned selectors shared by structured inspection and screenshot highlights."""

from math import isfinite
from shapely.geometry import Point
from ..model import LiteError


def validate_target(target):
    if target is None:
        return
    if target.kind != 'object' and (target.point_um is not None or target.layer is not None):
        raise LiteError('INVALID_ARGUMENTS', 'point_um/layer 仅用于对象接触点选择。')
    if target.kind != 'component' and target.query_ref is not None:
        raise LiteError('INVALID_ARGUMENTS', 'query_ref 仅与 component 引用一起使用。')


def referenced_component(graph, ident, query_ref):
    if not query_ref or query_ref != graph['query_ref']:
        raise LiteError(
            'COMPONENT_REFERENCE_STALE',
            '分量必须携带当前 net 查询的 query_ref。',
            current_query_ref=graph['query_ref'],
        )
    if ident not in {node['component_id'] for node in graph['nodes']}:
        raise LiteError('COMPONENT_UNKNOWN')
    return {ident}


def object_components(graph, uid, *, point_um=None, layer=None, scale=1, bounds=None):
    if (point_um is None) != (layer is None):
        raise LiteError('COMPONENT_SEED_REQUIRED', '接触点选择需同时提供 point_um 和 layer。')
    nodes = [node for node in graph['nodes'] if node['owner_uid'] == uid]
    if point_um is not None:
        if not all(isfinite(v) for v in point_um):
            raise LiteError('INVALID_COMPONENT_POINT', '接触点必须为有限坐标。')
        x, y = (v * scale for v in point_um)
        if bounds and not (bounds[0][0] <= x <= bounds[1][0] and bounds[0][1] <= y <= bounds[1][1]):
            raise LiteError('COMPONENT_POINT_OUTSIDE_REGION', '接触点超出已接入操作区。')
        point = Point(x, y)
        nodes = [
            node for node in nodes if node['layer'] == layer and node['geometry'].covers(point)
        ]
        components = {node['component_id'] for node in nodes}
        index = {node['id']: node['component_id'] for node in graph['nodes']}
        for edge in graph['edges']:
            if (
                edge['kind'] == 'via'
                and edge.get('via_owner_uid') == uid
                and edge['cut_layer'] == layer
                and edge['geometry'].covers(point)
            ):
                components.update(index[ident] for ident in edge['node_ids'])
        if not components:
            opaque=uid in graph.get('blackbox_ids',set())
            raise LiteError(
                'COMPONENT_SEED_NOT_CONDUCTIVE',
                ('该黑盒的内部几何不在当前查询范围内；此点未命中公开接口。请用公开 PIN ID 或公开 PIN 所在层与接触点查询，不代表内部没有金属。' if opaque else '此对象在指定层与坐标没有可查询的导体；不会改选其他层。'),
                layer=layer,
                point_um=list(point_um),
                **({'query_scope':'public_interfaces_only','public_pin_ids':[p['id'] for p in graph['pins'] if p['owner']==uid]} if opaque else {}),
            )
        if len(components) > 1:
            raise LiteError(
                'COMPONENT_SEED_AMBIGUOUS',
                '此点对应多个隔离的公开接入域，请换接触点或用当前分量引用。',
                components=sorted(components),
            )
        return components
    return {node['component_id'] for node in nodes}

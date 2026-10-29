"""Explain the shared physical graph; never infer connectivity from labels."""

from shapely.geometry import mapping
from shapely.ops import unary_union


def geometry_um(geometry, scale):
    from shapely.affinity import scale as resize

    return mapping(resize(geometry, xfact=1 / scale, yfact=1 / scale, origin=(0, 0)))


def pin_issues(graph, *, limit=256, net=None):
    scale = graph.get('dbu_per_micron', 1)
    conduction = graph.get('report', {}).get('coverage', {}).get('conduction', {})
    gate_layers = set(conduction.get('gate_layers', []))
    metals = set(conduction.get('metal_layers', []))
    material = {}
    for node in graph['nodes']:
        material.setdefault(node['layer'], []).append(node['geometry'])
    material = {layer: unary_union(rows) for layer, rows in material.items()}
    issues = []
    for pin in graph['pins']:
        if net is not None and pin['net'] != net:
            continue
        if pin.get('physical_required') is False:
            continue
        figures = pin.get('contact_figures', pin['figures'])
        original = pin.get('display_figures', pin['figures'])
        layers = {layer for layer, g in figures if not g.is_empty}
        reason = None
        if pin['net'] is None:
            reason, message = (
                'net_unknown',
                'PIN 未归属 Layout 网络，不能确认连接；请由人核对原生网络。',
            )
        elif not figures or all(g.is_empty for _, g in figures):
            reason, message = (
                'geometry_missing',
                'PIN 缺少有效接入几何，不能确认连接；请由人核对接口配置或刷新原生数据。',
            )
        elif layers & gate_layers and not layers & metals:
            reason, message = (
                'gate_requires_metal',
                '该 PIN 仅有 Gate/GT 接入，尚无可用金属接入；请由人补充金属引出后再交给 Agent 连接。',
            )
        elif not graph['pin_components'].get(pin['id']):
            reason, message = 'unattached', 'PIN 的有效接入区域尚未接触实际导体。'
        elif pin['id'] in graph['partial_pin_ids']:
            reason, message = (
                'partial_coverage',
                '已接触导体，但尚未完整覆盖有效接入区域；请检查 missing_geometry_um。',
            )
        if reason in ('unattached','partial_coverage') and pin['id'] in graph.get('optional_pin_ids',set()):
            reason=None
        if reason is None:
            continue
        row = {
            'pin_id': pin['id'],
            'pin_name': pin.get('display_name',pin.get('label', pin['id'])),
            'owner_name':pin.get('owner_name'),
            'owner': pin.get('owner'),
            'net': pin['net'],
            'reason': reason,
            'message': message,
            'coordinates': 'workspace_um',
            'components': sorted(graph['pin_components'].get(pin['id'], ())),
            'figures': [],
            'layer_mode':pin.get('layer_mode','single'),
            'coverage_mode':'any_layer' if pin.get('layer_mode')=='any_metal' else 'all_figures',
        }
        for index, (layer, g) in enumerate(figures if len(issues) < limit else []):
            if g.is_empty:
                continue
            metal = material.get(layer)
            missing = g if metal is None else g.difference(metal)
            covered = None if metal is None else g.intersection(metal)
            row['figures'].append(
                {
                    'figure_index': index,
                    'layer': layer,
                    'alternative_layer':pin.get('layer_mode')=='any_metal',
                    'effective_bounds_um': [v / scale for v in g.bounds],
                    'effective_geometry_um': geometry_um(g, scale),
                    'missing_geometry_um': geometry_um(missing, scale),
                    'covered_area_um2': 0 if covered is None else covered.area / scale**2,
                    'required_area_um2': g.area / scale**2,
                    'missing_area_um2': missing.area / scale**2,
                }
            )
        row['display_bounds_um'] = [
            [v / scale for v in g.bounds] for _, g in original if not g.is_empty
        ]
        if pin['local']:
            row['coverage_rule'] = (
                ('任意一层金属完整覆盖即可；各图层是备选，不要求全部覆盖。' if pin.get('layer_mode')=='any_metal' else '')+
                '本区域接口仅检查边界内的有效部分；子模块接口检查本层可接入的一侧。虚拟标记不能连接导体孤岛。'
            )
            if pin.get('access_configuration_issue'):
                row['access_configuration_issue']=pin['access_configuration_issue']
        issues.append(row)
    preparation = [
        {k: row[k] for k in ('pin_id', 'pin_name', 'owner', 'net', 'reason', 'message')}
        for row in issues
        if row['reason'] in ('net_unknown', 'geometry_missing', 'gate_requires_metal')
    ]
    return {
        'pin_issues': issues[:limit],
        'preparation_issues': preparation,
        'pin_issue_count': len(issues),
        'diagnostics_truncated': len(issues) > limit,
    }

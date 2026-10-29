"""Shared current-region connectivity and local checks; no router or GUI dependency."""

from collections import defaultdict
from .inspection_data import build_scope_graph
from .net_selection import index_contacts
from .interface_access import scoped_figures
from .drc.models import Region
from .drc.local import run
from .regions.query import members
from .model import digest


def scope_graph(w, p, scope):
    graph = build_scope_graph(w, p, scope, False)
    if scope:
        from .regions.query import boundary
        graph['warnings'] += [{'kind':'deferred_reference_interface','net':row['net'],
            'message':row['reason'],'region_id':scope} for row in boundary(w,scope).get('deferred',[])]
    graph['directional_markers'] = [pin for pin in graph['pins'] if pin.get('physical_required') is False]
    graph['pins'] = [pin for pin in graph['pins'] if pin.get('physical_required') is not False]
    graph['pins'] = [{**pin, 'display_figures': pin['figures'],
                      'figures': scoped_figures(w, scope, pin)} for pin in graph['pins']]
    graph['dbu_per_micron'] = p.dbu_per_micron
    graph['query_context'] = {'document_id': w.id, 'revision': w.revision, 'region_id': scope,
                             'baseline_session': w.baseline.session, 'baseline_counter': w.baseline.counter,
                             'technology_fingerprint': p.native_fingerprint}
    # Component numbers are runtime projections, not durable identities. Bind
    # the reference to their actual assignment as well as the document stamp.
    assignment=sorted((node['component_id'],node['owner_uid'],node['layer'],node['geometry'].wkb_hex)
                      for node in graph['nodes'])
    from .scope_state import fingerprint
    graph['query_ref'] = digest([fingerprint(w,scope),p.native_fingerprint,assignment])
    graph['pin_mode'] = w.local_data.regions[scope].pin_mode if scope else 'fixed'
    index_contacts(graph)
    return graph


def connectivity(graph):
    from .connection_diagnostics import pin_issues
    diagnostics = pin_issues(graph)
    preparation = diagnostics.pop('preparation_issues')
    nets = defaultdict(list)
    unresolved = [
        {
            'id': pin['id'],
            'name': pin.get('display_name',pin.get('label', pin['id'])),
            'net': pin['net'],
            'reason': 'PIN 未归属 Layout 网络' if pin['net'] is None else 'PIN 缺少几何',
        }
        for pin in graph['pins']
        if pin['net'] is None or not pin['figures']
    ]
    known = {row['id'] for row in unresolved}
    unresolved += [{'id': row['pin_id'], 'name': row['pin_name'], 'net': row['net'],
                    'reason': row['message'], 'reason_code': row['reason']}
                   for row in preparation if row['pin_id'] not in known]
    for pin in graph['pins']:
        if pin['net'] is None:
            continue
        nets[pin['net']].append(pin['id'])
    rows = []
    for name, ids in sorted(nets.items()):
        from .interface_contacts import component_count
        components = set().union(*(graph['pin_components'].get(pid, set()) for pid in ids))
        optional=graph.get('optional_pin_ids',set())
        missing = [pid for pid in ids if not graph['pin_components'].get(pid) and pid not in optional]
        partial = sorted((set(ids) & graph['partial_pin_ids'])-optional)
        links=[g for g in graph.get('interface_contact_groups',[]) if g['net']==name]
        count=component_count(components,links)
        rows.append(
            {
                'net': name,
                'pins': ids,
                'components': sorted(components),
                'logical_component_count':count,
                'child_interface_links':links,
                'optional_pin_ids':sorted(set(ids)&optional),
                'unattached': missing,
                'components_detail': [
                    {
                        'id': cid,
                        'pin_ids': sorted(set(ids) & graph['component_pins'].get(cid, set())),
                    }
                    for cid in sorted(components)
                ],
                'partial': partial,
                'connected': count == 1 and not missing and not partial
                and not any(row['net'] == name for row in unresolved),
            }
        )
    shorts = []
    pin_nets = {pin['id']: pin['net'] for pin in graph['pins']}
    pin_names = {pin['id']: pin.get('display_name',pin.get('label',pin['id'])) for pin in graph['pins']}
    for cid, ids in graph['component_pins'].items():
        names = {pin_nets[pid] for pid in ids if pin_nets[pid] is not None}
        if len(names) > 1:
            bounds=[node['geometry'].bounds for node in graph['nodes'] if node['component_id']==cid]
            scale=graph.get('dbu_per_micron',1)
            shorts.append({'component': cid, 'nets': sorted(names), 'pin_ids': sorted(ids),
                'pin_names':[pin_names[pid] for pid in sorted(ids)],
                'bounds_um':[min(b[0] for b in bounds)/scale,min(b[1] for b in bounds)/scale,
                             max(b[2] for b in bounds)/scale,max(b[3] for b in bounds)/scale] if bounds else None,
                'location_basis':'physical component bounds; not an inferred short point'})
    conflicted={name for short in shorts for name in short['nets']}
    for row in rows:
        row['shorted']=row['net'] in conflicted
        if row['shorted']:row['connected']=False
        by_id={pin['id']:pin for pin in graph['pins']}
        row['pin_labels']=[{'id':pid,'owner':by_id[pid].get('owner'),'owner_name':by_id[pid].get('owner_name'),
            'name':by_id[pid].get('name',by_id[pid]['label']),'display_name':by_id[pid].get('display_name',by_id[pid]['label'])} for pid in row['pins']]
    return {
        **graph.get('query_context', {}),
        'query_ref': graph.get('query_ref'),
        'component_reference_scope': 'component IDs are valid only for this query_ref and construction-level content; unrelated region edits do not expire them',
        'pin_mode': graph.get('pin_mode', 'fixed'),
        'directional_markers': [{'id': pin['id'], 'name': pin['label'], 'net': pin['net'],
                                 'side': pin.get('side'), 'physical_required': False}
                                for pin in graph.get('directional_markers', [])],
        **diagnostics,
        'nets': rows,
        'shorts': shorts,
        'warnings': graph['warnings'],
        'unresolved_pins': unresolved,
        'connected_nets': sum(row['connected'] for row in rows),
        'total_nets': len(rows),
        'complete': bool(rows)
        and all(r['connected'] for r in rows)
        and not shorts
        and not graph['warnings']
        and not unresolved,
    }


def analyze(w, p, drc, region_id, *, bounds_um=None):
    from .drc.design_warnings import blocking
    from .drc.reporting import report_payload
    graph = scope_graph(w, p, region_id)
    connections = connectivity(graph)
    region = w.local_data.regions[region_id]
    from .drc.scope import authorized_region
    roi=authorized_region(w,p,region_id,bounds_um)
    full=roi.bbox==region.bbox
    report = report_payload(run(w, p, drc, roi, scope_id=region_id))
    # Keep rule evidence, but do not expose editable identities in neighbouring
    # regions which happen to be in the DRC halo.
    owned = set(members(w, region_id))
    for marker in report['markers']:
        marker['objects'] = [
            o if o.get('uid') in owned else {'outside_region': True, 'kind': o.get('kind')}
            for o in marker['objects']
        ]
    return {
        'passed': connections['complete']
        and not any(blocking(marker) for marker in report['markers'])
        and report['coverage']['complete_for_configured_subset'],
        'revision': w.revision,
        'region_id': region_id,
        'completion_eligible': full,
        'check_scope': 'region' if full else 'roi',
        'bounds_um': [v/p.dbu_per_micron for point in roi.bbox for v in point],
        'connectivity': connections,
        'drc': report,
        'summary': (('全区检查完成' if full else '局部 DRC 完成（不用于全区完成验收）')+'；全区连通'+('通过' if connections['complete'] else '未完成')+
                    f"；工艺错误 {report['counts']['technology_errors']}；工艺提醒 {report['counts']['technology_warnings']}；设计 warning {report['counts']['design_warnings']}"+
                    ('' if report['coverage']['complete_for_configured_subset'] else '；存在未覆盖的检查内容')),
        'boundary': 'Layout PIN connectivity + configured local DRC; schematic is reference only',
        'pin_mode': region.pin_mode,
        'completion_scope': ('方位 PIN 模式：检查内部真实连接；本区域边缘标记不要求物理接入。'
                             if region.pin_mode == 'directional' else '固定 PIN 模式：内部和固定接口均须满足连接要求。'),
    }

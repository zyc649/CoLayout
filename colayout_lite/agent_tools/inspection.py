"""Bounded views over the human workspace; Layout defines every net target."""

from ..editor import projected
from ..regions.query import owner_map, children, object_bounds
from ..inspection_data import scope_pins
from ..region_analysis import scope_graph, connectivity
from ..actions import availability
from ..commands import COMMANDS
from .contract import EDIT_ACTIONS
from .discovery import helper_contracts


def direct_ids(w, region_id):
    owners = owner_map(w)
    return {
        uid
        for uid in projected(w)
        if owners.get(uid) == region_id and uid not in w.baseline.text_owners
    }


def bbox_um(bounds, scale):
    return (
        [bounds[0][0] / scale, bounds[0][1] / scale, bounds[1][0] / scale, bounds[1][1] / scale]
        if bounds
        else None
    )


def editable_actions(obj):
    return sorted(name for name in EDIT_ACTIONS if name in COMMANDS and not name.startswith('create_') and availability(name,obj)[0])


def layout(w, p, region_id, *, detail='full', uids=None, pin_ids=None,bounds_um=None,layers=None):
    from .layout_query import selection, markup_rows, pin_row
    from collections import Counter
    region = w.local_data.regions[region_id]
    from .spatial_query import SpatialQuery
    query=SpatialQuery(w,p,region_id,bounds_um,layers)
    scale = p.dbu_per_micron
    objects = projected(w)
    ids = direct_ids(w, region_id)
    all_pins, warnings = scope_pins(w, p, region_id, False)
    pin_counts=Counter(pin['owner'] for pin in all_pins)
    child_rows = children(w, region_id)
    markups = markup_rows(w, region_id, scale)
    keepouts=[{'uid':k.id,'kind':'keepout','bounds_um':bbox_um(k.bbox,scale),'layers':list(k.layers),'note':k.note,
        'actions':['resize_keepout','set_keepout','delete_keepout']} for k in w.local_data.keepouts.values() if k.scope_id==region_id]
    from ..native_routing_windows import describe
    windows=[{'uid':row.id,'kind':'native_routing_window',**describe(w,row,p,objects)}
             for row in w.local_data.native_routing_windows.values() if row.owner_uid in ids]
    selected, selected_pins = selection(ids, child_rows, markups+keepouts+windows, all_pins, uids, pin_ids)
    selected.update(row['id'] for row in windows if row['owner_uid'] in selected)
    matches={}
    pin_matches={}
    if query.active:
        matches={uid:match for uid in ids & selected if (match:=query.object_match(w,p,objects[uid])) is not None}
        context_ids={r.id for r in child_rows if r.id in selected and query.bounds_match(r.bbox)}
        context_ids.update(row['uid'] for row in markups+keepouts if row['uid'] in selected and query.bounds_match((tuple(v*scale for v in row['bounds_um'][:2]),tuple(v*scale for v in row['bounds_um'][2:]))))
        context_ids.update(row['id'] for row in windows if row['id'] in selected
            and (layers is None or set(layers)&set(row['layers']))
            and query.bounds_match((tuple(v*scale for v in row['effective_bounds_um'][:2]),tuple(v*scale for v in row['effective_bounds_um'][2:]))))
        selected=set(matches)|context_ids
        pin_matches={pin['id']:found for pin in all_pins if pin['id'] in selected_pins and (found:=query.figures_match(pin['figures']))}
        selected_pins=set(pin_matches)
    rows = []
    for uid in sorted(ids & selected):
        obj = objects[uid]
        row = {
            'uid': uid,
            'kind': obj.kind,
            'name': obj.attributes.get('name'),
            'bbox_um': bbox_um(object_bounds(w, obj, p), scale),
            'read_only_reason': obj.read_only_reason,
        }
        if obj.placement:
            row['placement'] = {
                'x': obj.placement.origin[0] / scale,
                'y': obj.placement.origin[1] / scale,
                'orientation': obj.placement.orientation,
            }
        if pin_counts[uid]:row['pin_count']=pin_counts[uid]
        if detail == 'full' and obj.kind in ('inst', 'mosaic'):
            row['parameters'] = obj.attributes.get('parameters', [])
        if detail == 'full' and obj.shape:
            row['shape_dbu'] = obj.shape.model_dump(mode='json')
        inst = w.layout_connectivity.instances.get(uid) if w.layout_connectivity else None
        if inst:
            row['master'] = inst.master
            row['black_box'] = inst.black_box
        row['actions'] = editable_actions(obj)
        if inst and inst.black_box:
            from ..regions.query import metals
            row['blocked_layers']=list(w.local_data.native_blocked_layers.get(uid,metals(p)))
            row['actions'].append('set_native_blocked_layers')
            row['actions'].append('create_native_routing_window')
            row['actions'].append('create_native_pin_escapes')
            row['routing_window_ids']=[r['id'] for r in windows if r['owner_uid']==uid]
        rows.append(row)
        if query.active:row['query_match']=matches[uid]
    pins = [pin for pin in all_pins if pin['id'] in selected_pins]
    omit_native_pins=detail=='summary' and uids is None and pin_ids is None and not query.active
    if omit_native_pins:pins=[pin for pin in pins if pin['local']]
    result = {
        'document_id': w.id,
        'revision': w.revision,
        'region_id': region_id,
        'deferred_interfaces': deferred_interfaces(w,region_id),
        'name': region.name,
        'pin_mode': region.pin_mode,
        'bounds_um': bbox_um(region.bbox, scale),
        'coordinates': 'workspace_um',
        'dbu_per_micron': scale,
        'bbox_semantics':'outward DBU envelope; child-region creation rounds the frame outward to the manufacturing grid',
        'note': region.note,
        'region_actions':['set_region','resize_region','tighten_region','set_region_pin','copy_region_pin'],
        'detail': detail,
        'filtered': uids is not None or pin_ids is not None or query.active,
        'omitted': (['objects.parameters', 'objects.shape_dbu', 'pins.figures']+
                    (['native PIN details; query by object uids or pin_ids'] if omit_native_pins else [])) if detail == 'summary' else [],
        'native_pin_details_omitted':omit_native_pins,
        'total_counts': {'objects': len(ids), 'children': len(child_rows), 'pins': len(all_pins), 'markups': len(markups)},
        'markups': [row for row in markups if row['uid'] in selected],
        'keepouts': [row for row in keepouts if row['uid'] in selected],
        'native_routing_windows':[row for row in windows if row['id'] in selected],
        'objects': rows,
        'children': [
            {
                'uid': r.id,
                'name': r.name,
                'bounds_um': bbox_um(r.bbox, scale),
                'blocked_layers': r.blocked_layers,
                'pin_mode': r.pin_mode,
                'pin_count': len(r.pins),
                'actions': ['transform','set_child_region','resize_child_region','tighten_child_region','set_child_pin','copy_child_pin','dissolve_child_region'],
                'internal_access':'blackbox; a separate agent may claim this region_id to work inside',
                'region_id':r.id,
            }
            for r in child_rows if r.id in selected
        ],
        'pins': [pin_row(pin, scale, detail) for pin in pins],
        'warnings': warnings,
        'connection_source': 'Layout PINs and physical geometry; schematic is reference only',
        'net_semantics': 'net is the routing connection-group identity; signal is the native display name. Equal signal names do not merge distinct net groups.',
    }
    if query.active:
        result['query']=query.describe()
        result['matched_counts']={key:len(result[key]) for key in ('objects','children','pins','markups')}
        for pin in result['pins']:pin['query_match']={'basis':'public_pin_geometry','layers':pin_matches[pin['id']]}
    return result


def deferred_interfaces(w,region_id):
    from ..regions.query import boundary
    # Expose interface obligations, not the internals of child regions.
    return [{'net':row['net'],'reason':row['reason']} for row in boundary(w,region_id).get('deferred',[])]


def reference(w, region_id, *, detail='full', uids=None, parameter_names=None, profile=None):
    if w.circuit is None:
        return {'role': 'layout_reference_only', 'instances': [], 'bindings': []}
    ids = direct_ids(w, region_id)
    if uids is not None:
        from ..model import LiteError
        if not set(uids)<=ids:raise LiteError('OBJECT_OUTSIDE_REGION')
        ids &= set(uids)
    bindings = [b for b in w.circuit.bindings if b.layout_uid in ids]
    from ..circuit.hierarchy import reference_rows
    result = {
        'role': 'layout_reference_only',
        'instances': reference_rows(w.circuit, bindings),
        'bindings': [b.model_dump(mode='json') for b in bindings],
        'reference_scope': 'Each instance is identified by reference_path; terminal nets are local to its owning schematic occurrence, not Layout net identities.',
    }
    if any(row.get('reference_nets_status')=='aggregate_only' for row in result['instances']):
        result['reference_scope']+=' aggregate_only: per-member schematic mapping was not captured; terminals.net is the original instance-wide aggregate, not this member connection. Use Layout PIN nets for routing.'
    if detail=='summary' or parameter_names is not None:
        from ..technology import DEFAULT_SCHEMATIC_SUMMARY_PARAMETERS
        keys=parameter_names if parameter_names is not None else profile.schematic_summary_parameters if profile else DEFAULT_SCHEMATIC_SUMMARY_PARAMETERS
        for item in result['instances']:
            raw=item['parameters']
            item['parameter_count']=len(raw)
            item['parameters']={name:{k:v for k,v in raw[name].items() if k in ('value','units','value_type','origin')}
                                for name in keys if name in raw}
            item['omitted_parameter_count']=len(raw)-len(item['parameters'])
            item.pop('instance_properties',None)
        result.update(detail=detail,parameter_names=list(keys),omitted=['unselected CDF parameters','parameter defaults','raw instance properties'],
                      read_full={'kind':'reference','detail':'full'},parameter_semantics='Native effective values and units, no evaluation or device inference')
    return result


def rules(p, drc):
    from .child_regions import contracts as child_contracts
    from ..autoroute.layers import capabilities
    from ..conduction_rules import ConductionRules
    from ..layout_helpers.guard import templates
    from ..layout_helpers.multilayer_path import automatic_layers
    from ..drc.poly_contact_graph import PatchRules
    patch=PatchRules(p)

    return {
        'grid_um': p.grid / p.dbu_per_micron,
        'units': {'coordinates': 'workspace absolute µm; displacement values are relative µm',
                  'via_definitions': 'native lengths/pairs are DBU; divide by dbu_per_micron for edit input µm; cutRows/cutColumns are integer counts',
                  'local_drc': 'value is µm for width/spacing/enclosure, µm² for area',
                  'native_parameters': 'verbatim native values; units are not inferred'},
        'dbu_per_micron': p.dbu_per_micron,
        'permissions_note': 'writable_lpps 决定编辑权限，routing 决定自动布线能力。conduction 不是可编辑层清单。GT 不供 Agent 编辑或接入，只有金属引出的 Gate PIN 才能继续布线。',
        'writable_lpps': p.writable_lpps,
        'routing': capabilities(p, drc) if drc else None,
        'local_drc': [r.model_dump(mode='json') for r in drc.rules if r.enabled] if drc else [],
        'mim_capacitor':drc.mim_capacitor.model_dump(mode='json') if drc else None,
        'local_drc_patches': [{'id':'cross_device_poly_contact','poly_layers':sorted(patch.gates),
            'contact_definitions':[{'names':list(r.names),'layers':list(r.layers),'cut_layer':r.cut}
                                   for r in patch.contacts if r.kind=='poly_contact'],
            'scope':'当前层普通叶器件之间的 Poly 接触；不按器件名称判断类型，不展开原生层次黑盒。',
            'outcomes':'不同 PIN 网络冲突报错；归属/孔/几何证据不足阻止本地通过；已确认同网接触允许。',
            'does_not_change':'普通连通性、高亮、可编辑层和路由规则。'}],
        'verification_workflow':{'recommended_order':['check_region','server_drc_region','release_region(done)'],'order_required':False,
            'frequency':'本地 DRC > 服务器 DRC','requires_current_full_region':True,
            'note':'服务器可独立排查。完成需当前全区本地检查与服务器 DRC 都通过。本地通过仅限已支持项目，不支持的宽度计算跳过；实际错误、数据缺失、失败、部分、截断、过期结果不能验收。'},
        'design_warnings': drc.design_warnings.model_dump(mode='json') if drc else None,
        'automatic_design_warnings':[{'id':'design.internal_metal_contact',
            'scope':'本层独立金属与普通叶器件内部金属接触；原生同层 PIN 连通延伸除外，不展开层次黑盒。',
            'blocking':False,'configuration_required':False,
            'note':'标记实际接触，提示检查走线路径；不是短路或 LVS 结论。'}],
        'automatic_path_layers': automatic_layers(p,drc) if drc else {},
        'via_definitions': p.vias,
        'guard_templates': [{key:value for key,value in row.items() if key!='template'} for row in templates(p)],
        'conduction': ConductionRules(p).describe(),
        'edit_actions': {
            **{
            name: {'required': sorted(c.required), 'fields': sorted(c.fields)}
            for name, c in COMMANDS.items()
            if name in EDIT_ACTIONS
            },
            **helper_contracts(),
            **child_contracts(),
        },
        'transform': {
            'uids': 'direct objects/child modules',
            'delta': '[dx,dy] in workspace um',
            'orientation': 'R0/R90/R180/R270/MX/MY/MXR90/MYR90',
            'pivot': 'selection bounds centre snapped to manufacturing grid; Python round ties-to-even, same as GUI',
        },
    }


def net_request(w,p,region_id,args):
    from ..model import LiteError
    if args.kind!='net' or args.parameter_names is not None or args.detail!='full' or args.uids is not None or args.pin_ids is not None:
        raise LiteError('INVALID_ARGUMENTS','net 查询不接收原理图参数、detail、uids 或 pin_ids。')
    location=None
    if args.markup_id:
        from .markup_query import resolve
        location=resolve(w,p,region_id,args.markup_id,args.padding_um,args.clip_to_region)
        args=args.model_copy(update={'bounds_um':tuple(location['bounds_um'])})
    result=net(w,p,region_id,args.net,target=args.target,include_members=args.include_members,bounds_um=args.bounds_um,layers=args.layers)
    if location:result['location']=location
    return result


def net(w, p, region_id, name=None,*,target=None,include_members=False,bounds_um=None,layers=None):
    from ..model import LiteError
    from ..circuit.net_names import signal_names
    from .spatial_query import SpatialQuery
    from . import component_query
    query=SpatialQuery(w,p,region_id,bounds_um,layers)
    if name is not None and target is not None:raise LiteError('INVALID_ARGUMENTS','net 和 target 请选择一种。')

    graph = scope_graph(w, p, region_id)
    report = connectivity(graph)
    expanded=include_members or target is not None or query.active
    ids,selection=component_query.select(w,p,region_id,graph,target) if expanded else (None,None)
    if name is not None and name not in {row['net'] for row in report['nets']}:
        raise LiteError('NET_OUTSIDE_REGION', '网络不属于此操作区。')
    selected_names={name} if name is not None else None
    if target is not None:
        selected_pin_ids=set().union(*(graph['component_pins'].get(cid,set()) for cid in ids))
        selected_names={pin['net'] for pin in graph['pins'] if pin['id'] in selected_pin_ids and pin['net'] is not None}
        if target.kind=='net':selected_names.add(target.id)
        if target.kind=='pin':selected_names.update(pin['net'] for pin in graph['pins']+graph.get('directional_markers',[]) if pin['id']==target.id and pin['net'] is not None)
    report['nets'] = [r for r in report['nets'] if selected_names is None or r['net'] in selected_names]
    if selected_names is not None:
        from ..connection_diagnostics import pin_issues
        report['region_totals'] = {'connected_nets': report['connected_nets'], 'total_nets': report['total_nets'],
                                   'complete': report['complete']}
        diagnostics=pin_issues({**graph,'pins':[pin for pin in graph['pins'] if pin['net'] in selected_names]});diagnostics.pop('preparation_issues')
        report.update(diagnostics)
        report['unresolved_pins'] = [row for row in report['unresolved_pins'] if row['net'] in selected_names]
        report['shorts'] = [row for row in report['shorts'] if selected_names & set(row['nets'])]
        report['total_nets'] = len(report['nets'])
        report['connected_nets'] = sum(row['connected'] for row in report['nets'])
        report['complete'] = bool(report['nets']) and all(row['connected'] for row in report['nets']) and not report['shorts'] and not report['unresolved_pins'] and not report['warnings']
    report['statistics_scope'] = 'region' if name is None else 'selected_net'
    if target is not None:report['statistics_scope']='selected_target_nets'
    labels = {pin['id']: pin.get('display_name',pin['label']) for pin in graph['pins']}
    signals = signal_names(w.layout_connectivity)
    for row in report['nets']:
        row['pin_names'] = [labels[pid] for pid in row['pins']]
        row['signal'] = signals.get(row['net'])
    if expanded:
        if name is not None:ids=set().union(*(set(row['components']) for row in report['nets']))
        report['components']=component_query.members(w,p,region_id,graph,ids,query,keep_empty=target is not None)
        report['component_query']={'selection':selection,'filters':query.describe(),
            'total_selected_components':len(ids),'returned_components':len(report['components']),
            'member_geometry':'summary only; use layout uids for whole object details',
            'net_intent_used_as_connection':False,'connectivity_scope':'whole claimed region, before member filters'}
    return report

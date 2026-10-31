"""Discoverable action documentation derived from the shared command registry."""

from ..commands import COMMANDS
from ..model import VIA_COUNTS, VIA_LENGTHS, VIA_PAIRS

PARAMETERS = {
    'x': 'µm；绝对 X。rect 是左下角，instance/via 是原生放置原点。',
    'y': 'µm；绝对 Y。rect 是左下角，instance/via 是原生放置原点。',
    'dx': 'µm；相对 X 位移。',
    'dy': 'µm；相对 Y 位移。',
    'width': 'µm；物理线宽或矩形宽度。仅路径创建可省略，采用当前图层默认值；显式值正常校验。',
    'height': 'µm；矩形高度。',
    'points': '[[x,y], ...]；工作区绝对 µm 顶点，90 动作只接受正交，45 动作接受 45°/90°。',
    'lpp': '[layer,purpose]，例如 ["M1","drawing"]；必须在 writable_lpps 内。',
    'net_intent': '连接组身份或 null；只是编辑意图，不证明物理连接。使用 inspect 的 net，不按 signal 合并伪并联组。',
    'orientation': 'R0/R90/R180/R270/MX/MY/MXR90/MYR90。',
    'pivot': '[x,y]，工作区绝对 µm 旋转/镜像中心；省略为 instance/via 原点、rect 左下角、路径/多边形首点。',
    'degrees': '仅接受整数 -90、90、180、270；相对旋转，省略为 90°。不接受 0、360 或 -180。',
    'axis': 'X 或 Y（大写）；镜像轴。',
    'definition': 'rules.via_definitions 中现有标准过孔定义名。',
    'via_parameters': '过孔覆盖参数字典：长度及长度二元数组输入 µm，cutRows/cutColumns 为无量纲整数；可用字段见 via_parameter_units。',
    'names': '要恢复为工艺默认值的过孔参数名称列表。',
    'style': 'Path 端头：truncateExtend/extendExtend/roundRound/varExtendExtend。',
    'begin_style': 'PathSeg 起点：truncate/extend/variable/chamfer/custom。',
    'end_style': 'PathSeg 终点：truncate/extend/variable/chamfer/custom。',
    'begin_extension': 'µm；自定义起点延伸。',
    'end_extension': 'µm；自定义终点延伸。',
    'begin_custom': '{left_diagonal,right_diagonal,right_half_width}；三项物理长度均输入 µm。',
    'end_custom': '{left_diagonal,right_diagonal,right_half_width}；三项物理长度均输入 µm。',
}


def edit_contracts(actions):
    result = {}
    for name in sorted(actions & COMMANDS.keys()):
        command = COMMANDS[name]
        fields = command.fields
        if name.startswith('create_pathseg'):
            fields = fields - {'style'}
        elif name.startswith('create_path'):
            fields = fields - {'begin_style', 'end_style', 'begin_custom', 'end_custom'}
        result[name] = {
            'title': command.title,
            'uid': 'omitted; APP assigns ID'
            if name.startswith('create_')
            else 'required; direct object only',
            'required_params': sorted(command.required),
            'params': {key: PARAMETERS.get(key, '见动作说明。') for key in sorted(fields)},
            'kinds': sorted(command.kinds),
            'units': 'lengths in workspace µm; counts dimensionless',
        }
        if 'points' in fields:
            if name.startswith('create_pathseg'):
                result[name]['params']['points']='恰好两个端点 [[x1,y1],[x2,y2]]，工作区绝对 µm；90 为正交，45 可为 45°/90°单段。多段请用 create_path90/45。'
            elif name.startswith('edit_path'):
                result[name]['params']['points']=PARAMETERS['points']+' 编辑 PathSeg 必须恰好两个端点；Path 可有多个顶点。'
    result['transform'] = {
        'uid': 'omitted',
        'required_params': ['uids'],
        'params': {
            'uids': '本层对象/直接子模块 UID 列表。',
            'delta': '[dx,dy] µm；默认 [0,0]。',
            'orientation': '默认 R0；以整体实际边界中心作变换，中心及 delta 按工艺 grid 取整（Python round，正负半格 ties-to-even）。公开 PIN 随模块整体变换，未选中外部线路不自动跟随。',
        },
    }
    return result


CONDITIONS = {
    'workspace': {
        'save': ['expected_document_id', 'expected_revision; saves a new immutable archive without changing the active file; allowed while agents work'],
        'load': ['expected_document_id', 'expected_revision', 'path under advertised import_roots', 'all leases released; no active jobs or unresolved native transaction; opens a fresh working copy and first archives the current workspace'],
        'status': ['no lease required; returns configured file roots and current document version'],
        'list': ['managed archives only; paginated with offset/limit'],
    },
    'edit_region': {
        'apply': ['expected_revision', 'nonempty operations'],
        'undo': ['expected_revision', 'operations must be empty'],
        'status': ['job_id'],
        'cancel': ['job_id'],
        'slow_helpers': [
            'create_guard/create_multilayer_path must be alone; up to 32 create_auto_vias operations may form one atomic batch; queued/running means edit_applied=false; completed result confirms adoption'
        ],
        'large_local_batches': [
            '8–64 direct-object or native-routing-window operations run as an atomic background job; use the same edit_region status/cancel protocol; queued/running is not applied; inspect completed result.edit_applied before continuing or undoing; never resubmit the original edit with a new request_id'
        ],
    },
    'check_region': {'start': ['expected_revision'], 'status': ['job_id']},
    'server_drc_region': {
        'start': ['expected_revision'],
        'status': ['job_id'],
        'cancel': ['job_id'],
    },
    'route_region': {
        'generate': ['expected_revision'],
        'status': ['job_id'],
        'discard': ['job_id'],
        'recheck': ['expected_revision', 'job_id', 'candidate_id'],
        'apply': ['expected_revision', 'job_id', 'candidate_id'],
    },
    'capture_region': {
        'candidate': ['job_id and candidate_id together; current ready candidate only']
    },
    'reference_cases': {'read': ['case_id'], 'preview': ['case_id']},
}


def usage(name, actions):
    result = {
        'conditional_required': CONDITIONS.get(name, {}),
        'response_semantics': {
            'ok': 'request executed; does not mean routing/check passed',
            'revision': 'current workspace revision',
            'state=completed': 'calculation finished',
            'current': 'result matches the claimed construction-level content and configuration; unrelated levels may have newer workspace revisions',
            'passed': 'current completed result satisfies this check scope',
            'historical_result': 'stale evidence; cannot authorize completion',
        },
        'recovery': '结果未知时沿用同 client_id/request_id 与原参数重试；不要换 ID 重画。STALE_REVISION 应重新查询。',
    }
    if name == 'edit_region':
        result['actions'] = edit_contracts(actions)
        result['actions'].update(helper_contracts())
        from .child_regions import contracts
        result['actions'].update(contracts())
        result['via_parameter_units'] = {
            **{k: 'integer count' for k in sorted(VIA_COUNTS)},
            **{k: 'µm' for k in sorted(VIA_LENGTHS)},
            **{k: '[µm, µm]' for k in sorted(VIA_PAIRS)},
        }
    if name in ('inspect_region','capture_region'):
        result['read_execution']='HTTP 截图/net 后台读取快照，调用方式不变，不新增 job_id/status。source_revision 为输入版本；current=true 表示首次完成时本层依赖有效，按 request_id 重放仍是原响应。READ_SNAPSHOT_STALE/READ_QUEUE_FULL/READ_TIMEOUT 可用新请求重新读取；传输超时或 OUTCOME_UNKNOWN 仍用原 request_id 对账，勿重发编辑。'
        result['guidance_box']={'markup_id':'当前层定位框 ID；与 bounds_um/target 互斥',
            'padding_um':'非负有限工作区 µm；默认 0',
            'clip_to_region':'默认 false，越界拒绝；true 显式裁到接入区。location 返回原框/请求/实际范围、版本与 clipped。capture 同时返回该版本的 context 布局摘要。'}
    if name=='inspect_region':
        result['terminal_lookup']={'kind':'terminals','instance_name':'精确原生名称','terminal':'可选端子或原生成员名',
            'name_source':'layout（默认，重名返回全部候选并标 ambiguous）或 schematic（顶层名列出本层全部展开成员；也可用 reference 返回的 qualified_name 查询具体层次实例）',
            'evidence':'contact_state 区分缺几何、unsupported_access、unattached、partial、attached 和 shorted；attached 仅为本层端口接触，不是跨区接缝或 LVS 结论。'}
        result['reference_query']={'summary':{'kind':'reference','detail':'summary'},
            'parameters':'parameter_names 可显式选择原生有效参数；[] 省略参数但保留端子和绑定。默认摘要用工艺的 schematic_summary_parameters。未配置时候选为 w/l/fw/fingers/nf/m/r/c，只返回实际存在字段，值和单位不推算，阻容值不代表并联合计。',
            'uids':'可选本层 Layout UID 列表，返回对应原理图实例及原生绑定。',
            'hierarchy':'读取深度跟随原生 Layout binding。实例以 reference_path（含成员/行/列）唯一定位；qualified_name 便于阅读；reference_nets 记录可确认的原理图跨层端口连接，不是 Layout 网络或物理导通证据。',
            'array_members':'reference_nets_status=aggregate_only 表示未采集逐成员原理图映射，reference_nets 为空；terminals.net 只保留整个实例的原生聚合表达式。不可把它当作每个成员的网络，实际布线使用 Layout PIN。',
            'full':{'kind':'reference','detail':'full'}}
        result['deferred_interfaces']='建区可先补原理图要求的本地边界 PIN。layout.deferred_interfaces 列出尚缺原生 PIN/保护环接入的网络；只有标记或同名金属不代表完成。实体端子的未知状态仍通过 terminals 查询。'
        result['native_routing_windows']={'query':'layout 返回当前层直属原生黑盒的豁免区，可用对象 UID 或豁免区 ID 筛选。',
            'auto_escape':'edit_region: create_native_pin_escapes，uid=直属原生黑盒 UID，params={width_um}。每个内部端子/金属层取最近的水平或垂直出口；只画豁免区，不画导线，不访问黑盒内部；重复调用复用已有覆盖。',
            'create':'edit_region: create_native_routing_window，uid=原生模块 UID，params={bounds_um,layers,name?,note?,enabled?}',
            'update':'set_native_routing_window，uid=豁免区 ID，可修改 bounds_um/layers/name/note/enabled；delete_native_routing_window 删除。',
            'semantics':'只豁免所属 Virtuoso 模块覆盖范围内的指定金属层；其他模块、独立禁布区和未选层不受影响。随原生对象位姿移动，内部继续黑盒，不开放原生内部编辑。'}
        result['query_options']={
            'layout':'bounds_um=[xmin,ymin,xmax,ymax] 工作区绝对 µm、layers=[M1,V1,M2] 可任选；与 detail/uids/pin_ids 取交集。实际几何与闭矩形相交，包含穿框长线和边界接触，无 DRC halo。',
            'whole_objects':'返回完整原对象和完整 PIN，绝不生成可编辑的裁剪片段；query_match 指明匹配层。过孔切孔及两侧金属均参与筛选。原生/子模块外框与定位框是图层无关上下文。',
            'net_members':'include_members=true 展开全区或所选网的分量成员；target 或 bounds_um/layers 也会触发展开。默认普通 net 查询保持简洁。',
            'target':'net 查询支持 target={kind:component,id:c3,query_ref:当前引用}，或 {kind:object,id:UID}，或对象加 point_um+layer，以及 {kind:pin,id:PIN-ID}。net 和 target 不可同时给。',
            'component_scope':'物理图始终覆盖整个接入区；bounds_um/layers 只筛成员，不重新切分分量。components[].nets/pin_ids/bounds_um 保留全分量事实，members_filtered 标记成员列表被筛选。',
            'ambiguity':'对象/接口有多个分量时 selection.ambiguous=true，不自动合并；用对象层点或当前分量引用定位。unassigned 不猜网络，shorted 保留多个目标网。',
        }
        result['native_width']={
            'perpendicular':'shape_dbu.width / dbu_per_micron 为垂直于走线方向的物理线宽（µm）。',
            'oa_diagonal':'45° PathSeg 使用 OA 对角表达：物理线宽 = shape_dbu.width / dbu_per_micron / sqrt(2)，不能只除 DBU。',
            'quantization':'编辑 width 始终是物理 µm。45° PathSeg 先乘 sqrt(2)，以 lcm(grid,2) DBU 四舍五入（half-up）；物理宽度误差不超过该步长/(2*sqrt(2)*dbu_per_micron)。45° Path 仍为 perpendicular。',
        }
    if name=='capture_region':
        result['framing']='细长图通过画面留白和图例换行保持说明可读；bounds_um 不变，真实几何保持纵横比例。geometry_rect_px 是 PNG 内对应 bounds_um 的矩形，可能有非零 x；其余像素不对应额外版图。'
        result['instance_labels']='display.instance_label_counts 给出当前取景可见且已请求实例的总数、显示数和省略数；omitted_instance_labels 含完整 id/name/bounds_um/reason/next。低缩放省略也计入；关闭 instance_names 时不计入。'
    if name=='server_drc_region':
        result['report_filter']='人端工艺 report_policy 是唯一过滤和服务器验收依据；规则 ID 精确匹配，关键词匹配规则 ID 与正文，忽略大小写/连续空白。返回 report_policy_digest、原始/有效/抑制计数及 suppressed_by_rule/reason。include_waived=true 查看已过滤项及依据，不改变 passed。旧 exclude_categories=[] 等价显示全部，其他旧类别参数不授予豁免。'
        result['policy_changes']='状态查询及 release(done) 按当前人端设置重新审阅仍有效的原始结果；无需因仅过滤变化重跑服务器。幂等重放保留原响应，重新查询使用新的 status 请求。失效几何、失败、截断、覆盖不足及非全区结果仍不能用于完成；本地检查不应用服务器过滤。'
        result['prerequisite']='可独立启动，无本地先通过门禁；仍需有效接入、expected_revision 和当前区域无运行中的任务。启动/执行成功不等于通过或完成。verification 分别显示当前全区本地与服务器结果，两项均通过才能完成。'
        result['execution_failures']='state=failed 是任务执行失败，不是 DRC 违规；没有 passed 结论。error.details 包含 stage/execution_stage、drc_completed、result_available、native_job_id/public_job_id 及 next_action；null 表示未知。文件访问只有限重试，不自动重复远端检查。'
    if name in ('check_region','server_drc_region','release_region'):
        result['mim_via_check']='本地检查按人端 drc.mim_capacitor 配置：独立标准过孔（含组合中的每一级）的实际切孔与配置的 MIM 图形重叠，且连接所选上下金属时，报 MIM_VIA_BLOCKED，阻断完成。不检查原生 PCell 内部孔；不改普通连通/高亮。inspect rules 可读配置状态；未配置不是不支持，不得自行猜层或增加豁免。'
        result['verification_workflow']='频繁本地检查 > 阶段性服务器检查，推荐先本地；服务器可独立启动。release(done) 要求当前全区本地与服务器均通过。本地只检查已支持项目；不支持的宽度计算跳过且不生成逐项记录。本地实际错误/Poly/PIN 问题、几何缺失、执行失败、截断、局部或过期结果仍阻断完成。区域结果不是整芯片或 LVS 签核。'
    if name=='route_region':
        result['permission']='默认关闭，仅人端工艺库勾选“允许 Agent 使用算法自动布线”并保存后开放。关闭时不列入实时 tools，generate/recheck/apply 均拒绝；已有任务仍可 status/discard。其他辅助编辑工具与人类 UI 不受影响。'
        result['size_limit']='最多 64 个当前层器件/直接子模块；超出返回 ROUTING_REGION_TOO_LARGE，可分区或使用显式路径动作。模拟部分不建议内置自动布线。'
    if name=='check_region':
        result['internal_metal_contact']='design.internal_metal_contact 是非阻断设计 warning：本层独立金属接触普通叶器件内部、未与公开 PIN 通过原生同层金属连通的部分。按线/器件/层合并并标出实际接触；合法原生 PIN 同层延伸不报，不展开层次黑盒。检查位置并避免误接；不提取内部电路，不代表 LVS 结论，无须为该提醒添加 waiver。'
        result['native_pin_area']='普通叶 PCell 参与检查。原生 PIN 若暴露金属面积不足，可能在未布线时触发 area 错误；可用同层合法连接补足后复查，不修改只读 PIN，不自动豁免，也不把此类错误一律降为 warning。'
    return result


def helper_contracts():
    from ..layout_helpers.contracts import MODELS

    result={
        key: {
            'uid': 'omitted',
            'input_schema': model.model_json_schema(),
            'units': 'workspace absolute µm; spacing is edge-to-edge; count is dimensionless',
            'atomic': True,
        }
        for key, model in MODELS.items()
    }
    for name in ('arrange','align'):
        result[name]['kinds']=['inst']
        result[name]['unsupported']='Local child regions use transform; these helpers do not accept child-region IDs.'
    result['create_guard']['geometry']='Exactly one of bounds_um (rectangular main path), uids (enclose direct objects), or points_um (open horizontal/vertical main path). All UI native templates and validated recipes are discoverable in inspect_region(kind=rules).guard_templates.'
    result['create_guard']['execution']='Submit alone; native private-preview job with status/cancel. Actual generated outer material must fit the claimed region and existing routing policy. No source-cell write or weakened source/dependency checks.'
    result['create_multilayer_path']['layers_semantics']='每段一个层名：len(layers)=len(points)-1。省略才使用已配置的水平/竖直首选层。'
    result['create_multilayer_path']['via_policy']='使用原生标准金属孔的固定尺寸并检查已配置的本地规则；缺少某个规则项不等于过孔不存在，已知尺寸/包围错误仍拒绝。原子生成仍核对完整连通、网络冲突、区域范围和本地 DRC。'
    result['create_multilayer_path']['landing']='每级至少两切孔（或工艺偏好要求的更多孔）；landing_size_um 是整个方形搜索窗口边长，不是单孔尺寸。建议省略以按原生尺寸自动选取；空间不足、接错网或 DRC 失败仍整次回滚。'
    result['create_auto_vias']['single_row']={'array_direction':'any（原行为）/horizontal（1×N）/vertical（N×1）',
        'scope':'单窗口、单个标准金属过孔、最多一个阵列；使用原 bounds/landing/target/net/DRC 限制',
        'maximality':'按孔数降序、全部网格位置搜索；成功才报告 maximal_on_grid。预算耗尽报 SINGLE_ROW_SEARCH_LIMIT 并原子回滚，不返回未经证明的较少孔数。',
        'existing':'只复用已验证达到容量的同方向单排；其他已有阵列保留并报告需明确处理，不自动删除或扩大窗口。'}
    result['create_auto_vias']['landing_semantics']={
        'allow_landing_false':'all via enclosure metal must be covered by existing access',
        'fit_target':'default when landing allowed: prefer one explicit native PIN, otherwise one start-layer target; landing_reference resolves ambiguity. Fill minimum one-cut enclosure width but do not extend reference length to add cuts. Other layers may need enclosure extension for that array.',
        'expand_window':'explicitly allow dense arrays/landing extension throughout bounds_um',
        'feedback':'landing_reference/landing_changes identify each original local target and layer; used_landing discloses new metal, not a DRC warning'}
    return result


def select_tools(rows, args):
    from ..model import LiteError

    if not isinstance(args, dict) or set(args) - {'tool', 'action'}:
        raise LiteError('INVALID_ARGUMENTS', 'tools 可选 tool 和 action。')
    tool = args.get('tool')
    action = args.get('action')
    if action and tool != 'edit_region':
        raise LiteError('INVALID_ARGUMENTS', 'action 目前用于 edit_region。')
    if tool:
        rows = [row for row in rows if row['name'] == tool]
        if not rows:
            raise LiteError('UNKNOWN_TOOL')
    if action:
        contracts = rows[0]['usage']['actions']
        if action not in contracts:
            raise LiteError('ACTION_NOT_ALLOWED', action=action)
        rows[0] = {**rows[0], 'usage': {**rows[0]['usage'], 'actions': {action: contracts[action]}}}
    return rows

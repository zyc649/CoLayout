"""Human-readable audit projection; no API execution or edit logic."""
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
import json
from .events import CallIdentity, observer_payload as safe_payload

TOOLS = {'tools': '读取工具清单', 'claim_region': '接入操作区', 'inspect_region': '查看操作区',
         'edit_region': '编辑版图', 'route_region': '自动布线', 'check_region': '检查连通与 DRC',
         'capture_region': '查看截图', 'release_region': '结束接入', 'human_release': '人工结束接入',
         'reference_cases': '查看参考案例', 'server_drc_region': '服务器全规则 DRC'}
ACTIONS = {'create_rect': '画矩形', 'create_path90': '画直角折线', 'create_path45': '画斜线',
           'create_pathseg90': '画直线段', 'create_pathseg45': '画斜线段',
           'create_polygon': '画多边形', 'create_via': '放置过孔', 'place_instance': '放置已有器件',
           'move': '移动', 'rotate': '旋转', 'mirror': '镜像', 'set_width': '修改线宽',
           'edit_rect': '调整矩形', 'edit_path90': '调整折线', 'edit_path45': '调整斜线',
           'edit_path_ends': '调整线端', 'edit_polygon': '调整多边形', 'edit_via': '调整过孔',
           'reset_via': '恢复过孔参数', 'set_net_intent': '设置网络标记', 'copy': '复制',
           'delete': '删除', 'transform': '整体变换'}
ACTIONS.update({'create_bus':'批量平行线','arrange':'排列器件','align':'对齐器件',
                'create_auto_vias':'自动打孔','create_multilayer_path':'跨层路径','create_guard':'生成保护环'})
ACTIONS.update({'create_child_region':'创建子操作区','set_child_region':'设置子操作区','resize_child_region':'调整子区边界',
                'set_child_pin':'调整子区接口 PIN','dissolve_child_region':'解散子操作区','create_keepout':'创建禁布区',
                'resize_keepout':'调整禁布范围','set_keepout':'设置禁布区','delete_keepout':'删除禁布区',
                'set_native_blocked_layers':'设置原生模块禁布层'})
KINDS = {'layout': '版图与 PIN', 'net': '网络连通', 'rules': '工艺规则', 'reference': '布局参考','terminals':'器件端子'}
VERBS = {'generate': '生成候选', 'status': '查询进度', 'recheck': '重新检查候选',
         'apply': '采用候选', 'discard': '丢弃候选', 'start': '开始检查'}
FIELDS = {'expected_revision': '依据版本', 'layers': '布线层', 'algorithms': '算法',
          'region_id': '操作区 ID', 'agent_name': 'Agent 名称', 'kind': '查询内容',
          'net': '网络', 'uid': '对象 ID', 'uids': '对象 ID', 'points': '路径点（µm）',
          'x': 'X（µm）', 'y': 'Y（µm）', 'dx': 'X 位移（µm）', 'dy': 'Y 位移（µm）',
          'width': '宽度', 'height': '高度', 'delta': '位移（µm）', 'lpp': '图层 / 用途',
          'orientation': '方向', 'net_intent': '网络标记', 'job_id': '任务 ID',
          'candidate_id': '候选 ID', 'outcome': '结束方式', 'mode': '操作方式',
          'bounds_um': '范围（µm）', 'definition': '过孔类型', 'action': '动作',
          'pin_id':'接口 PIN ID','pin_mode':'接口模式','blocked_layers':'模块禁布金属层','layer':'金属层',
          'instance_name':'器件名称','terminal':'端子','name_source':'名称来源','markup_id':'定位框 ID',
          'padding_um':'周边范围','clip_to_region':'裁到当前操作区','array_direction':'过孔排列方向',
          'landing_policy':'落脚策略','landing_reference':'接入参考目标','allow_landing':'允许补落脚金属'}




def label(tool, args):
    name = TOOLS.get(tool, tool)
    if tool == 'inspect_region':
        kind = str(args.get('kind', 'layout'))
        return '查看' + KINDS.get(kind, kind)
    if tool == 'server_drc_region':
        return '服务器 DRC · ' + {'start': '开始检查', 'status': '查询结果', 'cancel': '取消'}.get(args.get('action', 'start'), '')
    if tool == 'reference_cases':
        return {'list':'浏览案例库','read':'读取参考案例','preview':'预览参考案例'}.get(str(args.get('action','list')),name)
    if tool in ('route_region', 'check_region'):
        return VERBS.get(str(args.get('action', 'generate' if tool == 'route_region' else 'start')), name)
    if tool == 'edit_region':
        if args.get('mode') in ('status','cancel'):
            return '生成编辑 · '+('查询结果' if args['mode']=='status' else '取消生成')
        if args.get('mode') == 'undo':
            return '撤销自己的编辑'
        ops = args.get('operations') or []
        if not isinstance(ops, list):
            return name
        if len(ops) == 1 and isinstance(ops[0], dict):
            return ACTIONS.get(str(ops[0].get('action')), name)
        return f'编辑版图 · {len(ops)} 项操作'
    return name


def outcome(response):
    if not response.get('ok'):
        error = response.get('error', {})
        return '失败', error.get('message') or error.get('code', '调用失败')
    result = response.get('result', {})
    if result.get('save_warning'):
        return '需处理', result['save_warning']
    state = result.get('state')
    if state in ('queued', 'running'):
        return '进行中', result.get('message', '正在处理')
    if state == 'failed':
        return '失败', (result.get('error') or {}).get('message', '任务失败')
    if state == 'cancelled':
        return '已取消', '任务已取消'
    if result.get('current') is False:
        return '需重检', '版图已变化，这份结果需要重新检查'
    if result.get('kind')=='edit' and state=='completed':
        applied=result.get('result',{})
        return '完成', (f"已采用生成结果 · {len(applied.get('created_uids',[]))} 个新对象" if applied.get('edit_applied') else '已核对并复用现有对象；未重复生成')
    if 'passed' in result:
        if result.get('kind') == 'server_drc' or result.get('engine') == 'calibre':
            return ('通过', '服务器检查完成，当前反馈筛选下未发现活动错误') if result['passed'] else ('未通过', '服务器检查存在错误、覆盖不完整或结果已过期')
        summary=result.get('result',{}).get('summary')
        if summary:return ('通过' if result['passed'] else '未通过'),summary
        return ('通过', '连通性与本地 DRC 均通过') if result['passed'] else ('未通过', '检查完成，有问题需要处理')
    if 'candidates' in result:
        candidates = result['candidates']
        ready = sum(c.get('status', c.get('validation', {}).get('status')) == 'ready' for c in candidates)
        return ('完成' if ready else '未通过'), f'{len(candidates)} 个方案，{ready} 个可以采用'
    if result.get('exclusive'):
        return '已接入', '已独占接入此操作区'
    if result.get('released'):
        if result.get('outcome')=='handoff':return '已交接','本阶段交接，修改保留；不代表整体验收通过'+(' · '+result['note'] if result.get('note') else '')
        return '已结束', '任务完成并释放占用' if result.get('outcome') == 'done' else '已释放占用，已有编辑保留'
    if result.get('discarded'):
        return '已丢弃', '已丢弃布线结果'
    if result.get('undone'):
        return '完成', '已撤销自己的编辑'
    if 'created_uids' in result:
        count = len(result['created_uids'])
        return '完成', (f'已创建 {count} 个对象' if count else '编辑已完成') if result.get('changed') else '没有改变版图'
    if 'image_base64' in result:
        return '完成', f"截图已返回 · {result.get('width')} × {result.get('height')} 像素"
    if 'objects' in result:
        if any(not isinstance(item, dict) for item in result['objects']):
            return '完成', '已读取版图对象与 PIN（完整结果已记录）'
        return '完成', f"已读取 {len(result['objects'])} 个对象、{len(result.get('pins', []))} 个 PIN"
    if 'tools' in result:
        return '完成', f"已读取 {len(result['tools'])} 个工具"
    if 'cases' in result:
        return '完成', f"找到 {result.get('total',len(result['cases']))} 个参考案例"
    return '完成', '调用成功'


@dataclass
class Activity:
    key: str
    time: str
    tool: str
    arguments: dict
    region_id: str = ''
    region_name: str = ''
    agent: str = '未接入'
    status: str = '进行中'
    summary: str = '等待返回'
    response: dict = field(default_factory=dict)
    duration_ms: float | None = None
    request_id: str = ''
    retries: int = 0
    document_id: str = ''
    sequence: int = 0
    client_id: str = ''
    poll_count: int = 0
    last_poll_id: str = ''


class ActivityFeed:
    def __init__(self, region_name, limit=500):
        self.region_name = region_name
        self.limit = limit
        self.rows = OrderedDict()
        self.jobs = {}
        self.clients = {}
        self.version = 0
        self.sequence = 0
        self.hidden_before = {}
        self.pending_polls = OrderedDict()

    def visible(self, document_id, region_id):
        scope = (document_id or '', region_id or '')
        cutoff = self.hidden_before.get(scope, 0)
        return [row for row in reversed(self.rows.values())
                if (row.document_id, row.region_id) == scope and row.sequence > cutoff]

    def clear_display(self, document_id, region_id):
        self.hidden_before[(document_id or '', region_id or '')] = self.sequence
        self.version += 1

    def add(self, event):
        kind = event.get('event')
        key = event.get('request_id')
        if kind in ('request', 'replayed', 'rejected'):
            if kind == 'replayed' and key in self.rows:
                self.rows[key].retries += 1
                self.version += 1
                return
            if kind == 'rejected':
                key = f'{key}:rejected:{self.version}'
            args = event.get('arguments', {})
            args = args if isinstance(args, dict) else {'输入': args}
            identity = CallIdentity.from_event(event)
            client = identity.client_id
            document_id = event.get('document_id', '')
            known_agent, known_region = self.clients.get((document_id, client), ('未接入', ''))
            agent = str(event.get('agent_name') or args.get('agent_name') or known_agent)
            rid = str(event.get('region_id', '') if 'document_id' in event else
                      event.get('region_id') or args.get('region_id') or known_region)
            self.clients[(document_id, client)] = (agent, rid)
            if kind=='request' and event.get('tool') in ('server_drc_region','check_region','route_region','edit_region') and (args.get('action')=='status' or args.get('mode')=='status'):
                origin=self.rows.get(self.jobs.get(args.get('job_id')))
                if origin and (origin.document_id,origin.region_id,origin.client_id)==(document_id,rid,client) and origin.sequence>self.hidden_before.get((document_id,rid),0):
                    self.pending_polls[key]=origin.key
                    while len(self.pending_polls)>self.limit:self.pending_polls.popitem(last=False)
                    return
            try:
                stamp = datetime.fromisoformat(event['timestamp']).astimezone().strftime('%H:%M:%S')
            except (KeyError, ValueError):
                stamp = ''
            row = Activity(key, stamp, event.get('tool', ''), args, rid,
                           self.region_name(rid), agent,
                           request_id=identity.call_id)
            self.sequence += 1
            row.document_id, row.sequence = document_id, self.sequence
            row.client_id = client
            if kind == 'rejected':
                row.status, row.summary = '失败', str(event.get('error', '请求被拒绝'))
            elif kind == 'replayed':
                row.status, row.summary, row.retries = '已重试', '查询原调用的结果，未重复执行', 1
            self.rows[key] = row
            while len(self.rows) > self.limit:
                old, _ = self.rows.popitem(last=False)
                self.jobs = {job: origin for job, origin in self.jobs.items() if origin != old}
        elif kind=='response' and key in self.pending_polls:
            origin=self.rows.get(self.pending_polls.pop(key))
            if origin:
                raw=event.get('response',{})
                origin.status,origin.summary=outcome(raw)
                origin.poll_count+=1;origin.last_poll_id=CallIdentity.from_event(event).call_id
                origin.response['最近进度响应']=safe_payload(raw)
        elif kind == 'response' and key in self.rows:
            row = self.rows[key]
            raw = event.get('response', {})
            row.status, row.summary = outcome(raw)
            row.response = safe_payload(raw)
            row.duration_ms = event.get('duration_ms')
            result = raw.get('result', {})
            job = result.get('job_id')
            if job:
                origin=self.rows.get(self.jobs.get(job))
                if origin is not None and origin is not row:origin.status,origin.summary=row.status,row.summary
                if origin is None or origin.sequence<=self.hidden_before.get((row.document_id,row.region_id),0):
                    self.jobs[job]=key
        elif kind == 'job_finished':
            origin = self.rows.get(self.jobs.get(event.get('job_id')))
            if origin:
                result = event.get('result')
                payload = {'state': event.get('state'), 'error': event.get('error') or {},
                           'kind':event.get('kind'),'result':result if isinstance(result,dict) else {}}
                if event.get('kind') == 'route':
                    payload['candidates'] = result or []
                elif isinstance(result, dict):
                    payload.update(result)
                origin.status, origin.summary = outcome({'ok': True, 'result': payload})
                origin.response['后台任务结果'] = safe_payload(payload)
        elif kind == 'human_release':
            self.add({'event': 'request', 'timestamp': event.get('timestamp', ''),
                      'request_id': 'human-' + str(self.version), 'tool': 'human_release',
                      'agent_name': event.get('owner'), 'region_id': event.get('region_id'), 'source': '人',
                      'document_id': event.get('document_id', ''),
                      'arguments': {}})
            row = next(reversed(self.rows.values()))
            row.status, row.summary = '已结束', '人已结束此 Agent 的接入'
        else:
            return
        self.version += 1


def details(row):
    lines = [f'{row.agent}  ·  {row.region_name or row.region_id or "尚未接入操作区"}',
             f'工具：{label(row.tool, row.arguments)}（{row.tool}）',
             f'结果：{row.status} · {row.summary}', '', '调用参数']
    args = {k: v for k, v in row.arguments.items() if k != 'session_token'}
    ops = args.pop('operations', None)
    for key, value in args.items():
        text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        lines.append(f'{FIELDS.get(key, key)}（{key}）：{text}')
    if isinstance(ops, list):
        for i, op in enumerate(ops, 1):
            if not isinstance(op, dict):
                lines.append(str(op))
                continue
            action = str(op.get('action'))
            lines.append(f'\n{i}. {ACTIONS.get(action, action)}（{action}）')
            if op.get('uid'):
                lines.append('对象 ID：' + str(op['uid']))
            params = op.get('params') or {}
            if not isinstance(params, dict):
                lines.append('参数：' + json.dumps(params, ensure_ascii=False))
                continue
            for key, value in params.items():
                lines.append(f'{FIELDS.get(key, key)}（{key}）：{json.dumps(value, ensure_ascii=False)}')
    elif ops is not None:
        lines.append('操作：' + json.dumps(ops, ensure_ascii=False))
    if not args and not ops:
        lines.append('无额外参数（使用已接入的操作区）')
    error = row.response.get('error')
    if error:
        hint = {'REGION_MISSING': '该操作区已不存在，请从当前画布重新复制操作区 ID。',
                'STALE_REVISION': '本层依据版本不可用；请按失败原因重新读取当前操作区。',
                'SESSION_REQUIRED': 'Agent 尚未接入，或接入已经结束。',
                'REGION_ALREADY_WORKING': '此操作层级已有 Agent 在工作；父子层级可分别接入。'}.get(error.get('code'))
        if hint:
            lines.extend(['', hint])
        lines.extend(['', '失败原因', str(error.get('message') or error.get('code')),
                      '错误代码：' + str(error.get('code'))])
        if error.get('details'):
            lines.append(json.dumps(safe_payload(error['details']), ensure_ascii=False, indent=2))
    if row.region_id:
        lines.extend(['', '操作区 ID：' + row.region_id])
    lines.append('请求 ID：' + row.request_id)
    if row.client_id:
        lines.append('客户端 ID：' + row.client_id)
    if row.retries:
        lines.append(f'相同请求重试 {row.retries} 次；没有重复执行编辑')
    if row.poll_count:
        lines.append(f'已合并 {row.poll_count} 次进度查询；最近请求：{row.last_poll_id}。完整逐次记录仍在原始日志。')
    if row.duration_ms is not None:
        lines.append(f'调用耗时：{row.duration_ms / 1000:.3f} 秒')
    return '\n'.join(lines)

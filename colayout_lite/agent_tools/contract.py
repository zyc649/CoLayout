"""Small v2 tool contract; no layout strategies or transport escape hatch."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class Arguments(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Claim(Arguments):
    region_id: str = Field(min_length=1, max_length=200)
    agent_name: str = Field(min_length=1, max_length=80)


class WorkspaceFile(Arguments):
    action: Literal['status','save','list','load'] = 'status'
    expected_document_id: str | None = None
    expected_revision: StrictInt | None = None
    name: str | None = Field(default=None,max_length=100)
    path: str | None = Field(default=None,max_length=4000)
    offset: StrictInt = Field(default=0,ge=0)
    limit: StrictInt = Field(default=50,ge=1,le=100)

    @model_validator(mode='after')
    def applicable(self):
        if self.action in ('save','load') and (not self.expected_document_id or self.expected_revision is None):
            raise ValueError('save/load require expected_document_id and expected_revision')
        if self.action=='load' and not self.path:raise ValueError('load requires path')
        if self.path is not None and self.action!='load':raise ValueError('path is only used by load')
        if self.name is not None and self.action!='save':raise ValueError('name is only used by save')
        return self


class Scoped(Arguments):
    session_token: str = Field(min_length=16, max_length=200)


class ProcessConfigurationArgs(Arguments):
    action: Literal['requirements','list','get','submit','status','export']='requirements'
    proposal_id: str|None=Field(default=None,min_length=32,max_length=32)
    technology_key: str|None=Field(default=None,min_length=1,max_length=128)
    package: dict|None=None
    sample: dict[str,str]|None=None
    connection_id: str|None=Field(default=None,max_length=24)
    project_root: str|None=Field(default=None,max_length=4000)
    verification_id: str|None=Field(default=None,min_length=32,max_length=32)

    @model_validator(mode='after')
    def applicable(self):
        if self.action=='submit':
            if self.package is None or self.sample is None:raise ValueError('submit requires package and sample')
            if self.proposal_id or self.technology_key:raise ValueError('submit creates a proposal')
        elif self.package is not None or self.sample is not None or self.connection_id or self.project_root or self.verification_id:
            raise ValueError('package/sample/connection_id/project_root require submit')
        if self.action=='status' and not self.proposal_id:raise ValueError('status requires proposal_id')
        if self.action=='get' and bool(self.proposal_id)==bool(self.technology_key):raise ValueError('get requires exactly one proposal_id or technology_key')
        if self.action=='export' and not self.technology_key:raise ValueError('export requires technology_key')
        if self.proposal_id and self.action not in ('get','status'):raise ValueError('proposal_id requires get/status')
        if self.technology_key and self.action not in ('get','export'):raise ValueError('technology_key requires get/export')
        return self


class CaptureTarget(Arguments):
    kind: Literal['net', 'pin', 'object', 'component']
    id: str = Field(min_length=1, max_length=200)
    query_ref: str | None = None
    point_um: tuple[float, float] | None = None
    layer: str | None = None


class Located(Scoped):
    markup_id: str | None = Field(default=None,min_length=1,max_length=200)
    padding_um: float = Field(default=0,ge=0,allow_inf_nan=False)
    clip_to_region: bool = False

    @model_validator(mode='after')
    def location_options(self):
        if self.markup_id:
            if getattr(self,'bounds_um',None) is not None or getattr(self,'target',None) is not None:
                raise ValueError('markup_id cannot be combined with bounds_um or target')
        elif self.padding_um or self.clip_to_region:
            raise ValueError('padding_um/clip_to_region require markup_id')
        return self


class Inspect(Located):
    kind: Literal['layout', 'net', 'rules', 'reference', 'terminals'] = 'layout'
    net: str | None = None
    detail: Literal['full', 'summary'] = 'full'
    uids: list[str] | None = Field(default=None, min_length=1, max_length=256)
    pin_ids: list[str] | None = Field(default=None, min_length=1, max_length=256)
    bounds_um: tuple[float, float, float, float] | None = None
    layers: list[str] | None = Field(default=None, min_length=1, max_length=128)
    target: CaptureTarget | None = None
    include_members: bool = False
    parameter_names: list[str] | None = Field(default=None, max_length=128,
        description='reference only; [] omits CDF parameters while preserving terminal/binding data.')
    instance_name: str | None = Field(default=None,min_length=1,max_length=200)
    terminal: str | None = Field(default=None,min_length=1,max_length=200)
    name_source: Literal['layout','schematic'] = 'layout'

    @model_validator(mode='after')
    def terminal_options(self):
        if self.parameter_names is not None and self.kind!='reference':raise ValueError('parameter_names requires kind=reference')
        if self.kind=='terminals':
            if not self.instance_name:raise ValueError('terminals requires instance_name')
            if self.markup_id or self.net is not None or self.target or self.uids or self.pin_ids or self.bounds_um or self.layers or self.parameter_names or self.include_members or self.detail!='full':raise ValueError('terminals only supports instance_name/terminal/name_source')
        elif self.instance_name is not None or self.terminal is not None or self.name_source!='layout':raise ValueError('instance_name/terminal/name_source require kind=terminals')
        if self.markup_id and self.kind not in ('layout','net'):raise ValueError('markup_id requires layout/net')
        return self


class Operation(Arguments):
    action: str
    uid: str | None = None
    params: dict = Field(default_factory=dict)


class Edit(Scoped):
    expected_revision: StrictInt | None = Field(default=None, ge=0)
    mode: Literal['apply', 'undo', 'status', 'cancel'] = 'apply'
    job_id: str | None = None
    operations: list[Operation] = Field(default_factory=list, max_length=64)


class Route(Scoped):
    action: Literal['generate', 'status', 'recheck', 'apply', 'discard'] = 'generate'
    expected_revision: StrictInt | None = None
    layers: list[str] | None = Field(default=None, max_length=16)
    algorithms: list[
        Literal['builtin.astar', 'builtin.pattern', 'builtin.fanout', 'builtin.reorder']
    ] = Field(default_factory=lambda: ['builtin.astar'], min_length=1, max_length=4)
    job_id: str | None = None
    candidate_id: str | None = None


class Check(Scoped):
    action: Literal['start', 'status'] = 'start'
    expected_revision: StrictInt | None = None
    job_id: str | None = None
    bounds_um: tuple[float, float, float, float] | None = None


class Capture(Located):
    width: StrictInt = Field(default=2560, ge=320, le=4096)
    height: StrictInt = Field(default=2560, ge=240, le=4096)
    bounds_um: tuple[float, float, float, float] | None = None
    job_id: str | None = None
    candidate_id: str | None = None
    target: CaptureTarget | None = None
    highlight: Literal['auto', 'none', 'net', 'component'] = 'auto'
    fit: Literal['region', 'target'] = 'target'
    layers: list[str] | None = Field(default=None, min_length=1, max_length=128)
    style: Literal['native', 'outline'] = 'native'
    pin_names: bool = True
    instance_names: bool = True
    net_names: bool = False


class Release(Scoped):
    outcome: Literal['done', 'cancelled', 'handoff'] = 'cancelled'
    note: str = Field(default='', max_length=20000)


class ServerDrc(Scoped):
    action: Literal['start', 'status', 'cancel'] = 'start'
    expected_revision: StrictInt | None = None
    bounds_um: tuple[float, float, float, float] | None = None
    job_id: str | None = None
    exclude_categories: list[Literal['border', 'density', 'seal_ring']] = Field(
        default_factory=lambda: ['border', 'density', 'seal_ring'], max_length=3,
        description='兼容旧客户端：空列表等价 include_waived=true；非空值不授予额外豁免。过滤和验收仅使用人端工艺设置。')
    include_waived: bool = Field(default=False,description='显示已过滤项及依据；只改变列表，不改变 passed 或完成验收。')
    offset: StrictInt = Field(default=0, ge=0)
    limit: StrictInt = Field(default=100, ge=1, le=500)
    result_limit: StrictInt | None = Field(default=None, ge=1000, le=1000000,
        description='可选：本次每条规则及 APP 保留标记的上限；报告截断时显式提高后重新 start，不改变工艺规则。')


class Reference(Arguments):
    action: Literal['list', 'read', 'preview'] = 'list'
    case_id: str | None = None
    kind: Literal['summary', 'schematic', 'layout'] = 'summary'
    query: str = Field(default='', max_length=200)
    offset: StrictInt = Field(default=0, ge=0)
    limit: StrictInt = Field(default=100, ge=1, le=500)


TOOLS = {
    'process_configuration': (ProcessConfigurationArgs, '独立工艺配置：requirements 获取配置包 schema、采集清单和本机连接；list/get/status 读取配置与提案；submit 提交统一配置待人审核；export 返回可分享的配置 JSON。无需占用操作区。仅 UI 可以批准、验证并启用，API 没有 approve。双排保护环和开放路径必须来自用户样例。包不携带连接凭据；实际版图不受提交影响。'),
    'workspace': (WorkspaceFile, '整工作区文件：status/list 无需接入；save 保存独立存档而不切换当前文件；load 从已允许目录读取 .colayout.json，先备份当前文档，再打开工作副本。加载要求所有区域空闲、后台任务结束且没有未决原生事务。不会自动同步 Virtuoso。'),
    'reference_cases': (Reference, '查询人添加的本地案例库，读取原理图/版图快照或预览；只读，无需区域接入。'),
    'server_drc_region': (ServerDrc, '异步服务器 Calibre 全规则 DRC，可独立启动用于排查，不要求本地先通过。推荐经常先跑本地检查；完成仍需当前全区两类证据。默认整个已接入操作区，可给区内 bounds_um，但局部结果不能用于完成。仅直接子操作区与原生嵌套模块内部为黑盒；普通器件正常检查。start 必须给 expected_revision。UI、API 和完成验收统一使用人端工艺过滤设置；原始报告保留。'),
    'claim_region': (Claim, '凭人或父 Agent 分配的操作区 ID 独占当前层；父子可分别接入，只列出本层直属子区，不进入更深层。'),
    'inspect_region': (
        Inspect,
        '读取本层对象、Layout PIN/网络、工艺规则或仅供布局参考的原理图缓存。坐标为工作区绝对 µm。',
    ),
    'edit_region': (
        Edit,
        '原子编辑本层几何和直接子区框/接口/策略，或撤销自己的无冲突编辑；expected_revision 必填，无关区域编辑不使已读取版本失效。8–64 项直属对象/原生豁免批量操作在后台校验，返回 job_id；用 status 查询，完成且 edit_applied=true 才表示已采用。不得另换 request_id 重发。',
    ),
    'route_region': (
        Route,
        '为本区域生成本地布线候选、查询、重检、采用或丢弃。模拟部分不建议使用内置自动布线，数字部分可以考虑。采用后仍须本地及服务器 DRC。generate/recheck/apply 必须给 expected_revision。',
    ),
    'check_region': (
        Check,
        '显式异步检查 Layout 连通性、本地 DRC、设计警告及跨器件 Poly 接触补丁。包括非阻断的器件内部金属误接风险提醒，不代表 LVS 结论。建议频繁运行，频率高于服务器 DRC。本地 passed 仅表示连通性和支持的检查项通过；不支持的宽度计算直接跳过，不生成逐项记录。服务器 DRC 独立检查。默认整个接入区，可用 bounds_um 指定局部范围；局部结果不能用于完成。start 必须给 expected_revision。',
    ),
    'capture_region': (
        Capture,
        '返回本区域的 PNG 截图和坐标范围；可查看本区域当前布线候选，不改变人的视图。',
    ),
    'release_region': (Release, '释放本层占用；done 需当前全区本地检查和服务器 DRC 均 passed=true；本地实际错误、连通问题和检查失败仍阻断完成。没有顺序门禁，两类证据缺一不可。handoff 保留修改并交还，不代表验收通过，可附 note。区域完成不代表整芯片或 LVS 签核。'),
}
EDIT_ACTIONS = frozenset(
    (
        'create_rect',
        'create_path90',
        'create_path45',
        'create_pathseg90',
        'create_pathseg45',
        'create_polygon',
        'create_via',
        'place_instance',
        'move',
        'rotate',
        'mirror',
        'set_width',
        'edit_rect',
        'edit_path90',
        'edit_path45',
        'edit_path_ends',
        'edit_polygon',
        'edit_via',
        'reset_via',
        'set_net_intent',
        'copy',
        'delete',
        'transform',
        'create_bus',
        'create_guard',
        'create_auto_vias',
        'create_multilayer_path',
        'arrange',
        'align',
    )
)
from .child_regions import MODELS as CHILD_MODELS
EDIT_ACTIONS=EDIT_ACTIONS|CHILD_MODELS.keys()


def describe_tools():
    from .discovery import usage
    return [
        {'name': name, 'description': description, 'input_schema': model.model_json_schema(),
         'usage': usage(name, EDIT_ACTIONS)}
        for name, (model, description) in TOOLS.items()
    ]

# Agent API

**简体中文** | [English](../en/api.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

参数细节见[接口 schema（JSON）](../../templates/layout-agent/docs/api-schema.json)。实际使用前先查询运行中 APP 的接口发现结果。

## 通信与发现

APP 在 127.0.0.1 提供带身份验证的 HTTP 服务，将当前 URL/token 发布到 agent-connection.json。该文件是私有运行数据。使用生成的客户端目录，不写死端口；GET 不是工具调用协议。

向 /call 发送 POST，带 Authorization: Bearer <local-token>，JSON 对象必须恰好包含 tool、arguments、request_id 和 client_id。服务器限制请求大小并拒绝非有限 JSON 数值。建议使用附带客户端处理响应与轮询。

```json
{
  "tool": "workspace",
  "arguments": {"action": "status"},
  "request_id": "caller-generated-unique-id",
  "client_id": "layout-agent-1"
}
```

特殊的 tools 调用返回当前可用工具的 schema，不计入下面的业务工具。默认开放 10 项；人端工艺设置启用算法自动布线后再开放 route_region。静态 schema 列出全部可能工具，运行中的接口发现及权限检查优先。目前不支持 MCP 通信。

## 工具

| 工具 | 用途 |
|---|---|
| workspace | 状态查询，以及允许目录内的显式存档保存/加载 |
| reference_cases | 只读查询人提供的参考案例 |
| process_configuration | 初始化角色的需求查询、提案提交/查询和配置导出；无 API 批准动作 |
| claim_region | 独占一个操作层 |
| inspect_region | 查询本区域的版图、规则、连通和原理图参考 |
| edit_region | 校验后采用编辑批次，包含受支持的边界、PIN、保护环和局部布线豁免 |
| route_region | 默认关闭，仅人在工艺库启用后开放的算法自动布线 |
| check_region | 本地受支持 DRC 与连通检查任务 |
| capture_region | 区域只读截图，不改变人的视角 |
| server_drc_region | 服务器区域检查与结果查询 |
| release_region | 释放/阶段交接，或在证据通过后标记完成 |

API 不开放任意 Python/SKILL、直接 Bridge 访问、任意原生导入/同步、PCell 内部编辑或人端工艺批准。

工艺库“绘图与图层”页的“允许 Agent 使用算法自动布线”默认不勾选，旧配置也按关闭处理。该权限只限制 route_region：关闭时不列入实时 tools，generate/recheck/apply 返回 AGENT_AUTOROUTE_DISABLED；已启动任务仍可 status/discard，原请求的幂等回执保留。人类 UI 自动布线以及 Agent 的排列、对齐、自动过孔、多层路径等工具不受影响。inspect_region(kind=rules) 返回 agent_autoroute_enabled；routing 层/孔参数仍可读取，但不代表授权。process_configuration.submit 无权改变权限，省略字段时保留人端选择，尝试改变返回 AGENT_PERMISSION_UI_ONLY。共享配置导入后默认关闭，须由本机人端勾选并审核保存。

edit_region 的 tighten_region/tighten_child_region 与人端“收紧操作区”共用几何逻辑：按内容及直接子区 PIN 外形收紧，各轴自动预留自身/直接子区最大 PIN 尺寸的一半，再加 10%（至少一个制造网格），向外取整。padding_um 为额外叠加余量；返回 pin_clearance_um 为自动余量。仅在原框内收缩，不移动原生几何，不改变 PIN 模式，也不对已经过紧的原框额外提示余量不足。

## 身份、版本和任务

先 claim，保留返回的 session token；每个并行执行者使用独立客户端身份。编辑前 inspect，并提交 expected_revision 和实际对象 ID。不能以全局 revision 为由覆盖本区域的过期输入。

请求由 client_id + request_id + 相同 body 确定。网络超时后保留这组值，换 ID 可能产生第二次操作。对账成功前保留 pending。queued/running 不表示成功，应轮询原 job_id。遇到 stale/cancelled/failed，先理解结果、重新查询，再调整操作。

服务器 DRC 不强制先取得本地通过；done 仍要求当前全区本地和服务器两类证据。建议性 warning 与阻断错误分开。人端批准的报告过滤统一用于 UI、API 和服务器验收，原始已过滤记录仍可查看；它不能豁免本地物理错误。

## 客户端生成与 schema 维护

tools/create_layout_agent.py 仅复制执行模板、说明及生成的 SDK/schema，不复制另一个 Agent 的任务、身份或 pending。更新已有托管文件前核对哈希。目录权限由外部 Agent 宿主执行，说明文件不是安全沙箱。

修改 agent_tools/contract.py 后运行：

```powershell
.\.venv\Scripts\python.exe -m tools.build_customer_api_kit
.\.venv\Scripts\python.exe -m tools.build_customer_api_kit --check
```

再用 --update 更新指定的空闲客户端目录。不能默默扩大版图 Agent 到维护或工艺配置权限。

## 实现归属

http_api 把调用交给所属线程；session/leases 处理占用和重放；region_edits/region_tasks 编排领域服务和不可变后台输入；inspection/capture 保持范围；release_status 核对证据。业务规则放在共享 Editor、区域、物理和工艺服务，不在 HTTP 分支重复实现。

---

**简体中文** | [English](../en/api.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

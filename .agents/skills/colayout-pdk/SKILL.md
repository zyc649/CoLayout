---
name: colayout-pdk
description: Configure CoLayout process libraries by directly collecting Virtuoso samples, checking native geometry reproduction on copies, and submitting through the APP API for human review. Default onboarding does not run DRC. Use for PDK onboarding and process settings, not ordinary layout editing.
---

# CoLayout 工艺配置

用户提供样例，配置 Agent 直接采集并核对几何复现，再通过公开 HTTP API 提交。只有人端“工艺库 → 待审核 → 审核并启用”能启用配置。不要直接写正式配置、调用发布函数或替用户点击批准。

先加载项目级 `virtuoso` skill。复用现有 Bridge 环境和目标 Virtuoso；不重启进程、不改共享 PDK、不清原生身份或 pending 来绕过失败。配置 Agent 可运行本 skill 的专用采集/副本检查器；普通绘图 Agent 仍只使用区域 API。

## 入口

首次部署先按仓库 docs/zh/agent-setup.md（英文版 docs/en/agent-setup.md）完成安装、连接和 APP 就绪检查。只有连接正确且 API 可达后再采集；维护已有源码不代表需要重新配置工艺。具体命令位置、文件阶段和失败恢复见[执行与恢复](references/workflow.md)。

先完成仓库 setup.ps1 和服务器连接检查。使用项目 .venv 的 Python 3.13；本机状态位于项目根 .colayout/installation.json。脚本入口为本 skill 的 scripts/setup.py，实现来自安装的 colayout_lite.process_agent。默认读取本安装当前 APP 连接；明确选择其他安装时可传 --api-connection。不要把 Bridge token 当作 APP token。

先运行 `requirements` 获取实际配置包 schema 和连接 ID，再运行 `inspect` 确认已开的 Layout。多个候选时按用户明确的样例选择，仍有歧义才询问；不猜历史默认库/cell。参数名、层名和 via 名都取实际资料。

## 样例与采集

样例应保存，包含正常 MOS、电阻和原生 MIM 电容，以及每对相邻金属之间独立的默认 1×1 标准过孔。工艺确实不支持 MIM 时明确记录，不用其他种类电容冒充。样例不必有配对原理图。普通器件用来核对原生参数与 CDF；不能按器件名字建立通用的 MOS/电阻识别规则。

collect 后先核对 device_masters 摘要及 device-evidence.json 与用户声称的样例清单。实例名称不是器件类型证据：名字像 NMOS 的实例可能实际是 PMOS，两个不同名字也可能引用同一个 NMOS master。结合实际 master/CDF/PDK 资料核对；缺少所需样例时让用户补齐并保存，再用新目录重采，不能沿用旧 source_digest。原采集和已发送请求保留。

MIM 层位写入 `drc.mim_capacitor`：实际图层/用途、下方金属、上方金属及证据来源。依据样例、技术文件、层映射与当前选项下的 LVS/提取规则确认，不靠层名、颜色或单个 PIN 推断。具体采集与提交见 [MIM 接触层位](references/mim.md)。无法确认时保留 `unconfigured`，可提交待审核方案，由人在“本地 DRC → MIM 电容”确认；不得因采集失败填写 `unsupported`。只有确认工艺不支持 MIM 才使用 `unsupported`。

默认只启用已测量的金属层和 NW。用户要绘制其他工艺层时，需在样例中放置该层的独立矩形，采集原生 LPP、实际几何和显示样式；保持额外层未勾选，由用户在“绘图与图层”审核启用。样例图形不自动证明物理材质，材质仍取实际 PDK；标识层可以保留 unknown，不要为了开放绘制伪装成金属或井。记录 standalone_lpps，便于审核时直接显示已提供样例的层。

每种需要启用的 P/N 保护环类型，要求一段原生 90° 开放 MPP 路径，含直段、拐角和两个端头。直接采集开放端头，不再默认从闭环推算。双排必须有对应的真实双排开放样例；没有则不配置，不从单排扩展，也不把打平图形当作 MPP。闭环可作为补充参考，旧配置与旧几何保持兼容。

单排/双排指接触孔的排数，闭环/开放路径指形状，两者不要混淆。同一配方经核对后支持矩形闭环和开放 90° 路径，不必为同一截面重复配置两种条目。提交前明确列出孔排数与支持形状，不能把“单排”解释成只能画直条，或把闭环样例误认为双排样例。

开放端头与闭环接缝分开处理。原生闭环的重合起终点之间必须留足样例规定的孔间距，不能照搬开放端头的接触孔退让。使用生成器按配方孔间距/网格计算的闭环参数；有同截面闭环样例时作对照。数值不写死到某个 PDK；不以开放路径复现通过替代闭环接缝检查。

配置以采集和忠实复现为主。默认 check 不运行保护环 DRC，也不自动执行全套本地/服务器 DRC 试验；仅核对数据、文件路径/哈希和必要的原生往返。不能把几何核对通过描述为 DRC/LVS 通过。只有用户要求或具体问题需要定位时，才做针对性的额外检查，保留报告。实际设计仍需完整检查。

```powershell
$python = Join-Path (Get-Location) '.venv/Scripts/python.exe'
$setup = Join-Path (Get-Location) '.agents/skills/colayout-pdk/scripts/setup.py'
& $python $setup requirements
& $python $setup inspect
& $python $setup collect --library <库> --cell <样例> --out <新的采集目录>
```

采集目录保存 package.json、逐层默认宽度依据、原生 MPP、器件/CDF 和规则文件候选。目录必须是新的，保留旧记录。脚本不修改样例或正式配置。

默认金属顺序来自材质和 via 连接关系。分支不明确时核对后传 `--metal-stack`；同层对有不同单孔时传 `--via-uids <JSON>` 指定实际 UID。默认线宽取过孔外部金属矩形短边：首层取首对过孔下层金属，其余层取前一级过孔上层金属；不取切孔尺寸或 DRC 最小宽度。保留矩形长宽和测量依据。只有已测量的金属栈和阱层默认允许绘制。

部分旧 PDK 把原生材质留作 unknown。先查看采集目录的 native-technology.json，再根据该 PDK 的技术文件、层映射和规则正文补充 `--layer-materials <JSON>`：`{"实际层名":{"material":"metal","source":"真实文件与定义位置"}}`。仅能补充原生 unknown/null；不得覆盖原生已知材质、按 M1/GT 等名字猜测，或修改共享 PDK。原始值与依据随提案保留，UI 标明“补充”。修正失败采集后使用新目录，保留旧记录。

新配置按原生技术库、几何指纹和可选 `--variant` 区分。维护已知同源的旧项时可传 `--replace-key`；不同 PDK/工艺选项不能覆盖同一配置标识。

## 填齐配置并检查

阅读 [采集与规则依据](references/collection.md)，编辑采集目录的 package.json。填写真实规则来源、本地规则、方向/孔数设计提醒、服务器 deck/层映射/工具路径，以及需要的参数摘要和报告设置。默认画线宽度不是 DRC 最小值；不确定的规则不伪造。

新配置的默认方向：实际金属栈首层不指定；第二层横向、第三层竖向、第四层横向，依次交替。通常即 M1 未指定、M2 横向、M3 竖向、M4 横向；按实际栈位置取层，不写死层名。directions 中省略首层条目；Agent 不自行给首层加方向。明确由人设置的已有偏好应保留，人可在 UI 随时修改包括首层在内的方向；用户明确要求的例外优先。这是设计偏好，不是 foundry 规则，不新增 API 硬限制。

新配置默认开启服务器报告过滤：report_policy.enabled=true，keywords=["BORDER","density","seal ring"]，rule_ids 默认留空。人可调整；明确已有的人端设置或本次指示优先。UI、Agent API 与服务器区域完成验收统一使用人端批准的此策略，原始结果保留。不要把某个 PDK 的个别规则自动加入其他工艺的豁免；普通绘图 Agent 无权自行增加验收豁免。未豁免错误、检查失败/截断/过期以及本地检查仍按原规则阻断完成。

“原理图参数摘要”是 technology.schematic_summary_parameters：按顺序选择人端原理图参考与 Agent 默认摘要中显示的原生参数名，不是器件参数编辑或映射。必须从本工艺实际实例 CDF 核对内部 name、值及单位，不能复制其他工艺的 w/l/nf 等字段清单。具体含义及 Virtuoso 查找方法见 [参数与原理图](references/collection.md#参数与原理图)。

```powershell
& $python $setup check <采集目录>
& $python $setup request <采集目录>
& $python $setup submit <采集目录/submit-request.json>
```

check 在私有副本核对基本图形/默认尺寸往返、开放 MPP 与样例的逐层实际几何一致性、闭环生成与删除恢复，并检查规则数据及服务器文件。没有 DRC 求解或保护环全场景扫尺寸。成功后使用 checked-package.json；回执标明 native_reproduction / drc_checked=false。request 固定 client_id/request_id 和参数；submit 只提交提案，由 APP 通知人审核。

失败时只修有依据的参数。来源不符、原生结果未知或样例改变时停止该次流程，保留文件并核对；不要重发新 ID 或无限新建副本。已知校验失败且有新依据时可修 package 后再 check。结果未知的 submit 必须原样重试同一请求文件；不得编辑已发送文件。

返回 pending_review 表示等待人，不是已启用。用 status 查询 proposal_id；只有 confirmed 才告知配置已保存。人若改动影响验证的参数，APP 会重新检查；未改变且回执有效时只核对源和文件，不重复整套副本测试。

维护已审核工艺、仅更新 MIM 或设计提醒等本地设置时，可从 get 返回的完整配置提交修改，保留其他原生数据、保护环及其证据。审核会在严格核对保存基线和连接/样例引用后复用未变化的原生配置，不因历史样例对象 ID 已变化而重采保护环。不要为了让 MIM 配置通过而删除保护环或改写其 source.native_id。原生参数/工厂、规则阈值、服务器配置或采集证据变化仍需完整验证。

## 分享与边界

已保存项可以通过 UI 或 `export <配置key> --out <文件>` 导出单个 JSON。文件不含工作区、Bridge 凭据和原始 PDK/deck 文件。接收方导入后绑定本机服务器路径；导入继承配置，不假称已在新主机重新做全部原生往返。

本地 DRC 仅检查已支持的项目，不支持的宽度计算直接跳过。真实错误、数据缺失和检查失败仍需处理；完成版图仍需当前全区本地与服务器 DRC 都通过。配置验证不等于完整 LVS 或所有器件签核。

# 采集与规则依据

## 本机与服务器边界

requirements 中的 connection ID 指向本机已配置的 Bridge 连接；collection_connection_file 是专用采集器使用的配置路径，不是要分享的数据，也不是普通绘图 Agent 的文件权限扩展。采集器生成的临时连接只改变自己的输出目录和已核对的业务库根，不覆盖当前连接。

inspect 使用 Bridge 读取已开的 Layout、技术库、工程目录与未保存状态。目标必须来自用户指示或实际窗口。CONNECTED_PROJECT_MISMATCH 不能通过重置 ltInit/身份缓存解决：连接正确的 Virtuoso 实例。

## 信息来源与填写位置

| 信息 | 可靠来源 | 统一配置位置 |
| --- | --- | --- |
| DBU、制造网格、LPP、材料、标准 via | 原生 techfile 与标准对象，采集器保留完整数据 | technology 的 native 字段 |
| 金属顺序 | 原生金属材质、via 层对、工艺文档；有分支时明确选择 | editor_defaults.metal_stack |
| 每层默认线宽 | 实际 1×1 via master 金属矩形的短边，保留完整尺寸 | widths_um 与 sample_evidence.stack_measurement |
| 最小宽度/间距/面积/包围 | 已选工艺版本/金属选项的真实 DRC 规则正文 | drc.rules，含 source 与条件说明 |
| 走线方向与逆向提醒 | 已有设计偏好或工艺 routing 指南；缺少时提出建议给人审核 | drc.design_warnings.directions |
| 单孔提醒 | 设计偏好，不能冒称 foundry 最小孔数 | drc.design_warnings.via_enabled/minimum_cuts |
| Calibre、XStream、环境、deck 与 map | 已有 runset/项目配置及实际文件 | drc.remote |
| MPP 形状、截面、孔列、来源 | 样例中实际原生 MPP | technology.guard_recipes |
| CDF 字段/单位和 Layout PIN | 原生实例的 CDF/端子；不求值、不重命名 | device-evidence.json；summary_parameters 只选实际字段 |
| 报告过滤 | 本项目默认开启 BORDER/density/seal ring；人的明确设置优先 | report_policy；UI/API/服务器区域验收共用，保留原始报告 |
| MIM 层位 | 原生 MIM 样例、技术栈/层映射及当前选项的实际提取规则；不明时让人确认 | drc.mim_capacitor；详见 [MIM 接触层位](mim.md) |

首层默认宽度取首对 via 的下层金属，其他层取前一级 via 的上层金属；中间层不能改用下一级 via 的下层尺寸。切孔尺寸不是金属线宽。网格取整应保留原测量与建议值。

不同技术库可能具有相同几何层/孔定义，仍应区分配置 ID。原生技术库名用于核对，几何指纹继续用于原生事务。工艺选项/版本来自规则与 runset，不从样例外观推断；同库不同方案可用 --variant。

若原生材料为 unknown/null，配置 Agent 可从实际工艺资料补充 `metal/cut/poly/diff/nwell/pwell/nplus/pplus`。使用 collect 的 --layer-materials 文件，不更改服务器 tech.db。TechnologyProfile.layers 表示审核后的生效材质；material_evidence 保留被补充层原始 native 值及 source，native_layers 属性重建原生表用于严格核对。已有原生材质不能覆盖。金属、Poly、扩散、井和植入角色必须分别有依据，不能把所有未知层当作金属；这不是本地/服务器规则名对应表。材质变化需重新采样验证并审核。

工艺文件导出要求完整配置，UI/API 使用相同检查。缺少真实服务器 deck 时，submit/export 不会伪装成已完成；不能拿 ICC 路由规则或别的 PDK deck 替代。

## DRC

rule-candidates.json 仅列候选，不自动选规则。先确认主 deck、工艺版本、金属选项、include/宏和层映射，不能按文件名猜。local rule.id 不要求等于服务器规则名；source 必须指明真实依据。

本地规则是保守简化检查。不能把有特殊区域、线端、同网/异网等条件的复杂规则去掉条件后当作精确阈值。不确定的项保持未启用并说明；不要用 fabricated 数值凑齐配置。

方向是可审核偏好。新配置默认首层未指定（directions 中省略此层），第二层 horizontal、第三层 vertical，之后交替；Agent 不自行指定首层方向。依据实际金属栈位置，不按 M1/M2 字符串猜层。通常对应 M1 未指定、M2 横向、M3 竖向、M4 横向。已有明确的人端偏好保留，用户可手动修改任意层，明确指示优先；API 不强制禁止首层方向。方向不是测量得出的 foundry 规则，逆向长度和 minimum_cuts 同样是偏好。

默认 check 只核对规则结构、来源和服务器文件路径/哈希，不运行本地故意错误/修复或服务器 DRC。需要诊断时按具体问题另行调用检查器；不维护本地/服务器规则名对应表。采集/几何复现的回执必须与 DRC 签核区分。

### 服务器报告过滤默认值

新配置设 report_policy.enabled=true、keywords=["BORDER","density","seal ring"]、rule_ids=[]。这是人端批准的审阅与区域验收策略，UI、API 和 release(done) 共用；已有明确设置须保留。关键词匹配服务器规则 ID/可见规则正文，不区分大小写、连续空白归一化；不是正则，不匹配文件路径或整个规则文件标题。规则 ID 栏按完整 ID 匹配。不要自行加入井宽、间距、短路或某个 PDK 的特殊错误；只有人的明确决定才增加豁免。原始报告保留，按过滤设置的区域验收不代表整芯片或 LVS 签核，本地检查不应用这些过滤。

## 保护环

只有实际样例支持的双排类型可启用。查看 guard-samples.json 的原生 ID、截面和 contact_rows；单排/双排分别处理，不猜 P/N 类型或嵌套关系。使用已读取的实际材料，不能凭名字伪造阱或植入层。

contact_rows 是截面接触孔排数，closed_rectangle 是形状，两者独立。单排配方也可以生成闭环；同一配方的 validation.forms 应包含 ring 和 path。向人汇报及 UI 展示时把“单排接触孔”和“矩形闭环 / 开放 90° 路径”分开表达。

每种所需 P/N 类型以原生 90° 开放路径为采集样例，直接读取端头、截面、孔列和间距。闭环仅作补充参考；不要对已有开放样例重新推算端头。旧资料仅有闭环时需补开放样例或明确不配置该能力。

默认核对包括：开放样例按原尺寸平移复现，逐层比对实际几何与图形数量；生成一个闭环检查原生读回；删除新增对象后确认副本恢复，原样例未改。没有保护环 DRC 或多尺寸扫描。未通过复现时定位采集/生成问题，不用调参数或增加豁免掩盖差异。双排没有样例不配置。

闭环起终点位于同一点，接触孔退让不能沿用开放路径的端头包围量。生成器按每排原生 space 的一半向外网格取整，保留更大的显式退让；开放端头保持采集值。检查生成闭环接缝的实际孔间距，有闭环样例时对比其相应参数。此项是生成几何核对，不是全域 DRC，也不要求为此增加新的用户样例。

默认绘图只启用金属和 NW；额外层由用户在样例放独立矩形并在审核页勾选。standalone_lpps 记录这些顶层图形的 LPP，界面可直接列出；不自动勾选、不把 unknown 标识层改成导体。材质、图形颜色/填充和绘图权限是不同信息。额外层所需包围或电压域规则由实际 PDK 和设计上下文决定，不能以单个矩形存在推导规则或自动拓展别的层。

遇到报告，先判断是哪类问题：生成器偏离样例或几何本身错误，应修复；组件缺少器件/井区等伴随结构，应按真实用途在副本中补齐后检查；密度、芯片边界等全局项不能据此断言组件无效。需要上下文的配方应记录依据与使用条件，不能只凭规则名批量放行。

典型例子：独立 N+ / NWell 环可能因窄井环带或内孔报错，实际使用会与内部器件的完整井区合并。这属于使用上下文，不是配置失败的充分依据。需要诊断时可在副本补齐井区对照，不改原样例或屏蔽几何错误。默认配置流程不做这一 DRC 试验，普通绘图 Agent 仍须在实际设计中补井并复查。

有合理上下文后仍存在的真实违规必须处理，不能增加几何错误 Waive。缺乏上下文依据时保留报告并说明待核实条件，不把猜测写成工艺要求。相同原因连续失败且没有新依据时停止重试。导入的已验证样例配置可复用，不要求接收方重建原来的样例 cell。

## 参数与原理图

“原理图参数摘要”填写的是原生参数内部名称的有序列表。它决定人端原理图参考树和 Agent 默认参数摘要展示哪些字段；不会改器件数值、执行 PCell/CDF 回调、删掉已采集的其他参数或改变 Layout/原理图对应关系。某实例没有所选字段时只省略该字段，不补猜。人端“全部原生参数”和 API 显式参数查询仍可查看其他已采集字段。

常见候选包括 w（宽度）、l（长度）、fw（指宽）、fingers/nf（指数量）、m（倍乘）、r（电阻值）、c（电容值）；这些只是查找线索，不是跨 PDK 固定清单。w 是总宽还是单指宽、m 与 fingers/nf 的关系，以及阻容值是否已含分段等，都须查实际 CDF/PDK 定义。不从名字推导或相乘，不把表达式求值成新参数。

查找步骤：

1. 用 collect 读取用户已保存的 Layout 样例，查看 device-evidence.json。每个实例的 master 是真实库/cell/view；parameters 中每行依次为内部 name、type、units、有效 value、默认 defValue、来源和显式实例值。采集器调用 cdfGetInstCDF，保留实例有效 CDF 而非只读库的默认值。无 CDF 时记录缺失，不按器件名补猜。
2. 在 Virtuoso 中需要人工对照时，选中该实例查看对象属性，确认尺寸、指数量、倍乘和阻容值等含义。属性表上的标签可能是 CDF prompt，不一定等于内部 name。可从 CIW 的 Tools → CDF → Edit 打开对应 master 的库/cell，选择 Cell / Effective 查看参数定义，对照 Name、Prompt、Units；只查看并取消，不 Apply/保存或改共享 PDK。
3. 专用 Agent 优先使用上述采集器。需要补充读取时，先按 virtuoso skill 查询本机已安装文档中的 cdfGetInstCDF(d_instId)，再读取返回 CDF 的 parameters/name/value/defValue/units；不要执行回调或为读取参数修改实例。CDF 界面说明见该版本 Component Description Format User Guide 的 CDF Commands / Edit CDF Form，菜单变化时查安装文档。
4. 根据实际参数名、单位及含义挑选少量有用字段，保留大小写，写入 technology.schematic_summary_parameters；UI 用逗号分隔。w 与 Width 是不同名字，fingers 与 nf 也不能互相猜替。已有默认候选未覆盖本 PDK 真实字段时，依据证据选择正确名称，而非只保留默认词表的交集。

样例只有 Layout 时不强制补原理图，已有配对 schematic 可用于交叉核对。实际设计导入的原理图参数及 XL 原生对应仍由原有流程读取；例如本工艺仅提供 fingers 而没有 nf 时，不因另一工艺用了 nf 就把它加入摘要。

## 结果核对

check 成功返回 verification_id 和 checked-package.json。提案未审核前不影响用户工作区。status=needs_attention 时看具体错误与保留的报告；confirmed 仅表示配置已批准，不表示用户版图已通过检查。

分享文件保留配置与来源摘要，服务器路径可能需接收方绑定。不要把 .env、token、workspace、pending 或整份 PDK 文件复制进配置包或对话。

# 源码接手指南

**简体中文** | [English](../en/maintainer-guide.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

拉取仓库后要修复 bug 或修改行为，请从本页开始。接手不需要原作者的私有交接包、旧对话或已有用户文件。本页同时供人工维护者和编码 Agent 使用。

## 先判断当前任务

| 情况 | 阅读入口 |
|---|---|
| 新电脑／首次部署 | [Agent 初始化执行手册](agent-setup.md)，再按两项项目级技能执行 |
| 已有安装，修改源码 | 本页、[软件架构](architecture.md)、[源码实现详解](internals.md) |
| 工艺事实或配置提案 | 项目 colayout-pdk skill；不靠改变几何规则掩盖错误配置 |
| 在指定操作区画版图 | 生成的客户端目录中的专用说明，不走源码维护流程 |
| 依赖升级或打包 | [依赖来源](dependencies.md)和[许可说明](licensing.md) |

接手维护时，不要自动重新配置服务器、重采 PDK 或替换版图客户端。先确定用户实际运行哪套安装和进程。

## 首次检查

从仓库根目录运行：

~~~powershell
git status --short
git log -5 --oneline
.\.venv\Scripts\python.exe tools/check_environment.py
.\.venv\Scripts\python.exe -m colayout_lite.bootstrap status
~~~

新 checkout 没有 .venv 时先执行 setup.ps1。status 连接被拒绝仅表示 APP 不可达，不代表文档损坏，按[初始化手册](agent-setup.md)排查。保留已有未提交改动和本机配置。

在本机读取 .colayout/installation.json，核对实际文档、解释器、源码和当前客户端目录。其中 test_kit 是版图客户端目录，保留这个兼容字段名。不能把桌面上的 JSON 存档或记忆中的路径当作活动工作区。

修改前记录提交号、复现步骤、相关错误/request_id/job_id、文档 ID/revision 和操作层。必要时保存显式便携工作区副本。token、原生版图和日志不能进入公开报告。

## 源码阅读顺序

1. [软件架构](architecture.md)：所有权、两套层次和正确性边界。
2. [源码实现详解](internals.md)：数据模型、真实入口、调用链、持久状态和测试对应关系。
3. [Agent API](api.md)：请求身份、区域租约和异步语义。
4. [开发与验证](development.md)：测试与发布流程。
5. 阅读相关实现及其测试；文档用于导航，最终行为以当前代码为准。

按符号名搜索，不依赖会过期的行号：

~~~powershell
rg -n "class Editor|def publish|def transaction" colayout_lite/editor.py
rg -n "OUTCOME_UNKNOWN|RECONCILE_BEFORE_RETRY" colayout_lite tests_lite
rg -n "create_guard" colayout_lite/agent_tools colayout_lite/layout_helpers
~~~

## 保留用户数据的排错流程

1. 区分输入/配置、领域逻辑、GUI 生命周期、后台计算/采用、通信或原生源状态问题。
2. 用合成对象或已授权工作区副本复现。Editor 和几何回归不需要 SSH，原生操作单独显式执行。
3. 保留第一个失败及其证据；后续超时可能只是 Qt 主线程阻塞的表象。
4. 先找到共享领域服务，再决定是否需要 UI/API 适配。
5. 用行为回归证明 bug 和需要保持的不变量，覆盖失败与成功路径。
6. 跑相关专项，再跑公开完整回归及适用的 GUI／原生验证。
7. 交付时说明改动、验证证据和限制。Python 修改需要在 APP 空闲后正常重启加载，不停止 Virtuoso。

原生结果未知时，读取 Adapter 的持久工作区并对账。不能把旧存档覆盖到 submitting/indeterminate 文档上，不能删 pending、换请求 ID 或放松源核对。基线冲突与事务结果未知是两类问题，先确认实际变化。

## 验证命令

~~~powershell
.\.venv\Scripts\ruff.exe check colayout_lite tools
.\.venv\Scripts\python.exe -m pytest tests_lite -q
.\.venv\Scripts\python.exe -m tools.build_customer_api_kit --check
.\.venv\Scripts\python.exe tools/check_docs.py
.\.venv\Scripts\python.exe tools/audit_release.py
~~~

专项测试分组见源码实现详解。修改契约后先去掉 --check 执行生成器，检查差异，再核对一致性。

tools/smoke_onboarding.py 仅用于全新空白安装，会主动拒绝已有设计并禁止原生访问。它验证 Qt 交互、HTTP 和独立客户端，不覆盖任意设计编辑。GUI 修改同时使用控制台 Python 和 pythonw 验证。

## 现有测试的覆盖边界

公开测试使用合成数据，不含私有设计 fixture。通过不代表每个 PDK、原生规则、显卡、大场景、模态窗口生命周期或真实并行工作负载都已验证。相关区域缺少专项测试时，应新增复现，不能凭模块名字接近就声称覆盖。

渲染与部分编排仍分布在较大的模块中。优先沿已有边界做有针对性的提取，不把大改写与正确性修复混在一起。不要为了简化本地检查把原生层次打平为可编辑物理图。

代码变化时同步维护中英文文档、API/schema、技能与执行说明。每项改动应能找到实现入口、回归入口和恢复入口。

---

**简体中文** | [English](../en/maintainer-guide.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

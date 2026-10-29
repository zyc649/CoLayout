# 开发与验证

**简体中文** | [English](../en/development.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

## 环境与入口

使用 Windows 和仓库自己的 Python 3.13 虚拟环境。执行 setup.ps1 后运行：

```powershell
.\.venv\Scripts\python.exe tools/check_environment.py
.\.venv\Scripts\ruff.exe check colayout_lite tools
.\.venv\Scripts\python.exe -m pytest tests_lite -q
.\.venv\Scripts\python.exe -m tools.build_customer_api_kit --check
```

Start-CoLayout.cmd 委托 tools/project.ps1 启动。源码采用 editable 安装；有风险的实验使用独立 checkout 和运行目录，不能让测试安装指向用户的可写工作区或当前原生目标。

公开测试使用合成几何与模拟回执，不要求 PDK，也不连接服务器。它们不证明所有工艺或商业工具版本都通过。工艺专项验证使用用户样例与已授权的私有副本。

## 修改流程

1. 找出共享领域行为及其 UI、API、原生调用方。
2. 保持单位、对象 ID、权限和事务语义。
3. 物理、权限、异步结果采用和事务变更增加行为回归。简单文字或样式修改做适当显示检查，不编写只复述实现的测试。
4. 迭代时跑专项，集成前跑完整公开回归。
5. GUI 修改需实际 Qt 交互和 Windows pythonw 验证。仅成功导入或离屏截图不能证明任务栏身份、模态窗口生命周期正确。
6. API 契约变更后重新生成 SDK/schema，核对模板一致，并更新维护文档。

后台测试使用带截止时间的 QEventLoop，不用阻塞 Qt 的 sleep。既要断言成功结果，也要检查失败时保留的状态。

客户端验收可用项目 Python 执行 `tools/smoke_layout_client.py --out <新目录>`，Windows 也用 pythonw 验证。它创建独立合成 APP/文档，通过生成目录的 python.cmd 和真实 HTTP 测试发现、接入、兄弟区编辑、画线/过孔、网络查询、自有撤销、本地检查、截图、存档与交接，并验证越区编辑及未验收完成会被拒绝。它不使用真实 PDK 或服务器 DRC。输出保留用于排错，已有输出目录拒绝覆盖。

## 排错入口

| 现象 | 应检查的证据与入口 |
|---|---|
| API 拒绝连接 | APP 进程、安装指针、当前文档旁的 agent-connection.json、bootstrap status |
| API 请求超时 | 客户端 pending、原 request_id、HTTP/会话账本；不新建请求重发 |
| 并行任务时 UI 卡死 | GUI 回调归属、锁顺序、范围结果采用和刷新调度 |
| 检查过期 | 几何/范围/工艺指纹、覆盖范围和任务终态 |
| 同步基线不符 | 修改前的原生源/依赖事实和持久事务日志 |
| 原生结果未知 | Adapter 恢复、回执与保存证据；不能清 pending |
| 绘图或接触错误 | 实际 LPP、DBU、材质、过孔定义和公开 PIN 几何 |
| 导入工艺后缺少能力 | 样例证据、金属栈、保护环/MIM 配置和审核结果 |

软件 UI 以中文为主。面向读者的文档按 docs/zh 与 docs/en 一一对应维护；行为变化时同步修改两种语言，普通导航保持当前语言。

## 依赖

Bridge 固定源码版本并可重复应用补丁，升级前阅读[依赖来源](dependencies.md)。requirements 使用固定版本。setup.ps1 校验下载归档和补丁后的源码，不自动拉取上游 main。

Qt 仅安装 PySide6_Essentials，不安装未使用的 Addons。添加模块前检查其许可证。源码发布不包含 Qt 安装包、PDK 或 EDA 程序；二进制打包需要另做依赖、对应源码和许可审核。

## 发布验证

使用没有 .env、.colayout、config/technologies 或旧客户端状态的新 checkout，核对：

- 含空格和非 ASCII 字符的路径可以完成安装；
- APP 和 Bridge 的实际导入路径、哈希与本安装一致；
- 空白 APP 不访问服务器也能启动；
- SSH 信息缺失、多个原生窗口都有明确诊断；
- 客户端建立／更新保留自改文件、身份和 pending，只绑定指定 APP；
- 服务器采集、工艺提案和人端审核仍是明确分离的流程；
- 测试、SDK/schema、图标资源、文档链接及语言导航检查通过；
- 暂存区仅包含预期源码，并执行 tools/audit_release.py。

不提交日志、快照、报告、凭据或私有测试数据。检查暂存区字节，不只检查工作目录。私有仓库仍是外部副本，首次推送前也遵守相同边界。

## 原生集成验证

具备所需 EDA 工具和 PDK 权限时，私下记录工具版本，使用新的样例库/cell 或授权测试副本，验证导入、基础几何、保护环开放/闭合生成、保存/恢复、区域 DRC 和显式同步。保留原设计和未知结果，只公开脱敏总结，不把原生文件或 foundry 规则附在 issue 中。

并发回归使用不同 client_id 接入独立区域，交错执行编辑、查询、检查，并同时移动人端画布。覆盖旧结果拒绝、父层接口变化、取消、窗口关闭/重开和失败回执。

---

**简体中文** | [English](../en/development.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

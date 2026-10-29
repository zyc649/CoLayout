# 安装与初始化

**简体中文** | [English](../en/setup.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

## 人需要准备的内容

执行初始化的 Agent 可按[初始化执行手册](agent-setup.md)查看命令、成功判据和恢复判断。本页说明用户需要准备的条件。

| 项目 | 需要的信息 |
|---|---|
| Windows 电脑 | 可写的源码目录、Git、uv，以及初始化 Agent 执行本地命令的权限 |
| Linux 服务器或虚拟机 | IP／主机名或 SSH 别名、远程用户名、可访问的 SSH 服务、已核实的主机指纹 |
| EDA 环境 | 合法安装的 Virtuoso；服务器检查／导出流程所需的 Calibre、XStream；完整可用的 PDK |
| 工程目录 | 目标 Virtuoso 启动时所在的服务器绝对路径 |
| Layout 样例 | 已保存并在目标 Virtuoso 中打开；放在设计库中，不要直接改只读 PDK 库 |
| 工艺规则 | 对应版本和选项的真实 DRC 主文件、stream map、工具与环境文件路径 |

模型由你选择的 Agent 工具提供，CoLayout 不要求填写模型服务 API 密钥。版图 Agent 的执行工具需要运行在 APP 所在的 Windows 电脑上。

SSH 使用现有密钥或密钥代理；没有免密能力时请先配置或联系管理员。不要在对话中发送密码、私钥。首次连接正常核实服务器指纹，初始化工具不会关闭主机指纹验证。

## 1. 拉取和安装

```powershell
git clone https://github.com/zyc649/CoLayout.git
cd CoLayout
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

两个 CoLayout skill 已随仓库放在 .agents/skills 下。安装脚本建立 .venv，安装固定版本依赖，下载并校验固定提交的 Bridge，应用有说明的 Windows 兼容补丁，再安装其上游 Virtuoso skill。依赖安装阶段不操作服务器上的版图。

缺少 uv 时，按[官方安装说明（英文）](https://docs.astral.sh/uv/getting-started/installation/)安装，初始化 Agent 可在授权范围内协助。Python 3.13 由 uv 选择。

Bridge 下载按 dependencies/bridge-lock.json 校验。离线准备了同一归档时，可以传 setup.ps1 -BridgeArchive；仍需哈希一致，不能为绕过错误随意换成最新分支。

## 2. 打开 APP 并连接服务器

Start-CoLayout.cmd 会打开空白、尚未配置工艺的工作区。

```powershell
.\.venv\Scripts\python.exe -m colayout_lite.bootstrap configure --host layout-server.example.com --user designer --remote-root /workspace/design
.\.venv\Scripts\python.exe -m colayout_lite.bootstrap doctor
.\.venv\Scripts\python.exe -m colayout_lite.bootstrap windows
.\.venv\Scripts\python.exe -m colayout_lite.bootstrap connect --window "<实际返回的CIW编号>"
```

替换示例主机、用户名和工程目录。不知道目录时，先向用户／管理员确认，或用上游 Bridge 工具只读核对，不能用一个宽泛根目录代替。已有 Bridge 环境可通过 configure --existing-env 明确选择，不会覆盖原环境文件。

只有一个 CIW 时可省略 --window；多个窗口必须让用户选择。工具会核对 Bridge 端点对应的 Virtuoso PID、X11 窗口 PID 和工程目录。如果服务器没有提供窗口 PID，会明确报告无法证明绑定关系，需用上游工具进一步人工核实，不会默认为成功，也不会停止其他 Virtuoso 抢占端口。

端口使用 Bridge 的默认分配机制。多实例、跳板机和分离主机等高级连接按上游文档配置独立端口／profile，不能混淆会话。

| 提示 | 处理 |
|---|---|
| SERVER_HOST_REQUIRED / SSH_USER_REQUIRED | 补充服务器地址／用户名 |
| SSH_AUTH_REQUIRED | 在对话外配置免密 SSH 或密钥代理 |
| SSH_HOST_KEY_REVIEW_REQUIRED | 核实指纹，正常完成第一次 SSH 连接 |
| SSH_UNREACHABLE | 检查虚拟机、网络、VPN、防火墙和 SSH 配置 |
| VIRTUOSO_NOT_OPEN | 打开目标工程及样例 |
| VIRTUOSO_SELECTION_REQUIRED | 选择返回列表中的 CIW |
| VIRTUOSO_INSTANCE_MISMATCH | 核对端口和 profile，保留已有会话 |
| VIRTUOSO_IDENTITY_UNAVAILABLE | 人工核对窗口和 PID，不能直接当作已连接 |
| CONNECTED_PROJECT_MISMATCH | 连接正确工程，不重置原生身份记录绕过核对 |

本机安装状态在 .colayout/installation.json。连接、凭据、工作区与运行记录都不进入 Git。

## 3. 准备并配置工艺

小型 Layout 样例应包含：

- 常用 NMOS、PMOS、电阻，以及工艺支持时的原生 MIM 电容；配置样例不强制要求配套原理图。
- 每对相邻金属之间一个独立、默认的 1×1 标准过孔，包括最后一级顶层金属；保留两侧原生金属。
- 每种需要的 P/N 保护环各一段原生 90° 开放 MPP，包含直段、拐角和两个端头。需要双排就提供真实双排样例；没有样例则不启用对应能力。
- 对需要开放绘制的其他层，提供独立矩形。默认仅开放实测金属层与 n-well 材质层。

让初始化 Agent 使用 colayout-pdk。它读取真实材质、单位、网格、过孔、CDF 和保护环，并从真实规则文件填写统一配置。默认线宽取样例过孔外部金属矩形的短边，不取切孔大小或 DRC 最小值。

MIM 必须确认实际覆盖层的 LPP 和上下金属对，并有样例、工艺或提取资料依据。证据不足时保持“未配置”交由人确认，不能写成“不支持”。

默认走线偏好为首层不指定、第二层起横竖交替；这些是人可修改的偏好，不是 foundry 规则。服务器报告过滤也由人审核，保留原结果，不代表全芯片签核。

默认配置验证主要检查私有副本中的原生几何复现、基础往返和规则文件身份，不会自动开展大规模保护环 DRC 扫描。实际设计中的独立环可能需要配套井区和器件上下文。

提案经 process_configuration API 提交。在 APP 的“工艺库 → 待审核”查看各页，确认后点击“审核并启用”。只有人端操作能发布工艺；“已提交”不等于“已启用”。

缺少真实规则文件时保留采集结果，先补资料；不能用其他 PDK、编造阈值或清掉失败记录。导入已有配置包仍需人工审核及本机路径绑定。分享配置时须遵守 PDK 授权，CoLayout 的 MIT 许可不授予工艺数据的传播权。

## 4. 建立独立版图对话

```powershell
.\.venv\Scripts\python.exe tools/create_layout_agent.py
```

默认在源码目录旁建立同级文件夹，例如 CoLayout-layout-agent；也可用 --folder 指定。已有托管客户端用 --update 更新，其他非空目录不会被覆盖。身份、pending 和 outputs 会保留，自定义文件冲突会报告出来。

若返回 restart_required，先结束占用并正常关闭 APP，再启动并发布连接：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\project.ps1 -Action publish
```

确认 APP 返回的存档目录是新文件夹下的 workspaces，再新开一个只授权该文件夹的版图对话，让它阅读 AGENTS.md，并给出操作区 ID 和任务。

目录权限由 Agent 宿主工具执行；生成的说明和客户端不是操作系统沙箱。不要给版图对话源码目录、Bridge 或服务器凭据。

---

**简体中文** | [English](../en/setup.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

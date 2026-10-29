# CoLayout

**简体中文** | [English](README.md) · [文档目录](docs/zh/index.md) · [初始化提示词](#初始化提示词) · [版图 Agent 提示词](#版图-agent-提示词)

CoLayout 是面向人和 Agent 协作的轻量化 Windows 版图工作区，与 Cadence Virtuoso 配合使用。人划分本地操作区，版图 Agent 通过本机 HTTP API 编辑被分配的区域；工作区、权限、撤销、检查和显式同步都由 Windows APP 统一管理。

软件用于辅助版图工作，不代替完整 LVS 或工艺签核。Virtuoso、Calibre 和 PDK 由用户自行合法取得，本仓库不包含这些产品。

## 复制提示词开始使用

第一次部署使用下面的“初始化提示词”；软件准备好后，在专用客户端文件夹中新开对话，使用“版图 Agent 提示词”。

### 初始化提示词

交给负责安装和后续源码维护的 Agent。填写服务器、SSH 用户名和工艺名称即可。

<!-- BEGIN SETUP PROMPT -->
~~~text
请将 https://github.com/zyc649/CoLayout 克隆到本地，按仓库 AGENTS.md 完成初始化：配置环境和项目级技能，启动 APP 并连接 Virtuoso，建立版图 Agent 文件夹，再根据已打开并保存的 Layout 样例推送工艺配置，供我审核。

服务器：<IP>；SSH 用户：<用户名>；已配置免密登录。
工艺名称：<名称>。样例已按文档准备，没有双排保护环。
~~~
<!-- END SETUP PROMPT -->

[提示词说明](docs/zh/setup-prompt.md) · [样例准备清单](docs/zh/setup.md) · [初始化执行手册](docs/zh/agent-setup.md)

### 版图 Agent 提示词

在初始化时建立的客户端文件夹中新开对话，只授予该文件夹权限。填写操作区 ID 和任务，不需要服务器账号。

<!-- BEGIN LAYOUT PROMPT -->
~~~text
请阅读本文件夹的 AGENTS.md，连接 CoLayout 并查询可用 API，按文档在指定操作区完成版图任务。只通过 APP 操作，不访问服务器或修改软件源码。

操作区 ID：<ID>
任务：<具体要求>
~~~
<!-- END LAYOUT PROMPT -->

[版图提示词说明](docs/zh/layout-prompt.md) · [软件使用说明](docs/zh/usage.md)

## 阅读入口

| 你要做什么 | 从这里开始 |
|---|---|
| 安装、连接服务器、配置工艺 | [准备清单](docs/zh/setup.md) → [Agent 执行手册](docs/zh/agent-setup.md) |
| 与 Agent 一起画版图 | [使用说明](docs/zh/usage.md) → [API 说明](docs/zh/api.md) |
| 接手源码、修 bug 或重构 | [接手指南](docs/zh/maintainer-guide.md) → [架构](docs/zh/architecture.md) → [实现详解与测试索引](docs/zh/internals.md) |
| 查找其他文档 | [完整中文目录](docs/zh/index.md) |

## 两个对话，两种职责

- **初始化／软件维护对话：** 拉取并维护源码，安装依赖，选择服务器和 Virtuoso 窗口，采集工艺样例并提交待审核配置。
- **版图对话：** 单独打开一个对话，只授予生成的版图 Agent 文件夹权限。它只使用 APP API，不直接使用 Bridge、SSH 或软件源码。可以为两种工作选择不同的模型。

## 开始使用

新开对话时可使用[初始化提示词模板](docs/zh/setup-prompt.md)，填写自己的目录、服务器和 SSH 用户名。

准备 Windows、Git、[uv（官方英文安装说明）](https://docs.astral.sh/uv/getting-started/installation/)，以及可通过 SSH 访问、已安装合法 EDA 软件的 Linux 服务器。初始化 Agent 可以协助安装和诊断，但需要你提供服务器地址及必要的连接信息。

1. 拉取仓库，让初始化 Agent 阅读 [AGENTS.md（供初始化 Agent 阅读，英文）](AGENTS.md)。
2. 执行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1`。
3. 按[安装说明](docs/zh/setup.md)配置、检查服务器连接并启动 APP。地址缺失、SSH 认证失败或存在多个 Virtuoso 窗口时，应先明确处理。
4. 使用项目级 `colayout-pdk` skill 采集已保存的 Layout 样例。Agent 提交提案，人在 APP 中审核并启用。
5. 使用 `colayout-layout-agent` skill 生成独立工作文件夹，再新开版图对话。

仓库自带两项 CoLayout 技能；安装步骤另行下载固定版本的上游 Virtuoso skill，放入项目级技能目录。

## 工艺样例需要准备什么

代表性的 MOS、电阻、原生 MIM 电容（工艺支持时），以及每对相邻金属之间独立的默认 1×1 标准孔，包括顶层金属。每种需要的 P/N 保护环，要提供含直段、拐角和两个端头的原生 90° 开放 MPP 路径。双排必须提供真实双排样例，否则不启用。额外可绘制工艺层需提供独立图形，并由人审核勾选。

还需要真实 DRC 主规则、stream map、工具和环境文件。缺失时先补齐，不能拿其他 PDK 的规则替代。详见[完整准备清单](docs/zh/setup.md)。

## 软件的基本使用逻辑

- 兄弟区、父子区可分别接入 Agent；同一区域独占编辑。
- 父层只管理直接子区外框和接口，不越层编辑子区内部。
- 可以先用方位 PIN 完成主体，再收紧操作区、转固定 PIN、完成真实引出。
- 普通叶 PCell 参与检查；真正原生层次保持黑盒，只开放公开 PIN 和明确设置的局部布线豁免。
- 高频运行本地检查，在适当阶段运行服务器 DRC。完成验收要求当前全区两项检查均通过；本地检查只是受支持的子集，不是完整 LVS。
- 显式保存／导出用于交换文件，内部恢复备份和原生事务记录独立保留。

## 开发与许可

修改源码时，从[源码接手指南](docs/zh/maintainer-guide.md)、[架构](docs/zh/architecture.md)和[源码实现详解](docs/zh/internals.md)开始，再看[开发说明](docs/zh/development.md)、[API](docs/zh/api.md)与[贡献指南](docs/zh/contributing.md)。初始化 Agent 可直接按[执行手册](docs/zh/agent-setup.md)操作。文档同时面向人和协助开发的 Agent。

CoLayout 原创代码使用 MIT 协议；依赖保留各自的许可证，见 [MIT 许可证原文（英文）](LICENSE) 和[第三方声明](docs/zh/licensing.md)。不分发私人版图、工艺文件、凭据或开发对话。

特别感谢 **[Arcadia-1 及贡献者开发的 Virtuoso Bridge Lite](https://github.com/Arcadia-1/virtuoso-bridge-lite)**。CoLayout 通过它连接 Virtuoso。安装固定到明确的上游提交，保留一个有说明的 Windows 兼容补丁，不随上游更新而自动升级。详见[依赖来源](docs/zh/dependencies.md)。

---

**简体中文** | [English](README.md) · [文档目录](docs/zh/index.md) · [初始化提示词](#初始化提示词) · [版图 Agent 提示词](#版图-agent-提示词)

# Agent 初始化执行手册

**简体中文** | [English](../en/agent-setup.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

用于首次部署，不是已有安装的自动修复流程。[准备清单](setup.md)说明用户需要提供的服务器、合法 EDA、已保存样例和规则文件，不能猜测缺失信息。

## 0. 从初始化提示词进入正确工作区

将仓库克隆到用户指定的新目录，并把实际包含 AGENTS.md、setup.ps1、colayout_lite 的目录作为项目根。仓库仍为私有时需要 GitHub 授权；不要把认证失败当作依赖安装失败，也不要把 token 写进命令、远程 URL 或日志。

当前对话同时承担之后的源码维护。克隆后直接阅读 AGENTS.md、[源码接手指南](maintainer-guide.md)和[源码实现详解](internals.md)，不依赖以前的聊天或交接包。

两个自有 skill 已放在项目级 .agents/skills，setup.ps1 会补装上游 virtuoso skill。check_environment 的 project_skills 应全部为 true。宿主尚未刷新技能发现时，直接读取这三份 SKILL.md 按说明执行即可；不为此复制到全局，也不声称文件存在就等于已设置宿主权限。

## 1. 在指定 checkout 安装

从仓库根目录运行：

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
.\.venv\Scripts\python.exe tools/check_environment.py
~~~

安装命令成功退出且 check_environment 返回 passed 才算完成。两项自有项目级技能已在仓库中；安装器另将带 LICENSE 的固定版本上游 Virtuoso skill 放到 .agents/skills/virtuoso。原生采集前核对三份 SKILL.md 均存在。

缺少 Git/uv 会明确报错，在授权范围按官方方式安装后重试。离线 Bridge 归档通过 -BridgeArchive 指定，必须是锁定的同一文件。已有 .venv、依赖源码和安装状态不能随意丢弃；版本或路径冲突需核实，不删除用户运行数据。

## 2. 配置并核实原生连接

向用户取得主机、SSH 用户名和准确的服务器工程目录，原生操作前阅读已安装的 virtuoso skill。对尚未配置的空白安装执行：

~~~powershell
.\.venv\Scripts\python.exe -X utf8 -m colayout_lite.bootstrap configure --host layout-server.example.com --user designer --remote-root /workspace/design
.\.venv\Scripts\python.exe -X utf8 -m colayout_lite.bootstrap doctor
.\.venv\Scripts\python.exe -X utf8 -m colayout_lite.bootstrap windows
.\.venv\Scripts\python.exe -X utf8 -m colayout_lite.bootstrap connect --window "<实际返回的CIW编号>"
~~~

这些是占位符，不是默认值。已有 .env 保留，明确审核后才替换。复用已知环境时改用 configure --existing-env "<文件>" --remote-root "<工程>"，保留其 VB_HOME/会话，不另建冲突连接。

doctor 应返回 ssh_ready。有多个 CIW 时让用户选择实际返回的窗口，不默认选第一个。connect 必须返回 connected=true，且 PID、工程均符合目标。VIRTUOSO_IDENTITY_UNAVAILABLE 或 INSTANCE_MISMATCH 不是成功。端口/profile 的复杂情况按上游 skill 处理，不杀掉或重置用户的 Virtuoso。SSH 认证在对话外配置，不索要密码或私钥。

### 提示词只给服务器 IP 时

先核对已有 SSH 配置或已知的匹配 Bridge 环境，不从例子猜用户名。可只查看 SSH 解析出的公开连接字段：

~~~powershell
ssh -G layout-server.example.com | Select-String '^(user|hostname|port) '
~~~

解析出的 user 可能只是本机默认名，不能直接认定正确。使用该配置进行一次正常的 BatchMode 身份验证；若失败且用户没有提供远程用户名，就询问用户名，不循环尝试 root 等常见账号。不关闭主机指纹检查。

工程目录可以在所选服务器上只读查找：列出已运行的 Virtuoso 进程（例如 ps -C virtuoso -o pid=,comm=），再对实际观察到的数字 PID 读取 /proc/<PID>/cwd。多进程或不同工程时向用户确认，不自动选第一个。进程工作目录只是候选证据，后续仍须核对 CIW、Bridge 实际 PID 和 inspect 返回的工作目录。

已存在且匹配目标的 Bridge 环境应明确用 --existing-env 复用，沿用其 VB_HOME 和会话。不要为一次验证启动竞争服务或重置原生身份。没有配置或资料时明确补问；这些信息不能由工艺名称推导。

## 3. 启动 APP 并确认就绪

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\project.ps1 -Action start
.\.venv\Scripts\python.exe -X utf8 -m colayout_lite.bootstrap status
~~~

启动器返回 PID 不代表已就绪。允许初始化完成后读取 status。工艺配置前出现空白文档和未配置工艺是正常状态。连接被拒绝时核对此安装进程及 artifacts/lite/diagnostics，不扫描或连接其他 APP 端口。

## 4. 采集并提交工艺

阅读 colayout-pdk/SKILL.md 及 collection/MIM 参考。使用实际已保存样例的库/cell，以及 requirements 给出的连接 ID：

~~~powershell
$python = Join-Path (Get-Location) '.venv/Scripts/python.exe'
$setup = Join-Path (Get-Location) '.agents/skills/colayout-pdk/scripts/setup.py'
& $python -X utf8 $setup requirements
& $python -X utf8 $setup inspect
& $python -X utf8 $setup collect --name "<工艺名称>" --library "<库>" --cell "<cell>" --out ".colayout/pdk-collection-1"
~~~

输出目录必须是新的，必要时加 --connection-id。全局 --api-connection 放在子命令之前。提案不携带真实连接凭据。

查看采集后的 package.json 和证据，按 skill 填入真实规则阈值/依据、服务器路径、MIM 层位、设计偏好和报告策略。collect 不代表完整工艺已配置。缺顶层默认孔、所需开放保护环、实际规则文件或材质依据时，应明确补齐或决定不启用对应能力，不编造数据凑过 check。

~~~powershell
& $python -X utf8 $setup check ".colayout/pdk-collection-1"
& $python -X utf8 $setup request ".colayout/pdk-collection-1"
& $python -X utf8 $setup submit ".colayout/pdk-collection-1/submit-request.json"
& $python -X utf8 $setup status "<返回的proposal-id>"
~~~

check 核对原生复现和文件，不是完整 DRC/LVS。request 固定请求身份和内容；submit 结果未知时重试原文件，不改写。pending_review 表示请用户在 APP 审阅所有页签，只有人批准才启用。needs_attention 要先诊断，confirmed 才是批准完成。MIM 未配置时，启用前须由人确认。不调用内部发布函数，也不通过 GUI 自动化替人批准。

用户需要导出时，先 list 获取已批准的 key，再导出。已有输出文件不会覆盖：

~~~powershell
& $python -X utf8 $setup list
& $python -X utf8 $setup export "<已批准的key>" --out ".colayout/shared-process.json"
~~~

已有共享配置可以走人端导入/审核流程，不强制重采原样例。导入仍需正确绑定本机路径，也不能宣称在新主机完成了原生往返验证。

## 5. 建立仅供版图工作的目录

工艺提案处于 pending_review 时，也可以完成客户端目录建立及只读连接验证。用户要求的是“工艺推送”时，先完成这些剩余授权事项，再一起交付待审核结果；不要因为等待批准而遗漏客户端准备。客户端 ready 与工艺 enabled 分别报告，实际画图仍需工艺启用。

阅读 colayout-layout-agent/SKILL.md，使用默认同级目录或明确的独立目录：

~~~powershell
.\.venv\Scripts\python.exe -X utf8 tools/create_layout_agent.py
~~~

交付要求 connected=true、ready=true、没有未审核的 preserved_custom_files，且 APP 的 archive_folder 对应新目录中的 workspaces。--offline 只准备文件；--update 保留托管目录的身份、pending、输出历史和自改内容。

若返回 restart_required，等待会话/任务空闲、保存并正常关闭 APP，再通过 project.ps1 启动和发布：

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\project.ps1 -Action publish
~~~

进入新客户端目录执行：

~~~powershell
.\python.cmd service.py connect
.\python.cmd api.py --client setup-probe tools
.\python.cmd api.py --client setup-probe workspace status
~~~

以前使用过的 setup-probe 可能仍绑定旧 APP。按技能处理重启和对账，不通过删除 pending 或改身份掩盖未知编辑。验证连接不需要 claim 操作区。

## 6. 交付具体结果

报告所选原生 PID/工程、APP 状态、工艺 proposal/已批准 key 及审核状态、客户端准确目录、连接检查结果。缺少条件时明确指出，不笼统宣布全部完成。

用户另开只授权生成目录的对话，并给出操作区 ID 和任务。该对话不能使用 Bridge、SSH 或源码。原对话保留给源码维护。生成文件夹本身不会替用户配置 Agent 宿主的权限沙箱。

## 重跑与恢复判断

| 返回状态 | 下一步 |
|---|---|
| CONNECTION_EXISTS / INSTALLATION_MOVED | 保留状态，明确核对环境或路径绑定 |
| CONNECTION_SETUP_NOT_EMPTY | 保留设计，换服务器使用独立安装 |
| COLLECTION_DIRECTORY_EXISTS / REQUEST_FILE_EXISTS | 保留旧证据；新采集用新目录，未知提交沿用原请求 |
| PROCESS_DRC_REQUIRED／规则文件缺失 | 取得实际规则，不替用其他 PDK |
| needs_attention | 查看保留的提案/验证错误再处理 |
| ready=false 或 restart_required | 完成指定重启、自改文件核对、连接步骤后再交付 |
| 客户端提示 APP 身份已变化 | 确认旧 APP 退出，核对 pending，再按说明重置该本地客户端 |

---

**简体中文** | [English](../en/agent-setup.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

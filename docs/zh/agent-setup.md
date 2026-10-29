# Agent 初始化执行手册

**简体中文** | [English](../en/agent-setup.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

用于首次部署，不是已有安装的自动修复流程。[准备清单](setup.md)说明用户需要提供的服务器、合法 EDA、已保存样例和规则文件，不能猜测缺失信息。

## 0. 从初始化提示词进入正确工作区

将仓库克隆到用户指定的新目录，并把实际包含 AGENTS.md、setup.ps1、colayout_lite 的目录作为项目根。公开仓库可直接克隆，访问私有 fork 时需要 GitHub 授权；不要把认证失败当作依赖安装失败，也不要把 token 写进命令、远程 URL 或日志。

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

使用用户提供或已核实的主机和 SSH 用户名。工程目录优先采用用户给出的值；未提供时，按下文只读发现运行中 Virtuoso 的候选目录。候选唯一且后续身份/工程核对一致时继续，有歧义再询问，不从工艺名猜路径。原生操作前阅读已安装的 virtuoso skill。对尚未配置的空白安装执行：

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

### 同一服务器有多份 Bridge 配置时

主机和 SSH 用户相同，只能说明它是候选配置。先在本机核对下表，不从多份 .env 中随便选一份后反复 start/connect。

| 核对项 | 需要一致的证据 |
|---|---|
| 主机与用户 | 实际 daemon/GUI 主机、远程用户；分离主机按所选上游 profile 的有效设置核对 |
| 远程端口 | 配置的远端目标端口与现有 daemon 的监听/CIW 日志证据一致 |
| 本地转发 | 本地端口对应的实际隧道目标是该主机、该远端端口；仅有端口在监听不够 |
| 运行身份 | VB_HOME、profile 与该隧道的本机状态记录相符，不混用其他实例的状态目录 |
| 最终目标 | 后续核实的 CIW、Virtuoso PID、工作目录与用户指定目标一致 |

只查看必要连接字段和相关进程信息，不输出整份 .env、token 或状态文件。可按已安装上游技能，用显式 --env（及需要的 profile）查看 status；它能提供现有会话的诊断证据，但不能替代目标核对。

发现端口不一致时，先对照隧道、daemon/CIW 日志和候选配置，定位一致的组合，再执行正常连接验证。证据仍不明确就询问用户。工具输出中的 stop/restart 建议不是切换共享会话的授权；不能为了试配置而停止他人的连接或重置身份。

## 3. 启动 APP 并确认就绪

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\project.ps1 -Action start
.\.venv\Scripts\python.exe -X utf8 -m colayout_lite.bootstrap status
~~~

启动器返回 PID 不代表已就绪。允许初始化完成后读取 status。工艺配置前出现空白文档和未配置工艺是正常状态。连接被拒绝时核对此安装进程及 artifacts/lite/diagnostics，不扫描或连接其他 APP 端口。

### 首次启动的有界等待

只调用一次启动器，再使用上面的现有 status 命令重查。若本安装进程仍在、没有明确启动异常，但当前文档旁的 agent-connection.json 尚未生成，首次查询可能返回 SETUP_FAILED 和文件不存在信息；这不必然是安装失败。

建议每隔约 2 秒查询一次，观察约 30 秒；这是排查建议，不是所有机器的启动时限保证。单次命令自身也有耗时。不要在等待期间再启动第二个 APP。

| 观察结果 | 下一步 |
|---|---|
| API 返回工作区状态 | 核对 document_id、revision 和 archive_folder 是否属于本安装，再继续 |
| 描述文件未生成／连接暂时被拒绝，进程仍在 | 在上述观察窗口内重查，不改配置、不扫描其他端口 |
| 进程已退出、明确异常、认证或描述格式错误 | 立即诊断，不当成启动暂态反复重试 |
| 等待后仍不可达 | 核对 .colayout/installation.json 的文档路径、该进程和 artifacts/lite/diagnostics，再决定下一步 |

可达且返回预期文档状态才是就绪；PID 或端口监听本身不能证明就绪。

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

### 从 collect 到 check：补全哪些字段

以 requirements 返回的当前 schema 和 collect 产生的 package.json 为起点，保留已采集的原生数据，不从空白示例重建整包。

| 类别 | 字段 | 来源与处理 |
|---|---|---|
| 自动采集 | technology 的单位/网格、layers、vias、原生身份；sample_evidence | 来自本次原生样例；保留引用和证据，不手工伪造 |
| 实测默认值 | technology.editor_defaults 的 metal_stack、widths_um、layer、via_definition | 核对全部相邻层单孔测量，默认线宽不等于 DRC 最小线宽 |
| 本地规则 | drc.rules 的 kind、layer、other_layer、value、enabled、source、note | 仅启用能准确表达的真实规则；enclosure 的 other_layer 是包围层，面积阈值单位为 µm² |
| 服务器配置 | drc.remote 的 deck_path、layer_map、calibre、strmout、environment | 实际服务器绝对路径；check 核对可读/可执行及规则/map 哈希，不沿用示例路径 |
| 规则选项证据 | drc.provenance | 记录实际版本、runset、已启用宏/金属选项；记录文字不会替你改写或选择 deck 宏 |
| 可审核偏好 | drc.design_warnings、report_policy、technology.schematic_summary_parameters | 按技能默认和实际 CDF 核对；保留人已明确设置的偏好，不当作 foundry 阈值 |
| MIM 待确认 | drc.mim_capacitor | configured 需真实 LPP、上下金属及 source；未知可用 unconfigured，只有确认不支持才用 unsupported |
| 可选能力 | technology.guard_recipes / guard_templates | 新配置保留实际开放样例生成的配方；无双排样例不启用双排，不编造验证回执 |

check/submit 要求完整绘图默认值、服务器 DRC 配置、至少一条启用且有依据的本地规则，以及一致的技术身份/层引用；缺少这些会被拒绝。MIM 的 unconfigured 可以保留到待审核提案，但启用前必须由人确认。可选保护环不需要为“填满配置”而虚构。

当前 Rule 模型没有可填写的区域例外或电气条件表达式。source 是依据，note 是说明；例如把“排除某类区域”写进备注，并不会让该区域从检查中消失。无法表达条件的规则保持未启用并说明原因，不能删去条件后启用。结构/文件核对或原生几何复现通过，也不证明这些条件已经实现。

#### environment 的实际含义

它是服务器上供 Bash source 的环境初始化文件，设置工具所需的 PATH、许可证等环境；不是一个目录，也不能直接把 csh/tcsh 专用脚本当作 Bash 脚本。当前启动流程使用 bash -lc，先 source 此文件，再进入工程目录启动检查进程；加载输出会被重定向。

只读核对文件的语法、导出变量、所引用脚本及其与 calibre/strmout 路径的对应关系，不输出凭据。当前配置检查只验证环境文件可读，不执行完整环境/许可证自检；source 失败也不一定令启动命令立即失败。实际运行异常需查看保留的 launcher/worker/tool 日志，不能把“路径存在”当作环境已经有效。

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

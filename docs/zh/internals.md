# 源码实现详解

**简体中文** | [English](../en/internals.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

本页在[软件架构](architecture.md)之上列出实际调用链和修改入口。文件链接打开源码，使用符号名定位，不依赖固定行号。

## 1. 启动、所有权与关闭

[tools/project.ps1](../../tools/project.ps1) 读取 .colayout/installation.json，使用 pythonw -m colayout_lite.workspace_app 启动，传入文档、--installation 和 --agent-api。启动器识别同一指针的已有进程，文档锁仍是最终写入保护。

[workspace_app.main / WorkspaceWindow](../../colayout_lite/workspace_app.py) 安装诊断、创建 QApplication 和 StudioWindow、恢复内部文档及未决原生状态，然后启用 AgentHub。[StudioWindow](../../colayout_lite/studio_window.py) 在 WorkspaceWindow 上装配外壳；[ui.Window](../../colayout_lite/ui.py) 是共享画布/控制器基类，不是推荐的独立用户入口。

WorkspaceWindow.lock_path/replace_lock 管理 QLockFile 及安装/文档绑定，save_local 保存共享 Editor。AgentHub 在构造时读取存档/导入目录，所以切换客户端存档根目录需要在空闲时重启。[AgentHub.close](../../colayout_lite/agent_tools/app.py)、窗口关闭处理和任务控制器分别管理定时器、后台任务与订阅。关闭 Dock 不代表取消任务。

## 2. 数据与序列化

| 类型／入口 | 含义 |
|---|---|
| [Shape / Placement / Object](../../colayout_lite/model.py) | 精确几何、位姿、UID、原生事实和编辑能力 |
| Snapshot | 源库/cell/session/counter、依赖、对象、PIN、显示、route 和 group |
| Operation | create/update/delete/transform/guard/delete_guard；已有对象修改需要 before 指纹 |
| Workspace | 基线、操作、local_data、原理图参考、物理目标、revision、state、last_result |
| [LocalData](../../colayout_lite/local_models.py) | 本地操作区、接口、标注、定位/禁布信息和原生布线豁免 |
| [TechnologyProfile](../../colayout_lite/technology.py) | 单位/网格、材质、孔、可绘制 LPP、默认值和保护环样例能力 |
| [ProcessPackage](../../colayout_lite/process_package.py) | 工艺 + DRC + 报告策略 + 样例证据，整体提交审核 |

Record 禁止未知字段和非有限数值，模型层设为 frozen。但嵌套字典/列表并不会自动深度不可变：不要原地修改已发布的嵌套容器。构造替换值并通过 Editor 发布，缓存与后台快照依赖稳定的输入身份。

必须区分本地 Workspace.revision、原生 Snapshot.counter/session、scope_state.fingerprint。原生计数不是本地编辑版本；区域指纹覆盖相关物理/接口输入，不等同于所有兄弟区的任何修改。

[document.py](../../colayout_lite/document.py) 写入 colayout-document-1，内嵌 workspace 和 technology。load_document 检查版本、工艺身份、引用与区域约束，再执行明确的边缘 PIN 迁移。[storage.py](../../colayout_lite/storage.py) 还支持带 baseline_ref 的内部工作区文件，单独复制这种文件可能遗漏基线存储。交换数据使用便携文档／保存 API。

[WorkspaceStorage](../../colayout_lite/workspace_storage.py) 区分内部工作副本与外部存档，记录 document-source.json，并把恢复备份放在内部。打开/恢复不能让受保护备份变成“保存”目标。未知原生结果有单独持久状态；[sync_recovery.py](../../colayout_lite/sync_recovery.py) 在启动时与文档核对。

### 数据格式与兼容入口索引

以下是当前实现的版本与入口，不是迁移新格式的操作指令。优先用 APP 保存/打开、工艺导出/导入和公开客户端，不手改版本号强行加载。

| 类别与版本 | 读写入口 | 兼容边界与交付方式 |
|---|---|---|
| colayout-document-1 | document.document_text / save_document / load_document | 便携工作区包含 workspace + technology；其他外层版本被拒绝。加载还检查身份、引用与区域约束 |
| colayout-lite-workspace-1；colayout-local-data-1 | model.Workspace；local_models.LocalData | 内部模型，不应当作单独完整存档；通过便携文档交换 |
| colayout-lite-storage-1 / baseline_ref | storage.save_workspace / load_baseline；Workspace.baseline_reference | 内部优化格式；带 baseline_ref 时兼容省略 storage_version，但引用必须可解析。单独复制记录可能缺基线 |
| colayout-lite-layout-1…6（模型默认 6） | model.Snapshot；codec.decode 接收 colayout-lite-native-1…6 协议 | 旧标签可解析不代表缺失的新证据已补全；保留在工作区内，不按版本号猜测可编辑能力 |
| colayout-circuit-2/3/4；colayout-layout-connectivity-1 | circuit.models / circuit.codec | 原理图/物理目标缓存；v4 额外核对层次证据。它们不是单独可重绑定的设计文件 |
| colayout-lite-technology-1 | technology.TechnologyProfile | 读取时调用既有 MPP 配方迁移；仍需一致性/能力检查。对外分享统一工艺包，不分享裸本机注册表 |
| colayout-process-package-1；外层 colayout-process-file-1 | process_package.encode / decode；ProcessConfiguration.export | 文件外层含校验和；格式/校验和不符拒绝。导入需本机路径绑定与人审核，不迁入他人运行凭据 |
| colayout-drc-profile-1；colayout-drc-result-1 | drc.models / config / job_storage | 设置属于工艺包，结果属于带版本/范围证据的任务；旧文件缺 MIM 字段按 unconfigured，不假称不支持 |
| colayout-agent-connection-2；colayout-agent-api-2 / colayout-agent-response-2 | agent_tools.http_api / session / client | 当前客户端只接受 v2 连接描述，拒绝 Bridge/v1 描述；用发布器更新本机描述，不手改 token 或版本 |
| colayout-installation-1；colayout-customer-runtime-1 | bootstrap、客户端生成/发布工具 | 安装与客户执行器的本机路径配置，不是可分享的工作区/工艺文件 |

旧内部 PIN 的兼容入口是 edge_pin_migration.normalize：满足条件时先保留原文件备份再归一到边缘；submitting/indeterminate/conflict 状态不做此迁移，无法合法放置时明确失败。入口兼容只解决已有格式读取，不允许绕过 pending 或证据核对。

当前推荐：workspace_app/官方启动器用于人端工作区，process_agent 配合统一 process_configuration API 用于工艺提案。process_dialog.py 等兼容导入和旧辅助入口不应替代这些流程。

## 3. 人端编辑与 API 编辑

人端输入经过 [MouseEdit](../../colayout_lite/mouse_edit.py)、[HumanEdit](../../colayout_lite/human_edit.py)、Actions/区域服务，再到 Editor。属性和快捷键应调用共享领域动作，不直接改图元坐标。

API 调用链：

~~~text
AgentHTTPServer POST /call
  -> QtDispatcher 排队 / 所属线程执行
  -> AgentSession.invoke[_async] / 审计 / 契约校验
  -> RegionLeases.lease + actor
  -> region_edits.edit_region / apply_operation
  -> Actions / RegionActions / layout_helpers.service
  -> Editor.transaction -> Editor.publish
  -> save_local + 审计响应
~~~

[QtDispatcher](../../colayout_lite/agent_tools/http_api.py) 限制排队容量，并在请求间交还事件循环。request_not_started 仅描述当前 HTTP 请求；状态查询超时不证明原编辑任务没有执行。执行后的 OUTCOME_UNKNOWN 必须保留原请求身份。

[AgentSession](../../colayout_lite/agent_tools/session.py) 在分发前查询幂等审计记录。[RegionLeases.actor](../../colayout_lite/agent_tools/leases.py) 仅在旧版本已被该客户端观察、且对应区域指纹仍一致时接受旧 revision。不能改成无条件接受，也不能简单要求全局版本永远相同。

[Editor.transaction](../../colayout_lite/editor.py) 按顺序暂存操作，仅在源未变化时一次发布。publish 验证区域约束、引用和占用，生成一步撤销并通知视图。新原生基线是撤销历史边界。Agent 自有撤销使用历史 token，不另建撤销栈。

## 4. 并行后台任务与结果采用

[batch_edits.py](../../colayout_lite/agent_tools/batch_edits.py) 将符合条件的大批次交给 [batch_worker.py](../../colayout_lite/agent_tools/batch_worker.py)，prepare_local 复用顺序领域校验。[edit_adoption.adopt_edit](../../colayout_lite/agent_tools/edit_adoption.py) 核对取消、租约、当前输入，再调用 workspace_delta.merge 和 Editor.publish。

例如后台正在计算 A 区时，兄弟 B 区已完成编辑。应把 A 的改动合入当前工作区并保留 B，而不是用旧快照覆盖。若 A 的边界/PIN/位姿或相关父输入已改变，必须拒绝旧结果。不能把后台产生的整个旧 Workspace 直接设为当前状态。

[read_pool.py](../../colayout_lite/agent_tools/read_pool.py) 对重型网络/截图查询提供有界只读进程、冻结快照和结果缓存。截图指纹还包括可见上下文和覆盖物。最终校验与审计由所属线程完成，只读后台不发布编辑。

[JobRegistry](../../colayout_lite/agent_tools/jobs.py) 管理 queued/running/completed/failed/cancelled，并在所属线程采用结果。“任务完成”、edit_applied 和“证据当前有效”是不同事实。[native_lane.channel](../../colayout_lite/native_lane.py) 在本安装的锁目录内按 Bridge 环境/工程串行化原生动作，不是所有独立 clone 共用的服务器锁。不要让独立安装并发写同一原生目标。

## 5. 原生同步状态

人端 [SyncController](../../colayout_lite/presentation/synchronization.py) 负责界面准备、备份和任务；[Adapter.commit / reconcile](../../colayout_lite/adapter.py) 负责原生正确性。

| Workspace 状态 | 含义 |
|---|---|
| clean | 没有待写回原生操作，但可能存在本地组织数据 |
| editing | 保留本地待提交操作 |
| submitting | 已持久化请求和提交前工作区，原生结果可能尚未知 |
| indeterminate | 分发、回执或读回未能证明安全终态 |
| conflict | 源或工作流冲突，需明确处理 |

commit 核对可提交状态、引用、源/依赖和待提交几何；准备 TransactionJournal 与备份身份；持久化 submitting；执行原生事务；核验回执和实际保存几何。只有验证成功才采用新基线并清操作。确认回滚仍保留草稿；分发后异常保留 indeterminate 证据。

[TransactionJournal / Receipt](../../colayout_lite/transactions.py) 绑定 request_id、payload hash 和目标。reconcile 比较实际目标与预期结果、原基线；两者都不符合时报 INDETERMINATE_COMMIT。仅有回执不够。没有未决事务的基线差异，不能通过清日志“修复”。

[NativeTransport](../../colayout_lite/transport.py) 在构造时连接，首次使用时加载 NATIVE_SCRIPTS，编码数据而非任意代码。colayout_lite/skill 是 CoLayout 的原生协议实现，上游 Python 依赖单独安装。修改协议时同步处理两端和失败回归，保持 wire version、回执结构与 UID 核对兼容。

## 6. 检查、过滤与工艺审核

[RegionTasks](../../colayout_lite/agent_tools/region_tasks.py) 构造区域输入。[drc/local.run](../../colayout_lite/drc/local.py) 执行支持项，geometry、scope、Poly、MIM 和提醒模块分离。UI 高亮不是这个物理检查器。

[drc/jobs.py](../../colayout_lite/drc/jobs.py) 先持久化输入，再启动 [drc/worker.py](../../colayout_lite/drc/worker.py)。state.json 是进度，terminal.json 是结果写完后的终态证据。进程死掉但没有有效终态/结果不能算通过。[rdb.py](../../colayout_lite/drc/rdb.py) 解析服务器记录；[reporting.py](../../colayout_lite/drc/reporting.py) 与 waivers.py 应用审核策略，不改写原始证据。

[release_status.py](../../colayout_lite/agent_tools/release_status.py) 对最新相关本地、服务器任务检查 current、全区、passed、completion_eligible。相关输入改变后重查，本地 warning 和服务器过滤保持各自语义。

工艺调用链为 process_agent.collect → check/prepare → request/submit → process_configuration 提案 → process_review.approve → process_transaction.publish_files。[process_center.py](../../colayout_lite/process_center.py) 是 UI，process_dialog.py 是兼容导入；process_api.py 没有 approve 接口。原生指纹、配置身份和审核摘要各有用途，不能互相覆盖。新增字段需要通过校验、UI 往返、便携导出/导入。

## 7. 渲染与诊断

[Canvas](../../colayout_lite/presentation/canvas.py)、[layout_scene.py](../../colayout_lite/presentation/layout_scene.py)、owner_graphics.py、view_scope.py、vector_preview.py 分别处理交互、对象可见性和矢量缓存。SnapshotCanvas 不创建主 Editor/窗口即可生成区域截图。按改变的 owner 和相关工艺/范围失效缓存；显示折叠不等于权限或 DRC 黑盒。

[circuit/panel.py](../../colayout_lite/circuit/panel.py)、reference_data.py、reference_table.py 实现本地原理图参考。参考或模态窗口卡顿时核查重复信号连接、所属线程计算、展开/选择事件与延迟刷新。

[diagnostics.install](../../colayout_lite/diagnostics.py) 在 artifacts/lite/diagnostics 写 Python/Qt/fault 日志。[UiWatchdog](../../colayout_lite/ui_watchdog.py) 在 Qt 无响应时写 PID 对应的 ui-stall 线程栈。Agent 运行记录位于当前文档旁 agent-runs；原生日志遵循 connection.state_directory；DRC 任务位于 artifacts/drc/jobs。本机查看，公开前脱敏。

## 8. 修改位置与已有回归对应关系

测试名均位于 tests_lite。它们是起点，不代表已穷尽所有场景。

| 修改领域 | 已有测试／额外验证 |
|---|---|
| 几何、事务、撤销 | [test_kernel.py](../../tests_lite/test_kernel.py)、[test_actions.py](../../tests_lite/test_actions.py)、[test_path_outline07.py](../../tests_lite/test_path_outline07.py)、[test_path_backtracking.py](../../tests_lite/test_path_backtracking.py) |
| 原生提交/恢复/保存 | [test_transactions.py](../../tests_lite/test_transactions.py)、[test_verified_save_barrier.py](../../tests_lite/test_verified_save_barrier.py)、[test_transport_boundary.py](../../tests_lite/test_transport_boundary.py)、[test_native_lane.py](../../tests_lite/test_native_lane.py) |
| 操作区、权限、PIN | [test_regions.py](../../tests_lite/test_regions.py)、[test_work_sessions.py](../../tests_lite/test_work_sessions.py)、[test_human_edit.py](../../tests_lite/test_human_edit.py)、[test_copied_interface_contacts.py](../../tests_lite/test_copied_interface_contacts.py)、[test_edge_pin_migration.py](../../tests_lite/test_edge_pin_migration.py) |
| 材质与物理检查 | [test_conduction_access.py](../../tests_lite/test_conduction_access.py)、[test_agent_connectivity.py](../../tests_lite/test_agent_connectivity.py)、[test_poly_contact_drc.py](../../tests_lite/test_poly_contact_drc.py)、[test_mim_via_check.py](../../tests_lite/test_mim_via_check.py) |
| 内部金属提醒／性能 | [test_internal_metal_contacts.py](../../tests_lite/test_internal_metal_contacts.py)、[test_drc_performance_equivalence.py](../../tests_lite/test_drc_performance_equivalence.py) |
| 保护环和原生豁免 | [test_mpp_sample_choppability.py](../../tests_lite/test_mpp_sample_choppability.py)、[test_guard_ports.py](../../tests_lite/test_guard_ports.py)、[test_native_routing_window_router.py](../../tests_lite/test_native_routing_window_router.py) |
| 过孔组合动作／布线 | [test_auto_vias.py](../../tests_lite/test_auto_vias.py)、[test_via_landing_intent.py](../../tests_lite/test_via_landing_intent.py)、[test_layout_helpers.py](../../tests_lite/test_layout_helpers.py)、[test_routes.py](../../tests_lite/test_routes.py) |
| 服务器任务／报告存储 | [test_drc_jobs.py](../../tests_lite/test_drc_jobs.py)、[test_drc_job_storage.py](../../tests_lite/test_drc_job_storage.py)、[test_drc_hierarchy_scope.py](../../tests_lite/test_drc_hierarchy_scope.py)；解析语法改变时补专项报告 fixture |
| 初始化与客户端 | [test_bootstrap_portability.py](../../tests_lite/test_bootstrap_portability.py)、[test_release_boundary.py](../../tests_lite/test_release_boundary.py)、[test_client_parallel_replay.py](../../tests_lite/test_client_parallel_replay.py)、[test_customer_cli_uid.py](../../tests_lite/test_customer_cli_uid.py) |
| 工艺采集／配置 | [test_process_setup.py](../../tests_lite/test_process_setup.py)、[test_onboarding.py](../../tests_lite/test_onboarding.py)；schema 改变时补审核/导出测试 |
| GUI／渲染 | [test_translation_cache.py](../../tests_lite/test_translation_cache.py)、[test_compact_contrast.py](../../tests_lite/test_compact_contrast.py)、[test_gui_streams.py](../../tests_lite/test_gui_streams.py)；仍需实际 Qt/pythonw 和代表场景 |

新增编辑动作通常涉及共享命令/模型、权限/范围、契约/发现、同步与异步路径、UI 适配及生成的客户端 schema。修 bug 只改必要部分，同时验证两类入口一致。

---

**简体中文** | [English](../en/internals.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

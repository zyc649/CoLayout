# 执行、文件阶段与恢复

从源码根目录执行，使用该 checkout 的 Python，不使用全局 Python。所有采集输出放到未跟踪目录，例如 .colayout 下的新子目录，不把原生几何、规则证据或提交文件放进 Git。

~~~powershell
$python = Join-Path (Get-Location) '.venv/Scripts/python.exe'
$setup = Join-Path (Get-Location) '.agents/skills/colayout-pdk/scripts/setup.py'
& $python -X utf8 $setup --help
& $python -X utf8 $setup requirements
& $python -X utf8 $setup inspect
~~~

requirements 返回实际 schema 和 connections；inspect 返回当前原生窗口中的 Layout。多个连接用 inspect/collect 的 --connection-id 选择。覆盖 APP 描述文件时，全局参数放在命令前：setup.py --api-connection "<描述文件>" requirements。APP token 和 Bridge token 不能混用。

## 阶段和文件

| 命令 | 输入与结果 | 是否代表完成 |
|---|---|---|
| collect --name "<工艺>" --library "<库>" --cell "<cell>" --out "<新目录>" | package.json、collection.json、原生技术/样例、器件 CDF、默认宽度和 MPP 证据、规则候选 | 只完成采集；尚需依据真实资料补齐配置 |
| check "<采集目录>" | 读取 package.json；成功写 checked-package.json、verification.json | 原生几何/文件核对，不是 DRC/LVS 签核 |
| request "<采集目录>" | 用已检查包和回执创建 submit-request.json，固定 client_id/request_id/body | 尚未提交 |
| submit "<采集目录>/submit-request.json" | 提交到 APP，并保留独立响应文件 | pending_review 只是待审核 |
| status "<proposal_id>" | 查询提案状态 | confirmed 才表示人端审核完成；needs_attention 需看错误 |
| list | 获取已配置项和真实 key | 不触发配置 |
| export "<key>" --out "<新文件>" | 导出已配置项；已有文件拒绝覆盖 | 分享前仍需检查敏感工艺参数与本机路径 |

collect 的 --metal-stack 使用实际层名；--via-uids 和 --layer-materials 接受 JSON 文件，格式与依据见 collection.md。--variant 区分同工艺不同选项，--replace-key 仅维护已确认同源的旧配置。用户不需要保护环时可明确 --skip-guards，不能用它掩盖所需样例解析失败。

## 失败后怎么继续

- APP 不可达：检查本安装的 status 和描述文件，先恢复连接，不直接改正式配置文件。
- collect 目录已存在：保留它。需要新采集时选新目录，避免混入两次原生事实。
- 缺规则、顶层默认孔、材料或必要样例：取得真实证据或让用户决定不启用对应能力，不猜数字补齐。
- check 确认失败：按具体错误修有依据的 package 字段，再检查。保留失败报告，不扩大 DRC 豁免。
- request 文件已存在或 submit 超时：不覆盖原文件、不换 ID。原请求结果未知时用完全相同文件重试核对。
- 已确定被拒绝且需要新方案：保留旧提案与提交文件，重新准备/检查新方案和新请求；不要改写已发送请求。
- pending_review：告知用户打开“工艺库 → 待审核”，检查并批准。配置 Agent 不代点批准。
- needs_attention：读取具体错误和验证记录，先区分配置、源变化、路径、未知原生结果；不直接改状态。

交付时列出工艺名/key、样例与所选原生实例、proposal_id、审核状态、默认宽度/金属栈、启用的保护环形状、MIM 状态、未完成项。没有 confirmed 不称“工艺已启用”。用户仅要求推送时，pending_review 已完成提交阶段；继续完成其已授权的客户端目录准备等独立事项，再一起交付待审核结果，不要求用户立刻批准才能继续。实际画图仍需工艺审核启用，不绕过人端确认。

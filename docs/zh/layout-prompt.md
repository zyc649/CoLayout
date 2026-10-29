# 给版图 Agent 的提示词

**简体中文** | [English](../en/layout-prompt.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

在初始化 Agent 建好的专用客户端文件夹中新开对话，只授予该文件夹权限。提示词不用包含服务器地址或 SSH/root 账号。

~~~text
请阅读本文件夹的 AGENTS.md，连接 CoLayout 并查询可用 API，按文档在指定操作区完成版图任务。只通过 APP 操作，不访问服务器或修改软件源码。

操作区 ID：<ID>
任务：<具体要求>
~~~

还没有操作区 ID 时，先让它验证连接、查看工具，等你分配区域后再接入。软件维护与工艺配置留在初始化对话。

生成的客户端自带 PROMPT.md、README.md、AGENTS.md 和 docs/API.md。连接、工具发现、区域接入和查询命令都在其中；每个并行 Agent 使用独立且稳定的 --client 名称。工艺必须已审核启用，工具的实际参数以运行中 APP 的发现结果为准。

常规检查与完成规则由客户端说明承担，无须反复写进提示词。连接失败或会话重启时按恢复说明处理，不能直接连接 Virtuoso 绕过 APP。

---

**简体中文** | [English](../en/layout-prompt.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

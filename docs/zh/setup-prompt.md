# 可复制的初始化提示词

**简体中文** | [English](../en/setup-prompt.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

填写服务器、SSH 用户名和工艺名称即可；免密状态和双排样例情况请按实际修改。样例要求见[准备清单](setup.md)。

~~~text
请将 https://github.com/zyc649/CoLayout 克隆到本地，按仓库 AGENTS.md 完成初始化：配置环境和项目级技能，启动 APP 并连接 Virtuoso，建立版图 Agent 文件夹，再根据已打开并保存的 Layout 样例推送工艺配置，供我审核。

服务器：<IP>；SSH 用户：<用户名>；已配置免密登录。
工艺名称：<名称>。样例已按文档准备，没有双排保护环。
~~~

执行顺序、源码维护职责、两项技能、人工审核和失败恢复均由仓库文档规定，不需要在提示词重复。Agent 按 [AGENTS.md（Agent 指令，英文）](../../AGENTS.md) 和[初始化执行手册](agent-setup.md)完成；缺少无法自行查明的连接信息时再询问。

---

**简体中文** | [English](../en/setup-prompt.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

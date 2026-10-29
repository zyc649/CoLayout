# CoLayout layout workspace / 版图工作文件夹

This client talks only to the running Windows APP. Give a separate layout conversation access to this folder only, and start with AGENTS.md.

本客户端只连接 Windows APP。请为单独的版图对话仅授权本文件夹，先阅读 AGENTS.md。安装、工艺配置、源代码维护和直接服务器操作由初始化／维护对话负责。

[版图 Agent 提示词 / Layout prompt](PROMPT.md)可直接复制；填写操作区 ID 和任务即可。无需提供 SSH 或 root 账号。

```powershell
.\python.cmd service.py connect
.\python.cmd api.py --client layout-1 tools
.\python.cmd api.py --client layout-1 claim "<user-provided-region-id>" --name "Layout agent"
.\python.cmd api.py --client layout-1 inspect layout
.\python.cmd api.py --client layout-1 inspect rules
```

Confirm exact command options with `api.py --help` and `api.py claim --help`; detailed edit fields are in the current tools response and docs/api-schema.json.

Each parallel agent uses a different --client name. Keep runtime/clients, pending requests and outputs when updating or reconnecting. If the APP has restarted, reconcile old unknown requests before resetting the old session; never replay edits automatically.

See docs/API.md for the workflow. Feedback belongs in feedback/ and should include a minimal request, region/revision, error code, expected/actual behavior and sanitized screenshots. Never include token/session_token or private process files in public issues.

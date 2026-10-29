# Security and data boundaries / 安全与数据边界

CoLayout is a trusted local desktop tool. Its HTTP token authenticates local clients; it is not a hardened multi-tenant service. Keep it bound to loopback. Do not expose it through a public proxy or share agent-connection.json.

版图 Agent 应只获得自己的客户端目录权限。维护／工艺配置 Agent 的源码、Bridge、SSH 权限由宿主分别控制；生成的 AGENTS.md 不是操作系统沙箱。

Keep .env, Bridge state, SSH keys, workspaces, reports, process packages and native transaction journals private. Process exports omit credentials and original deck files but can still contain sensitive process parameters and server paths; review them before sharing.

Do not paste secrets in issues. For a vulnerability, use GitHub private vulnerability reporting when enabled. If unavailable, open a minimal issue asking for a private reporting channel without exploit details or sensitive artifacts.

A sync failure or timeout is not authorization to delete journals or force a write. Preserve receipts and reconcile the unknown native result. Validate imported configuration/files from untrusted sources before enabling them.

No public EDA server, hosted model service or foundry library is provided by this repository.

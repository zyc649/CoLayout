# Security and data boundaries

[简体中文](../zh/security.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

CoLayout is a trusted local desktop tool. Its HTTP token authenticates local clients; it is not a hardened multi-tenant service. Keep it bound to loopback. Do not expose it through a public proxy or share agent-connection.json.

Give a layout agent access only to its client folder. The host separately controls source, Bridge and SSH permissions for maintenance/process setup. A generated AGENTS.md is not an operating-system sandbox.

Keep .env, Bridge state, SSH keys, workspaces, reports, process packages and native transaction journals private. Process exports omit credentials and original deck files but can still contain sensitive process parameters and server paths; review them before sharing.

Do not paste secrets in issues. For a vulnerability, use GitHub private vulnerability reporting when enabled. If unavailable, open a minimal issue asking for a private reporting channel without exploit details or sensitive artifacts.

A sync failure or timeout is not authorization to delete journals or force a write. Preserve receipts and reconcile the unknown native result. Validate imported configuration/files from untrusted sources before enabling them.

No public EDA server, hosted model service or foundry library is provided by this repository.

---

[简体中文](../zh/security.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

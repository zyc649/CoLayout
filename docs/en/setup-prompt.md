# Copyable setup prompt

[简体中文](../zh/setup-prompt.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

Fill in the server, SSH user and process name. Adjust authentication and double-row sample availability to match your setup. See the [sample preparation checklist](setup.md).

~~~text
Clone https://github.com/zyc649/CoLayout locally and follow AGENTS.md to initialize it: set up dependencies and project skills, start the APP, connect Virtuoso, create the layout-agent folder, and submit a process proposal from my saved, open Layout sample for my review.

Server: <host>; SSH user: <user>; key-based login is configured.
Process: <name>. The sample follows the documented requirements; no double-row guards are provided.
~~~

The repository defines task order, source-maintenance responsibilities, skills, human review and recovery. Users need not repeat them in the prompt. The agent follows [AGENTS.md (Agent instructions)](../../AGENTS.md) and the [setup runbook](agent-setup.md), asking only for required connection details it cannot establish.

---

[简体中文](../zh/setup-prompt.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

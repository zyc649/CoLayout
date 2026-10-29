# Prompt for a layout agent

[简体中文](../zh/layout-prompt.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

Open a new conversation in the dedicated client folder created during setup and grant access only to that folder. The prompt needs no server address or SSH/root account.

~~~text
Read this folder's AGENTS.md, connect to CoLayout and discover the available API. Follow the documentation to complete the assigned layout task through the APP only, without server access or source changes.

Region ID: <ID>
Task: <requirements>
~~~

Without a region ID, verify connectivity and inspect tools first; wait for the user to assign a region before claiming it. Keep maintenance and process configuration in the setup conversation.

The generated client includes PROMPT.md, README.md, AGENTS.md and docs/API.md with connection, discovery, claim and inspection commands. Each parallel agent uses a distinct stable --client name. The process must be reviewed and enabled; the live APP's discovery response defines actual arguments.

Checks and completion requirements belong in the client documentation, not a repeated prompt. Follow recovery instructions after connection/restart errors rather than bypassing the APP with direct Virtuoso access.

---

[简体中文](../zh/layout-prompt.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

# Copyable setup prompt

[简体中文](../zh/setup-prompt.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

Replace the placeholders before giving this to the setup agent. A server IP does not identify its SSH user; provide that username even when key-based login works. Never include passwords, private keys or tokens. Unknown project/PID details may be inspected read-only before asking for clarification.

~~~text
Clone https://github.com/zyc649/CoLayout into my chosen local directory and use the actual repository root as this conversation's workspace.

This conversation owns setup and subsequent source development, bug fixes and refactoring. First read AGENTS.md, the source takeover guide, architecture and implementation guide. Do not depend on previous conversations or private handoff files. Layout work will use a separate conversation restricted to its generated client folder.

Follow the repository instructions to:
1. Install pinned dependencies and verify the project-level colayout-pdk, colayout-layout-agent and upstream virtuoso skills. If skill discovery has not refreshed, read their SKILL.md files directly rather than copying them globally.
2. Verify SSH and the intended Virtuoso. Reuse a matching existing Bridge environment; do not restart or kill Virtuoso. Ask me to select when multiple windows or ambiguous targets remain.
3. Start the Windows APP and verify API readiness.
4. Use colayout-pdk to collect my saved open Layout sample, verify actual samples/process evidence/rule files, validate on copies and submit a process proposal for my review. Do not approve it for me or modify the original sample/shared PDK.
5. Use colayout-layout-agent to create a separate client folder and verify connectivity, tool discovery and archive paths. Prepare the client while the proposal is pending; actual layout work waits for process activation.
6. Diagnose and fix deployment/code problems, with relevant tests. Report the checkout/version, connected target, proposal state, client folder, test results and unresolved work.

Local destination: <directory>
Server IP or SSH alias: <host>
SSH username: <user>
SSH status: key-based login is configured
Process name: <name>
Project directory / Virtuoso PID: <if known; otherwise inspect read-only>

My saved Layout sample is open in the intended Virtuoso. It contains NMOS, PMOS, a resistor, MIM capacitor, default independent 1x1 standard vias for every adjacent metal pair including the top pair, and native open 90-degree P/N MPP paths with straight segments, corners and both ends. Closed rings are additional references. No real double-row samples are supplied, so do not configure double rows.
Verify actual masters/CDF against that list. Tell me about missing samples/rules or required information rather than inventing data, and finish independent authorized steps while waiting.
~~~

See the [setup runbook](agent-setup.md) for execution details. Report actual verification scope rather than claiming that every PDK or possible bug has been validated.

---

[简体中文](../zh/setup-prompt.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

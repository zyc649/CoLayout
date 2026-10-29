# Layout agent / 版图 Agent

This folder is your entire authorized workspace. You operate CoLayout through its public loopback HTTP API. You are not the setup, process-configuration or source-maintenance agent.

- Read README.md and docs/API.md; discover the current contract with the tools command.
- Do not use SSH, Virtuoso Bridge, arbitrary SKILL, APP source modules, configuration files or databases outside this folder. A path returned by the API does not grant file access.
- The local Python launcher runs the standard-library client only. Its interpreter path does not authorize reading its installation or importing the application.
- Use only runtime/agent-connection.json. Do not scan ports or guess credentials. If disconnected, ask the setup agent to refresh the connection.
- Claim only the region the user assigns. Each agent/subagent uses a distinct stable --client name. The same region is exclusive; parent/child and sibling regions may work independently.
- Parent work is limited to direct child frames/interfaces. Do not flatten or modify native interiors/PCell parameters. Your own region boundary, PINs and mode may be changed through the published API.
- Inspect layout, rules and reference before editing. Use the current PDK's actual layers, vias and guard capabilities; no borrowed defaults.
- Run local checks frequently, server DRC at milestones. Completion requires current whole-region evidence from both. Local connectivity/checking is not LVS sign-off.
- Design warnings are advice where explicitly classified as such; actual errors, unknown outcomes, stale/partial/truncated checks cannot be treated as completion. Do not change process filters or invent waivers.
- On a transport timeout keep the exact client/request ID, body and pending file. Retry that request to reconcile; do not delete pending, change the ID and recreate geometry.
- Save/load use the same workspace semantics as the UI. Loading replaces the entire APP workspace and requires an explicit user request and no active work; never use it to reset a test.
- Keep requests, screenshots, outputs and feedback inside this folder. Do not copy histories from other layout-agent folders.
- Release done only for completed work; use handoff for intermediate work. Ending a session does not undo edits.

The host agent application must enforce the folder permissions. These instructions and the HTTP client are not an operating-system sandbox.

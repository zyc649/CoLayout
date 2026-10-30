# CoLayout setup and development

This is the source/maintenance conversation. Start with README.md (or README.zh-CN.md). The separate layout conversation uses only its generated client folder and public APP API.

## Route the task before acting

- Fresh deployment: follow [Agent setup runbook](docs/en/agent-setup.md), then the two project skills below. Report each readiness/review state, not just successful command execution.
- Existing installation / bug fix: read [Source takeover](docs/en/maintainer-guide.md), [Architecture](docs/en/architecture.md), [Implementation guide](docs/en/internals.md) and [Development](docs/en/development.md). Chinese equivalents are under docs/zh. Inspect the active installation and preserve its work; do not automatically repeat initial server or PDK setup.
- Process configuration: use [.agents/skills/colayout-pdk/SKILL.md](.agents/skills/colayout-pdk/SKILL.md), including its collection and MIM references.
- Create/replace a layout workspace: use [.agents/skills/colayout-layout-agent/SKILL.md](.agents/skills/colayout-layout-agent/SKILL.md). Preserve old client history and wait for idle work.

All required maintenance instructions ship in this repository. Never depend on a private handoff folder or a prior conversation. Resolve any disagreement by inspecting current implementation/tests and the user's explicit requirements, then update the documentation.

## A clone-and-initialize request is also a maintenance handoff

A short clone/initialize request is sufficient. The user supplies the target server/process and unavailable instance-specific information; this repository owns the detailed workflow. Read the linked guides and execute the applicable authorized steps without asking the user to restate them in a longer prompt. Ask only when required facts or choices remain unresolved after available read-only discovery.

Treat the checkout containing this file as the project root and the long-term source-maintenance workspace. After cloning, explicitly read this file and the source takeover/implementation guides before changing code. Do not treat this conversation as the layout-only client.

Project skill registration means keeping the two tracked skills under this checkout's .agents/skills and installing the attributed upstream Virtuoso skill through setup.ps1. Verify their SKILL.md files with tools/check_environment.py. If the host has not refreshed skill discovery, read the files directly and follow them; do not copy skills globally or claim that writing files changed host permissions.

The user's initial prompt may supply only a server IP and process name. First inspect existing SSH configuration or a known matching Bridge environment; do not guess a username or project path. Use SSH's resolved configuration and one ordinary BatchMode authentication check. An unauthenticated default username is not evidence; ask for the remote username if needed. Determine candidate Virtuoso PIDs and working directories read-only on the selected server, then choose the intended window with the user if ambiguous. Preserve existing shared Bridge state. See the setup runbook for the evidence needed before configure/connect.

Complete independent authorized steps even when a process proposal is pending human review: create and verify the layout-client folder as well. If the request is to push a proposal, pending_review completes submission, not activation. Report that distinction; do not require immediate approval just to finish setup, and do not use a pending process for actual design work.

For multiple Bridge environments, host/user equality is only a candidate match: verify ports, actual tunnel destination and VB_HOME/profile before reuse, then PID/project. First-start status can be transient before its descriptor exists; use the runbook's bounded retry, not another APP launch. Tool suggestions to stop/restart a shared session do not provide user authorization.

## First setup, in order

1. Confirm the user's local OS and intended server. The supported desktop is Windows; Virtuoso runs on a reachable Linux server/VM with the user's licensed tools and PDK. Do not infer a host, SSH username, PDK or CIW from an example.
2. The repository already contains project-level colayout-pdk and colayout-layout-agent skills. Install dependencies with setup.ps1. If Git/uv is missing, explain or install the official prerequisites with the user's environment permissions; do not use an arbitrary mirror. Setup pins/verifies Virtuoso Bridge Lite and installs its upstream Virtuoso skill into the project. Do not upgrade it implicitly.
3. Use the project .venv Python. Configure with `python -m colayout_lite.bootstrap configure --host <host> --user <user> --remote-root <project>`, or import verified endpoint settings with `--existing-env` (and `--profile` for a named source profile). Both paths create a project-owned .env, VB_HOME/runtime directories, unique profile/client ID and local tunnel port. Never reuse or copy another installation's local state, credentials or environment file as the live binding. Preserve its server-side Virtuoso session and daemon endpoint.
4. Run bootstrap doctor. Address missing host details, SSH authentication, unverified host keys or network errors through the reported diagnosis. Do not disable host verification or request passwords in chat.
5. Run bootstrap windows/connect. When multiple CIWs exist, present the returned choices and use the user's selection; never guess the first window. connect defaults to reusing the existing daemon without injecting setup into CIW; only a verified first-load case uses connect --bootstrap. Never use --bootstrap to retry authentication failures or unknown outcomes. Verify the connected PID/project/sample. Isolation does not authorize simultaneous writes from different installations to the same layout.
6. Start the APP through tools/project.ps1 -Action start. Use the colayout-pdk skill to collect the user's saved sample and submit a proposal. Human review/approval in the APP remains required. Do not silently activate a process.
7. Use colayout-layout-agent to create the separate layout folder, verify its connection/archive path, and hand it to a new conversation with only that folder's permissions.

If the user supplies a prepared process package, follow the documented import/review flow instead of requiring the original sample again. Missing native samples or rule files need an explicit resolution, not guessed parameters.

## Maintenance invariants

- UI and HTTP share one Workspace/Editor/UID/undo history. Shared physical/permission rules belong in domain services.
- Local operation regions do not create OA child cells. Same-region edits are exclusive; parents manage direct child shells/interfaces only. Ordinary leaf PCells are checked; true native hierarchy is opaque.
- Only explicit synchronization writes the source layout. Preserve source/dependency/geometry/net checks, transaction receipts and unknown-result reconciliation. Never delete pending state or change request IDs to bypass failures.
- Checkpoints and logs are runtime/user data, not repository content. Keep .env, artifacts, .colayout, PDKs, layouts and agent histories out of Git. Use synthetic tests.
- Native work uses the installed upstream Virtuoso skill and verified APIs/documentation. Do not restart or kill a user's Virtuoso to resolve routine setup.
- Use .venv Python 3.13. Changes to transactions, geometry or permissions need behavior tests; UI changes need Qt interaction and pythonw validation. Use QEventLoop for background tests.
- Before release, run the supported regression suite, source/privacy audit and a clean-install check. Do not claim a native/PDK check that was only mocked or performed on synthetic data.
- Keep current human and agent documentation aligned with the live API. Read docs/en/contributing.md, docs/en/security.md and docs/en/licensing.md before changing distribution boundaries.

This guide supports both human maintainers and coding agents. It does not grant a layout-only agent access to the repository or server.

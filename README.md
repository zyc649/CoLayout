# CoLayout

[简体中文](README.zh-CN.md) | **English** · [Documentation](docs/en/index.md) · [Setup prompt](#setup-prompt) · [Layout-agent prompt](#layout-agent-prompt)

CoLayout is a lightweight Windows layout workspace for human–agent collaboration with Cadence Virtuoso. Humans organize a design into local operation regions; layout agents edit their assigned regions through a loopback HTTP API. The Windows application owns the workspace, permissions, undo history, checks and explicit native synchronization.

CoLayout is a complementary layout tool, not a replacement for foundry sign-off or a full LVS extractor. Cadence Virtuoso, Calibre and PDKs are separate licensed products and are not included.

## Copy a prompt to get started

Use the setup prompt for the first deployment. Once the application is ready, open a separate conversation in the generated client folder and use the layout-agent prompt.

### Setup prompt

Give this to the agent responsible for installation and future source maintenance. Fill in your server, SSH username and process name.

<!-- BEGIN SETUP PROMPT -->
~~~text
Clone https://github.com/zyc649/CoLayout locally and follow AGENTS.md to initialize it: set up dependencies and project skills, start the APP, connect Virtuoso, create the layout-agent folder, and submit a process proposal from my saved, open Layout sample for my review.

Server: <host>; SSH user: <user>; key-based login is configured.
Process: <name>. The sample follows the documented requirements; no double-row guards are provided.
~~~
<!-- END SETUP PROMPT -->

[Prompt guidance](docs/en/setup-prompt.md) · [Preparation checklist](docs/en/setup.md) · [Setup runbook](docs/en/agent-setup.md)

### Layout-agent prompt

Open a new conversation with access only to the generated client folder. Supply a region ID and task; no server account is needed.

<!-- BEGIN LAYOUT PROMPT -->
~~~text
Read this folder's AGENTS.md, connect to CoLayout and discover the available API. Follow the documentation to complete the assigned layout task through the APP only, without server access or source changes.

Region ID: <ID>
Task: <requirements>
~~~
<!-- END LAYOUT PROMPT -->

[Layout prompt guidance](docs/en/layout-prompt.md) · [User guide](docs/en/usage.md)

## Reading paths

| What you want to do | Start here |
|---|---|
| Install, connect and configure a process | [Preparation](docs/en/setup.md) → [Agent runbook](docs/en/agent-setup.md) |
| Work on layout with an agent | [User guide](docs/en/usage.md) → [API guide](docs/en/api.md) |
| Take over source, fix bugs or refactor | [Takeover guide](docs/en/maintainer-guide.md) → [Architecture](docs/en/architecture.md) → [Implementation and test map](docs/en/internals.md) |
| Find another document | [Full English index](docs/en/index.md) |

## Two conversations, two roles

- **Setup / development:** clone and maintain this repository, install dependencies, select the server and Virtuoso window, collect a PDK sample and submit a configuration for human review.
- **Layout:** open a separate conversation with access only to its generated layout-agent folder. It uses the APP API, not Virtuoso Bridge, SSH or application source files. Choose a different model for this role if useful.

## Getting started

Use the [setup prompt template](docs/en/setup-prompt.md) for a new conversation, filling in your destination, server and SSH username.

Prepare a Windows machine, Git, [uv](https://docs.astral.sh/uv/getting-started/installation/), an SSH-accessible Linux server with your licensed EDA tools, and a saved Layout sample. Your setup agent can help install prerequisites and diagnose missing host details, SSH authentication or multiple Virtuoso windows.

1. Clone this repository and ask your setup agent to follow [AGENTS.md (Agent instructions)](AGENTS.md).
2. Run `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1`.
3. Configure and check the server connection, then start the APP as described in [Setup](docs/en/setup.md).
4. Use the project skill `colayout-pdk` to collect the sample and submit a proposal. Review and enable it in the APP.
5. Use `colayout-layout-agent` to create a separate client folder and start a new layout conversation there.

The repository contains the two CoLayout skills. Setup installs the pinned upstream Virtuoso skill into the project as a separately attributed dependency.

## Prepare the PDK sample

Include representative MOS devices, a resistor, a native MIM capacitor where supported, and one independent default 1×1 via for every adjacent metal pair, including the top metal. For every required P/N guard type, include a native open 90° MPP path with a corner and both ends. Double-row guards require actual double-row samples. Other drawable process layers need standalone sample shapes and human opt-in.

Provide the actual DRC deck, stream map and tool/environment paths. Do not substitute another PDK's rules. Missing evidence is reported for resolution. See the [complete preparation checklist](docs/en/setup.md).

## Working model

- Independent sibling and parent/child regions may have different agents. Same-region edits are exclusive.
- A parent manages direct child frames and interfaces; it cannot edit child interiors.
- Directional PIN mode supports building the interior first. Tighten the region, switch to fixed PIN mode and complete physical exits when appropriate.
- Ordinary leaf PCells participate in checks; true native hierarchy stays opaque except for public PINs and explicitly configured routing windows.
- Run local checks frequently and server DRC at meaningful milestones. Completion requires current full-region evidence from both. Local checks remain a supported subset, not full LVS.
- Explicit save/export creates portable files. Internal recovery and native transaction evidence remain separate.

## Development and licensing

For source work, start with [Taking over maintenance](docs/en/maintainer-guide.md), [Architecture](docs/en/architecture.md) and [Implementation guide](docs/en/internals.md), then [Development](docs/en/development.md), [API](docs/en/api.md) and [Contributing](docs/en/contributing.md). Deployment agents can follow the [setup runbook](docs/en/agent-setup.md).

Original CoLayout code is MIT-licensed. Dependencies retain their own licenses; see [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](docs/en/licensing.md). No PDKs, private layouts, credentials or development transcripts are distributed.

CoLayout relies on **[Virtuoso Bridge Lite by Arcadia-1 and its contributors](https://github.com/Arcadia-1/virtuoso-bridge-lite)** for communication with Virtuoso. We gratefully acknowledge their work. Installation uses a fixed upstream commit and a small documented Windows compatibility patch; it does not silently follow upstream updates. See [dependency provenance](docs/en/dependencies.md).

---

[简体中文](README.zh-CN.md) | **English** · [Documentation](docs/en/index.md) · [Setup prompt](#setup-prompt) · [Layout-agent prompt](#layout-agent-prompt)

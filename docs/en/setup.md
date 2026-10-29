# Setup and preparation

[Project home](../../README.md) · [Documentation](index.md) · **English** | [简体中文](../zh/setup.md)

## What the user prepares

| Item | Required information |
|---|---|
| Windows workstation | A writable checkout, Git, uv, permission for the setup agent to execute local commands |
| Linux server or VM | Host/IP or SSH alias, remote username, reachable SSH service and verified host fingerprint |
| EDA environment | Licensed Cadence Virtuoso; Calibre and XStream for the server check/export workflow; a working PDK |
| Project | The absolute server directory from which the intended Virtuoso instance was launched |
| Layout sample | Saved and open in that Virtuoso instance; use a design library, not the read-only PDK library |
| Rule files | Actual process/version/options DRC main deck, stream map, executable and environment paths |

The LLM runs in your chosen agent host. CoLayout does not require model-provider API keys. The layout agent's tools execute on the same Windows machine as the APP.

For SSH, configure an existing key/agent or obtain help from your administrator. Do not send passwords or private keys to a conversation. On first connection verify the host fingerprint normally. The setup helper uses BatchMode and never disables host-key verification.

## 1. Clone and install

```powershell
git clone https://github.com/zyc649/CoLayout.git
cd CoLayout
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

The repository already includes the two CoLayout skills under .agents/skills. Setup creates .venv, installs pinned packages, verifies/downloads the pinned Bridge source and applies its documented Windows compatibility patch. Its upstream Virtuoso skill is installed into the project, outside the tracked publication files. Nothing starts on the remote server during dependency installation.

If uv is missing, use its [official installation instructions](https://docs.astral.sh/uv/getting-started/installation/). The setup agent may assist within the permissions you grant. Python 3.13 is selected through uv.

Downloads are verified against dependencies/bridge-lock.json. For an offline dependency archive use `setup.ps1 -BridgeArchive <archive>`; the same hash is required. Do not replace the lock with a newer upstream branch just to bypass a failure.

## 2. Open the APP and bind the server

Start-CoLayout.cmd opens an initially empty, unconfigured local workspace. A process configuration is not invented for you.

```powershell
.\.venv\Scripts\python.exe -m colayout_lite.bootstrap configure --host layout-server.example.com --user designer --remote-root /workspace/design
.\.venv\Scripts\python.exe -m colayout_lite.bootstrap doctor
.\.venv\Scripts\python.exe -m colayout_lite.bootstrap windows
.\.venv\Scripts\python.exe -m colayout_lite.bootstrap connect --window "<returned-CIW-ID>"
```

Replace the example host, user and directory. If the directory is unknown, identify it with the server owner or the upstream Bridge tools; do not guess a broad filesystem root. An existing Bridge environment may be selected explicitly with `configure --existing-env <file> --remote-root <project>`; it is not overwritten.

When exactly one CIW is found, connect may omit --window. With multiple CIWs, choose with the user. The helper checks the endpoint's Virtuoso PID against X11 window metadata and checks the connected project. If X11 does not expose the PID, it reports that it cannot prove the binding; complete the checks manually using the upstream tools before proceeding. It never stops another Virtuoso process to take its port.

Bridge allocates its default ports; explicit port/profile changes and advanced jump/split-host setups follow the upstream documentation. Keep each independent native session's endpoint unambiguous.

| Diagnosis | Next action |
|---|---|
| SERVER_HOST_REQUIRED / SSH_USER_REQUIRED | Supply the missing address or username |
| SSH_AUTH_REQUIRED | Set up passwordless SSH/key-agent access outside the chat |
| SSH_HOST_KEY_REVIEW_REQUIRED | Verify the fingerprint and perform a normal first SSH connection |
| SSH_UNREACHABLE | Check VM/network/VPN/firewall and SSH config |
| VIRTUOSO_NOT_OPEN | Open the intended Virtuoso project and sample |
| VIRTUOSO_SELECTION_REQUIRED | Select one returned CIW |
| VIRTUOSO_INSTANCE_MISMATCH | Check Bridge ports/profiles; preserve all existing sessions |
| VIRTUOSO_IDENTITY_UNAVAILABLE | Manually verify the selected window/PID; do not assume connection success |
| CONNECTED_PROJECT_MISMATCH | Select the correct instance/project; do not reset native identity data |

The local setup metadata is in .colayout/installation.json. Connection settings, workspaces and credentials are untracked runtime data.

## 3. Prepare and configure the process

Save a small Layout containing:

- Representative NMOS and PMOS, a resistor and a native MIM capacitor if supported. A schematic counterpart is not required for the onboarding sample.
- One independent default 1×1 standard via for each adjacent metal pair, including the last/top-metal pair. Keep both native metal enclosures.
- For each required P/N guard type, one native open 90° MPP path with a straight segment, corner and two ends. Supply actual double-row paths if you need double rows. No sample means that capability remains unavailable.
- A standalone rectangle for every extra drawable process layer you want to opt into. Default drawing permissions cover measured metals and the n-well role.

Ask the setup agent to use colayout-pdk. It collects actual native materials, units, grid, vias, CDF data and guard geometry, then fills the unified process package from actual rule files. Wire defaults come from the short dimension of the sample via's metal rectangle, not its cut or a DRC minimum.

MIM configuration requires the actual mask LPP and the lower/upper metal pair, supported by the sample and process/extraction evidence. Missing evidence remains unconfigured for human confirmation. It must not be misreported as unsupported.

The default direction preference leaves the first metal unspecified, then alternates horizontal/vertical from the second. These are editable design preferences, not foundry rules. Report-filter defaults are reviewable, preserve original results and do not represent full-chip sign-off.

The standard qualification checks native geometry reproduction on private copies and rule-file identity; it does not automatically run a large guard DRC campaign. An isolated guard may need surrounding well/device context in a real design.

The agent submits through process_configuration. In the APP, open 工艺库 → 待审核, inspect all sections and use 审核并启用 when satisfied. Only this human UI action publishes a configuration. A submitted proposal is not an enabled PDK.

If actual rule files are missing, stop that qualification and preserve the collected evidence. Never use another process deck, fabricate thresholds or clear failed receipts. Imported process packages still require human review and local path binding.

## 4. Create the separate layout conversation

```powershell
.\.venv\Scripts\python.exe tools/create_layout_agent.py
```

The default folder is a sibling of the checkout, such as CoLayout-layout-agent. Use --folder for an explicit alternative. Existing managed folders need --update; unrelated nonempty folders are not overwritten. The generator retains client identity/pending/output files and reports customized template conflicts.

If restart_required is true, first finish all work, close the APP normally, start it again, and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\project.ps1 -Action publish
```

Verify the live workspace archive folder matches the new client's workspaces folder. Then open a new conversation with only that folder's permissions, read its AGENTS.md, and supply the intended operation-region ID.

Folder restrictions are enforced by your agent host. The generated files are not an OS sandbox. Do not grant the layout conversation this source checkout, Bridge tools or server credentials.

---

[Project home](../../README.md) · [Documentation](index.md) · **English** | [简体中文](../zh/setup.md)

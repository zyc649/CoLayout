# Agent setup runbook

[简体中文](../zh/agent-setup.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

Use this for a fresh deployment, not as an automatic repair for an existing installation. The [preparation checklist](setup.md) explains the user's server, licensed tools, saved sample and rule files. Do not guess missing facts.

## 0. Establish the project and maintenance workspace

Clone into the user's chosen new directory. Treat the directory containing AGENTS.md, setup.ps1 and colayout_lite as the project root. A private repository requires GitHub authorization; distinguish that from dependency installation failure, and never put tokens in commands, remote URLs or logs.

This conversation also owns future source maintenance. After cloning, read AGENTS.md, [Taking over source maintenance](maintainer-guide.md) and the [implementation guide](internals.md), without relying on previous conversations or a private handoff.

Both owned skills are already in project-level .agents/skills; setup.ps1 installs the upstream virtuoso skill. check_environment must report all project_skills as true. If the host has not refreshed discovery, explicitly read those SKILL.md files and execute their instructions. Do not copy them globally or confuse file presence with host permission configuration.

## 1. Install in the selected checkout

Run from its root:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
.\.venv\Scripts\python.exe tools/check_environment.py
~~~

Success means the setup command exits successfully and check_environment reports passed. Both project-owned skills are already tracked. Setup adds the pinned upstream Virtuoso skill with its LICENSE under .agents/skills/virtuoso. Confirm all three SKILL.md files exist before native collection.

Missing Git/uv is reported; install from official instructions within the user's authorization, then retry. For a downloaded offline Bridge archive, use -BridgeArchive with the exact locked archive. Existing .venv, dependency source or installation metadata is not disposable: resolve version/path mismatches without deleting user runtime.

## 2. Configure and prove the native connection

Get host/SSH user and the exact server project directory from the user. Read the installed virtuoso skill before native work. For an unconfigured empty installation:

~~~powershell
.\.venv\Scripts\python.exe -X utf8 -m colayout_lite.bootstrap configure --host layout-server.example.com --user designer --remote-root /workspace/design
.\.venv\Scripts\python.exe -X utf8 -m colayout_lite.bootstrap doctor
.\.venv\Scripts\python.exe -X utf8 -m colayout_lite.bootstrap windows
.\.venv\Scripts\python.exe -X utf8 -m colayout_lite.bootstrap connect --window "<returned-CIW-ID>"
~~~

These are placeholders, not defaults. Existing .env is preserved unless an explicit reviewed replacement is requested. To reuse a known environment, use configure --existing-env "<file>" --remote-root "<project>" instead; preserve its VB_HOME/session rather than creating a competing connection.

doctor must report ssh_ready. With several CIWs, ask which returned window to use; do not bootstrap the first one. connect must report connected=true with the intended PID and project. VIRTUOSO_IDENTITY_UNAVAILABLE or INSTANCE_MISMATCH is not success. Resolve advanced ports/profiles through the upstream skill without killing/resetting the user's Virtuoso. Missing SSH authentication must be fixed outside the chat; do not ask for passwords/private keys.

### When the prompt provides only a server IP

Inspect existing SSH configuration or a known matching Bridge environment first; do not guess a username from examples. Limit SSH configuration output to connection fields:

~~~powershell
ssh -G layout-server.example.com | Select-String '^(user|hostname|port) '
~~~

The resolved user can merely be the local default. Verify it with one ordinary BatchMode authentication attempt. If it fails and no remote username was provided, ask for the username instead of trying common accounts such as root. Preserve host-key verification.

Discover project candidates read-only on the selected server: list running Virtuoso processes (for example ps -C virtuoso -o pid=,comm=), then read /proc/<PID>/cwd for an observed numeric PID. Ask when several processes/projects are plausible. The process cwd is only candidate evidence; still verify the selected CIW, actual Bridge PID and working directory returned by inspect.

Explicitly reuse a matching existing Bridge environment with --existing-env, preserving its VB_HOME/session. Do not create a competing service or reset native identity for a test. Ask for unresolved information rather than deriving it from a process-library name.

## 3. Start the APP and inspect readiness

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\project.ps1 -Action start
.\.venv\Scripts\python.exe -X utf8 -m colayout_lite.bootstrap status
~~~

The launcher returning a PID is not proof of readiness. Allow initialization, then read status. An empty document and unconfigured process are expected before onboarding. If refused, inspect this installation's process and artifacts/lite/diagnostics; do not scan for another APP or attach to an unrelated port.

## 4. Collect and submit the process

Read colayout-pdk/SKILL.md and its collection/MIM references. Use the saved sample's actual library/cell and current connection ID from requirements:

~~~powershell
$python = Join-Path (Get-Location) '.venv/Scripts/python.exe'
$setup = Join-Path (Get-Location) '.agents/skills/colayout-pdk/scripts/setup.py'
& $python -X utf8 $setup requirements
& $python -X utf8 $setup inspect
& $python -X utf8 $setup collect --name "<process-name>" --library "<library>" --cell "<cell>" --out ".colayout/pdk-collection-1"
~~~

The output directory must be new. Use --connection-id when needed. The global --api-connection option comes before the subcommand. Do not send actual credentials to the API proposal.

Review collected package.json and evidence; fill actual rule thresholds/sources, server paths, MIM position, design preferences and report policy according to the skill. collect is not a complete configured PDK. Missing default top-metal via, required open guard sample, actual rule deck or material evidence requires an explicit resolution. Do not invent data to pass check.

~~~powershell
& $python -X utf8 $setup check ".colayout/pdk-collection-1"
& $python -X utf8 $setup request ".colayout/pdk-collection-1"
& $python -X utf8 $setup submit ".colayout/pdk-collection-1/submit-request.json"
& $python -X utf8 $setup status "<returned-proposal-id>"
~~~

check validates native reproduction and files, not full DRC/LVS. request fixes the identity/body; if submit has an unknown outcome, retry that unchanged file. pending_review means ask the user to review all tabs in the APP; only human approval activates it. needs_attention requires diagnosis, confirmed means approval completed. Unconfigured MIM needs human confirmation before activation. Never call an internal publication function or approve through GUI automation on behalf of the user.

Use list to discover the approved key, then export when requested. Export never overwrites an existing file:

~~~powershell
& $python -X utf8 $setup list
& $python -X utf8 $setup export "<approved-key>" --out ".colayout/shared-process.json"
~~~

An existing shared configuration can use the human import/review path instead of recollecting the original sample. Imported packages still need appropriate local path binding and cannot claim a new native round-trip.

## 5. Create the layout-only folder

Create the folder and verify its read-only HTTP connection while a process proposal is pending_review. If the user requested proposal submission, finish these independent authorized tasks before handing over the pending proposal. Report client ready separately from process enabled; actual design work still requires activation.

Read colayout-layout-agent/SKILL.md. Use the default sibling or an explicit separate directory:

~~~powershell
.\.venv\Scripts\python.exe -X utf8 tools/create_layout_agent.py
~~~

Success requires connected=true and ready=true, no unreviewed preserved_custom_files, and the APP's archive_folder matching the folder's workspaces directory. --offline only prepares files; --update preserves managed-folder identity, pending/output history and custom changes.

If restart_required, wait for idle sessions/jobs, save, close normally, restart with project.ps1 and publish:

~~~powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\project.ps1 -Action publish
~~~

In the new client folder:

~~~powershell
.\python.cmd service.py connect
.\python.cmd api.py --client setup-probe tools
.\python.cmd api.py --client setup-probe workspace status
~~~

A previous setup-probe identity may be bound to an earlier APP. Follow the skill's restart/reconciliation instructions; do not delete pending or change identity to hide an unknown edit. Verification does not need a region claim.

## 6. Finish with a concrete handoff

Report the selected native PID/project, APP status, process proposal/approved key and review state, exact client folder, and successful connection check. State any missing requirement instead of declaring everything ready.

The user opens a separate conversation with only the generated folder's permissions and supplies the intended region ID/task. That conversation cannot use Bridge/SSH/source. The original conversation remains available for source maintenance. Creating a folder does not itself configure an agent host's sandbox.

## Re-run and recovery decisions

| Result | Next step |
|---|---|
| CONNECTION_EXISTS / INSTALLATION_MOVED | Preserve state; explicitly review environment/path binding |
| CONNECTION_SETUP_NOT_EMPTY | Preserve the design; use a separate installation for another server |
| COLLECTION_DIRECTORY_EXISTS / REQUEST_FILE_EXISTS | Preserve prior evidence; a new collection needs a new directory, an unknown submit reuses its original request |
| PROCESS_DRC_REQUIRED / missing deck | Obtain the actual rule data; do not substitute another PDK |
| needs_attention | Inspect retained proposal/verification error before resubmitting |
| ready=false or restart_required | Complete the stated restart/custom-file/connection step before handoff |
| Client says APP identity changed | Confirm old APP exited, reconcile pending, then reset that local client with the documented command |

---

[简体中文](../zh/agent-setup.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

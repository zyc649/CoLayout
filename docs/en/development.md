# Development

[简体中文](../zh/development.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

## Environment and entry points

Use Windows and the checkout's own Python 3.13 virtual environment. Run setup.ps1, then:

```powershell
.\.venv\Scripts\python.exe tools/check_environment.py
.\.venv\Scripts\ruff.exe check colayout_lite tools
.\.venv\Scripts\python.exe -m pytest tests_lite -q
.\.venv\Scripts\python.exe -m tools.build_customer_api_kit --check
```

Start-CoLayout.cmd delegates to tools/project.ps1. The installed source is editable; use a separate checkout and runtime for risky experiments. Never point a test installation at a user's writable workspace or active native target.

The public tests use synthetic geometry and mocked/native receipts. They do not require a PDK or connect to a server. They are not evidence that every PDK or proprietary tool version has passed. PDK-specific qualification uses the owner's sample and private copies with explicit authorization.

## Change workflow

1. Identify the shared domain behavior and its UI/API/native callers.
2. Preserve units, object IDs, permissions and transaction semantics.
3. Add a behavioral regression for physical, permission, asynchronous adoption or transaction changes. Simple text/style edits need appropriate visual verification rather than tests that only repeat implementation.
4. Run targeted checks while iterating; run the full public suite before integration.
5. For GUI changes, exercise actual Qt interactions and pythonw on Windows. A successful import or offscreen screenshot alone does not validate taskbar identity or modal lifecycle.
6. Regenerate SDK/schema after contract changes, verify no template drift, and update the maintenance docs.

Background-thread tests use QEventLoop with deadlines, not sleeps that starve Qt. Assert the result and retained state on failure as well as on success.

For the shipped layout client, run `tools/smoke_layout_client.py --out <new-folder>` with the project Python (also pythonw on Windows). It creates a separate synthetic APP/document and uses the generated folder's python.cmd through real HTTP: discovery, claims, sibling edits, wires/vias, net inspection, owned undo, local checks, screenshot, archive and handoff. It verifies rejection of out-of-scope edits and unverified completion. It never uses a real PDK or server DRC. Keep the output for diagnosis; an existing output directory is refused.

## Areas to inspect when debugging

| Symptom | Evidence and entry points |
|---|---|
| API refused | APP process, installation pointer, current document's agent-connection.json, bootstrap status |
| API request timed out | Client pending and same request_id; HTTP/session ledger; do not create a new request |
| UI freezes with parallel jobs | GUI callback ownership, lock order, scoped worker adoption and refresh scheduling |
| Stale check | Geometry/scope/process fingerprints, coverage and terminal task state |
| Sync baseline mismatch | Actual native source/dependency facts and persisted journal before any mutation |
| Native result unknown | Adapter recovery and receipt/save evidence; never clear pending |
| Incorrect drawing/contact | Actual LPP, DBU, materials, via definition and public PIN geometry |
| Missing capability after PDK import | Sample evidence, configured metal stack/guard/MIM data and review result |

The UI is predominantly Chinese. Reader documentation has matching English and Chinese pages. Keep both versions aligned when behavior changes; ordinary navigation stays in the current language.

## Prepare an isolated development installation

1. Run setup.ps1 in a new checkout so it creates its own .venv, .colayout, generated config and artifacts. Do not copy production runtime directories, workspace history or pending files; keep the tracked configuration examples.
2. Run tools/check_environment.py and read this checkout's .colayout/installation.json. Verify app_root, python_executable, document, test_kit and workspace_archive_root. The client is normally a separate sibling folder, not application source.
3. Prefer public pytest or smoke_layout_client.py --out <new-folder> for offline work; smoke_onboarding.py is for an empty installation. Respect their scope and never supply a production document to a smoke test.
4. For native validation, verify the connection through the setup runbook and use explicitly authorized test copies. A matching shared Bridge environment/VB_HOME may be reused, but does not create a cross-installation write lock; never write one native target concurrently from two installations.
5. After startup, use this checkout's bootstrap status to verify document ID, revision and archive_folder, and check the process command line's --installation pointer. Window titles may be similar and are not sufficient to distinguish production/development. Keep each installation's descriptors/logs/archives separate; close the appropriate test window normally and preserve diagnostic evidence.

## Acceptance by change type

Use the [existing targeted test map](internals.md#8-change-location-and-existing-regression-map), not a competing list. Run the full public regression before integrating code changes; additional GUI/native checks depend on impact.

| Change | Validation and evidence |
|---|---|
| Documentation/skill text only | Links, homepage prompt and generated-client consistency, git diff --check; no native test solely for a wording change |
| Local geometry/permissions/merging | Synthetic targeted checks then full regression; verify failure publishes nothing, siblings survive and undo boundaries hold. Add GUI checks if display is affected |
| UI/worker lifecycle | Real Windows Qt interaction and pythonw; offscreen covers only some widget/rendering behavior, not focus, taskbar or window-close behavior |
| API/client | Contract/generated files and real loopback HTTP/client checks; cover restart/reconnect and unknown requests, retaining original request_id, pending and APP audit |
| Native transactions/protocol | Offline fault tests plus authorized-copy round trips/failure recovery; retain input, receipts, save-readback and reconciliation evidence |
| Process/check formats | Validation/serialization checks; use authorized copies when native generation or rule execution changes. Distinguish structure, reproduction, region DRC and sign-off |

Repository CI still runs its configured checks. Public synthetic tests do not establish every PDK, server rule or real GUI scenario; report what was actually tested and what remains outside that evidence.

## Dependencies

Bridge is source-pinned and patched reproducibly. Read [Dependency provenance](dependencies.md) before updating it. Requirements are exact versions. setup.ps1 checks the downloaded archive and patched source; it does not pull main automatically.

Qt is installed as PySide6_Essentials, without unused Addons. Do not add a module without reviewing its license. This source release distributes no Qt wheels, PDKs or EDA executables. Binary packaging requires a separate dependency/source-license review.

## Release verification

Use a fresh checkout with no .env, .colayout, config/technologies or pre-existing client state. Verify:

- setup succeeds with paths containing spaces and non-ASCII characters;
- source and installed Bridge paths/hashes match the checkout;
- an empty APP opens without server access;
- missing SSH information and multiple native windows produce explicit diagnoses;
- client creation is idempotent, preserves customized files/identity/pending, and binds only the intended live APP;
- server/PDK collection remains a separate explicit workflow with human approval;
- tests, SDK schema, icon resources and documentation links pass;
- only intended source files are staged; run tools/audit_release.py.

Do not commit logs, snapshots, reports, credentials or proprietary fixtures. Audit staged bytes, not only the working tree. A private repository is still an external copy, so use the same publication boundary before its first push.

## Native integration qualification

When a contributor has the required tools and a redistributable/private PDK, record tool versions privately, use a new sample library/cell or authorized test copies, and verify import, geometry creation, guard open/closed generation, save/recovery, scoped DRC and explicit sync. Preserve the original design and uncertain outcomes. Publish only a sanitized summary; do not attach native files or foundry rules to issues.

For parallel regressions, claim independent regions with distinct client IDs, interleave edits/reads/checks and move the human camera. Include stale-result rejection, parent-interface changes, cancellation, close/reopen and failed native receipts.

---

[简体中文](../zh/development.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

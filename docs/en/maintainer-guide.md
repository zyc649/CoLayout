# Taking over source maintenance

[简体中文](../zh/maintainer-guide.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

Read this when cloning CoLayout to fix a bug or change behavior. You do not need a private handoff, a previous conversation or an existing user's files. This guide is for human maintainers and coding agents.

## Choose the correct starting point

| Situation | Start here |
|---|---|
| New machine / first deployment | [Agent setup runbook](agent-setup.md), then the two project skills |
| Existing installation, source bug | This page, [architecture](architecture.md), then [implementation guide](internals.md) |
| PDK facts or configuration proposal | Project colayout-pdk skill; do not change geometry rules to hide a bad configuration |
| Drawing an assigned design region | The generated client folder's own instructions; not this source workflow |
| Dependency or packaging change | [Dependency provenance](dependencies.md) and [licensing](licensing.md) |

For maintenance, do not automatically rerun server configuration, PDK collection or client-folder replacement. First identify which installation and process the user actually uses.

## First inspection

From the checkout root:

~~~powershell
git status --short
git log -5 --oneline
.\.venv\Scripts\python.exe tools/check_environment.py
.\.venv\Scripts\python.exe -m colayout_lite.bootstrap status
~~~

Missing .venv on a new checkout means run setup.ps1. A refused status call means the APP is not reachable; it does not prove document corruption. Follow the [setup runbook](agent-setup.md). Keep an existing dirty tree and user configuration intact.

Read .colayout/installation.json locally. It records the actual document, interpreter, source and current client folder. The field test_kit is the current layout-client directory; retain its schema name. Do not infer the active document from a desktop JSON archive or a remembered directory.

Before changing code, record the commit, reproduction, relevant error/request/job ID, active document ID/revision and affected construction level. Save an explicit portable workspace copy when needed. Keep tokens, native layouts and logs out of public reports.

## Reading order

1. [Architecture](architecture.md): ownership, two hierarchies and correctness boundaries.
2. [Implementation guide](internals.md): data models, actual entry points, call chains, persisted state and test map.
3. [Agent API](api.md): request identity, scoped leases and asynchronous semantics.
4. [Development](development.md): test/release workflow.
5. Read the affected implementation and its tests; documents are a navigation aid, not a substitute for the current code.

Use symbol names with search rather than stale line numbers:

~~~powershell
rg -n "class Editor|def publish|def transaction" colayout_lite/editor.py
rg -n "OUTCOME_UNKNOWN|RECONCILE_BEFORE_RETRY" colayout_lite tests_lite
rg -n "create_guard" colayout_lite/agent_tools colayout_lite/layout_helpers
~~~

## Debug without losing the user's work

1. Determine whether the failure is input/configuration, local domain logic, GUI lifecycle, worker/adoption, transport, or native source state.
2. Reproduce offline with synthetic objects or an authorized workspace copy. No SSH is needed for Editor/geometry regressions. Keep native operations explicit.
3. Capture the first failure and retained evidence. A later timeout may only be a symptom of a blocked Qt thread.
4. Locate the shared domain service before adding a UI/API special case.
5. Add a behavior regression proving the observed bug and preserved invariants. Validate both failure and success paths.
6. Run the affected tests, then the public suite and applicable GUI/native qualification.
7. Report what changed, the evidence, and the remaining limits. Restart an idle APP normally to load Python changes; do not kill Virtuoso.

For native unknown outcomes, read Adapter's persisted workspace and reconcile it. Do not reload an older archive over a submitting/indeterminate document, delete pending, change the request ID or relax source checks. For a baseline conflict, establish what changed; it is different from an unknown transaction.

## Verification commands

~~~powershell
.\.venv\Scripts\ruff.exe check colayout_lite tools
.\.venv\Scripts\python.exe -m pytest tests_lite -q
.\.venv\Scripts\python.exe -m tools.build_customer_api_kit --check
.\.venv\Scripts\python.exe tools/check_docs.py
.\.venv\Scripts\python.exe tools/audit_release.py
~~~

See the implementation guide for targeted test groups. After changing a contract, run the generator without --check first, inspect the changes, then check it.

tools/smoke_onboarding.py is only for a fresh empty installation. It deliberately refuses an existing design and forbids native access. It verifies Qt interactions, the HTTP surface and a separate client, not arbitrary design editing. Use pythonw as well as console Python for GUI changes.

## Test coverage and maintenance limits

The public tests are synthetic and exclude proprietary design fixtures. Passing them does not prove every PDK, native rule deck, display driver, large scene, modal-window lifecycle or real parallel workload. If the changed area lacks a specific test, add one; do not claim coverage from a similarly named module.

Production rendering and some orchestration still span substantial modules. Prefer targeted extractions behind existing domain boundaries, not a broad rewrite mixed with a correctness fix. Never convert native hierarchy into an editable flattened graph merely to simplify a local check.

Keep both language editions, API/schema, skills and instructions aligned with code. Readers should be able to find an implementation path, a regression path and a recovery path for a change.

---

[简体中文](../zh/maintainer-guide.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

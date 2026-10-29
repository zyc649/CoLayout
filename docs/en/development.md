# Development

[Project home](../../README.md) · [Documentation](index.md) · **English** | [简体中文](../zh/development.md)

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

[Project home](../../README.md) · [Documentation](index.md) · **English** | [简体中文](../zh/development.md)

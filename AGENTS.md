# CoLayout setup and development

This is the source/maintenance conversation. Read README.md (or README.zh-CN.md), docs/architecture.md and docs/development.md. The separate layout conversation uses only its generated client folder and public APP API.

## First setup, in order

1. Confirm the user's local OS and intended server. The supported desktop is Windows; Virtuoso runs on a reachable Linux server/VM with the user's licensed tools and PDK. Do not infer a host, SSH username, PDK or CIW from an example.
2. The repository already contains project-level colayout-pdk and colayout-layout-agent skills. Install dependencies with setup.ps1. If Git/uv is missing, explain or install the official prerequisites with the user's environment permissions; do not use an arbitrary mirror. Setup pins/verifies Virtuoso Bridge Lite and installs its upstream Virtuoso skill into the project. Do not upgrade it implicitly.
3. Use the project .venv Python. Configure with `python -m colayout_lite.bootstrap configure --host <host> --user <user> --remote-root <project>`, or explicitly reuse an existing Bridge environment with `--existing-env`. Do not copy passwords, private keys or another installation's runtime state.
4. Run bootstrap doctor. Address missing host details, SSH authentication, unverified host keys or network errors through the reported diagnosis. Do not disable host verification or request passwords in chat.
5. Run bootstrap windows/connect. When multiple CIWs exist, present the returned choices and use the user's selection; never guess the first window. Verify the connected native project/sample. Existing native sessions and unknown outcomes must not be reset to make a connection appear successful.
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
- Keep current human and agent documentation aligned with the live API. Read CONTRIBUTING.md, SECURITY.md and THIRD_PARTY_NOTICES.md before changing distribution boundaries.

This guide supports both human maintainers and coding agents. It does not grant a layout-only agent access to the repository or server.

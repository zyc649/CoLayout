# Dependency provenance

[简体中文](../zh/dependencies.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

CoLayout gratefully acknowledges [Virtuoso Bridge Lite](https://github.com/Arcadia-1/virtuoso-bridge-lite), created by Arcadia-1 and its contributors. It provides the native communication foundation. CoLayout's shared workspace, UI, domain checks and Agent API are maintained separately.

## Bridge

- Repository: https://github.com/Arcadia-1/virtuoso-bridge-lite
- Pinned commit: 93be53e17da95913e1b252ceaf6e367050f2dc51 (package 0.8.0)
- Archive URL and SHA-256: [lock file (JSON)](../../dependencies/bridge-lock.json)
- Original MIT attribution: [preserved license](../../LICENSES/virtuoso-bridge-lite-MIT.txt)
- Local modification: [Windows patch (source diff)](../../dependencies/patches/windows-pid-probe.patch), Windows process liveness probing only.

On Windows, os.kill(pid, 0) is not a safe Unix-style existence probe. The patch uses a read-only process query/GetExitCodeProcess path; the POSIX path is unchanged. It changes no wire protocol or Virtuoso operation. The patch contains upstream context and remains covered by the upstream MIT notice.

setup.ps1 downloads the exact archive into ignored .colayout/dependencies, verifies its SHA-256, safely extracts it, applies the patch and checks before/after file hashes. It installs from that source and copies the upstream Virtuoso skill, with attribution, to the ignored project skill directory. The complete dependency source remains locally available. --BridgeArchive supports the identical archive offline.

The Git repository does not vendor the complete dependency or silently update it. A dependency outage produces a diagnosis; never fall back to an unverified main branch or another package with the same name.

Run `.\.venv\Scripts\python.exe tools/check_dependencies.py` after a default installation. It verifies the archive hash, compares the checked-out dependency sources against that archive with only the documented patch allowed, and checks verbatim notices in the repository, installed source and copied skill. If setup used an external archive, pass the same file with --archive. This is a source/provenance check, not a substitute for native integration.

## Updating

In a separate checkout, choose a reviewed upstream commit, compare the used APIs and patch, record the new official archive hash, verify the exact source before/after hashes, reinstall cleanly and run public regressions plus authorized native integration. Update the lock, notices and version pins together. Keep recovery compatibility and never upgrade a live shared Bridge session implicitly.

## Other packages

requirements-locked.txt lists exact runtime and development versions. The source install uses PySide6_Essentials, not unused Addons. [Third-party notices](licensing.md) and the installed-package license inventory document the terms.

This is a source distribution. Binary installers, wheels bundled with third-party libraries, and appliances require their own complete corresponding-source/license/relinking review. Do not infer binary redistribution compliance from the application MIT license.

---

[简体中文](../zh/dependencies.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

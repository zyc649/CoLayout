# Licensing and third-party notices

[简体中文](../zh/licensing.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

CoLayout's original source and artwork are licensed under [MIT](../../LICENSE), copyright zyc649. That license does not relicense its dependencies, EDA software, PDKs or imported user data. Third-party copyright names and dates are intentionally preserved.

## Virtuoso Bridge Lite

We gratefully acknowledge **Arcadia-1 and the Virtuoso Bridge Lite contributors** for the communication infrastructure on which CoLayout depends.

- Upstream: https://github.com/Arcadia-1/virtuoso-bridge-lite
- Authors named in its license: Zhishuai Zhang, Xintian Li, Nan Sun, Lu Jie.
- Terms: [upstream MIT license, verbatim](../../LICENSES/virtuoso-bridge-lite-MIT.txt).
- Exact version, archive hash and local Windows patch: [dependency provenance](dependencies.md).

The full Bridge source is downloaded at installation rather than vendored in this Git repository. The small compatibility patch includes upstream context, so the upstream notice is included here as well. No affiliation or endorsement by upstream is claimed.

## Qt for Python and Qt

The source installer uses PySide6_Essentials and shiboken6. CoLayout uses QtCore, QtGui, QtWidgets and QtSvg (QtTest for tests). These components have an LGPL open-source licensing option; Qt also offers other license options. CoLayout does not use unused PySide6_Addons modules.

See [Qt for Python licenses](https://doc.qt.io/qtforpython-6/licenses.html), [Qt SVG licensing](https://doc.qt.io/qt-6/qtsvg-index.html#licenses-and-attributions) and [Qt's LGPL obligations](https://www.qt.io/development/open-source-lgpl-obligations). Copies of [LGPLv3](../../LICENSES/LGPL-3.0.txt) and its referenced [GPLv3](../../LICENSES/GPL-3.0.txt) are included. Installed wheel notices are retained in LICENSES/dependencies.

This repository distributes application source, not Qt binaries. The installer obtains unmodified dependency packages separately. Users can inspect and replace their Python environment/libraries. A future binary distributor must provide the applicable notices, complete corresponding library source or a compliant source offer, and the installation/replacement rights required by the chosen licenses. An application MIT license alone does not satisfy those obligations. Reassess licensing if adding other Qt modules.

Upstream source repositories: [PySide/Shiboken](https://code.qt.io/pyside/pyside-setup.git/) and [Qt](https://code.qt.io/qt/). Select the exact installed version when obtaining source.

## Other installed libraries

[dependencies/licenses.json](../../dependencies/licenses.json) records the exact package versions, metadata and verbatim notice paths captured from the locked environment. [tools/license_inventory.py](../../tools/license_inventory.py) regenerates it. Null metadata means the package omitted that field; read its actual notice rather than assuming it has no license.

Key dependencies include:

| Package | Upstream terms (consult complete notices) |
|---|---|
| Shapely | BSD 3-Clause; bundled GEOS has LGPL 2.1 terms |
| NumPy | BSD and additional component notices |
| Pydantic / pydantic-core | MIT |
| Paramiko | LGPL 2.1 |
| cryptography | Apache 2.0 or BSD 3-Clause |
| PyNaCl / cffi / bcrypt | Their included Apache/BSD/MIT and bundled-component notices |
| python-dotenv | BSD 3-Clause |
| PyYAML, Beautiful Soup, markdownify | MIT |
| pytest, Ruff and other development dependencies | Their included notices |

Setuptools is a build-system dependency installed in an isolated build environment; its [MIT license](https://github.com/pypa/setuptools/blob/main/LICENSE) remains applicable. Python, uv, Git and system SSH are external tooling with their own licenses. The repository does not redistribute those executables.

## Commercial EDA and process data

Cadence Virtuoso, OpenAccess-related vendor products, Calibre, foundry PDKs and process decks are separate user-provided dependencies. This repository includes none of their proprietary libraries, rule files or example layouts. Product names are used to describe compatibility; no vendor affiliation or endorsement is implied.

---

[简体中文](../zh/licensing.md) | **English** · [Project home](../../README.md) · [Documentation](index.md)

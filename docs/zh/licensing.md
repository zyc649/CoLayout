# 许可与第三方声明

**简体中文** | [English](../en/licensing.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

CoLayout 原创源码和图标按 [MIT 协议原文（英文）](../../LICENSE)发布，署名 zyc649。该协议不改变依赖、EDA 软件、PDK 或用户导入数据的许可。第三方的原作者姓名与年份按原文保留。

## Virtuoso Bridge Lite

特别感谢 **Arcadia-1 和 Virtuoso Bridge Lite 的贡献者**，CoLayout 依赖他们提供的通信基础。

- 上游：[Virtuoso Bridge Lite](https://github.com/Arcadia-1/virtuoso-bridge-lite)。
- 原许可证署名：Zhishuai Zhang、Xintian Li、Nan Sun、Lu Jie。
- 条款：[上游 MIT 许可证原文（英文）](../../LICENSES/virtuoso-bridge-lite-MIT.txt)。
- 固定版本、归档哈希和 Windows 补丁：[依赖来源](dependencies.md)。

完整 Bridge 源码在安装时下载，不内置进本 Git 仓库。兼容补丁包含上游上下文，因此本仓库也保留原声明。不宣称获得上游背书或与其存在隶属关系。

## Qt for Python 与 Qt

安装使用 PySide6_Essentials 和 shiboken6。CoLayout 使用 QtCore、QtGui、QtWidgets、QtSvg，测试使用 QtTest。这些组件提供 LGPL 开源许可选项，Qt 也提供其他许可选项。项目不使用未引入的 PySide6_Addons 模块。

可查阅 [Qt for Python 许可说明（官方英文）](https://doc.qt.io/qtforpython-6/licenses.html)、[Qt SVG 许可说明（官方英文）](https://doc.qt.io/qt-6/qtsvg-index.html#licenses-and-attributions)及 [Qt 的 LGPL 义务说明（官方英文）](https://www.qt.io/development/open-source-lgpl-obligations)。仓库保留 [LGPLv3 原文（英文）](../../LICENSES/LGPL-3.0.txt)和其引用的 [GPLv3 原文（英文）](../../LICENSES/GPL-3.0.txt)，已安装 wheel 的声明位于 LICENSES/dependencies。

当前仓库分发应用源码，不分发 Qt 二进制。安装器单独取得未修改的依赖包，用户可查看和替换 Python 环境与库。后续若分发二进制，需按所选许可提供适用声明、完整对应库源码或合规源码提供方式，并满足安装和替换权利要求。应用本体的 MIT 协议不能替代这些义务。新增 Qt 模块时需要重新审查。

上游源码：[PySide/Shiboken](https://code.qt.io/pyside/pyside-setup.git/) 与 [Qt](https://code.qt.io/qt/)。取得源码时选择实际安装的对应版本。

## 其他依赖

[依赖许可清单（JSON）](../../dependencies/licenses.json)记录固定环境中的包版本、元数据和许可证原文位置，可用 [license_inventory.py（生成脚本）](../../tools/license_inventory.py)重新生成。元数据中的 null 表示该包未填写对应字段，不表示没有许可证，应阅读实际声明。

| 包 | 上游条款摘要，完整内容以原声明为准 |
|---|---|
| Shapely | BSD 3-Clause；所附 GEOS 有 LGPL 2.1 条款 |
| NumPy | BSD 及其组件附加声明 |
| Pydantic / pydantic-core | MIT |
| Paramiko | LGPL 2.1 |
| cryptography | Apache 2.0 或 BSD 3-Clause |
| PyNaCl / cffi / bcrypt | 所附 Apache/BSD/MIT 及组件声明 |
| python-dotenv | BSD 3-Clause |
| PyYAML、Beautiful Soup、markdownify | MIT |
| pytest、Ruff 及其他开发依赖 | 各自附带的声明 |

Setuptools 在独立构建环境中使用，其 [MIT 许可证原文（英文）](https://github.com/pypa/setuptools/blob/main/LICENSE)仍适用。Python、uv、Git 和系统 SSH 是各有许可证的外部工具，本仓库不分发这些可执行文件。

## 商业 EDA 与工艺资料

Cadence Virtuoso、OpenAccess 相关厂商产品、Calibre、foundry PDK 和规则文件都是用户自行提供的依赖。仓库不包含它们的专有库、规则或样例版图。产品名称仅用于描述兼容关系，不表示厂商背书或隶属关系。

本页是中文说明；各许可证的法律条款以所链接的原文为准。

---

**简体中文** | [English](../en/licensing.md) · [项目首页](../../README.zh-CN.md) · [文档目录](index.md)

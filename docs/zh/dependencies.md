# 依赖来源与版本管理

[项目首页](../../README.zh-CN.md) · [文档目录](index.md) · **简体中文** | [English](../en/dependencies.md)

感谢 **[Arcadia-1 及贡献者开发的 Virtuoso Bridge Lite（上游项目）](https://github.com/Arcadia-1/virtuoso-bridge-lite)**，它提供了连接原生工具的基础。CoLayout 的共享工作区、UI、领域检查和 Agent API 分别维护。

## Bridge

- 上游仓库：[Virtuoso Bridge Lite](https://github.com/Arcadia-1/virtuoso-bridge-lite)。
- 固定提交：93be53e17da95913e1b252ceaf6e367050f2dc51，包版本 0.8.0。
- 归档 URL 和 SHA-256：[锁定文件（JSON）](../../dependencies/bridge-lock.json)。
- 原作者声明：[保留的 MIT 许可证原文（英文）](../../LICENSES/virtuoso-bridge-lite-MIT.txt)。
- 本地修改：[Windows PID 兼容补丁（代码差异）](../../dependencies/patches/windows-pid-probe.patch)，只处理进程存活探测。

Windows 的 os.kill(pid, 0) 不能安全地当作 Unix 式存在性探测。补丁改用只读进程查询和 GetExitCodeProcess；POSIX 分支不变，也不改变通信协议或 Virtuoso 操作。补丁包含上游上下文，因此保留上游 MIT 声明。

setup.ps1 将固定归档下载到被 Git 忽略的 .colayout/dependencies，核对 SHA-256，安全解压，应用补丁并检查修改前后文件哈希。随后从该源码安装，并将带来源声明的上游 Virtuoso skill 复制到项目级忽略目录。完整依赖源码保留在本地；--BridgeArchive 支持离线使用同一个归档。

Git 仓库不内置完整 Bridge，也不默默更新它。上游下载失败时给出诊断，不能回退到未校验的 main 分支或另一个同名包。

## 升级方法

在独立 checkout 中选择已审阅的上游提交，比较所用 API 和补丁，记录官方归档新哈希，核验修改前后源码，重新干净安装并运行公开回归及已授权的原生集成验证。锁定文件、声明和版本号一起更新。保持恢复兼容，不隐式升级正在使用的共享 Bridge 会话。

## 其他包

requirements-locked.txt 列出运行和开发依赖的固定版本。源码安装使用 PySide6_Essentials，不引入未用的 Addons。许可条款见[许可与第三方声明](licensing.md)及[依赖清单（JSON）](../../dependencies/licenses.json)。

本项目当前发布源码。若制作二进制安装包、捆绑第三方库的 wheel 或设备，需要另行检查完整对应源码、许可和重新链接要求，不能仅凭应用本体采用 MIT 就推定整包满足分发条件。

---

[项目首页](../../README.zh-CN.md) · [文档目录](index.md) · **简体中文** | [English](../en/dependencies.md)

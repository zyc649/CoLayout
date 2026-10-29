# 开发入门

[English / 详细流程](../development.md) · [架构](architecture.md)

使用仓库自己的 Python 3.13 虚拟环境。先执行 setup.ps1，再运行：

```powershell
.\.venv\Scripts\python.exe tools/check_environment.py
.\.venv\Scripts\ruff.exe check colayout_lite tools
.\.venv\Scripts\python.exe -m pytest tests_lite -q
.\.venv\Scripts\python.exe -m tools.build_customer_api_kit --check
```

共享行为先改领域服务，再做 UI/API 适配。物理、权限、并发结果采用和事务修改必须有行为回归；GUI 修改需实际 Qt 交互和 pythonw 验证。

公开测试使用合成数据，不连接服务器，也不代表所有工艺均已验证。原生集成测试使用独立副本，保留原设计和未知结果回执。不要把真实工艺规则、版图、日志、凭据或客户任务历史放进提交。

接口修改后同步生成客户端 schema；依赖升级先核对固定版本和许可证。发布前从全新目录重装并运行完整公开回归。详细模块、排错入口和发布流程见英文维护文档。

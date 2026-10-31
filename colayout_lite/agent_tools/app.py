"""Install the region API into the normal Windows APP, not a demo Editor."""

from pathlib import Path
from uuid import uuid4
from PySide6.QtCore import QObject, QTimer, Qt,Signal,Slot
from PySide6.QtWidgets import QDockWidget
from .session import AgentSession
from .http_api import QtDispatcher, AgentHTTPServer
from .capture import capture
from ..drc import config


class AgentHub(QObject):
    process_configuration_changed=Signal()
    def __init__(self, window, *, folder=None, connection_file=None):
        super().__init__(window)
        self.window = window
        self.closed = False
        self.panel = None
        parent = (
            Path(getattr(window, 'project_path', Path('workspace.colayout.json'))).resolve().parent
        )
        self.folder = Path(folder) if folder else parent / 'agent-runs' / uuid4().hex
        self.connection_file = (
            Path(connection_file) if connection_file else parent / 'agent-connection.json'
        )
        import json
        from ..workspace_files import WorkspaceFiles
        installation=getattr(window,'installation_path',None)
        settings=json.loads(installation.read_text(encoding='utf8')) if installation else {}
        from ..process_configuration import ProcessConfiguration
        self.process_configuration=ProcessConfiguration(window.process_store,
            connection=lambda:window.connection_config,changed=self.process_configuration_changed.emit)
        self.process_configuration_changed.connect(self.refresh_process_notification,Qt.ConnectionType.QueuedConnection)
        self.workspace_files=WorkspaceFiles(lambda:window.editor,
            lambda:getattr(window,'project_path',parent/'workspace.colayout.json'),
            getattr(window,'open_prepared_document',window.open_document),
            settings.get('workspace_archive_root',str(parent/'saved-workspaces')),
            import_roots=[parent,*settings.get('workspace_import_roots',[])],
            busy=getattr(window,'document_busy',lambda:window.busy),
            save_busy=lambda:window.busy,
            path_warning=lambda:getattr(window,'document_path_warning',None),
            storage=getattr(window,'storage',None),
            import_files=lambda:(getattr(window,'document_path',None),))
        self.runtime = AgentSession(
            lambda: window.editor,
            lambda: config.load(window.editor.profile) if window.editor else None,
            self.folder,
            save=window.save_local,
            capture=capture,
            busy=lambda: window.busy,
            remote_enabled=lambda: getattr(window, 'remote_enabled', True),
            workspace_files=self.workspace_files,
            process_configuration=self.process_configuration,
            autoroute_enabled=lambda:self.process_configuration.agent_autoroute_enabled(
                window.editor.profile if window.editor else None),
        )
        self.dispatcher = QtDispatcher(self.runtime.invoke, self, audit=self.runtime.audit.emit,invoke_async=self.runtime.invoke_async)
        self.server = AgentHTTPServer(self.dispatcher, self.connection_file)
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.poll)
        self.timer.start()
        self.refresh_process_notification()

    @Slot()
    def refresh_process_notification(self):
        pending=self.process_configuration.store.drafts()
        count=sum(data.get('schema_version')=='colayout-process-proposal-3' for _,data in pending)
        title='工艺库设置'+(f' · {count} 待审核' if count else '')
        shell=getattr(self.window,'studio',None)
        if shell and 'process' in shell.commands.actions:shell.commands.actions['process'].setText(title)
        if count and not self.window.busy:self.window.status.setText(f'收到 {count} 项工艺配置提案，请打开“工艺库设置”审核。')
        elif getattr(self.process_configuration.store,'scan_errors',[]) and not self.window.busy:
            self.window.status.setText('有工艺提案无法读取，原文件保留；请在工艺库查看详情。')

    def document_changed(self, path):
        self.connection_file=Path(path).parent/'agent-connection.json'
        self.server.publish_connection(self.connection_file)

    def poll(self):
        self.runtime.poll()
        if self.panel and self.panel.isVisible():
            self.panel.refresh()

    def show(self):
        if self.panel is None:
            from .panel import AgentPanel
            from ..panel_chrome import style_dock

            self.panel = AgentPanel(self)
            self.dock = QDockWidget('Agent 活动', self.window)
            self.dock.setObjectName('agentApiDock')
            self.dock.visibilityChanged.connect(lambda _:self.window.view_state_changed.emit())
            self.dock.setWidget(self.panel)
            self.window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            style_dock(self.window, self.dock)
            self.window.resizeDocks([self.dock], [560], Qt.Orientation.Horizontal)
        from ..tool_panels import show_tool

        show_tool(self.window, self.dock)
        self.panel.refresh()
        return self.panel

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.timer.stop()
        if self.panel is not None:
            self.panel.dispose()
        self.server.close()
        self.runtime.close()


def enable(window, **options):
    hub = getattr(window, 'agent_hub', None)
    if hub is None:
        window.agent_hub = hub = AgentHub(window, **options)
    return hub


def show(window):
    return enable(window).show()


def toggle(window):
    hub=enable(window)
    if getattr(hub,'dock',None) and not hub.dock.isHidden():hub.dock.close()
    else:hub.show()


def main():
    # The previous Agent demo is retired; use the normal shared workspace entry.
    import sys
    from ..workspace_app import main as workspace_main

    if '--agent-api' not in sys.argv:
        sys.argv.append('--agent-api')
    workspace_main()


if __name__ == '__main__':
    main()

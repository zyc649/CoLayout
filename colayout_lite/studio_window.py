"""Production entry: canvas-first presentation over one WorkspaceWindow."""
from .workspace_app import WorkspaceWindow
from .studio_shell import StudioShell


class StudioWindow(WorkspaceWindow):
    def __init__(self,path,*,shortcut_path=None,mode=None,installation_path=None,storage=None):
        super().__init__(path,shortcut_path=shortcut_path,installation_path=installation_path,storage=storage)
        self.studio=StudioShell(self,mode=mode)
        self.resize(1580,980)

    def createPopupMenu(self):
        # Panels are opened through the explicit toolbar / View menu.
        return None

    def closeEvent(self,event):
        super().closeEvent(event)
        if event.isAccepted() and hasattr(self,'studio'):self.studio.close()

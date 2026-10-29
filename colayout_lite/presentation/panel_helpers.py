"""Small shared side-panel presentation helpers; no edit state."""

from PySide6.QtWidgets import QPushButton


def _scope_name(workspace, ident):
    region = workspace.local_data.regions.get(ident)
    return region.name if region else '顶层'


def _session_key(editor):
    sessions = getattr(editor, 'work_sessions', None)
    if sessions is None:
        return ()
    return tuple(
        (ident, session.id, session.owner)
        for ident in editor.w.local_data.regions
        if (session := sessions.for_region(ident)) is not None
    )


def _locked(editor, ident=None, *, action='edit'):
    sessions = getattr(editor, 'work_sessions', None)
    return sessions.readonly_reason(ident, action=action) if sessions else None


def _button(text, name, handler):
    widget = QPushButton(text)
    widget.setObjectName(name)
    widget.clicked.connect(handler)
    return widget

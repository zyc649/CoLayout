"""Mutually exclusive canvas creation gestures; no model or communication code."""


def cancel_drawing(window,except_tool=None):
    for name in ('region_panel','guard_panel','rectangle_panel','native_routing_window_panel'):
        tool=getattr(window,name,None)
        if tool is not None and tool is not except_tool:
            callback=getattr(tool,'cancel_draw',None) or tool.cancel
            callback()
    if getattr(window,'drc',None):window.drc.pick.setChecked(False)
    if getattr(window,'human',None):window.human.escape()
    if getattr(window,'selection_ui',None):window.selection_ui.cancel()

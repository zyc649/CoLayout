"""Read-only GUI adapters that bind existing DRC jobs to a local region ID."""
from .model import LiteError


def target_region(window):
    e=window.editor
    if not e:return None
    ids=window.human.ids() if hasattr(window,'human') else []
    if ids:return ids[0] if len(ids)==1 and ids[0] in e.w.local_data.regions else None
    return e.scope_id if e.scope_id in e.w.local_data.regions else None


def check_region(window,engine=None,region_id=None):
    if window.busy:return
    region_id=region_id or target_region(window)
    if not window.editor or region_id not in window.editor.w.local_data.regions:
        raise LiteError('DRC_REGION_REQUIRED','请选中或进入一个本地操作区；此入口不按原生模块或普通图形取范围。')
    if engine=='calibre' and not getattr(window,'remote_enabled',True):raise LiteError('OFFLINE_TRIAL','离线试用窗口不能执行服务器检查。')
    from .tool_panels import show_tool
    window.drc.bind_region(region_id);show_tool(window,window.drc_dock)
    if engine:window.drc.start(engine)

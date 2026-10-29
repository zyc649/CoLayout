"""Human recovery helpers: preserve evidence and never resend uncertain writes."""
from pathlib import Path
from .model import Workspace,LiteError
from .paths import ROOT
from .transport import load_connection


def persisted_pending(workspace):
    config_path=workspace.connection_config
    if not config_path or not Path(config_path).is_file():return None
    # Reading durable local evidence must work before SSH/Bridge is configured.
    # NativeTransport still requires its environment before every connection.
    _,config,_=load_connection(config_path,require_environment=False)
    path=ROOT/config['state_directory']/'workspaces'/f'{workspace.id}.json'
    if not path.exists():return None
    saved=Workspace.model_validate_json(path.read_text(encoding='utf8'))
    if saved.id!=workspace.id or (saved.baseline.library,saved.baseline.cell)!=(workspace.baseline.library,workspace.baseline.cell):
        raise LiteError('WORKSPACE_ID_MISMATCH','持久同步记录的目标与当前工作区不同。')
    return saved if saved.state in ('submitting','indeterminate') else None


def restore_pending_state(workspace):
    pending=persisted_pending(workspace)
    return workspace.model_copy(update={'state':pending.state,'last_result':pending.last_result}) if pending else workspace


def backup(window,prefix):
    from .workspace_storage import WorkspaceStorage
    storage=getattr(window,'storage',None) or WorkspaceStorage()
    return storage.backup(window.editor.w,window.editor.profile,prefix)


def recovery_message(workspace):
    cause=workspace.last_result.get('error') or '上次提交尚未确认完成'
    return ('上次同步尚未确认。请用“文件 → 核对未完成同步”；也可备份后重新导入。'
        f'\n原因：{cause}\n核对会读取提交回执和服务器实际版图。'
        '\n也可用“文件 → 从 Virtuoso 重新导入”，完整备份当前工作区后重新读取服务器。不会重发旧提交。')

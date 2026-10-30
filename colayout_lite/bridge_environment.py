"""Project-owned Bridge settings; import endpoints, never credentials or state."""
from pathlib import Path
import re
import socket

from dotenv import dotenv_values

from .model import LiteError, digest


# Deliberately not a VB_* wildcard: runtime paths, tokens, authentication bypasses
# and other profiles must not leak from another installation into this one.
CONNECTION_KEYS = (
    'VB_REMOTE_HOST', 'VB_REMOTE_USER', 'VB_GUI_HOST', 'VB_DEPLOY_HOST',
    'VB_DAEMON_HOST', 'VB_SPECTRE_HOST', 'VB_REMOTE_PORT',
    'VB_JUMP_HOST', 'VB_JUMP_USER', 'VB_REMOTE_SCRATCH_ROOT',
    'VB_SSH_BACKEND', 'VB_SSH_MAX_SESSIONS', 'VB_CADENCE_CSHRC', 'VB_SPECTRE_BIN',
)
RUNTIME_DIRS = {'VB_CONFIG_DIR':'config', 'VB_STATE_DIR':'state', 'VB_CACHE_DIR':'cache',
                'VB_LOG_DIR':'logs', 'VB_TMP_DIR':'tmp', 'VB_OUTPUT_DIR':'artifacts'}


def project_environment(root, *, host=None, user=None, source=None, profile=None):
    values = {}
    if source:
        source = Path(source).expanduser().resolve()
        if not source.is_file():raise LiteError('BRIDGE_ENV_MISSING', str(source))
        raw = dotenv_values(source, interpolate=False)
        # Never resolve ${...} against this process's unrelated environment.
        selected = profile or raw.get('VB_PROFILE')
        if selected and not re.fullmatch(r'[A-Za-z0-9_-]+', selected):
            raise LiteError('INVALID_BRIDGE_PROFILE')
        suffix = '_'+selected if selected else ''
        if selected and not any(k+suffix in raw for k in CONNECTION_KEYS):
            raise LiteError('BRIDGE_PROFILE_UNKNOWN', 'Select a profile present in the source environment.')
        values = {k:raw[k+suffix] for k in CONNECTION_KEYS if raw.get(k+suffix)}
        # These upstream options are global, or support a global fallback.
        for key in ('VB_REMOTE_SCRATCH_ROOT','VB_SSH_BACKEND','VB_SSH_MAX_SESSIONS',
                    'VB_CADENCE_CSHRC','VB_SPECTRE_BIN'):
            if key not in values and raw.get(key):values[key]=raw[key]
        if not selected and not any(values.get(k) for k in ('VB_REMOTE_HOST','VB_GUI_HOST','VB_DAEMON_HOST')):
            raise LiteError('BRIDGE_PROFILE_REQUIRED', 'Select a source profile with --profile; profiles are not guessed.')
        if not values.get('VB_REMOTE_PORT'):
            raise LiteError('BRIDGE_REMOTE_PORT_REQUIRED', 'Verify and set the existing daemon port in the selected source profile.')
    else:
        if profile:raise LiteError('BRIDGE_PROFILE_REQUIRES_ENV')
        values = {'VB_REMOTE_HOST':host, 'VB_REMOTE_USER':user}
    if not any(values.get(k) for k in ('VB_REMOTE_HOST','VB_GUI_HOST','VB_DAEMON_HOST')):
        raise LiteError('SERVER_HOST_REQUIRED', 'Provide the server host.')
    if not values.get('VB_REMOTE_USER'):
        raise LiteError('SSH_USER_REQUIRED', 'Provide the remote SSH username.')
    for key, value in values.items():
        if value is None:continue
        if any(c in value for c in ('\n','\r','\0')) or '${' in value:
            raise LiteError('INVALID_BRIDGE_SETTING', 'Use a literal single-line value for '+key)
        if key.endswith('_HOST') or key.endswith('_USER'):
            if not re.fullmatch(r'[A-Za-z0-9_.:-]+',value) or value.startswith('-'):
                raise LiteError('INVALID_SSH_TARGET', key)
    if values.get('VB_REMOTE_PORT'):
        if not values['VB_REMOTE_PORT'].isdigit() or not 1 <= int(values['VB_REMOTE_PORT']) <= 65535:
            raise LiteError('INVALID_BRIDGE_PORT')
    else:
        # Use the pinned upstream policy for a new endpoint; never for reuse.
        from virtuoso_bridge.virtuoso.basic.bridge import _default_remote_port
        values['VB_REMOTE_PORT'] = str(_default_remote_port(values['VB_REMOTE_USER']))
    # Do not inherit another installation's local listener. start rechecks races.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        values['VB_LOCAL_PORT'] = str(listener.getsockname()[1])
    root = Path(root).resolve()
    name = 'colayout-'+digest(str(root))[:12]
    runtime = root/'.colayout/bridge-runtime'
    # A unique profile also prevents the pinned Bridge's legacy state-file
    # fallback from adopting a global state.json when this project is new.
    result = {**values, **{k+'_'+name:v for k,v in values.items()},
              'VB_PROFILE':name, 'VB_CLIENT_ID':name, 'VB_HOME':runtime.as_posix()}
    result.update({k:(runtime/v).as_posix() for k,v in RUNTIME_DIRS.items()})
    return result


def select_environment(path):
    """Load an explicit binding before upstream resolves ambient VB_PROFILE."""
    from virtuoso_bridge.env import set_runtime_env_file, load_vb_env
    set_runtime_env_file(Path(path).resolve())
    load_vb_env()

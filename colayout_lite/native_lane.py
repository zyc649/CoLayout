"""One cancellable native command lane per bridge/project, across app workers.

The OS releases the lock after a process crash. Reentry on the same thread is
allowed so construction and compound adapter operations share the same guard.
"""

from contextlib import contextmanager, nullcontext
from functools import wraps
from hashlib import sha256
from pathlib import Path
from threading import local
from time import sleep
import json
import os
from .paths import ROOT
from .model import LiteError

_held = local()


def key_for(config_path=None):
    path = Path(config_path or ROOT / 'config/colayout_lite.json').resolve()
    data = json.loads(path.read_text(encoding='utf8'))
    identity = [
        os.path.normcase(str((ROOT / data['bridge_env']).resolve())),
        data['allowed_remote_root'],
    ]
    return sha256(json.dumps(identity, ensure_ascii=False).encode('utf8')).hexdigest()


@contextmanager
def channel(config_path=None, *, cancelled=lambda: False, progress=None, lock_root=None):
    key = key_for(config_path)
    held = getattr(_held, 'keys', set())
    if key in held:
        yield
        return
    root = Path(lock_root or ROOT / 'artifacts/native-lanes')
    root.mkdir(parents=True, exist_ok=True)
    path = root / (key + '.lock')
    with path.open('a+b') as stream:
        if path.stat().st_size == 0:
            stream.write(b'0')
            stream.flush()
        acquired = False
        announced = False
        try:
            while not acquired:
                if cancelled():
                    raise LiteError('NATIVE_REQUEST_CANCELLED', '已取消等待；未开始服务器操作。')
                try:
                    stream.seek(0)
                    if os.name == 'nt':
                        import msvcrt

                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except (BlockingIOError, PermissionError, OSError) as exc:
                    if getattr(exc, 'errno', None) not in (11, 13, 35, 36):
                        raise
                    if not announced and progress:
                        progress('等待服务器通道：其他保护环/DRC 请求正在执行，本请求尚未开始。')
                        announced = True
                    sleep(0.05)
            _held.keys = held | {key}
            if cancelled():
                raise LiteError('NATIVE_REQUEST_CANCELLED', '请求尚未执行。')
            yield
        finally:
            if acquired:
                _held.keys = held
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def serialized_adapter(operation):
    @wraps(operation)
    def execute(self, *args, **kwargs):
        config = getattr(self.native, 'config_path', None)
        # In-memory test transports have no native process to serialize.
        gate = (
            channel(config, progress=kwargs.get('progress'))
            if config is not None
            else nullcontext()
        )
        with gate:
            return operation(self, *args, **kwargs)

    return execute

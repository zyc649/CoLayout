"""Short process-wide publication lock, preserved backups and rollback on failure."""
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
import hashlib
from PySide6.QtCore import QLockFile
from .model import LiteError


def file_key(path):
    path=Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@contextmanager
def locked(store):
    store.path.parent.mkdir(parents=True,exist_ok=True)
    lock=QLockFile(str(store.path)+'.publication.lock')
    if not lock.tryLock(0):raise LiteError('PROCESS_CONFIGURATION_BUSY','另一项工艺配置正在保存，请稍后重试。')
    try:yield
    finally:lock.unlock()


def publish_files(store,writes,expected,writer):
    with locked(store):
        for name,sha in expected.items():
            if file_key(name)!=sha:raise LiteError('PROCESS_CONFIGURATION_CHANGED','配置在审阅后发生变化，请刷新。')
        folder=store.folder/'publications'/uuid4().hex;folder.mkdir(parents=True)
        originals={Path(p):Path(p).read_bytes() if Path(p).exists() else None for p in writes}
        manifest={'status':'prepared','files':[]}
        for i,(path,raw) in enumerate(originals.items()):
            backup=folder/(str(i)+'.before')
            if raw is not None:backup.write_bytes(raw)
            manifest['files'].append({'target':str(path.resolve()),'backup':str(backup.resolve()) if raw is not None else None})
        writer(folder/'manifest.json',manifest)
        try:
            for path,value in writes.items():writer(path,value)
            manifest['status']='committed';writer(folder/'manifest.json',manifest)
        except Exception:
            for path,raw in originals.items():
                if raw is None:path.unlink(missing_ok=True)
                else:
                    temp=path.with_name(path.name+'.restore.tmp');temp.write_bytes(raw);temp.replace(path)
            manifest['status']='rolled_back';writer(folder/'manifest.json',manifest);raise

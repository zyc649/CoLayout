"""Shared saved-workspace use cases with explicit file roots and no native calls."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from .document import load_document, save_document
from .model import LiteError
from .transactions import write_json_atomic


class WorkspaceFiles:
    def __init__(self, editor, current_path, open_document, folder, *, import_roots=(),
                 busy=lambda: False, save_busy=None, path_warning=lambda: None,
                 storage=None, import_files=lambda: ()):
        from .workspace_storage import WorkspaceStorage
        self.storage = storage or WorkspaceStorage(Path(folder) / '.runtime')
        self.import_files = import_files
        self.editor = editor
        self.current_path = current_path
        self.open_document = open_document
        self.folder = Path(folder).resolve()
        self.import_roots = tuple(dict.fromkeys([
            self.folder, self.storage.folder/'backups', *(Path(p).resolve() for p in import_roots)]))
        self.busy = busy
        self.save_busy = save_busy or busy
        self.path_warning = path_warning

    def status(self):
        e = self.editor()
        return {'document_id':e.w.id, 'revision':e.w.revision, 'state':e.w.state,
                'path':str(self.current_path()), 'library':e.w.baseline.library,
                'cell':e.w.baseline.cell, 'pending_operations':len(e.w.operations),
                'active_regions':len(e.work_sessions.snapshots()),
                'archive_folder':str(self.folder),
                'import_roots':[str(p) for p in self.import_roots],
                'import_files':[str(Path(p).resolve()) for p in self.import_files() if p],
                'can_load':not self.busy() and not e.work_sessions.snapshots()
                    and e.w.state not in ('submitting','indeterminate','conflict')}

    def expected(self, args):
        e = self.editor()
        if args.expected_document_id != e.w.id:
            raise LiteError('WORKSPACE_CHANGED','请先读取 workspace status；当前文档已改变。')
        if type(args.expected_revision) is not int or args.expected_revision != e.w.revision:
            raise LiteError('STALE_REVISION','请先读取当前工作区版本。')
        return e

    def _save(self, e, name):
        name = (name or e.w.baseline.cell).strip()
        if not name or len(name)>100 or re.search(r'[<>:"/\\|?*\x00-\x1f]',name):
            raise LiteError('INVALID_WORKSPACE_NAME','name 是存档名称，不是目录；不要包含路径分隔符。')
        self.folder.mkdir(parents=True,exist_ok=True)
        stem=f'{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{name}_r{e.w.revision}_{uuid4().hex[:8]}'
        path=self.folder/(stem+'.colayout.json')
        save_document(path,e.w,e.profile)
        row={'path':str(path),'name':name,'document_id':e.w.id,'revision':e.w.revision,
             'created_at_utc':datetime.now(timezone.utc).isoformat(),
             'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
             'pending_operations':len(e.w.operations),'regions':len(e.w.local_data.regions)}
        try:
            index=self.storage.folder/'archive-index'/hashlib.sha256(str(path).encode()).hexdigest()
            write_json_atomic(index.with_suffix('.meta.json'),row)
        except OSError as exc:
            row['save_warning']='工作区文件已保存，但目录索引写入失败：'+str(exc)
        return row

    def input_path(self, value):
        if not value:
            raise LiteError('WORKSPACE_FILE_REQUIRED')
        path=Path(value)
        path=(path if path.is_absolute() else self.folder/path).resolve()
        if (path not in {Path(p).resolve() for p in self.import_files() if p}
                and not any(path.is_relative_to(root) for root in self.import_roots)):
            raise LiteError('WORKSPACE_FILE_OUTSIDE_ROOT','文件须位于 workspace status 的 import_roots，或属于 import_files 中明确选定的文件。')
        if path.suffix.lower()!='.json' or not path.is_file():
            raise LiteError('WORKSPACE_FILE_REQUIRED','请选择已保存的 .colayout.json 文件。')
        if path.stat().st_size>256*1024*1024:
            raise LiteError('WORKSPACE_FILE_TOO_LARGE','单个工作区文件上限为 256 MiB。')
        return path

    def invoke(self, args):
        if args.action=='status':
            return self.status()
        if args.action=='list':
            rows={}
            # Legacy sidecar indexes remain readable; new ones stay internal.
            for index in (self.folder,self.storage.folder/'archive-index'):
                for file in index.glob('*.meta.json'):
                    row=json.loads(file.read_text(encoding='utf8'))
                    if Path(row['path']).resolve().parent==self.folder and Path(row['path']).is_file():
                        rows[row['path']]=row
            rows=sorted(rows.values(),key=lambda r:r['created_at_utc'],reverse=True)
            return {'files':rows[args.offset:args.offset+args.limit], 'total':len(rows)}
        e=self.expected(args)
        if args.action=='save':
            if self.save_busy():
                raise LiteError('WORKSPACE_BUSY','等待当前原生/文档任务结束后保存存档。')
            return {'saved':True,'active_document_changed':False,**self._save(e,args.name)}
        e.check_revision(args.expected_revision)
        e.work_sessions.require_idle()
        if self.busy():
            raise LiteError('WORKSPACE_BUSY','加载前请结束所有后台任务。')
        path=self.input_path(args.path)
        raw=path.read_bytes()
        try:
            payload=json.loads(raw)
        except (ValueError,UnicodeError) as exc:
            raise LiteError('WORKSPACE_FILE_INVALID','不是有效的工作区 JSON 文件。') from exc
        if not isinstance(payload,dict) or payload.get('schema_version')!='colayout-document-1':
            raise LiteError('WORKSPACE_FILE_INVALID','不是 CoLayout 工作区文件。')
        # Validation/migrations operate on a new working file, never on the archive.
        working,_=self.storage.prepare(path)
        loaded,profile=load_document(working)
        from .sync_recovery import restore_pending_state
        loaded=restore_pending_state(loaded)
        if loaded.state in ('submitting','indeterminate','conflict'):
            raise LiteError('WORKSPACE_REQUIRES_RECOVERY','该存档有未决原生状态，需由维护者先核对回执。')
        saved=self.storage.backup(e.w,e.profile,'before-load')
        backup={'path':str(saved),'document_id':e.w.id,'revision':e.w.revision,
                'sha256':hashlib.sha256(saved.read_bytes()).hexdigest()}
        self.open_document(working)
        result={'loaded':True,'archive_path':str(path),'previous_backup':backup,
                'archive_unchanged':path.read_bytes()==raw,**self.status()}
        if self.path_warning():
            result['save_warning']=self.path_warning()
        return result

"""Keep portable documents separate from autosave, locks and recovery files."""
import json
from pathlib import Path
from uuid import uuid4

from .paths import ROOT
from .transactions import write_json_atomic, write_text_atomic

RUNTIME_ROOT = ROOT / 'artifacts/workspace-runtime'


class WorkspaceStorage:
    def __init__(self, folder=None):
        self.folder = Path(folder or RUNTIME_ROOT).resolve()
        self.documents = self.folder / 'documents'

    def prepare(self, source, *, resume=False):
        """Resume an internal working file, or copy an archive before migration."""
        source = Path(source).resolve()
        metadata = source.parent / 'document-source.json'
        if resume and source.is_relative_to(self.documents) and source.name == 'workspace.colayout.json' and metadata.is_file():
            return source, self.archive_path(source)
        raw = source.read_text(encoding='utf8')
        working = self.documents / uuid4().hex / 'workspace.colayout.json'
        write_text_atomic(working, raw)
        # Restoring an automatic recovery file must not make Save overwrite it.
        protected = source.is_relative_to(self.folder / 'backups') or (
            source.is_relative_to(self.documents) and source.name == 'workspace.colayout.json'
            and metadata.is_file())
        archive = None if protected else source
        self.remember_archive(working, archive)
        return working, archive

    def archive_path(self, working):
        metadata = Path(working).parent / 'document-source.json'
        value = json.loads(metadata.read_text(encoding='utf8')).get('archive_path')
        return Path(value) if value else None

    def remember_archive(self, working, archive):
        write_json_atomic(Path(working).parent / 'document-source.json',
                          {'archive_path': str(Path(archive).resolve()) if archive else None})

    def backup_folder(self, workspace_id):
        # Hash arbitrary document IDs instead of accepting them as directory names.
        from hashlib import sha256
        return self.folder / 'backups' / sha256(workspace_id.encode()).hexdigest()[:24]

    def backup(self, workspace, profile, prefix):
        from .document import save_document
        from .sync_recovery import persisted_pending
        path = self.backup_folder(workspace.id) / f'{prefix}-{uuid4().hex[:12]}.colayout.json'
        save_document(path, workspace, profile)
        pending = persisted_pending(workspace)
        if pending and pending != workspace:
            save_document(path.with_name(path.stem + '.pending.colayout.json'), pending, profile)
        return path

"""One portable local document: workspace (including user content) + technology."""
import json
from pathlib import Path
from .model import Workspace,LiteError
from .technology import TechnologyProfile
from .transactions import write_text_atomic
from .editor import projected
from .local_models import require_references


def document_text(workspace,profile):
    """Pure encoding of immutable input; safe for a read worker's snapshot writer."""
    return '{"schema_version":"colayout-document-1","workspace":'+workspace.model_dump_json()+',"technology":'+profile.model_dump_json()+'}'


def save_document(path,workspace,profile):
    require_references(workspace.local_data,projected(workspace))
    # Avoid constructing and encoding a second full Python copy of the native
    # display/CDF data on each GUI gesture. The on-disk document remains portable.
    data=document_text(workspace,profile)
    write_text_atomic(Path(path),data)


def load_document(path):
    data=json.loads(Path(path).read_text(encoding='utf8'))
    if data.get('schema_version')!='colayout-document-1':raise LiteError('DOCUMENT_VERSION')
    w=Workspace.model_validate(data['workspace']);p=TechnologyProfile.model_validate(data['technology'])
    if w.baseline.technology_fingerprint!=p.native_fingerprint:raise LiteError('TECHNOLOGY_MISMATCH')
    require_references(w.local_data,projected(w))
    from .regions.constraints import validate_workspace
    validate_workspace(w,p)
    from .edge_pin_migration import normalize
    w=normalize(w,p,path=path)
    return w,p

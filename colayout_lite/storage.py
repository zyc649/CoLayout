"""Immutable baseline files + small atomic draft records (no Qt/bridge)."""
import json,weakref
from pathlib import Path
from uuid import uuid4

_baselines={}

def remember(snapshot,path):
    key=id(snapshot)
    _baselines[key]=(weakref.ref(snapshot,lambda ref:_baselines.pop(key,None)),Path(path))

def save_workspace(workspace,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    entry=_baselines.get(id(workspace.baseline))
    baseline_path=entry[1] if entry and entry[0]() is workspace.baseline and entry[1].exists() else None
    if baseline_path is None:
        baseline_path=path.parent/'baselines'/f'{uuid4().hex}.json';baseline_path.parent.mkdir(exist_ok=True)
        temporary=baseline_path.with_suffix('.tmp')
        temporary.write_text(workspace.baseline.model_dump_json(),encoding='utf-8');temporary.replace(baseline_path)
        remember(workspace.baseline,baseline_path.resolve())
    record=workspace.model_dump(exclude={'baseline'});record['baseline_ref']=str(baseline_path.resolve());record['storage_version']='colayout-lite-storage-1'
    temporary=path.with_name(path.name+'.tmp');temporary.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)

def load_baseline(path):
    from .model import Snapshot
    p=Path(path)
    if not p.is_absolute() or p.suffix!='.json':raise ValueError('Invalid baseline reference')
    result=Snapshot.model_validate_json(p.read_text(encoding='utf-8'));remember(result,p);return result

"""Manifest-only discovery. Registering an algorithm does not execute it."""
import json
from pathlib import Path
from hashlib import sha256
from ..model import LiteError
from ..transactions import write_json_atomic
from .models import PluginManifest
from .builtin import ALGORITHMS


def descriptor(path):
    path=Path(path).resolve()
    if path.stat().st_size>65536:raise ValueError('Plugin manifest exceeds 64 KiB')
    manifest=PluginManifest.model_validate_json(path.read_text(encoding='utf8'))
    if manifest.id.startswith('builtin.'):raise ValueError('builtin.* IDs are reserved')
    entry=(path.parent/manifest.entry).resolve();entry.relative_to(path.parent)
    if not entry.is_file() or entry.stat().st_size>2*1024*1024:raise ValueError('Missing or oversized Python entry')
    return {**manifest.model_dump(mode='json'),'manifest_path':str(path),'entry_path':str(entry),'builtin':False,
            'digest':sha256(path.read_bytes()+b'\0'+entry.read_bytes()).hexdigest()}


class Registry:
    def __init__(self,path):self.path=Path(path)

    def paths(self):
        if not self.path.exists():return []
        value=json.loads(self.path.read_text(encoding='utf8'))
        if not isinstance(value,list) or not all(isinstance(p,str) for p in value):raise ValueError('Invalid plugin registry')
        return value

    def list(self):
        root=Path(__file__).parent
        implementation=sha256(b''.join((root/name).read_bytes() for name in ('builtin.py','maze.py','geometry.py','fanout.py','layers.py','repair.py','reorder.py','port_escape.py'))).hexdigest()
        rows=[{'id':ident,'name':name,'version':'2.0','description':description,'builtin':True,
               'digest':implementation,'timeout_seconds':180 if ident=='builtin.reorder' else 90} for ident,(name,_,description) in ALGORITHMS.items() if ident!='builtin.dijkstra']
        for path in self.paths():
            try:rows.append(descriptor(path))
            except Exception as exc:rows.append({'id':path,'name':Path(path).name,'manifest_path':path,'builtin':False,'error':str(exc)})
        return rows

    def register(self,path):
        row=descriptor(path);paths=self.paths()
        if any(r['id']==row['id'] and r.get('manifest_path')!=row['manifest_path'] for r in self.list()):
            raise LiteError('PLUGIN_ID_EXISTS','请先移除相同 ID 的旧登记。',algorithm_id=row['id'])
        if row['manifest_path'] not in paths:paths.append(row['manifest_path'])
        write_json_atomic(self.path,paths);return row

    def remove(self,path):
        write_json_atomic(self.path,[p for p in self.paths() if p!=str(Path(path).resolve())])

    def resolve(self,ids):
        rows={r['id']:r for r in self.list()}
        if not ids or len(ids)>8 or len(ids)!=len(set(ids)):raise LiteError('ROUTING_ALGORITHM_SELECTION','请勾选至少一个可用算法，最多 8 个且不能重复。')
        if any(i not in rows or rows[i].get('error') for i in ids):raise LiteError('ROUTING_PLUGIN_UNAVAILABLE')
        return [rows[i] for i in ids]

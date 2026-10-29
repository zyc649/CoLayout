"""Check the portable installation and its audited upstream compatibility patch."""
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def check():
    errors=[]
    if sys.version_info[:2]!=(3,13):errors.append('Python 3.13 is required.')
    spec=importlib.util.find_spec('colayout_lite')
    if not spec or Path(spec.origin).resolve()!=ROOT/'colayout_lite/__init__.py':
        errors.append('CoLayout is not imported from this repository.')
    versions={}
    for name in ('colayout-lite','virtuoso-bridge','PySide6_Essentials','pydantic','shapely'):
        try:versions[name]=metadata.version(name)
        except metadata.PackageNotFoundError:errors.append(name+' is not installed.')
    lock=json.loads((ROOT/'dependencies/bridge-lock.json').read_text(encoding='utf8'))
    if versions.get('virtuoso-bridge')!=lock['version']:errors.append('Bridge version differs from the dependency lock.')
    try:
        from virtuoso_bridge.transport import tunnel
        actual=hashlib.sha256(Path(tunnel.__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        if actual!=lock['patches'][0]['after_sha256']:errors.append('Bridge compatibility source differs from the audited lock.')
    except ImportError:errors.append('Bridge is unavailable.')
    skills={}
    for name in ('colayout-pdk','colayout-layout-agent','virtuoso'):
        path=ROOT/'.agents/skills'/name/'SKILL.md'
        skills[name]=path.is_file()
        if not skills[name]:errors.append('Project skill missing: '+name)
    if not (ROOT/'.agents/skills/virtuoso/LICENSE').is_file():
        errors.append('Upstream Virtuoso skill license is missing.')
    return {'status':'failed' if errors else 'passed','versions':versions,'project_skills':skills,'errors':errors}


if __name__=='__main__':
    result=check();print(json.dumps(result,indent=2));raise SystemExit(bool(result['errors']))

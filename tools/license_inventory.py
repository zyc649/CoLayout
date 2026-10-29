"""Record license metadata and verbatim notices from the locked installed environment."""
import json
from importlib import metadata
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def inventory():
    names = [line.split('==')[0] for line in (ROOT/'requirements-locked.txt').read_text().splitlines()
             if line and not line.startswith('#')]
    names += ['virtuoso-bridge']
    records = []
    for name in names:
        dist = metadata.distribution(name)
        key = re.sub(r'[-_.]+', '-', name).lower()
        notices = []
        for entry in dist.files or []:
            if '.dist-info/' not in str(entry).replace('\\', '/'):
                continue
            if not any(part.lower().startswith(('license', 'copying', 'notice', 'authors'))
                       for part in entry.parts):
                continue
            source = dist.locate_file(entry)
            if not source.is_file():
                continue
            # Strip only the package's dist-info directory; preserve notice bytes.
            relative = Path(*entry.parts[1:])
            target = ROOT/'LICENSES/dependencies'/key/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            notices.append(target.relative_to(ROOT).as_posix())
        records.append({
            'name': dist.metadata['Name'], 'version': dist.version,
            'license': dist.metadata.get('License-Expression') or dist.metadata.get('License'),
            'project_urls': dist.metadata.get_all('Project-URL') or [],
            'notices': notices})
    (ROOT/'dependencies/licenses.json').write_text(
        json.dumps(records, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(json.dumps({'packages': len(records), 'notices': sum(len(r['notices']) for r in records),
                      'missing_notices': [r['name'] for r in records if not r['notices']]}))


if __name__ == '__main__':
    inventory()

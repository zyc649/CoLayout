"""Read-only audit of the pinned Bridge archive, notices and publication boundary."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def check(archive=None):
    lock = json.loads((ROOT/'dependencies/bridge-lock.json').read_text(encoding='utf8'))
    bundle = Path(archive) if archive else ROOT/'.colayout/dependencies/upstream.zip'
    if not bundle.is_file():
        raise ValueError('Pinned archive is not cached. Pass --archive with the same verified setup archive.')
    if sha(bundle.read_bytes()) != lock['sha256']:
        raise ValueError('Upstream archive checksum mismatch')
    source = ROOT/'.colayout/dependencies/virtuoso-bridge'
    with ZipFile(bundle) as zipped:
        prefixes = {name.split('/')[0] for name in zipped.namelist()}
        if len(prefixes) != 1:
            raise ValueError('Unexpected archive roots')
        prefix = prefixes.pop()+'/'
        license_text = zipped.read(prefix+'LICENSE')
        for relative in (
            'LICENSES/virtuoso-bridge-lite-MIT.txt',
            'LICENSES/dependencies/virtuoso-bridge/licenses/LICENSE',
            '.agents/skills/virtuoso/LICENSE',
            '.colayout/dependencies/virtuoso-bridge/LICENSE',
        ):
            if (ROOT/relative).read_bytes() != license_text:
                raise ValueError('Upstream notice differs: '+relative)
        patches = {p['file']: p for p in lock['patches']}
        checked = 0
        for name in zipped.namelist():
            relative = name[len(prefix):]
            if not relative.startswith('src/') or name.endswith('/'):
                continue
            upstream = zipped.read(name)
            local = (source/relative).read_bytes()
            if relative in patches:
                patch = patches[relative]
                if sha(upstream.replace(b'\r\n', b'\n')) != patch['before_sha256']:
                    raise ValueError('Wrong upstream patch input')
                if sha(local.replace(b'\r\n', b'\n')) != patch['after_sha256']:
                    raise ValueError('Wrong patched source')
            elif local != upstream:
                raise ValueError('Undocumented dependency source change: '+relative)
            checked += 1
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf8').split('\0')
    if any(p.startswith(('.colayout/', '.venv/', '.agents/skills/virtuoso/')) for p in tracked):
        raise ValueError('Runtime dependency source must not be tracked')
    return {'passed': True, 'commit': lock['commit'], 'archive_sha256': lock['sha256'],
            'license_sha256': sha(license_text), 'identical_notice_copies': 4,
            'dependency_source_files_checked': checked, 'documented_patches': len(patches)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    try:
        result = check(args.archive)
    except (ValueError, OSError, KeyError) as exc:
        result = {'passed': False, 'error': str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(not result['passed'])

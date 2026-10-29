"""Download the audited upstream dependency; never replace a user's checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(project=ROOT, archive=None):
    project = Path(project).resolve()
    lock = json.loads((project / 'dependencies/bridge-lock.json').read_text(encoding='utf8'))
    cache = project / '.colayout/dependencies'
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / 'virtuoso-bridge'
    stamp = sha(json.dumps(lock, sort_keys=True).encode())
    receipt = destination / '.colayout-upstream.json'
    if destination.exists():
        if not receipt.is_file() or json.loads(receipt.read_text())['lock_digest'] != stamp:
            raise ValueError('Existing Bridge source has a different origin; it was not replaced.')
        for patch in lock['patches']:
            data = (destination / patch['file']).read_bytes().replace(b'\r\n', b'\n')
            if sha(data) != patch['after_sha256']:
                raise ValueError('Bridge source was modified; preserve and review it before upgrading.')
        return destination
    bundle = Path(archive) if archive else cache / 'upstream.zip'
    if not bundle.exists():
        request = urllib.request.Request(lock['url'], headers={'User-Agent': 'CoLayout-bootstrap'})
        temporary = cache / 'download.partial'
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open('wb') as output:
            shutil.copyfileobj(response, output)
        if sha(temporary.read_bytes()) != lock['sha256']:
            raise ValueError('Bridge download checksum mismatch; no source was installed.')
        os.replace(temporary, bundle)
    if sha(bundle.read_bytes()) != lock['sha256']:
        raise ValueError('Bridge archive checksum mismatch; no source was installed.')
    with tempfile.TemporaryDirectory(prefix='unpack-', dir=cache) as temporary:
        stage = Path(temporary).resolve()
        assert stage.is_relative_to(cache.resolve())
        with ZipFile(bundle) as zipped:
            roots = set()
            for entry in zipped.infolist():
                path = stage / entry.filename
                if not path.resolve().is_relative_to(stage) or ((entry.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ValueError('Unsafe path in dependency archive.')
                roots.add(Path(entry.filename).parts[0])
            if len(roots) != 1:
                raise ValueError('Unexpected Bridge archive structure.')
            zipped.extractall(stage)
        source = stage / roots.pop()
        if not (source / 'LICENSE').is_file() or not (source / 'pyproject.toml').is_file():
            raise ValueError('Incomplete upstream source.')
        for patch in lock['patches']:
            file = source / patch['file']
            normalized = file.read_bytes().replace(b'\r\n', b'\n')
            if sha(normalized) != patch['before_sha256']:
                raise ValueError('Upstream patch precondition mismatch.')
            file.write_bytes(normalized)
            patch_file = project / patch['patch']
            directory = source.relative_to(project).as_posix()
            patch_bytes = patch_file.read_bytes().replace(b'\r\n', b'\n')
            subprocess.run(['git', 'apply', '--directory='+directory, '--check', '-'], input=patch_bytes, cwd=project, check=True)
            subprocess.run(['git', 'apply', '--directory='+directory, '-'], input=patch_bytes, cwd=project, check=True)
            if sha(file.read_bytes().replace(b'\r\n', b'\n')) != patch['after_sha256']:
                raise ValueError('Patched Bridge checksum mismatch.')
        (source / '.colayout-upstream.json').write_text(
            json.dumps({'lock_digest': stamp, 'commit': lock['commit']}, indent=2), encoding='utf8')
        assert source.resolve().is_relative_to(stage)
        assert destination.resolve().is_relative_to(cache.resolve())
        shutil.move(str(source), str(destination))
    return destination


def install_skill(source, project=ROOT):
    destination = Path(project) / '.agents/skills/virtuoso'
    if destination.exists():
        return  # Existing user-maintained skill is never silently replaced.
    origin = Path(source) / 'skills/virtuoso'
    if not (origin / 'SKILL.md').is_file():
        raise ValueError('Pinned upstream archive is missing its Virtuoso skill.')
    shutil.copytree(origin, destination)
    shutil.copyfile(Path(source) / 'LICENSE', destination / 'LICENSE')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    source = prepare(archive=args.archive)
    install_skill(source)
    print(source)

"""Publication/install safeguards tested with synthetic data only."""
import hashlib
import json
from pathlib import Path
import zipfile
import pytest
from tools import bootstrap_bridge


def lock(root, raw, patches=()):
    (root/'dependencies').mkdir()
    (root/'dependencies/bridge-lock.json').write_text(json.dumps({
        'url':'https://example.com/unreachable.zip', 'commit':'synthetic',
        'sha256':hashlib.sha256(raw).hexdigest(), 'patches':list(patches)}))
    archive=root/'sample.zip'
    archive.write_bytes(raw)
    return archive


def test_bad_archive_never_installs_source(tmp_path):
    archive=lock(tmp_path,b'expected')
    archive.write_bytes(b'changed')
    with pytest.raises(ValueError,match='checksum mismatch'):
        bootstrap_bridge.prepare(tmp_path,archive)
    assert not (tmp_path/'.colayout/dependencies/virtuoso-bridge').exists()


def test_zip_traversal_is_rejected(tmp_path):
    import io
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        z.writestr('../../outside.txt','unsafe')
    archive=lock(tmp_path,stream.getvalue())
    with pytest.raises(ValueError,match='Unsafe path'):
        bootstrap_bridge.prepare(tmp_path,archive)
    assert not (tmp_path/'outside.txt').exists()


def test_existing_unmanaged_dependency_is_preserved(tmp_path):
    archive=lock(tmp_path,b'unused')
    source=tmp_path/'.colayout/dependencies/virtuoso-bridge'
    source.mkdir(parents=True)
    sentinel=source/'my-changes.py';sentinel.write_text('keep')
    with pytest.raises(ValueError,match='different origin'):
        bootstrap_bridge.prepare(tmp_path,archive)
    assert sentinel.read_text()=='keep'


def test_new_drc_defaults_do_not_assume_a_vendor_installation():
    from colayout_lite.drc.models import RemoteConfig
    cfg=RemoteConfig(deck_path='/workspace/rules.drc',layer_map='/workspace/layers.map')
    assert all(getattr(cfg,key).startswith('/path/to/') for key in ('calibre','strmout','environment'))


@pytest.mark.skipif(__import__('sys').platform!='win32',reason='Windows native process query')
def test_bridge_process_probe_is_read_only():
    import os
    from virtuoso_bridge.transport.tunnel import _pid_is_alive
    assert _pid_is_alive(os.getpid())
    assert not _pid_is_alive(-1)

"""Tests never put workspace recovery files into the user's runtime store."""
import pytest


@pytest.fixture(autouse=True)
def isolated_workspace_storage(tmp_path):
    # Keep this patch independent: requesting the shared monkeypatch fixture
    # here would leave test-injected failures active during window teardown.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr('colayout_lite.workspace_storage.RUNTIME_ROOT', tmp_path / 'runtime')
        yield

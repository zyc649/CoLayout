from types import SimpleNamespace
import pytest
from colayout_lite.adapter import Adapter
from colayout_lite.editor import Editor, projected
from colayout_lite.model import LiteError
from colayout_lite.sync_checks import verify
from tests_lite.test_agent_connectivity import tech, workspace, rect


def test_delayed_native_update_is_verified_before_guarded_save(tech, tmp_path, monkeypatch):
    e = Editor(workspace(tech), tech)
    e.create(rect(0, 0, 100, 100))
    dirty = e.w.baseline.model_copy(
        update={'objects': projected(e.w), 'dirty': True, 'counter': '2'}
    )
    clean = dirty.model_copy(update={'dirty': False, 'counter': '3'})
    calls = []
    a = Adapter(SimpleNamespace(state=tmp_path, call=lambda *args: calls.append(args)))
    monkeypatch.setattr(a, 'read', lambda *args: (clean, tech))
    with pytest.raises(LiteError, match='READBACK_NOT_SAVED'):
        verify(e.w, dirty, profile=tech)
    assert a._verify_saved_readback(e.w, dirty, tech) is clean
    assert calls == [('ltPersistVerified', 'L', 'C', '2')]


def test_foreign_geometry_is_never_saved_to_settle_callbacks(tech, tmp_path):
    e = Editor(workspace(tech), tech)
    e.create(rect(0, 0, 100, 100))
    wrong = e.w.baseline.model_copy(update={'dirty': True, 'counter': '2'})
    calls = []
    a = Adapter(SimpleNamespace(state=tmp_path, call=lambda *args: calls.append(args)))
    with pytest.raises(LiteError, match='READBACK_OBJECT_SET'):
        a._verify_saved_readback(e.w, wrong, tech)
    assert not calls


def test_unsettled_native_callbacks_fail_after_bounded_saves(tech, tmp_path, monkeypatch):
    w = workspace(tech, [rect(0, 0, 100, 100)])
    dirty = w.baseline.model_copy(update={'dirty': True})
    calls = []
    a = Adapter(SimpleNamespace(state=tmp_path, call=lambda *args: calls.append(args)))
    monkeypatch.setattr(a, 'read', lambda *args: (dirty, tech))
    with pytest.raises(LiteError, match='READBACK_NOT_SAVED'):
        a._verify_saved_readback(w, dirty, tech)
    assert len(calls) == 3

"""Reproduce file contention without launching or replaying native operations."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from colayout_lite.drc import jobs, job_storage, worker
from colayout_lite.model import LiteError
from tests_lite.test_drc import tech, workspace, profile, rule, rect, ROI


@pytest.fixture
def frozen_job(tech, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, 'BASE', tmp_path)
    monkeypatch.setattr(job_storage, 'sleep', lambda _: None)
    launches = []
    def launch(*args, **kwargs):
        launches.append(args)
        return SimpleNamespace(pid=123)
    monkeypatch.setattr(jobs.subprocess, 'Popen', launch)
    monkeypatch.setattr('virtuoso_bridge.transport.tunnel._pid_is_alive', lambda _: True)
    w = workspace(tech, [rect(0, 0, 100, 100)])
    initial = jobs.start(w, tech, profile(tech, rule('width')), ROI, 'local')
    return initial['job_id'], launches


def test_transient_state_read_does_not_cancel_or_relaunch(frozen_job, monkeypatch):
    uid, launches = frozen_job
    original = Path.read_text
    attempts = []
    def read(path, *args, **kwargs):
        if path.name == 'state.json':
            attempts.append(path)
            if len(attempts) <= 2:
                raise PermissionError(13, 'sharing violation', str(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    assert jobs.status(uid)['status'] == 'queued'
    assert len(attempts) == 3 and len(launches) == 1
    assert not (jobs.job_folder(uid) / 'cancel.flag').exists()
    worker.execute(uid)
    assert jobs.status(uid)['status'] == 'completed'
    assert jobs.result(uid).job_id == uid


def test_state_replace_contention_retries_same_atomic_write(frozen_job, monkeypatch):
    uid, launches = frozen_job
    original = Path.replace
    attempts = []
    def replace(path, target):
        if Path(target).name == 'state.json':
            attempts.append(path)
            if len(attempts) <= 2:
                raise PermissionError(13, 'sharing violation', str(target))
        return original(path, target)
    monkeypatch.setattr(Path, 'replace', replace)
    worker.execute(uid)
    state = jobs.status(uid)
    assert state['status'] == 'completed' and state['result_available']
    assert len(launches) == 1 and not list(jobs.job_folder(uid).glob('*.tmp'))


def test_terminal_receipt_preserves_saved_result_when_state_mirror_locked(frozen_job, monkeypatch):
    uid, _ = frozen_job
    original = Path.replace
    def replace(path, target):
        if Path(target).name == 'state.json' and (path.parent / 'terminal.json').exists():
            raise PermissionError(13, 'locked state mirror', str(target))
        return original(path, target)
    monkeypatch.setattr(Path, 'replace', replace)
    worker.execute(uid)
    assert jobs.status(uid)['status'] == 'completed'
    assert jobs.status(uid)['drc_completed'] is True
    assert jobs.result(uid).job_id == uid
    assert json.loads((jobs.job_folder(uid) / 'state.json').read_text(encoding='utf8'))['status'] == 'running'


@pytest.mark.parametrize('locked,completed', [('state.json', False), ('result.json', True)])
def test_permanent_write_failure_keeps_stage_and_no_false_drc_verdict(frozen_job, monkeypatch, locked, completed):
    uid, _ = frozen_job
    original = Path.replace
    def replace(path, target):
        if Path(target).name == locked:
            raise PermissionError(13, 'locked', str(target))
        return original(path, target)
    monkeypatch.setattr(Path, 'replace', replace)
    worker.execute(uid)
    state = jobs.status(uid)
    assert state['status'] == 'failed' and 'passed' not in state
    details = state['error']['details']
    assert details['stage'] == locked.removesuffix('.json') + '_write'
    assert details['drc_completed'] is completed and details['result_available'] is False
    assert details['next_action'] == 'contact_maintenance' and details['native_job_id'] == uid
    assert (jobs.job_folder(uid) / 'error.txt').exists()


def test_permanent_read_failure_is_bounded_and_parse_errors_are_not_retried(frozen_job, monkeypatch):
    uid, _ = frozen_job
    original = Path.read_text
    attempts = []
    def read(path, *args, **kwargs):
        if path.name == 'state.json':
            attempts.append(path)
            raise PermissionError(13, 'denied', str(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    with pytest.raises(LiteError) as failure:
        jobs.status(uid)
    assert len(attempts) == len(job_storage.RETRY_DELAYS) + 1
    assert failure.value.details['stage'] == 'state_read'
    assert failure.value.details['drc_completed'] is None
    monkeypatch.setattr(Path, 'read_text', original)
    (jobs.job_folder(uid) / 'state.json').write_text('{broken', encoding='utf8')
    with pytest.raises(json.JSONDecodeError):
        jobs.status(uid)


def test_terminal_arriving_during_read_retry_wins_locked_state(frozen_job, monkeypatch):
    uid, _ = frozen_job
    worker.execute(uid)
    terminal = jobs.job_folder(uid) / 'terminal.json'
    saved = terminal.read_bytes()
    terminal.unlink()  # Simulate the last receipt arriving after the first probe.
    original = Path.read_text
    def read(path, *args, **kwargs):
        if path.name == 'state.json':
            terminal.write_bytes(saved)
            raise PermissionError(13, 'state locked', str(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    assert jobs.status(uid)['status'] == 'completed'
    assert jobs.result(uid).job_id == uid


def test_launcher_receipt_failure_retains_job_id_and_requests_stop(frozen_job, tech, monkeypatch):
    _, launches = frozen_job
    original = Path.replace
    def replace(path, target):
        if Path(target).name == 'launcher.json':
            raise PermissionError(13, 'launcher locked', str(target))
        return original(path, target)
    monkeypatch.setattr(Path, 'replace', replace)
    w = workspace(tech, [rect(0, 0, 100, 100)])
    with pytest.raises(LiteError) as failure:
        jobs.start(w, tech, profile(tech, rule('width')), ROI, 'local')
    uid = failure.value.details['native_job_id']
    assert failure.value.details['cancellation_requested']
    assert (jobs.job_folder(uid) / 'cancel.flag').exists()
    assert len(launches) == 2  # One fixture job, one new job; no hidden relaunch.

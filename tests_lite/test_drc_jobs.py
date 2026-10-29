import json
import pytest
from tests_lite.test_drc import tech,workspace,profile,rule,rect,ROI
from colayout_lite.drc import jobs
from colayout_lite.model import LiteError


def test_workspace_units_and_technology_rejected_before_worker(tech):
    w=workspace(tech,[rect(0,0,100,100)]);cfg=profile(tech,rule('width'))
    with pytest.raises(LiteError,match='DBU_MISMATCH'):jobs.start(w,tech.model_copy(update={'dbu_per_micron':1000}),cfg,ROI,'local')
    w=w.model_copy(update={'baseline':w.baseline.model_copy(update={'technology_fingerprint':'wrong'})})
    with pytest.raises(LiteError,match='MISMATCH'):jobs.start(w,tech,cfg,ROI,'local')


def test_dead_worker_is_failed_and_no_result(tech,tmp_path,monkeypatch):
    monkeypatch.setattr(jobs,'BASE',tmp_path);uid='a'*32;folder=tmp_path/uid;folder.mkdir()
    (folder/'state.json').write_text(json.dumps({'status':'running','job_id':uid}),encoding='utf8')
    (folder/'launcher.json').write_text('{"pid":123}',encoding='utf8')
    monkeypatch.setattr('virtuoso_bridge.transport.tunnel._pid_is_alive',lambda pid:False)
    assert jobs.status(uid)['status']=='failed'
    with pytest.raises(FileNotFoundError):jobs.result(uid)


def test_finished_state_wins_process_exit_race(tmp_path,monkeypatch):
    monkeypatch.setattr(jobs,'BASE',tmp_path);uid='b'*32;folder=tmp_path/uid;folder.mkdir()
    (folder/'state.json').write_text(json.dumps({'status':'running','job_id':uid}),encoding='utf8')
    (folder/'launcher.json').write_text('{"pid":123}',encoding='utf8')
    def exits(pid):
        (folder/'state.json').write_text(json.dumps({'status':'completed','job_id':uid}),encoding='utf8');return False
    monkeypatch.setattr('virtuoso_bridge.transport.tunnel._pid_is_alive',exits)
    assert jobs.status(uid)['status']=='completed'


@pytest.mark.parametrize('bad',['../elsewhere','', 'A'*32, '0'*33])
def test_job_identifier_cannot_escape(bad):
    with pytest.raises(LiteError):jobs.job_folder(bad)

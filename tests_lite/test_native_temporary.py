import json
from types import SimpleNamespace
import pytest
from colayout_lite.native_temporary import TemporaryCopies,track


def adapter(tmp_path,info=None,fail=False):
    calls=[]
    def call(name,*args):
        calls.append((name,args))
        if fail:raise RuntimeError('native unavailable')
        return (info or ['ready','counter-1']) if name=='ltTemporaryInfo' else ['deleted']
    return SimpleNamespace(state=tmp_path,native=SimpleNamespace(call=call)),calls


def test_only_owned_successful_scope_copies_are_deleted_backup_first(tmp_path):
    a,calls=adapter(tmp_path)
    track(a,'L','user','source')
    with TemporaryCopies(a) as scope:
        track(a,'L','private','source');track(a,'L','backup','private')
    assert [args[1] for name,args in calls if name=='ltTemporaryDelete']==['backup','private']
    assert all(args[-1]=='counter-1' for name,args in calls if name=='ltTemporaryDelete')
    assert json.loads(scope.path.read_text())['status']=='complete'


def test_unknown_or_failed_work_keeps_every_copy_and_receipt(tmp_path):
    a,calls=adapter(tmp_path)
    with pytest.raises(RuntimeError):
        with TemporaryCopies(a) as scope:
            track(a,'L','private','source');raise RuntimeError('outcome unknown')
    assert not calls and json.loads(scope.path.read_text())['status']=='retained_for_recovery'


@pytest.mark.parametrize('info',[['retained','window_open'],['retained','unsaved'],['retained','source_tag'],['absent']])
def test_native_refusals_and_already_absent_are_not_forced(tmp_path,info):
    a,calls=adapter(tmp_path,info)
    with TemporaryCopies(a):track(a,'L','private','source')
    assert not any(name=='ltTemporaryDelete' for name,args in calls)


def test_cleanup_error_does_not_change_successful_work_outcome(tmp_path):
    a,calls=adapter(tmp_path,fail=True)
    with TemporaryCopies(a) as scope:track(a,'L','private','source')
    assert json.loads(scope.path.read_text())['status']=='needs_attention'
    assert a._temporary_copies is None


def test_nested_tasks_do_not_delete_outer_task_while_it_is_active(tmp_path):
    a,calls=adapter(tmp_path)
    with TemporaryCopies(a):
        track(a,'L','outer','source')
        with TemporaryCopies(a):track(a,'L','inner','outer')
        assert a._temporary_copies.rows[0]['cell']=='outer'
        assert [args[1] for name,args in calls if name=='ltTemporaryDelete']==['inner']
    assert [args[1] for name,args in calls if name=='ltTemporaryDelete']==['inner','outer']

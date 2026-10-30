"""MPP enumeration order is not geometry; real part changes remain conflicts."""
from copy import deepcopy

import pytest

from colayout_lite.model import LiteError, MultipartPath, Object, Shape
from colayout_lite.editor import projected
from colayout_lite.sync_checks import canonical_object, guard_readback_semantic, require_unchanged, verify
from colayout_lite.transactions import TransactionJournal
from tests_lite.test_transactions import rig


def guard():
    return Object(uid='g',native_id='old-g',kind='mpp',mpp=MultipartPath(
        name='synthetic-guard',master=Shape(kind='path',lpp=('M1','drawing'),width=200,
            points=((0,0),(2000,0),(2000,2000),(0,2000),(0,0))),
        parts=[dict(name='part-cut',kind='rectangle',lpp=['cut','drawing'],width_um=.2,
                    space_um=.3,net_name='rail',terminal_name=None),
               dict(name='part-metal',kind='offsetPath',lpp=['M1','drawing'],width_um=.4,
                    net_name='rail',terminal_name=None)],
        member_counts={'rect/cut/drawing':12},native_definition='original ordered definition'))


def with_guard(rig):
    adapter,native,editor=rig
    g=guard()
    baseline=editor.w.baseline.model_copy(update={'objects':{'g':g}})
    editor.w=editor.w.model_copy(update={'baseline':baseline})
    native.current=baseline
    native.draft=editor.w
    return adapter,native,editor,g


def reordered(g):
    return g.model_copy(update={'native_id':'reopened-g',
        'mpp':g.mpp.model_copy(update={'parts':list(reversed(deepcopy(g.mpp.parts))),
                                     'native_definition':'reopened ordered definition'})})


def test_reopened_part_order_passes_precondition_without_changing_draft_or_hash(rig):
    adapter,native,editor,g=with_guard(rig)
    original=editor.w.model_dump_json(); payload=adapter._payload_hash(editor.w)
    native.current=native.current.model_copy(update={'session':'reopened','objects':{'g':reordered(g)}})
    require_unchanged(editor.w,native.current)
    assert editor.w.model_dump_json()==original
    assert adapter._payload_hash(editor.w)==payload
    # Serialization stays ordered: historical requests/receipts are not migrated.
    assert g.semantic()!=reordered(g).semantic()


def test_commit_readback_and_duplicate_accept_part_order_only(rig):
    adapter,native,editor,g=with_guard(rig)
    draft=editor.w
    expected_hash=adapter._payload_hash(draft)
    native.current=native.current.model_copy(update={'objects':{'g':reordered(g)}})
    transact=native.transact
    def apply(*args):
        receipt=transact(*args)
        objects=dict(native.current.objects);objects['g']=reordered(objects['g'])
        native.current=native.current.model_copy(update={'objects':objects})
        return receipt
    native.transact=apply
    result=adapter.commit(draft,request_id='order-only')
    assert result.state=='clean' and not result.operations
    assert set(result.baseline.objects)=={'g','r'}
    assert adapter.commit(draft,request_id='order-only').state=='clean'
    assert native.submissions==1
    assert TransactionJournal(adapter.state,'order-only').read()['hash']==expected_hash


@pytest.mark.parametrize('behavior',['rolled_back','lost_before_apply','lost_after_apply'])
def test_recovery_preserves_draft_and_request_identity_with_reordered_parts(rig,behavior):
    adapter,native,editor,g=with_guard(rig)
    native.current=native.current.model_copy(update={'objects':{'g':reordered(g)}})
    native.behavior=behavior
    original_hash=adapter._payload_hash(editor.w)
    if behavior=='rolled_back':
        result=adapter.commit(editor.w,request_id='recovery')
    else:
        with pytest.raises(TimeoutError):adapter.commit(editor.w,request_id='recovery')
        pending=adapter.load_workspace(editor.w.id)
        objects=dict(native.current.objects);objects['g']=reordered(objects['g'])
        native.current=native.current.model_copy(update={'objects':objects})
        assert adapter._payload_hash(pending)==original_hash
        result=adapter.reconcile(pending)
    assert native.submissions==1
    assert result.state==('clean' if behavior=='lost_after_apply' else 'editing')
    if result.state=='editing':assert result.operations==editor.w.operations
    assert TransactionJournal(adapter.state,'recovery').read()['hash']==original_hash


def test_recovery_does_not_accept_true_drift_with_reordered_parts(rig):
    adapter,native,editor,g=with_guard(rig)
    native.current=native.current.model_copy(update={'objects':{'g':reordered(g)}})
    native.behavior='lost_before_apply'
    with pytest.raises(TimeoutError):adapter.commit(editor.w,request_id='recovery')
    pending=adapter.load_workspace(editor.w.id)
    altered=reordered(g)
    parts=deepcopy(altered.mpp.parts);parts[0]['width_um']=.8
    altered=altered.model_copy(update={'mpp':altered.mpp.model_copy(update={'parts':parts})})
    native.current=native.current.model_copy(update={'objects':{'g':altered}})
    with pytest.raises(LiteError,match='INDETERMINATE_COMMIT'):adapter.reconcile(pending)
    assert adapter.load_workspace(editor.w.id).state=='indeterminate'
    assert native.submissions==1


@pytest.mark.parametrize('change',['width','net','terminal','layer','name','remove','duplicate','master','count'])
def test_real_guard_changes_are_rejected_before_write_and_at_readback(rig,change):
    adapter,native,editor,g=with_guard(rig)
    altered=reordered(g)
    parts=deepcopy(altered.mpp.parts)
    if change in ('width','net','terminal','layer','name'):
        key,value={'width':('width_um',.8),'net':('net_name','other-rail'),
                   'terminal':('terminal_name','pin'),'layer':('lpp',['other','drawing']),
                   'name':('name','different-part')}[change]
        parts[0][key]=value
    elif change=='remove':parts.pop()
    elif change=='duplicate':parts.append(deepcopy(parts[0]))
    body=altered.mpp.model_copy(update={'parts':parts})
    if change=='master':body=body.model_copy(update={'master':body.master.model_copy(update={'width':400})})
    if change=='count':body=body.model_copy(update={'member_counts':{'rect/cut/drawing':13}})
    altered=altered.model_copy(update={'mpp':body})
    native.current=native.current.model_copy(update={'objects':{'g':altered}})
    with pytest.raises(LiteError,match='SOURCE_CONFLICT'):
        adapter.commit(editor.w,request_id='real-change')
    assert native.submissions==0 and not (adapter.state/'transactions').exists()
    empty=editor.w.model_copy(update={'operations':()})
    with pytest.raises(LiteError,match='READBACK_OBJECT_MISMATCH'):
        verify(empty,native.current)


def test_net_enrichment_matches_part_identity_after_reordering():
    g=guard()
    parts=deepcopy(g.mpp.parts);parts[1]['net_name']=None
    expected=g.model_copy(update={'mpp':g.mpp.model_copy(update={'parts':parts})})
    actual=reordered(g).model_copy(update={'observed_net':'rail'})
    before=expected.model_dump_json()
    assert guard_readback_semantic(expected,actual,canonical_object(expected))==canonical_object(actual)
    assert expected.model_dump_json()==before


@pytest.mark.parametrize('pin_net',['rail','conflicting-rail',None])
def test_existing_guard_enrichment_still_requires_physical_net_proof(rig,monkeypatch,pin_net):
    adapter,native,editor,g=with_guard(rig)
    parts=deepcopy(g.mpp.parts);parts[1]['net_name']=None
    expected=g.model_copy(update={'mpp':g.mpp.model_copy(update={'parts':parts})})
    editor.w=editor.w.model_copy(update={'baseline':editor.w.baseline.model_copy(update={'objects':{'g':expected}})})
    objects=projected(editor.w);objects['g']=reordered(g).model_copy(update={'observed_net':'rail'})
    actual=native.current.model_copy(update={'objects':objects})
    graph={'warnings':[], 'nodes':[
        {'owner_uid':'g','layer':'M1','component_id':'connected'},
        {'owner_uid':'r','layer':'M1','component_id':'connected'}],
        'pins':[{'id':'p','net':pin_net,'local':False,'owner':'device'}],
        'component_pins':{'connected':['p']}}
    monkeypatch.setattr('colayout_lite.region_analysis.scope_graph',lambda *a,**k:graph)
    if pin_net=='rail':assert verify(editor.w,actual,profile=editor.profile)
    else:
        with pytest.raises(LiteError,match='READBACK_OBJECT_MISMATCH'):
            verify(editor.w,actual,profile=editor.profile)
    # The readback-only exception never permits a changed source baseline.
    with pytest.raises(LiteError,match='SOURCE_CONFLICT'):require_unchanged(editor.w,actual)


@pytest.mark.parametrize('change',['assigned_net','terminal','geometry','ambiguous_duplicate'])
def test_enrichment_cannot_hide_other_part_changes(change):
    g=guard()
    parts=deepcopy(g.mpp.parts);parts[1]['net_name']=None
    expected=g.model_copy(update={'mpp':g.mpp.model_copy(update={'parts':parts})})
    actual=reordered(g).model_copy(update={'observed_net':'rail'})
    ap=deepcopy(actual.mpp.parts)
    if change=='assigned_net':ap[1]['net_name']='other-rail'
    elif change=='terminal':ap[0]['terminal_name']='pin'
    elif change=='geometry':ap[0]['width_um']=.8
    else:
        expected=expected.model_copy(update={'mpp':expected.mpp.model_copy(update={'parts':[parts[1],deepcopy(parts[1])]})})
        ap=[deepcopy(ap[0]),deepcopy(ap[0])]
    actual=actual.model_copy(update={'mpp':actual.mpp.model_copy(update={'parts':ap})})
    assert guard_readback_semantic(expected,actual,canonical_object(expected))!=canonical_object(actual)

"""Large native requests remain one exact transaction without list evaluation."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pytest
from colayout_lite.sexpr import parse_native
from colayout_lite.transport import skill, skill_literal
from tests_lite.test_transport_boundary import result, transport


def test_literal_keeps_nested_values_and_inline_encoder_unchanged():
    data={'text':'name "quoted"\\path\nlist(unsafe)', 'coords':(-12,'3.25'),
          'empty':[], 'none':None, 'nested':{'cell':'测试单元'}}
    expected=[['text',data['text']],['coords',['-12','3.25']],['empty',[]],
              ['none',None],['nested',[['cell','测试单元']]]]
    assert parse_native(skill_literal(data))==expected
    assert skill({'x':[1,'2',None]})=='list(list("x" list(1 "2" nil)))'
    assert skill_literal(123)=='123' and skill_literal(None)=='nil'
    assert skill_literal('name')=='"name"'


def test_large_request_load_is_one_quoted_payload_and_one_transaction(tmp_path):
    operations=[{'action':'update','uid':f'wire-{i}',
                 'shape':{'kind':'rect','lpp':['M1','drawing'],
                          'bbox':[[str(i),'0'],[str(i+1),'10']],
                          'net_intent':'VDD'}} for i in range(4096)]
    payload={'request_id':'same-request','hash':'same-hash','counter':'123',
             'backup':'same-backup','operations':operations,'fail_after':None}
    before=deepcopy(payload);loaded=[];calls=[]
    def load(path):
        text=Path(path).read_text(encoding='utf8')
        head,body=text.split('=quote(',1)
        assert head.startswith('ltRequests[') and body.endswith(')\n')
        parsed=dict(parse_native(body[:-2]))
        assert parsed['request_id']=='same-request' and parsed['hash']=='same-hash'
        assert parsed['counter']=='123' and parsed['backup']=='same-backup'
        actual=parsed['operations']
        assert len(actual)==4096
        for i,row in enumerate(actual):
            op=dict(row);shape=dict(op['shape'])
            assert op['uid']==f'wire-{i}' and op['action']=='update'
            assert shape==operations[i]['shape']
        assert parsed['fail_after'] is None
        loaded.append(path)
        return result()
    def execute(expression,**kwargs):
        calls.append(expression)
        return result()
    native=transport(tmp_path,SimpleNamespace(load_il=load,execute_skill=execute))
    native.transact('L','C',payload)
    assert payload==before and len(loaded)==1
    assert len(calls)==2 and calls[0].startswith('ltRunRequest("L" "C" ')
    assert calls[1]=='ltReceiptRead("same-request")'
    assert len(list((tmp_path/'requests').glob('*.result.json')))==1


@pytest.mark.parametrize('value',[True,False,1.25,float('nan'),object()])
def test_invalid_literal_data_cannot_reach_native_loader(tmp_path,value):
    loaded=[]
    native=transport(tmp_path,SimpleNamespace(load_il=lambda path:loaded.append(path)))
    with pytest.raises(TypeError):
        native._upload_request('request',{'nested':[value]})
    assert not loaded and not list((tmp_path/'requests').glob('*.il'))


def test_literal_strings_cannot_escape_the_payload(tmp_path):
    text='") ltRunRequest("other" "cell" "token") ;\\\n'
    native=transport(tmp_path,SimpleNamespace(load_il=lambda _:result()))
    native._upload_request('slot',{'text':text})
    encoded=(tmp_path/'requests/slot.il').read_text(encoding='utf8').split('=quote(',1)[1][:-2]
    assert parse_native(encoded)==[['text',text]]

import pytest
from colayout_lite.codec import check_native_masters
from colayout_lite.model import LiteError


def test_native_failed_pcell_is_not_accepted_as_valid_device_geometry():
    failure=['id','label',None,['marker','error'],None,
             [['errorDesc','string',['string','native PDK evaluation failed']]],
             [['text','pcellEvalFailed']]]
    graph=['root',[['master','foreign_pdk','mos','layout',1000,None,[failure]]]]
    with pytest.raises(LiteError) as exc:check_native_masters(graph)
    assert exc.value.code=='PCELL_EVALUATION_FAILED'
    assert exc.value.details['failures'][0]['master']==['foreign_pdk','mos','layout']
    failure[6]=[['text','ordinary label']]
    check_native_masters(graph)

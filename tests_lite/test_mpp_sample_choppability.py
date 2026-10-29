"""Mixed sample flags must survive both ring and open-path protocol payloads."""
# ruff: noqa: F811
import pytest
from colayout_lite.mpp_recipe import GuardPart,GuardRecipe
from tests_lite.test_kernel import profile


@pytest.mark.parametrize('open_path',[False,True])
def test_sample_subpath_flags_are_not_coerced_to_make_a_choppable_master(profile,open_path):
    parts=(GuardPart(kind='enclosurePath',lpp=('wire_a','drawing'),enclosure=-100,choppable=False),
           GuardPart(kind='rectangle',lpp=('wire_a','drawing'),width=100,length=100,space=100,choppable=True))
    recipe=GuardRecipe(id='mixed',name='Native sample',library='Sample',kind='single',
        technology_fingerprint=profile.native_fingerprint,master_lpp=('wire_a','drawing'),width=400,
        parts=parts,open_parts=parts,min_side_dbu=1600,min_length_dbu=1600)
    original=recipe.model_dump()
    payload=recipe.payload(((0,0),(5000,5000)),profile.grid,net_intent='SUPPLY',
                           points=[(0,0),(5000,0),(5000,5000)] if open_path else None)
    assert [p['choppable'] for p in payload['parts']]==['no','yes']
    assert payload['parts'][0]['enclosure']=='-100'
    assert payload['parts'][1]['space']=='100'
    assert recipe.model_dump()==original

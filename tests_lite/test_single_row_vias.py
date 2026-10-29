import pytest
from colayout_lite.layout_helpers.service import execute
from colayout_lite.model import LiteError
from tests_lite.test_auto_vias import tech,landing,via_rules

def test_single_row_maximum_and_idempotent_reuse(tech):
    e=landing(tech);rules=via_rules(tech)
    args={'bounds_um':[0,0,1,.2],'start_layer':'M1','end_layer':'M2','net_intent':'N','array_direction':'horizontal'}
    result=execute(e,'create_auto_vias',args,rules=rules)
    assert result['total_cuts']==12 and result['levels'][0]['maximal_on_grid']
    shape=e.object(result['created_uids'][0]).shape
    assert tech.effective_via(shape)['cutRows']==1
    before=e.w;again=execute(e,'create_auto_vias',args,rules=rules)
    assert e.w is before and again['reused_uids']==result['created_uids']

def test_single_column_never_silently_becomes_row_or_exceeds_budget(tech):
    e=landing(tech);result=execute(e,'create_auto_vias',{'bounds_um':[0,0,1,.2],'start_layer':'M1','end_layer':'M2','net_intent':'N','array_direction':'vertical'},rules=via_rules(tech))
    assert result['total_cuts']==2 and tech.effective_via(e.object(result['created_uids'][0]).shape)['cutColumns']==1
    e=landing(tech);before=e.w
    with pytest.raises(LiteError):execute(e,'create_auto_vias',{'bounds_um':[0,0,1,.06],'start_layer':'M1','end_layer':'M2','net_intent':'N','array_direction':'horizontal'},rules=via_rules(tech))
    assert e.w is before

def test_budget_exhaustion_is_failure_not_smaller_success(tech,monkeypatch):
    import colayout_lite.layout_helpers.auto_vias as module
    e=landing(tech);before=e.w
    monkeypatch.setattr(module,'checked_candidate',lambda *a,**kw:(False,{'reason':'obstacle'}))
    with pytest.raises(LiteError,match='SINGLE_ROW_SEARCH_LIMIT'):
        execute(e,'create_auto_vias',{'bounds_um':[0,0,1,.2],'start_layer':'M1','end_layer':'M2','net_intent':'N','array_direction':'horizontal'},rules=via_rules(tech))
    assert e.w is before


def test_obstacle_rejects_larger_rows_before_accepting_maximum(tech,monkeypatch):
    import colayout_lite.layout_helpers.auto_vias as module
    from colayout_lite.layout_helpers.via_candidates import footprints
    from shapely.ops import unary_union
    e=landing(tech);seen=[]
    def blocked(access,geometry):
        width=geometry['V1'].bounds[2]-geometry['V1'].bounds[0]
        count=round((width-40)/80)+1;seen.append(count)
        return [{'reason':'other_net_contact'}] if count>10 else []
    monkeypatch.setattr(module.Access,'conflicts',blocked)
    result=execute(e,'create_auto_vias',{'bounds_um':[0,0,1,.08],'start_layer':'M1','end_layer':'M2','net_intent':'N','array_direction':'horizontal'},rules=via_rules(tech))
    assert result['total_cuts']==10 and max(seen)==12 and 11 in seen
    assert result['levels'][0]['maximal_on_grid'] and result['search']['max_arrays_per_level']==1


def test_custom_existing_pitch_is_not_reported_as_default_optimum(tech):
    from colayout_lite.model import Shape
    from colayout_lite.layout_helpers.via_candidates import footprints
    from shapely.ops import unary_union
    e=landing(tech)
    uid=e.create(Shape(kind='stdVia',via_definition='V12',origin=(500,100),
        via_parameters={'cutRows':1,'cutColumns':10,'cutSpacing':(44,40)},net_intent='N'))
    before=e.w;b=unary_union(list(footprints(e.object(uid).shape,tech).values())).bounds
    with pytest.raises(LiteError,match='SINGLE_ROW_EXISTING_ARRAY'):
        execute(e,'create_auto_vias',{'bounds_um':[v/1000 for v in b],'start_layer':'M1','end_layer':'M2','net_intent':'N','array_direction':'horizontal'},rules=via_rules(tech))
    assert e.w is before

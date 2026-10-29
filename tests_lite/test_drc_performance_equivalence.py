"""Geometry/marker equivalence for DRC preparation and report reuse."""
# ruff: noqa: F811
import json
from copy import deepcopy
import pytest
from shapely.geometry import Polygon,box,LineString
from shapely.ops import unary_union
from shapely import affinity,make_valid
from colayout_lite.geometry_paths import figure_path
from colayout_lite.materials import polygon_from_figure,apply_delta,associate,AssociationIndex,Physical
from colayout_lite.drc import local,scope,job_storage
from colayout_lite.drc.rdb import parse
from colayout_lite.drc.models import Result
from tests_lite.test_drc import tech,workspace,rect,profile,rule,ROI


def qt_geometry(figure):
    geometry=Polygon()
    for ring in figure_path(figure).simplified().toSubpathPolygons():
        points=[(p.x(),-p.y()) for p in ring]
        if len(points)>=3:
            polygon=Polygon(points)
            if not polygon.is_valid:raise ValueError('Invalid physical display polygon')
            geometry=geometry.symmetric_difference(polygon)
    return geometry


@pytest.mark.parametrize('bounds',[
    ((0,0),(80,100)),((-90,-80),(50,60)),((2,3),(4,5)),
    ((-1000000000,-900000000),(900000000,1000000000)),
    ((.1,-.2),(.3,.4)),((0,0),(1e-13,1)),((0,0),(0,10)),
    ((0,0),(10,0)),((10,20),(0,0)),((10,0),(0,20)),
])
def test_rectangle_fast_path_preserves_qt_contour(bounds):
    f={'kind':'rect','bbox':bounds,'geometry':{}};before=deepcopy(f)
    actual=polygon_from_figure(f);expected=qt_geometry(f)
    assert actual.equals_exact(expected,0) and actual.is_valid==expected.is_valid
    assert f==before


def test_identity_delta_reuses_immutable_geometry_and_moved_shape_still_transforms():
    g=Polygon([(0,0),(100,0),(100,100),(0,100)],holes=[[(20,20),(30,20),(30,30),(20,30)]])
    before=g.wkb
    assert apply_delta(g,(1,0,0,1,0,0)) is g
    assert apply_delta(g,(0,-1,1,0,200,300)).equals_exact(affinity.affine_transform(g,[0,-1,1,0,200,300]),0)
    assert g.wkb==before


def test_only_enabled_rule_layers_are_unioned_and_pin_context_is_not_lost(tech,monkeypatch):
    w=workspace(tech,[rect(0,0,100,100),rect(500,0,700,100,layer='B'),rect(900,0,910,10,layer='W')])
    # A pin context extends the first conductor. It must participate in the
    # area check, while the unchanged B layer must not be unioned twice.
    monkeypatch.setattr(scope,'pin_context',lambda *a:[Physical('0','A',box(100,0,200,100))])
    union=local.unary_union;calls=[]
    def counted(rows):
        rows=list(rows);calls.append(tuple(g.bounds for g in rows));return union(rows)
    monkeypatch.setattr(local,'unary_union',counted)
    cfg=profile(tech,rule('area',.004,'A'),rule('area',.004,'B'),rule('area',1,'W',enabled=False))
    result=local.run(w,tech,cfg,ROI)
    assert not result.markers and result.coverage['complete_for_configured_subset']
    assert result.metrics['physical_primitives']==4  # W is still available to patch checks.
    assert len(calls)==3 and len(calls[-1])==2
    assert not any((900.,0.,910.,10.) in rows for rows in calls)


@pytest.mark.parametrize('limit',[1,5,32])
def test_spatial_association_keeps_candidates_order_metadata_and_limits(tech,limit):
    w=workspace(tech,[rect(i*10,0,i*10+20,20) for i in range(40)])
    rows=[Physical(uid,'A',box(*obj.bbox[0],*obj.bbox[1]),True,(uid,'path'))
          for uid,obj in w.baseline.objects.items()]
    rows+=rows[:8]  # repeated internal figures must not duplicate an owner.
    index=AssociationIndex(rows);g=box(0,0,500,30);near=g.buffer(.001)
    for source in (rows,index):
        original=[]
        for row in source.query(near) if isinstance(source,AssociationIndex) else source:
            if any(o['uid']==row.owner for o in original) or not row.geometry.intersects(near):continue
            obj=w.baseline.objects[row.owner]
            original.append({'uid':row.owner,'name':obj.attributes.get('name'),'kind':obj.kind,
                'inside_instance':row.inside_instance,'inside_mpp':bool(obj.mpp),'read_only_reason':obj.read_only_reason,
                'group_uid':obj.group_uid,'occurrence_path':row.path})
            if len(original)>=limit:break
        assert associate(source,w.baseline.objects,g,limit=limit)==tuple(original)


def test_rdb_spatial_witnesses_align_after_roi_and_limits_and_keep_native_walks():
    text=('TOP 1000\nRULE\n3 3 1 stamp\nmessage\n'
          'p 1 4\n20000 20000\n21000 20000\n21000 21000\n20000 21000\n'
          'p 2 10\n0 0\n1000 0\n1000 1000\n900 1000\n900 100\n100 100\n100 900\n900 900\n900 1000\n0 1000\n'
          'e 3 2\n0 0 100 100\n0 100 100 0\n')
    for limit in (0,1,2,10):
        witnesses=[];markers,counts=parse(text,ROI,2000,max_markers=limit,geometries=witnesses)
        reference,reference_counts=parse(text,ROI,2000,max_markers=limit)
        assert markers==reference and counts==reference_counts and len(markers)==len(witnesses)
        assert counts['total_context_markers']==3
        for marker,g in zip(markers,witnesses,strict=True):
            old=Polygon(marker.points) if marker.kind=='polygon' else unary_union([LineString([(a,b),(c,d)]) for a,b,c,d in marker.edges])
            assert make_valid(g).buffer(1).equals_exact(make_valid(old).buffer(1),0)
        if markers:assert len(markers[0].points)==10
    with pytest.raises(Exception):
        parse(text+'BROKEN\n1 1 0\np 1 3\n0 0\n',ROI,2000,max_markers=0,geometries=[])


def test_compact_result_storage_preserves_pretty_legacy_reports(tech,tmp_path):
    result=local.run(workspace(tech,[rect(0,0,100,100)]),tech,profile(tech,rule('width')),ROI)
    old=tmp_path/'old.json';old.write_text(json.dumps(result.model_dump(mode='json'),ensure_ascii=False,indent=2),encoding='utf8')
    new=tmp_path/'new.json';job_storage.write_result(new,result)
    assert job_storage.read_result(new)==job_storage.read_result(old)
    assert job_storage.read_result(new).model_dump(mode='json')==result.model_dump(mode='json')
    assert json.loads(new.read_text(encoding='utf8'))==json.loads(old.read_text(encoding='utf8'))
    assert new.stat().st_size<old.stat().st_size

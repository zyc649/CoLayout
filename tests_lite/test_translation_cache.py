"""Certified translation reuse must agree with a fresh vector compilation."""
import pytest
from PySide6.QtCore import Qt,QPointF,QRectF
from PySide6.QtGui import QBrush,QColor,QFont,QImage,QPainter,QPen,QTransform
from PySide6.QtWidgets import QApplication,QGraphicsItemGroup,QGraphicsScene

from colayout_lite.preview import PreviewView
from colayout_lite.render import NativeFigureItem,PreviewRectItem,PreviewTextItem,make_texture
from colayout_lite.vector_preview import VectorCache


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def figures(scene,transform,*,pattern=False):
    group=QGraphicsItemGroup();scene.addItem(group);group.setOpacity(.8)
    rect=PreviewRectItem(QRectF(12,15,31,18));rect.setPen(QPen(QColor('#aec8dd'),1))
    rect.setBrush(QBrush(QColor('#315574')));group.addToGroup(rect)
    text=PreviewTextItem('PIN G');text.setFont(QFont('Segoe UI',9));text.setBrush(QBrush(QColor('#dec57a')))
    text.setPos(10,40);group.addToGroup(text)
    style={'fill_style':'stipple' if pattern else 'solid','fill_rgb':[90,170,135],
           'outline_rgb':[120,205,165],'line_width':1,'line_pattern':[1],
           'stipple':[[1,0,0,1],[0,1,1,0],[0,1,1,0],[1,0,0,1]],'is_cut':False,
           'priority':10,'lpp':('wire_a','drawing')}
    figure={'id':'poly','owner_id':'a','style':'wire_a/drawing','kind':'polygon',
            'bbox':((15,-12),(55,10)),
            'geometry':{'points':((15,10),(55,10),(44,-12),(24,-8))}}
    polygon=NativeFigureItem(figure,style,texture=make_texture(style));group.addToGroup(polygon)
    group.setTransform(transform)
    return group,[rect,text,polygon]


def pixels(cache):
    image=QImage(800,550,QImage.Format.Format_ARGB32_Premultiplied);image.fill(QColor('#17191c'))
    painter=QPainter(image);tr=QTransform(1.7,0,0,1.7,300,270);painter.setTransform(tr)
    inverse,_=tr.inverted()
    cache.paint(painter,inverse.mapRect(QRectF(0,0,800,550)),1.7,inverse)
    painter.end();return bytes(image.constBits())


def cache_for(rows):
    cache=VectorCache(QRectF(-500,-500,1000,1000));cache.update(rows,rows.__getitem__)
    return cache


@pytest.mark.parametrize('orientation',[(1,0,0,1),(-1,0,0,1),(0,1,-1,0),(0,1,1,0)])
@pytest.mark.parametrize('delta',[(137,-92),(-166,131)])
@pytest.mark.parametrize('pattern',[False,True])
def test_translation_matches_fresh_compile_for_text_polygon_mirror_and_tiles(app,orientation,delta,pattern,monkeypatch):
    scene=QGraphicsScene();group,items=figures(scene,QTransform(*orientation,17,-21),pattern=pattern)
    other,stationary=figures(scene,QTransform.fromTranslate(-117,37),pattern=pattern)
    rows={'a':items,'b':stationary};cache=cache_for(rows)
    original_keys=set(cache.owners['a']);original_pixels=pixels(cache)
    untouched={key:batch for key,batch in cache.batches.items() if 'a' not in cache.records[key]}
    _,shared=cache.split({'a'})
    shared_pixels=pixels(shared)
    def forbidden(*_):raise AssertionError('Translation reread Qt graphics')
    monkeypatch.setattr(cache,'_record',forbidden)
    assert cache.translate_owners({'a':delta,'missing':delta})=={'a'}
    group.setPos(QPointF(*delta))
    fresh=cache_for(rows)
    assert cache.owners==fresh.owners and set(cache.batches)==set(fresh.batches)
    assert cache.owners['a']!=original_keys
    assert pixels(cache)==pixels(fresh) and pixels(cache)!=original_pixels
    assert pixels(shared)==shared_pixels  # Reuse never mutates shared paths/transforms.
    for key,batch in untouched.items():
        if key not in cache.owners['a']:assert cache.batches[key] is batch
    assert cache.translate_owners({'a':(-delta[0],-delta[1])})=={'a'}
    group.setPos(QPointF())
    assert pixels(cache)==original_pixels and pixels(cache)==pixels(cache_for(rows))


def test_translation_mixed_batches_and_invalid_or_unknown_owners_are_safe(app):
    scene=QGraphicsScene();a,aa=figures(scene,QTransform());b,bb=figures(scene,QTransform())
    rows={'a':aa,'b':bb};cache=cache_for(rows)
    assert any(set(owners)=={'a','b'} for owners in cache.records.values())
    before=pixels(cache)
    assert cache.translate_owners({'missing':(1,2),'a':(float('nan'),1),'b':(1,)})==set()
    assert pixels(cache)==before
    assert cache.translate_owners({'a':(128,-16),'b':(-96,32)})=={'a','b'}
    a.setPos(128,-16);b.setPos(-96,32)
    assert pixels(cache)==pixels(cache_for(rows))


@pytest.fixture
def preview(app):
    scene=QGraphicsScene();group,items=figures(scene,QTransform())
    rows={'a':items};view=PreviewView(scene);view.owner_ids=lambda:rows.keys();view.owner_items=rows.__getitem__
    view.configure_preview(8000);view.prepare_preview()
    yield view,group,rows
    view._build_timer.stop();view.close();view.deleteLater();app.processEvents()


def test_clean_preview_reuses_only_certified_owner_and_invalidates_scope_snapshots(preview,monkeypatch):
    view,group,rows=preview;cache=view._vectors;revision=view._revision
    view._scope_cache['inactive']=(cache,cache.bytes)
    group.setPos(130,20)
    def forbidden(*_):raise AssertionError('Satisfied translation was recompiled')
    monkeypatch.setattr(cache,'_record',forbidden)
    view.invalidate_preview({'a'},translations={'a':(130,20),'not_requested':(2,3)})
    assert view._vectors is cache and not view._dirty and not view._scope_cache
    assert view._revision==revision+1 and view.preview_stats['translated_owners']==1
    view.prepare_preview()
    assert pixels(cache)==pixels(cache_for(rows))


@pytest.mark.parametrize('blocked',['dirty','drag','disabled','small'])
def test_uncertain_preview_falls_back_instead_of_reusing_a_stale_cache(preview,blocked,monkeypatch):
    view,group,rows=preview;cache=view._vectors;original=pixels(cache)
    if blocked=='dirty':view._dirty={'earlier_edit'}
    elif blocked=='drag':view.drag_visual=object()
    elif blocked=='disabled':view.preview_enabled=False
    elif blocked=='small':view.large_scene=False
    def forbidden(*_):raise AssertionError('Uncertain display state was reused')
    monkeypatch.setattr(cache,'translate_owners',forbidden)
    view.invalidate_preview({'a'},translations={'a':(130,20)})
    assert 'a' in view._dirty and pixels(cache)==original


def test_unknown_owner_reloads_and_full_invalidation_ignores_translation(preview):
    view,group,rows=preview;cache=view._vectors
    added,items=figures(view.scene(),QTransform.fromTranslate(150,30));rows['new']=items
    view.invalidate_preview({'new'},translations={'new':(150,30)})
    assert view._dirty=={'new'}
    view.prepare_preview();assert pixels(view._vectors)==pixels(cache_for(rows))
    view.invalidate_preview(translations={'a':(3,4)})
    assert view._vectors is None
    view.prepare_preview();assert view._vectors is not cache
    assert pixels(view._vectors)==pixels(cache_for(rows))

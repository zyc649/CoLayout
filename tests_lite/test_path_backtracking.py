import pytest
from colayout_lite.actions import Actions
from colayout_lite.editor import Editor
from colayout_lite.model import LiteError, Shape
from tests_lite.test_agent_connectivity import tech, workspace


@pytest.mark.parametrize(
    'points,code',
    [
        ([[174.751, -40.423], [158.521, -40.423], [174.061, -40.423]], 'PATH_BACKTRACK'),
        ([[0, 0], [1, 1], [0.5, 0.5]], 'PATH_BACKTRACK'),
        ([[0, 0], [0, 0], [1, 0]], 'INVALID_PATH_SEGMENT'),
    ],
)
def test_create_and_edit_reject_unstable_path_atomically(tech, points, code):
    p = tech.model_copy(update={'grid': 1})
    e = Editor(workspace(p), p)
    uid = e.create(Shape(kind='path', lpp=('M1', 'drawing'), points=((0, 0), (1000, 0)), width=200))
    before = e.w
    for action, target in [('create_path45', None), ('edit_path45', uid)]:
        with pytest.raises(LiteError) as caught:
            Actions(e).execute(
                action, {'lpp': ['M1', 'drawing'], 'points': points, 'width': 0.2}, uid=target
            )
        assert caught.value.code == code
        assert (
            caught.value.details['point_indices'] and caught.value.details['edit_applied'] is False
        )
        assert e.w is before


def test_native_loading_and_deletion_of_legacy_path_remain_possible(tech):
    shape = Shape(
        kind='path', lpp=('M1', 'drawing'), points=((0, 0), (1000, 0), (500, 0)), width=200
    )
    e = Editor(workspace(tech, [shape]), tech)
    e.delete('0')
    assert e.w.operations[0].action == 'delete'
    with pytest.raises(LiteError, match='PATH_BACKTRACK'):
        Editor(workspace(tech), tech).create(shape)


@pytest.mark.parametrize(
    'points', [((0, 0), (1000, 0), (2000, 0)), ((0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0))]
)
def test_forward_collinear_and_closed_orthogonal_path_remain_valid(tech, points):
    e = Editor(workspace(tech), tech)
    assert e.create(Shape(kind='path', lpp=('M1', 'drawing'), points=points, width=200))

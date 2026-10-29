import pytest
from colayout_lite.model import Object,Shape,LiteError
from colayout_lite.permissions import apply_profile_permissions
from colayout_lite.actions import availability
from colayout_lite.adapter import require_unchanged
from tests_lite.test_kernel import editor,profile


def test_nonwritable_layer_permissions_match_editor_policy(editor,profile):
    obj=Object(uid='implant',native_id='n',kind='rect',shape=Shape(kind='rect',lpp=('implant','drawing'),bbox=((0,0),(2000,2000))),deletion_allowed=True)
    snapshot=editor.w.baseline.model_copy(update={'objects':{'implant':obj}})
    restricted=apply_profile_permissions(snapshot,profile)
    o=restricted.objects['implant']
    assert o.read_only_reason=='layer_not_writable'
    assert not availability('move',o)[0] and not availability('edit_rect',o)[0]
    assert availability('delete',o)[0]
    # Changing declared policy can re-enable the layer, not native restrictions.
    expanded=profile.model_copy(update={'writable_lpps':profile.writable_lpps+(('implant','drawing'),)})
    assert apply_profile_permissions(restricted,expanded).objects['implant'].read_only_reason is None


def test_profile_never_unprotects_parent_child_or_pin(editor,profile):
    objects={reason:Object(uid=reason,native_id=reason,kind='rect',shape=Shape(kind='rect',lpp=('wire_a','drawing'),bbox=((0,0),(2000,2000))),read_only_reason=reason)
             for reason in ('pin_geometry','native_parent_child_requires_adapter','protected_group')}
    s=editor.w.baseline.model_copy(update={'objects':objects})
    assert apply_profile_permissions(s,profile).objects==objects


def test_parent_child_relation_changes_are_not_ignored(editor):
    obj=Object(uid='parent',native_id='n',kind='stdVia',read_only_reason='native_parent_child_requires_adapter',
        attributes={'native_relationships':{'parent':None,'children':['child1']}})
    base=editor.w.baseline.model_copy(update={'objects':{'parent':obj}})
    editor.w=editor.w.model_copy(update={'baseline':base})
    changed=obj.model_copy(update={'attributes':{'native_relationships':{'parent':None,'children':['child2']}}})
    with pytest.raises(LiteError,match='SOURCE_CONFLICT'):require_unchanged(editor.w,base.model_copy(update={'objects':{'parent':changed}}))

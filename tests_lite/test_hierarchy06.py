import copy
from pathlib import Path
import pytest
from colayout_lite.hierarchy import child_count,effective_mode,same_dependencies,merge_fragment
from colayout_lite.model import Workspace,Snapshot,Object,Placement,Shape,LiteError
from colayout_lite.scene import figures_by_owner
from colayout_lite.editor import Editor
from colayout_lite.adapter import require_unchanged
from tests_lite.test_kernel import profile,editor

def test_heuristic_uses_child_instances_not_vias_or_cell_names():
    node=['m','PDK','whatever','layout','1000',None,[],[],[],[],[['v','vm','stdVia',[0,0],'R0','1']]]
    assert child_count(node)==0 and effective_mode(node)=='full'
    node[10].append(['i','im','inst',[0,0],'R0','1'])
    assert effective_mode(node)=='box_pins' and effective_mode(node,'full')=='full'
    assert effective_mode(node,'box_pins')=='box_pins'

def test_display_preferences_preserve_physical_undo_and_serialize(editor,tmp_path):
    editor.place('inst',(2000,0));ops=editor.w.operations
    editor.set_instance_display('inst','box_pins',{'nodes':{}})
    assert editor.w.operations==ops
    editor.undo();assert not editor.w.operations and editor.w.instance_display['inst']=='box_pins'
    editor.redo();assert editor.w.operations==ops
    p=tmp_path/'w.json';editor.w.save(p)
    assert Workspace.model_validate_json(p.read_text()).instance_display=={'inst':'box_pins'}

def test_hidden_master_versions_cannot_silently_change(editor):
    deps=[['session:m','L','M','layout','7']]
    a=editor.w.baseline.model_copy(update={'dependency_scheme':'native_versions','protected_dependencies':deps,'dependency_digest':'a'})
    b=a.model_copy(update={'protected_dependencies':[['session:m','L','M','layout','8']],'dependency_digest':'b'})
    assert not same_dependencies(a,b)
    with pytest.raises(LiteError):require_unchanged(editor.w.model_copy(update={'baseline':a}),b)
    assert same_dependencies(a,a.model_copy(update={'display':{'nodes':{}}}))

def test_instance_display_is_per_occurrence_with_actual_pin_geometry(editor):
    # Two instances of a user module, itself containing one leaf child.
    style=['M/drawing',[['M','drawing'],'M','10',True,'metal',['display','M','blank','solid','red','red','solid'],['display','red','255','0','0',None],['display','red','255','0','0',None],None,['display','solid','1','3',['1']]]]
    pin=['pin','rect',[['0','0'],['200','200']],['M','drawing'],None,[],None]
    pinfig=['pinfig','pin',False,None,'rect','M/drawing',[['0','0'],['200','200']],None]
    detail=['inside','inside',False,None,'rect','M/drawing',[['300','300'],['400','400']],None]
    leaf=['leaf','L','device','layout','1000',[[0,0],[1000,1000]],[],[],[],[detail],[]]
    module=['module','L','block','layout','1000',[[0,0],[1000,1000]],[],[],[['P','input','P',[[pin]]]],[pinfig],[['child','leaf','inst',['0','0'],'R0','1']]]
    root=['root','L','top','layout','1000',[[0,0],[4000,1000]],[],[],[],[],[['a','module','inst',['0','0'],'R0','1'],['b','module','inst',['3000','0'],'R0','1']]]
    objects={u:Object(uid=u,native_id=u,kind='inst',placement=Placement(origin=(x,0)),attributes={'name':u,'master_key':'module'}) for u,x in [('a',0),('b',3000)]}
    snap=editor.w.baseline.model_copy(update={'objects':objects,'display':{'root':'root','nodes':{'root':root,'module':module,'leaf':leaf},'styles':[style]}})
    figures,_=figures_by_owner(snap,modes={'a':'full'})
    assert any(f['id']=='inside' for f in figures['a'])
    assert not any(f['id']=='inside' for f in figures['b'])
    displayed_pin=next(f for f in figures['b'] if f.get('pin_name')=='P')
    assert displayed_pin['bbox']==((3000.0,0.0),(3200.0,200.0))
    assert any(f.get('geometry',{}).get('text')=='P' for f in figures['b'])

"""UID convenience aliases must not silently become network query targets."""
import importlib.util
import sys
from contextlib import nullcontext
from pathlib import Path
import pytest


@pytest.fixture
def cli(monkeypatch):
    kit=Path(__file__).resolve().parents[1]/'templates/layout-agent'
    monkeypatch.syspath_prepend(str(kit))
    spec=importlib.util.spec_from_file_location('customer_cli_uid_test',kit/'api.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'exclusive_cli',nullcontext)
    requests=[]
    def call(tool,args,**kwargs):
        requests.append((tool,args));return {'ok':True,'result':{}}
    monkeypatch.setattr(module,'call',call)
    return module,requests


@pytest.mark.parametrize('kind',['layout','reference'])
def test_repeated_uid_alias_queries_all_objects(cli,monkeypatch,kind):
    module,requests=cli
    monkeypatch.setattr(sys,'argv',['api.py','inspect',kind,'--uid','A','--uid','B','--uid','A'])
    module.main();assert requests==[('inspect_region',{'kind':kind,'uids':['A','B']})]


def test_single_net_uid_keeps_target_semantics(cli,monkeypatch):
    module,requests=cli
    monkeypatch.setattr(sys,'argv',['api.py','inspect','net','--uid','A'])
    module.main();assert requests==[('inspect_region',{'kind':'net','target':{'kind':'object','id':'A'}})]


def test_multiple_net_uids_fail_before_sending_a_request(cli,monkeypatch):
    module,requests=cli
    monkeypatch.setattr(sys,'argv',['api.py','inspect','net','--uid','A','--uid','B'])
    with pytest.raises(ValueError,match='只允许一个'):module.main()
    assert requests==[]


def test_plural_and_alias_merge_without_dropping_uids(cli,monkeypatch):
    module,requests=cli
    monkeypatch.setattr(sys,'argv',['api.py','inspect','layout','--uids','A','B','--uid','C'])
    module.main();assert requests[0][1]['uids']==['A','B','C']


def test_explicit_empty_parameters_retains_reference_query(cli,monkeypatch):
    module,requests=cli
    monkeypatch.setattr(sys,'argv',['api.py','inspect','reference','--parameters'])
    module.main();assert requests[0][1]=={'kind':'reference','parameter_names':[]}


def test_empty_parameters_are_only_valid_for_reference():
    from colayout_lite.agent_tools.contract import Inspect
    from pydantic import ValidationError
    assert Inspect(session_token='x'*32,kind='reference',parameter_names=[]).parameter_names==[]
    with pytest.raises(ValidationError,match='requires kind=reference'):
        Inspect(session_token='x'*32,kind='layout',parameter_names=[])

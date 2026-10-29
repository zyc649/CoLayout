"""Run the shipped layout CLI against an isolated synthetic Qt APP and real HTTP API."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fixture():
    from colayout_lite.model import Snapshot, Workspace, Object, Placement
    from colayout_lite.technology import TechnologyProfile
    from colayout_lite.editor import Editor
    from colayout_lite.regions.actions import RegionActions
    from colayout_lite.circuit.models import (CircuitContext, LayoutConnectivity, ViewRef,
        Terminal, LayoutInstance, ReferenceInstance, NativeBinding, NativePathSegment, NativeCheck)
    from colayout_lite.drc.models import DrcProfile, Rule
    profile = TechnologyProfile(id='synthetic-client', label='Synthetic client verification',
        native_fingerprint='synthetic-client', dbu_per_micron=1000, grid=1,
        layers=[{'layer':name,'purpose':'drawing','material':material} for name,material in
                (('wire_a','metal'),('wire_b','metal'),('cut_x','cut'))],
        writable_lpps=(('wire_a','drawing'),('wire_b','drawing')),
        editor_defaults={'metal_stack':['wire_a','wire_b'],'layer':['wire_a','drawing'],
                         'width_um':.4,'widths_um':{'wire_a':.4,'wire_b':.4},'via_definition':'JOIN'},
        vias={'JOIN':{'kind':'stdViaDef','layer1':'wire_a','layer2':'wire_b','cut_layer':'cut_x',
                      'defaults':{'cutWidth':200,'cutHeight':200,'cutRows':1,'cutColumns':1,
                                  'cutSpacing':[200,200],'layer1Enc':[100,100],'layer2Enc':[100,100]}}})
    objects = {}; pins = []; instances = {}; references = {}; bindings = []; children = []
    master_box = [[0,0],[1000,1000]]
    master = ['terminal','fixture','terminal','layout',1000,master_box,[],[],[],
              [['f','f',False,None,'rect','wire_a/drawing',master_box,[]]],[],[['child_count',0]]]
    for uid,x,net in (('A',0,'left-net'),('B',4000,'left-net'),
                      ('C',12000,'right-net'),('D',16000,'right-net')):
        objects[uid] = Object(uid=uid,native_id='native-'+uid,kind='inst',
            placement=Placement(origin=(x,0)),bbox=((x,0),(x+1000,1000)),
            attributes={'name':uid,'master':['fixture','terminal','layout'],'master_key':'terminal'})
        pins.append({'instance_uid':uid,'terminal':'P','pin_index':0,'figure_index':0,
            'lpp':['wire_a','drawing'],'kind':'rect','local_bbox':master_box,
            'bbox':[[x,0],[x+1000,1000]],'local_geometry':{},'transform':[1,0,0,1,x,0]})
        terminals={'P':Terminal(name='P',net=net,members={'P':net})}
        instances[uid]=LayoutInstance(uid=uid,name=uid,master=('fixture','terminal','layout'),
                                      terminals=terminals,black_box=False)
        references[uid]=ReferenceInstance(name=uid,master=('fixture','terminal','symbol'),terminals=terminals)
        bindings.append(NativeBinding(layout_uid=uid,schematic_paths=((NativePathSegment(
            library='fixture',cell='client',view='schematic',instance=uid,member=0,row=0,column=0),),)))
        children.append(['native-'+uid,'terminal','inst',[x,0],'R0',1])
    root=['root','fixture','client','layout',1000,[[0,0],[17000,1000]],[],[],[],[],children,[]]
    style=lambda layer,material:[[layer,'drawing'],None,1,True,material,None,None,None,None,None]
    display={'root':'root','nodes':{'root':root,'terminal':master},
             'styles':[[layer+'/drawing',style(layer,role)] for layer,role in
                       (('wire_a','metal'),('wire_b','metal'),('cut_x','cut'))],'unsupported':[]}
    source=ViewRef(library='fixture',cell='client',view='layout',session='synthetic',counter='1')
    baseline=Snapshot(library='fixture',cell='client',library_path='/synthetic/fixture',
        session='synthetic',counter='1',dirty=False,dbu_per_micron=1000,grid=1,objects=objects,
        pins=pins,display=display,routes={},fig_groups={},technology_fingerprint=profile.native_fingerprint)
    workspace=Workspace(baseline=baseline,profile_id=profile.id,
        circuit=CircuitContext(source=source.model_copy(update={'view':'schematic'}),pair_id='synthetic-pair',
            instances=references,ports={},bindings=tuple(bindings),native_check=NativeCheck(report='synthetic fixture')),
        layout_connectivity=LayoutConnectivity(source=source,pair_id='synthetic-pair',instances=instances,ports={}))
    editor=Editor(workspace,profile)
    regions=[RegionActions(editor).create(bounds,name) for bounds,name in (
        ((-1000,-1000,7000,4000),'Left synthetic region'),((11000,-1000,19000,4000),'Right synthetic region'))]
    rules=DrcProfile(id='Synthetic checks',technology_fingerprint=profile.native_fingerprint,
        rules=(Rule(id='wire-width',kind='width',layer='wire_a',value=.1,source='Synthetic test specification'),))
    return editor.w,profile,rules,regions


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True,help='New output folder, never an existing workspace')
    args=parser.parse_args();out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=False)
    from PySide6.QtCore import QEventLoop,QTimer
    from PySide6.QtWidgets import QApplication
    from colayout_lite import app_identity
    from colayout_lite.document import save_document
    from colayout_lite.transactions import write_json_atomic
    from colayout_lite.workspace_storage import WorkspaceStorage
    from colayout_lite.studio_window import StudioWindow
    from colayout_lite.agent_tools.app import enable
    from colayout_lite.agent_tools.client import AgentClient
    from tools import create_layout_agent as generator
    app_identity.APPLICATION_ID='CoLayout.Lite.ClientVerification'
    app=QApplication([]);app.setStyle('Fusion');app_identity.configure_application(app)
    report={'scope':'Synthetic geometry, real APP/HTTP and shipped CLI; no SSH or native DRC',
            'steps':[]};window=None
    def forbid(*args,**kwargs):
        raise AssertionError('This synthetic test must not contact Virtuoso')
    with (patch('colayout_lite.transport.NativeTransport.__init__',forbid),
          patch('colayout_lite.workspace_storage.RUNTIME_ROOT',out/'runtime'),
          patch('colayout_lite.process_library.ROOT',out),
          patch('colayout_lite.drc.config.ROOT',out),
          ThreadPoolExecutor(3) as pool):
        def wait(predicate,timeout=45000):
            loop=QEventLoop();timer=QTimer();deadline=QTimer()
            timer.setInterval(15);deadline.setSingleShot(True)
            timer.timeout.connect(lambda:loop.quit() if predicate() else None)
            deadline.timeout.connect(loop.quit);timer.start();deadline.start(timeout);loop.exec()
            timer.stop();deadline.stop()
            assert predicate(),'Timed out while pumping Qt'
        def work(callback):
            future=pool.submit(callback);wait(future.done);return future.result()
        try:
            workspace,profile,rules,regions=fixture()
            connection=out/'config/connection.json'
            write_json_atomic(connection,{'schema_version':'colayout-lite-connection-1',
                'bridge_env':str(out/'no-native.env'),'allowed_remote_root':'/synthetic',
                'state_directory':str(out/'native'),'profiles_directory':str(out/'profiles'),
                'default_library':'fixture','default_source_cell':'client'})
            workspace=workspace.model_copy(update={'connection_config':str(connection)})
            document=out/'fixture.colayout.json';save_document(document,workspace,profile)
            rules.save(out/'config/drc'/f'{profile.key}.json')
            folder=out/'layout-client';pointer=out/'installation.json'
            console_python=Path(sys.executable)
            if console_python.name.lower()=='pythonw.exe':
                console_python=console_python.with_name('python.exe')
            settings={'app_root':str(ROOT),'project_root':str(ROOT),'python_executable':str(console_python),
                'document':str(document),'test_kit':str(folder),
                'workspace_archive_root':str(folder/'workspaces'),'workspace_import_roots':[str(folder/'workspaces')]}
            write_json_atomic(pointer,settings)
            window=StudioWindow(document,installation_path=pointer,storage=WorkspaceStorage(out/'runtime'),
                                shortcut_path=out/'keys.json')
            window.setWindowTitle('CoLayout · synthetic client verification')
            window.resize(1100,700);window.show()
            hub=enable(window);connection_file=hub.connection_file
            with (patch.object(generator,'settings',lambda:json.loads(pointer.read_text(encoding='utf8'))),
                  patch.object(generator,'installation_path',lambda:pointer),
                  patch.object(generator,'client',lambda:AgentClient(connection_file))):
                prepared=work(lambda:generator.create(folder))
            assert prepared['ready']
            assert (folder/'PROMPT.md').is_file()
            report['steps'].append('client folder prepared with prompt and live connection')
            def cli(name,*arguments,expected_error=None):
                process=subprocess.run([str(folder/'python.cmd'),'api.py','--client',name,*arguments],
                    cwd=folder,capture_output=True,text=True,encoding='utf8',timeout=40,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                if expected_error:
                    assert process.returncode!=0 and expected_error in process.stderr,process.stderr+process.stdout
                    return {'expected_error':expected_error}
                assert process.returncode==0,process.stderr+process.stdout
                return json.loads(process.stdout)
            def call(name,tool,arguments,expected_error=None):
                path=folder/'requests'/f'{uuid4().hex}.json'
                write_json_atomic(path,arguments)
                return cli(name,'call',tool,'--args',str(path),'--wait-seconds','20',expected_error=expected_error)
            def invoke(name,tool,arguments,expected_error=None):
                return work(lambda:call(name,tool,arguments,expected_error))
            service=work(lambda:subprocess.run([str(folder/'python.cmd'),'service.py','connect'],
                cwd=folder,capture_output=True,text=True,encoding='utf8',timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))
            assert service.returncode==0,service.stderr
            tools=work(lambda:cli('left','tools'))['result']['tools']
            assert len(tools)==11 and all(t.get('description') for t in tools)
            work(lambda:cli('left','tools','--tool','edit_region','--action','create_path90'))
            for name,region in zip(('left','right'),regions):
                work(lambda n=name,r=region:cli(n,'claim',r,'--name','Synthetic '+n))
                for kind in ('layout','rules','reference'):
                    work(lambda n=name,k=kind:cli(n,'inspect',k))
            report['steps'].append('service, 11 tools, edit parameters, claims and scoped inspections')
            observed=work(lambda:cli('left','inspect','net'))
            before=observed['result']
            assert not before['complete'] and before['total_nets']==1
            rev=observed['revision']
            invoke('left','edit_region',{'expected_revision':rev,'operations':[
                {'action':'move','uid':'C','params':{'dx':1,'dy':0}}]},'OBJECT_OUTSIDE_REGION')
            operations={}
            for name,x in (('left',0),('right',12)):
                operations[name]=[
                    {'action':'create_path90','params':{'points':[[x+.5,.5],[x+4.5,.5]],
                      'width':.4,'lpp':['wire_a','drawing']}},
                    {'action':'create_via','params':{'x':x+2.5,'y':.5,'definition':'JOIN','via_parameters':{'cutRows':2}}},
                    {'action':'create_path90','params':{'points':[[x+2.5,.5],[x+2.5,2]],
                      'width':.4,'lpp':['wire_b','drawing']}}]
            futures=[pool.submit(call,name,'edit_region',{'expected_revision':rev,'operations':operations[name]})
                     for name in ('left','right')]
            wait(lambda:all(f.done() for f in futures))
            edits=[f.result() for f in futures]
            assert all(len(r['result']['created_uids'])==3 for r in edits)
            connected=work(lambda:cli('left','inspect','net'))['result']
            assert connected['complete'] and connected['connected_nets']==1
            report['steps'].append('sibling parallel wire/via edits connect real synthetic PIN geometry; cross-region edit rejected')
            observed=work(lambda:cli('right','inspect','layout'))
            invoke('right','edit_region',{'mode':'undo','expected_revision':observed['revision']})
            undone=work(lambda:cli('right','inspect','net'))
            assert not undone['result']['complete']
            assert work(lambda:cli('left','inspect','net'))['result']['complete']
            invoke('right','edit_region',{'expected_revision':undone['revision'],'operations':operations['right']})
            report['steps'].append('owned undo preserves sibling edit; reapply restores connection')
            for name in ('left','right'):
                observed=work(lambda n=name:cli(n,'inspect','layout'))
                result=invoke(name,'check_region',{'action':'start','expected_revision':observed['revision']})['result']
                if result.get('state') in ('queued','running'):
                    result=invoke(name,'check_region',{'action':'status','job_id':result['job_id']})['result']
                assert result['state']=='completed' and result['passed'],result
            work(lambda:cli('left','capture','--size','640','--output','outputs/verified.png'))
            assert (folder/'outputs/verified.png').read_bytes().startswith(b'\x89PNG')
            observed=work(lambda:cli('left','inspect','layout'))
            invoke('left','server_drc_region',{'action':'start','expected_revision':observed['revision']},
                   'REMOTE_DRC_NOT_CONFIGURED')
            failed=work(lambda:cli('left','release','--outcome','done',expected_error='REGION_NOT_VERIFIED'))
            assert failed['expected_error']=='REGION_NOT_VERIFIED'
            for name in ('left','right'):
                work(lambda n=name:cli(n,'release','--outcome','handoff','--note','Synthetic verification only'))
            saved=work(lambda:cli('left','workspace','save','--name','verified-synthetic'))
            report['steps'].append('local checks, PNG capture, archive save and handoff; false done blocked without server evidence')
            assert not window.editor.work_sessions.snapshots()
            report.update(status='passed',tools=11,server_drc_tested=False,real_pdk_tested=False,
                          client_folder=str(folder),saved_archive=saved['result'])
        except Exception:
            report.update(status='failed',error=traceback.format_exc())
        finally:
            if window:
                if getattr(window,'agent_hub',None):
                    for token in list(window.agent_hub.runtime.leases):
                        window.agent_hub.runtime.revoke(token)
                window.close()
    write_json_atomic(out/'result.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='saved_archive'},ensure_ascii=False,indent=2))
    return 0 if report.get('status')=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())

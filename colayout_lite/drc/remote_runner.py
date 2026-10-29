"""Server-side helper (Python 3.6+). Runs only a manifest in its own job folder."""
import os,sys,json,time,subprocess,re,hashlib,signal,traceback
from remote_deck import build_deck,validate_windows,waiver_receipt


def write(path,data):
    temp=path+'.tmp'
    with open(temp,'w') as f:json.dump(data,f,indent=2)
    os.replace(temp,path)


def main():
    folder=os.path.realpath(sys.argv[1]);manifest=json.load(open(os.path.join(folder,'manifest.json')))
    assert folder==manifest['job_directory']
    assert re.match(r'^drc-[0-9a-f]{32}$',os.path.basename(folder))
    assert folder.startswith(os.path.realpath(manifest['allowed_root'])+'/.colayout-drc/')
    state={'status':'starting','job_id':manifest['job_id'],'phase':'export'};path=os.path.join(folder,'state.json');write(path,state)
    config=manifest['remote']
    def execute(args,phase):
        state.update(status='running',phase=phase,command=args);write(path,state)
        with open(os.path.join(folder,phase+'.log'),'w') as log:
            process=subprocess.Popen(args,cwd=manifest['allowed_root'] if phase=='export' else folder,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            start=time.time();state['pid']=process.pid;write(path,state)
            while process.poll() is None:
                if os.path.exists(os.path.join(folder,'cancel.flag')) or time.time()-start>config['timeout_seconds']:
                    state['status']='cancelled' if os.path.exists(os.path.join(folder,'cancel.flag')) else 'failed'
                    state['error']='cancel requested' if state['status']=='cancelled' else 'phase timeout'
                    os.killpg(process.pid,signal.SIGTERM)
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
                    write(path,state);return False
                time.sleep(.25)
            if process.returncode:
                state.update(status='failed',error=phase+' exit '+str(process.returncode));write(path,state);return False
        return True
    try:
        waived=validate_windows(manifest.get('waive_regions_um',[]))
        for key,sha in [('deck_path','deck_sha256'),('layer_map','layer_map_sha256')]:
            actual_hash=hashlib.sha256(open(config[key],'rb').read()).hexdigest()
            if config.get(sha):
                assert actual_hash==config[sha],key+' changed since configuration'
            state['source_'+sha]=actual_hash
        gds=os.path.join(folder,'layout.gds')
        command=[config['strmout'],'-library',manifest['library'],'-topCell',manifest['cell'],'-view','layout',
            '-strmFile',gds,'-layerMap',config['layer_map'],'-logFile',os.path.join(folder,'xstream.log'),'-runDir',folder]
        if not execute(command,'export'):return
        if not os.path.isfile(gds) or os.path.getsize(gds)==0:raise RuntimeError('XStream did not produce GDS')
        # The client validates XStream's log and dependency counters before permitting DRC.
        state.update(status='exported',phase='waiting_for_export_verification');write(path,state)
        started=time.time()
        while not os.path.exists(os.path.join(folder,'export.ok')):
            if os.path.exists(os.path.join(folder,'cancel.flag')):state.update(status='cancelled');write(path,state);return
            if time.time()-started>config['timeout_seconds']:raise RuntimeError('export verification timeout')
            time.sleep(.25)
        # Preserve foundry deck bytes (older decks contain Latin-1 comments).
        data=open(config['deck_path'],encoding='latin-1').read()
        data=build_deck(data,gds,manifest['cell'],folder,manifest['window_um'],config['max_results_per_rule'],waived)
        deck=os.path.join(folder,'region.drc');open(deck,'w',encoding='latin-1').write(data)
        state['effective_deck_sha256']=hashlib.sha256(data.encode('latin-1')).hexdigest()
        state['waiver_application']=waiver_receipt(waived)
        # Flat output guarantees top-level marker coordinates; no hierarchy guessing.
        if not execute([config['calibre'],'-drc',deck],'calibre'):return
        if not os.path.isfile(os.path.join(folder,'drc.results')) or not os.path.isfile(os.path.join(folder,'drc.summary')):
            raise RuntimeError('Calibre returned without complete result files')
        state.update(status='completed',phase='completed');write(path,state)
    except Exception as exc:state.update(status='failed',error=str(exc),traceback=traceback.format_exc());write(path,state)


if __name__=='__main__':main()

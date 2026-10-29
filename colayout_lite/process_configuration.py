"""One process configuration repository; publication is human-only and transactional."""
import json
from pathlib import Path,PurePosixPath
from datetime import datetime,timezone
from .model import LiteError,digest
from .process_library import ProcessLibrary,write_json
from .process_package import ProcessPackage,encode
from .technology import TechnologyProfile
from .drc.models import DrcProfile
from .drc.waivers import WaiverPolicy
from .process_transaction import file_key


class ProcessConfiguration:
    def __init__(self,store=None,*,connection=lambda:None,changed=lambda:None):
        self.store=store or ProcessLibrary()
        self.connection=connection
        self.changed=changed

    def load(self,key):
        from .process_transaction import locked
        with locked(self.store):return self._load(key)

    def _load(self,key):
        entry=self.store.entries()[key]
        p=TechnologyProfile.model_validate_json(Path(entry['profile']).read_text(encoding='utf8'))
        if p.key!=key:raise LiteError('PROCESS_REGISTRY_MISMATCH')
        dp=self.store.root/'config/drc'/(key+'.json')
        wp=self.store.root/'config/drc-waivers'/(digest(key)+'.json')
        return ProcessPackage(technology=p,
            drc=DrcProfile.model_validate_json(dp.read_text(encoding='utf8')) if dp.exists() else None,
            report_policy=WaiverPolicy.model_validate_json(wp.read_text(encoding='utf8')) if wp.exists() else WaiverPolicy(technology_fingerprint=p.native_fingerprint,configuration_id=p.configuration_id),
            notes=entry.get('notes',''))

    def connection_choices(self):
        paths={str(Path(e['connection']).resolve()) for e in self.store.entries().values()}
        if self.connection():paths.add(str(Path(self.connection()).resolve()))
        return {digest(path)[:24]:Path(path) for path in paths if Path(path).is_file()}

    def resolve_connection(self,key=None):
        choices=self.connection_choices()
        if key:
            if key not in choices:raise LiteError('PROCESS_CONNECTION_UNKNOWN')
            return choices[key]
        if self.connection():return Path(self.connection()).resolve()
        if len(choices)==1:return next(iter(choices.values()))
        raise LiteError('PROCESS_CONNECTION_REQUIRED','请在人端选择本机 Bridge 连接。')

    def paths(self,package,connection):
        p=package.technology;cfg=json.loads(Path(connection).read_text(encoding='utf8'))
        configured_folder=(self.store.root/cfg.get('profiles_directory','config/technologies')).resolve()
        folder=configured_folder if configured_folder.is_relative_to(self.store.root.resolve()) else self.store.root/'config/technologies'
        matches=[]
        for path in folder.glob('*.json'):
            other=TechnologyProfile.model_validate_json(path.read_text(encoding='utf8'))
            if other.id==p.id and other.key!=p.key:raise LiteError('PROFILE_NAME_IN_USE')
            if other.key==p.key:matches.append(path)
        if len(matches)>1:raise LiteError('AMBIGUOUS_TECHNOLOGY_PROFILE')
        key=p.key
        matching_binding=(cfg.get('preferred_profile')==p.id and
                          configured_folder==folder.resolve())
        binding=Path(connection) if matching_binding else self.store.root/'config/connections'/(
            'configured-'+digest([key,cfg.get('bridge_env'),cfg.get('allowed_remote_root')])[:24]+'.json')
        return {'technology':matches[0] if matches else folder/('process-'+digest(key)[:16]+'.json'),
                'drc':self.store.root/'config/drc'/(key+'.json'),
                'report_policy':self.store.root/'config/drc-waivers'/(digest(key)+'.json'),
                'registry':self.store.path,'connection':Path(connection),'binding':binding}

    def base(self,package,connection):
        expected={str(p.resolve()):file_key(p) for p in self.paths(package,connection).values()}
        entry=self.store.entries().get(package.technology.key)
        if entry:expected[str(Path(entry['profile']).resolve())]=file_key(entry['profile'])
        return expected

    def submit(self,package,sample,*,client_id,request_id,connection_id=None,project_root=None,verification_id=None,imported=False):
        if isinstance(package,ProcessPackage):package=package.model_dump(mode='json')
        request_digest=digest({'package':package,'sample':sample,'connection_id':connection_id,
                               'project_root':project_root,'verification_id':verification_id,'imported':bool(imported)})
        ident=digest([client_id,request_id])[:32]
        path=self.store.folder/'drafts'/ident/'proposal.json'
        if path.exists():
            data=json.loads(path.read_text(encoding='utf8'))
            if data.get('request_digest')!=request_digest:raise LiteError('REQUEST_ID_CONFLICT')
            return data.get('submission_receipt',self.summary(path,data))
        package=ProcessPackage.model_validate(package).require_complete()
        entries=self.store.entries();p=package.technology
        if p.key in entries:
            previous=self.load(p.key).technology
            if previous.native_fingerprint!=p.native_fingerprint or (previous.native_technology_name and p.native_technology_name and previous.native_technology_name!=p.native_technology_name):
                raise LiteError('PROCESS_IDENTITY_MISMATCH','此配置标识已属于另一工艺，请使用独立配置标识。')
            p=p.model_copy(update={'id':entries[p.key]['id']})
        elif any(e['id']==p.id for e in entries.values()):
            p=p.model_copy(update={'id':'process-'+digest(p.key)[:16]})
        package=package.model_copy(update={'technology':p})
        if not (imported and not sample) and (set(sample)!={'library','cell'} or any(not isinstance(v,str) or not v.strip() or len(v)>256 for v in sample.values())):
            raise LiteError('PROCESS_SAMPLE_REQUIRED','需要明确的样例库名与 Layout cell。')
        cp=self.resolve_connection(connection_id)
        content={'package':package.model_dump(mode='json'),'source':sample,'connection':str(cp),
                 'project_root':project_root,'imported':bool(imported)}
        if project_root:
            remote=PurePosixPath(project_root)
            if not remote.is_absolute() or remote==PurePosixPath('/') or '..' in remote.parts or any(c in project_root for c in ('\n','\r','\0')):
                raise LiteError('PROCESS_PROJECT_ROOT_INVALID')
            cfg=json.loads(cp.read_text(encoding='utf8'))
            if cfg.get('allowed_remote_root')!=str(remote):
                # Use the host's existing Bridge environment, never credentials
                # or arbitrary local paths supplied in the package.
                cfg.update(allowed_remote_root=str(remote),profiles_directory=str((self.store.root/'config/technologies').resolve()),
                           state_directory=str((path.parent/'native-runtime').resolve()))
                cp=path.parent/'connection.json';write_json(cp,cfg)
        # No submitted proof is sufficient to install a process. UI approval
        # performs native verification; the payload and review hash are frozen.
        data={'schema_version':'colayout-process-proposal-3','id':ident,'status':'pending_review',
              'created_at':datetime.now(timezone.utc).isoformat(),'client_id':client_id,
              **content,'connection':str(cp),'profile':package.technology.model_dump(mode='json'),
              'request_digest':request_digest,'review_digest':package.fingerprint(),
              'publication_base':self.base(package,cp)}
        if verification_id:
            from .process_review import verification
            data['verification']=verification(self,verification_id,package,sample,cp)
            data['verification_id']=verification_id
        data['submission_receipt']=self.summary(path,data)
        write_json(path,data);self.changed()
        return self.summary(path,data)

    def proposal(self,ident):
        if not isinstance(ident,str) or len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):
            raise LiteError('PROCESS_PROPOSAL_UNKNOWN')
        path=self.store.folder/'drafts'/ident/'proposal.json'
        if not path.is_file():raise LiteError('PROCESS_PROPOSAL_UNKNOWN')
        data=json.loads(path.read_text(encoding='utf8'))
        if data.get('schema_version')!='colayout-process-proposal-3':raise LiteError('PROCESS_PROPOSAL_FORMAT')
        return path,data

    @staticmethod
    def summary(path,data):
        return {'proposal_id':data['id'],'status':data['status'],'name':data['profile']['label'],
                'technology_fingerprint':data['profile']['native_fingerprint'],
                'configuration_key':data['profile'].get('configuration_id') or data['profile']['native_fingerprint'],
                'created_at':data['created_at'],'review_digest':data['review_digest'],
                'mim_confirmation_required':(data.get('package',{}).get('drc') or {}).get('mim_capacitor',{}).get('status','unconfigured')=='unconfigured',
                'error':data.get('error'),'next_action':'Windows APP → 工艺库 → 待审核' if data['status']=='pending_review' else None}

    def reject(self,ident,expected_digest):
        path,data=self.proposal(ident)
        if data['status'] not in ('pending_review','needs_attention') or data['review_digest']!=expected_digest:
            raise LiteError('PROCESS_PROPOSAL_CHANGED')
        data['status']='rejected';write_json(path,data);self.changed()

    def publish(self,package,connection,expected,*,proposal_path=None,proposal=None):
        """Called after human review; backup all targets, rollback caught failures."""
        package=ProcessPackage.model_validate(package);paths=self.paths(package,connection)
        for path in paths.values():
            if expected.get(str(path.resolve()),'not-captured')!=file_key(path):
                raise LiteError('PROCESS_CONFIGURATION_CHANGED','配置在审阅期间已变化，请刷新后再保存。')
        p=package.technology;key=p.key;entries=self.store.entries()
        previous=entries.get(key,{})
        if previous:
            old=TechnologyProfile.model_validate_json(Path(previous['profile']).read_text(encoding='utf8'))
            if old.native_fingerprint!=p.native_fingerprint or (old.native_technology_name and p.native_technology_name and old.native_technology_name!=p.native_technology_name):
                raise LiteError('PROCESS_IDENTITY_MISMATCH')
        if previous.get('connection')!=str(paths['binding'].resolve()):
            previous={k:v for k,v in previous.items() if k not in ('workspace','sample')}
        entries[key]={**previous,'id':p.id,'label':p.label,'native_fingerprint':p.native_fingerprint,
                      'native_technology_name':p.native_technology_name,'profile':str(paths['technology'].resolve()),
                      'connection':str(paths['binding'].resolve()),'drc_profile':str(paths['drc'].resolve()),
                      'confirmed':True,'configured_sections':['technology','guards','report_policy']+
                        (['local_drc','design_warnings'] if package.drc else [])+
                        (['remote_drc'] if package.drc and package.drc.remote else [])}
        entries[key]['notes']=package.notes
        if proposal:entries[key]['configuration_origin']='shared' if proposal.get('imported') else 'sample'
        if proposal and proposal['source']:entries[key]['sample']=proposal['source']
        writes={paths['technology']:p.model_dump(mode='json'),paths['registry']:{'schema_version':'colayout-process-library-1','entries':entries}}
        if paths['binding'].resolve()!=Path(connection).resolve():
            cfg=json.loads(Path(connection).read_text(encoding='utf8'))
            cfg.update(preferred_profile=p.id,profiles_directory=str(paths['technology'].parent.resolve()))
            if proposal and proposal['source']:
                cfg.update(default_library=proposal['source']['library'],default_source_cell=proposal['source']['cell'])
            writes[paths['binding']]=cfg
        if package.drc:writes[paths['drc']]=package.drc.model_dump(mode='json')
        if package.report_policy:writes[paths['report_policy']]=package.report_policy.model_dump(mode='json')
        if proposal_path:
            writes[proposal_path]={**proposal,'status':'confirmed','confirmed_at':datetime.now(timezone.utc).isoformat(),
                                   'package':package.model_dump(mode='json'),'profile':p.model_dump(mode='json'),
                                   'review_digest':package.fingerprint()}
        from .process_transaction import publish_files
        publish_files(self.store,writes,expected,write_json)
        self.changed()
        return key

    def export(self,key):
        from .process_package import decode
        data=encode(self.load(key));decode(data).require_complete()
        return data

    def save_settings(self,key,package,expected):
        current=self.load(key)
        if current.fingerprint()!=expected:raise LiteError('PROFILE_SETTINGS_CONFLICT')
        package=ProcessPackage.model_validate(package)
        from .process_review import verify_native_facts
        verify_native_facts(package.technology,current.technology)
        if package.technology.layers!=current.technology.layers or package.technology.material_evidence!=current.technology.material_evidence:
            raise LiteError('PROCESS_SAMPLE_REVIEW_REQUIRED','图层材质补充需从样例重新验证并提交审核。')
        if any(raw not in current.technology.guard_recipes for raw in package.technology.guard_recipes):
            raise LiteError('PROCESS_REVIEW_REQUIRED','新增保护环需从样例提交审核。')
        old=current.drc;new=package.drc
        if (old is None)!=(new is None) or old and (old.rules!=new.rules or old.remote!=new.remote):
            raise LiteError('PROCESS_REVIEW_REQUIRED','工艺规则或服务器配置已修改，需要验证并审核。')
        connection=self.store.entries()[key]['connection']
        return self.publish(package,connection,self.base(current,connection))

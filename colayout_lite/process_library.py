"""Local process registry and per-process workspaces; no native calls."""
from pathlib import Path
from uuid import uuid4
import json
from .paths import ROOT
from .technology import TechnologyProfile
from .model import Workspace, LiteError


def write_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(path)


class ProcessLibrary:
    def __init__(self, root=None):
        self.root=Path(root or ROOT)
        self.path=self.root/'config/process-library.json'
        self.folder=self.root/'artifacts/process-library'

    def entries(self):
        return json.loads(self.path.read_text(encoding='utf8'))['entries'] if self.path.exists() else {}

    def register(self, profile, profile_path, connection_path, *, confirmed=False):
        entries=self.entries();key=profile.key
        previous=entries.get(key,{})
        if previous and Path(previous['connection'])!=Path(connection_path).resolve():
            # An existing workspace belongs to its previous project connection.
            previous={k:v for k,v in previous.items() if k!='workspace'}
        entries[key]={**previous,'id':profile.id,'label':profile.label,'native_fingerprint':profile.native_fingerprint,
            'profile':str(Path(profile_path).resolve()),'connection':str(Path(connection_path).resolve()),
            'confirmed':confirmed or previous.get('confirmed',False)}
        write_json(self.path,{'schema_version':'colayout-process-library-1','entries':entries})
        return key

    def migrate_existing(self):
        """Import known configured connections once, without inventing validation."""
        entries=self.entries()
        for connection in sorted((self.root/'config').glob('colayout_lite*.json')):
            cfg=json.loads(connection.read_text(encoding='utf8'));preferred=cfg.get('preferred_profile')
            if not preferred:continue
            for path in (self.root/cfg['profiles_directory']).glob('*.json'):
                p=TechnologyProfile.model_validate_json(path.read_text(encoding='utf8'))
                if p.id==preferred and p.key not in entries:
                    self.register(p,path,connection);entries=self.entries()

    def remember(self,w):
        entries=self.entries()
        matches=[key for key,entry in entries.items() if entry['id']==w.profile_id and entry.get('native_fingerprint',key)==w.baseline.technology_fingerprint]
        key=matches[0] if len(matches)==1 else w.baseline.technology_fingerprint
        if key not in entries:return
        entry=entries[key]
        if w.connection_config and Path(w.connection_config).resolve()!=Path(entry['connection']).resolve():return
        path=self.folder/'workspaces'/(key+'.json');w.save(path)
        if entry.get('workspace')!=str(path.resolve()):
            entry['workspace']=str(path.resolve());write_json(self.path,{'schema_version':'colayout-process-library-1','entries':entries})

    def load(self,key):
        entry=self.entries()[key]
        p=TechnologyProfile.model_validate_json(Path(entry['profile']).read_text(encoding='utf8'))
        if p.key!=key:raise LiteError('PROCESS_REGISTRY_MISMATCH')
        w=None
        if entry.get('workspace') and Path(entry['workspace']).exists():
            w=Workspace.model_validate_json(Path(entry['workspace']).read_text(encoding='utf8'))
            if w.baseline.technology_fingerprint!=p.native_fingerprint:raise LiteError('PROCESS_WORKSPACE_MISMATCH')
            from .permissions import apply_profile_permissions
            updated=apply_profile_permissions(w.baseline,p)
            if w.operations and updated.semantic()!=w.baseline.semantic():
                raise LiteError('PROCESS_POLICY_CHANGED_WITH_DRAFT','工艺权限已变化，原草稿仍保留；请先处理原草稿再加载新权限。')
            w=w.model_copy(update={'baseline':updated,'profile_id':p.id})
        return entry,p,w

    def update_settings(self,key,*,width_um,layers,expected_profile,widths_um=None,schematic_summary_parameters=None):
        """Legacy preference adapter; current UI uses ProcessConfiguration.save_settings."""
        from .process_compat import update_preferences
        return update_preferences(self,key,width_um=width_um,layers=layers,expected_profile=expected_profile,
                                  widths_um=widths_um,schematic_summary_parameters=schematic_summary_parameters)

    def drafts(self):
        result=[];self.scan_errors=[]
        for path in (self.folder/'drafts').glob('*/proposal.json'):
            try:
                data=json.loads(path.read_text(encoding='utf8'))
                if not isinstance(data.get('profile',{}).get('label'),str) or not isinstance(data.get('status'),str):raise ValueError('Missing proposal metadata')
                if data['status'] not in ('confirmed','superseded','rejected'):result.append((path,data))
            except (ValueError,OSError,TypeError,AttributeError) as exc:self.scan_errors.append({'path':str(path),'error':str(exc)})
        return sorted(result,key=lambda row:str(row[1].get('created_at','')),reverse=True)

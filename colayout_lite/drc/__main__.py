"""JSON CLI for deterministic agent use. python -m colayout_lite.drc --help"""
import argparse,json,sys,shlex,hashlib,re
from pathlib import Path
from . import jobs,config
from .models import DrcProfile,RemoteConfig,Region
from ..model import Workspace
from ..technology import TechnologyProfile
from ..paths import ROOT
from ..transport import NativeTransport


def load(path,model):return model.model_validate_json(Path(path).read_text(encoding='utf8'))


def main():
    parser=argparse.ArgumentParser(description='Colayout region DRC; input µm, output integer/fractional DBU with explicit scale.')
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ['status','result','cancel','review']:
        p=commands.add_parser(name);p.add_argument('job_id')
    p=commands.add_parser('run');p.add_argument('--workspace',type=Path,required=True);p.add_argument('--technology',type=Path,required=True)
    p.add_argument('--profile',type=Path);p.add_argument('--engine',choices=['local','calibre'],default='local');p.add_argument('--region',nargs=4,required=True)
    p=commands.add_parser('config-init');p.add_argument('--technology',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p=commands.add_parser('config-probe');p.add_argument('--profile',type=Path,required=True);p.add_argument('--connection',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p=commands.add_parser('config-install');p.add_argument('--profile',type=Path,required=True);p.add_argument('--technology',type=Path,required=True)
    p=commands.add_parser('config-discover');p.add_argument('--connection',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.command=='config-discover':
            from .onboarding import discover
            answer=discover(args.connection)
        elif args.command in ('status','cancel'):answer=getattr(jobs,args.command)(args.job_id)
        elif args.command=='result':answer=jobs.result(args.job_id).model_dump(mode='json')
        elif args.command=='review':
            from .waivers import review
            answer=review(jobs.result(args.job_id))
        elif args.command=='run':
            w=load(args.workspace,Workspace);p=load(args.technology,TechnologyProfile)
            drc=load(args.profile,DrcProfile) if args.profile else config.load(p)
            if drc is None:raise ValueError('DRC 尚未配置')
            answer=jobs.start(w,p,drc,Region.from_um(args.region,p.dbu_per_micron),args.engine)
        elif args.command=='config-init':
            if args.out.exists():raise ValueError('Output already exists; refusing to overwrite')
            p=load(args.technology,TechnologyProfile)
            drc=DrcProfile(id=p.label+' DRC',technology_fingerprint=p.native_fingerprint,configuration_id=p.configuration_id,provenance={'validation':'unconfigured','instructions':'Read real foundry rules; no thresholds inferred from drawing defaults.'})
            drc.save(args.out);answer={'profile':str(args.out),'drawing_layers':[r['layer'] for r in p.layers if r['purpose']=='drawing'],'next':'Fill local rules and optional remote runner paths; probe and validate on a copied sample.'}
        elif args.command=='config-install':
            p=load(args.technology,TechnologyProfile);drc=load(args.profile,DrcProfile);config.save(drc,p)
            answer={'installed':str(config.path_for(p)),'validation':drc.provenance.get('validation','not_verified')}
        else:
            drc=load(args.profile,DrcProfile)
            if drc.remote is None:raise ValueError('Remote runner not configured')
            # Keep bridge debug logging separate from the CLI JSON result.
            from contextlib import redirect_stdout
            with redirect_stdout(sys.stderr):
                from .onboarding import probe
                updated=probe(drc,args.connection);updated.save(args.out)
                hashes={'deck_sha256':updated.remote.deck_sha256,'layer_map_sha256':updated.remote.layer_map_sha256}
            answer={'profile':str(args.out),'verified_paths':True,'hashes':hashes,'next':'Run deliberate bad/fixed ROI fixtures and compare native reports. Path verification alone is not DRC verification.'}
        print(json.dumps(answer,ensure_ascii=False,indent=2))
    except Exception as exc:
        print(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False));return 1
    return 0


if __name__=='__main__':raise SystemExit(main())

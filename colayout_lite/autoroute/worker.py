"""Private host worker CLI. Large geometry/DRC work stays outside the UI process."""
import argparse,json,traceback
from pathlib import Path
from ..document import load_document
from ..drc.models import DrcProfile
from ..model import LiteError
from .models import RoutingProblem,PluginResult


def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','builtin','validate'])
    parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--algorithm');parser.add_argument('--source',type=Path);parser.add_argument('--problem',type=Path)
    args=parser.parse_args()
    try:
        if args.stage=='prepare':
            from .snapshot import prepare
            request=json.loads(args.input.read_text(encoding='utf8'));w,p=load_document(request['document'])
            drc=DrcProfile.model_validate(request['drc'])
            result=prepare(w,p,drc,request['region_id'],request_id=request['request_id'],layers=request.get('layers')).model_dump(mode='json')
        elif args.stage=='builtin':
            from .builtin import generate
            problem=RoutingProblem.model_validate_json(args.input.read_text(encoding='utf8'))
            result=generate(problem,args.algorithm).model_dump(mode='json')
        else:
            from .validation import validate
            request=json.loads(args.source.read_text(encoding='utf8'));w,p=load_document(request['document'])
            drc=DrcProfile.model_validate(request['drc']);problem=RoutingProblem.model_validate_json(args.problem.read_text(encoding='utf8'))
            if args.input.stat().st_size>16*1024*1024:raise LiteError('PLUGIN_OUTPUT_TOO_LARGE')
            response=PluginResult.model_validate_json(args.input.read_text(encoding='utf8'))
            if response.request_id!=problem.request_id or response.source_digest!=problem.source_digest:
                raise LiteError('PLUGIN_SOURCE_MISMATCH')
            result={'candidates':[{'proposal':proposal.model_dump(mode='json'),'validation':validate(w,p,drc,problem,proposal)}
                       for proposal in response.candidates],'diagnostics':response.diagnostics}
        args.output.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf8');return 0
    except Exception as exc:
        args.output.write_text(json.dumps({'error':{'code':getattr(exc,'code','ROUTING_WORKER_FAILED'),'message':str(exc),
            'details':getattr(exc,'details',{})}},ensure_ascii=False),encoding='utf8')
        traceback.print_exc();return 1

if __name__=='__main__':raise SystemExit(main())

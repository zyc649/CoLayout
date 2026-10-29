"""Private local-batch process: no server IO and no live Editor access."""
import json
import sys
from pathlib import Path
from ..document import load_document, save_document
from ..transactions import write_json_atomic
from ..model import Operation, LiteError
from ..local_models import LocalData
from ..autoroute import runner


def prepare(source, profile, region_id, args, folder, cancelled):
    folder.mkdir(parents=True, exist_ok=True)
    save_document(folder / 'source.colayout.json', source, profile)
    request, output = folder / 'batch.json', folder / 'result.json'
    write_json_atomic(request, {'region_id': region_id, 'edit': args.model_dump(exclude={'session_token'})})
    try:
        data = runner.run([runner.python_executable(), '-X', 'utf8', '-m',
                           'colayout_lite.agent_tools.batch_worker', str(request), str(output)],
                          output, folder / 'batch.log', cancelled, 180)
    except LiteError as exc:
        # The generic process runner nests domain details under its diagnostics.
        # Keep the edit API's operation index and atomic-failure fields flat.
        nested = exc.details.pop('details', {})
        if isinstance(nested, dict):
            exc.details = {**nested, **exc.details}
        exc.details['edit_applied'] = False
        raise
    old = {op.uid: op for op in source.operations}
    operations = [Operation.model_validate(row) for row in data['operations']]
    candidate = source.model_copy(update={
        'operations': tuple(old[op.uid] if old.get(op.uid) == op else op for op in operations),
        'local_data': LocalData.model_validate(data['local_data']),
        'guard_previews': {k: v for k, v in source.guard_previews.items() if k not in data['removed_guards']},
    })
    return candidate, data['result']


def main():
    request, output = map(Path, sys.argv[1:])
    try:
        from .contract import Edit
        from .batch_edits import eligible, prepare_local
        data = json.loads(request.read_text(encoding='utf8'))
        args = Edit.model_validate({**data['edit'], 'session_token': 'private-batch-worker'})
        if not eligible(args):
            raise LiteError('INVALID_BATCH_WORKER_INPUT')
        source, profile = load_document(request.parent / 'source.colayout.json')
        candidate, result = prepare_local(source, profile, data['region_id'], args.operations)
        write_json_atomic(output, {
            'operations': [op.model_dump(mode='json') for op in candidate.operations],
            'local_data': candidate.local_data.model_dump(mode='json'),
            'removed_guards': sorted(source.guard_previews.keys() - candidate.guard_previews.keys()),
            'result': result,
        })
        return 0
    except Exception as exc:
        write_json_atomic(output, {'error': {'code': getattr(exc, 'code', 'BATCH_EDIT_FAILED'),
                          'message': str(exc), 'details': getattr(exc, 'details', {})}})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

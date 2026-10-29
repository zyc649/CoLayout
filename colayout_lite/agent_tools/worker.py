"""Local check worker. No Adapter, network transport or remote DRC."""

import json, sys
from pathlib import Path
from ..document import load_document
from ..drc.models import DrcProfile
from ..region_analysis import analyze





def main():
    request, output = map(Path, sys.argv[1:])
    data = json.loads(request.read_text(encoding='utf8'))
    try:
        w, p = load_document(data['document'])
        rules=DrcProfile.model_validate(data['drc'])
        result = analyze(w, p, rules, data['region_id'],bounds_um=data.get('bounds_um'))
        output.write_text(json.dumps(result, ensure_ascii=False), encoding='utf8')
        return 0
    except Exception as exc:
        output.write_text(
            json.dumps(
                {
                    'error': {
                        'code': getattr(exc, 'code', 'CHECK_FAILED'),
                        'message': str(exc),
                        'details': getattr(exc, 'details', {}),
                    }
                },
                ensure_ascii=False,
            ),
            encoding='utf8',
        )
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

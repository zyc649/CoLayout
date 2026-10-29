"""Generate SDK, schema and copyable prompt; never overwrite customer scripts or runtime."""

import argparse
import json
from pathlib import Path
from colayout_lite.agent_tools.contract import describe_tools

APP = Path(__file__).resolve().parents[1]
KIT = APP / 'templates/layout-agent'


def generated_files():
    prompts={}
    for language in ('zh','en'):
        document=(APP/'docs'/language/'layout-prompt.md').read_text(encoding='utf8')
        prompts[language]=document.split('~~~text\n',1)[1].split('\n~~~',1)[0]
    prompt=('# Layout prompt / 版图提示词\n\n'
            '[简体中文](#简体中文) | [English](#english) · [README](README.md)\n\n'
            '<!-- Generated from docs/zh/layout-prompt.md and docs/en/layout-prompt.md. -->\n\n'
            '## 简体中文\n\n~~~text\n'+prompts['zh']+'\n~~~\n\n'
            '## English\n\n~~~text\n'+prompts['en']+'\n~~~\n')
    return {
        'PROMPT.md':prompt.encode('utf8'),
        'colayout_client.py': (APP / 'colayout_lite/agent_tools/client.py').read_bytes(),
        'docs/api-schema.json': json.dumps(describe_tools(), ensure_ascii=False, indent=2).encode(
            'utf8'
        ),
    }


def build(destination=KIT, *, check=False):
    changed = []
    for relative, content in generated_files().items():
        path = Path(destination) / relative
        if path.exists():
            actual = path.read_bytes()
            if actual == content or (path.suffix == '.json' and json.loads(actual) == json.loads(content)):
                continue
        changed.append(relative)
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--destination', type=Path, default=KIT)
    args = parser.parse_args()
    changed = build(args.destination, check=args.check)
    print(json.dumps({'check': args.check, 'different_files': changed}, ensure_ascii=False))
    return int(args.check and bool(changed))


if __name__ == '__main__':
    raise SystemExit(main())

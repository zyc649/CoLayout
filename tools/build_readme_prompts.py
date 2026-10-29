"""Keep prominent homepage prompts synchronized with their language-specific guides."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prompt(language, kind):
    text = (ROOT/'docs'/language/(kind+'-prompt.md')).read_text(encoding='utf8')
    return text.split('~~~text\n', 1)[1].split('\n~~~', 1)[0]


def update(check=False):
    changed = []
    for language, filename in (('en', 'README.md'), ('zh', 'README.zh-CN.md')):
        path = ROOT/filename
        original = text = path.read_text(encoding='utf8')
        for kind in ('setup', 'layout'):
            start = '<!-- BEGIN '+kind.upper()+' PROMPT -->'
            end = '<!-- END '+kind.upper()+' PROMPT -->'
            if text.count(start) != 1 or text.count(end) != 1:
                raise ValueError(filename+': missing/duplicate prompt markers')
            before, rest = text.split(start)
            _, after = rest.split(end)
            text = before+start+'\n~~~text\n'+prompt(language, kind)+'\n~~~\n'+end+after
        if text != original:
            changed.append(filename)
            if not check:
                path.write_text(text, encoding='utf8', newline='\n')
    return changed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    changed = update(args.check)
    print({'check': args.check, 'different_files': changed})
    raise SystemExit(bool(args.check and changed))

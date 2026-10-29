"""Check tracked/staged publication files; does not read or alter runtime secrets."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_BINARY = {
    'colayout_lite/assets/branding/colayout-e2.png',
    'colayout_lite/assets/branding/colayout-e2.ico',
}


def audit(staged=False):
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf8').split('\0')
    problems = []
    checked = 0
    for name in filter(None, names):
        path = Path(name)
        if (any(part in ('.venv', '.colayout', 'artifacts', '__pycache__', 'layout-agents') for part in path.parts)
            or path.name in ('.env', 'agent-connection.json', 'active-installation.json')
            or (path.suffix.lower() in ('.pdf', '.gds', '.oas', '.db', '.log', '.dmp', '.zip', '.exe', '.dll'))
            or name.startswith('.agents/skills/virtuoso/')):
            problems.append((name, 'runtime/private/proprietary file category'))
        raw = (subprocess.check_output(['git', 'show', ':'+name], cwd=ROOT)
               if staged else (ROOT/name).read_bytes())
        checked += 1
        if name in ALLOWED_BINARY:
            continue
        try:
            body = raw.decode('utf-8-sig')
        except UnicodeError:
            problems.append((name, 'unexpected non-UTF8 binary'))
            continue
        # Upstream notices retain names/dates/URLs. They are not personal project history.
        if name.startswith('LICENSES/') or name == 'dependencies/licenses.json':
            continue
        checks = {
            'private Windows user/project path': r'(?i)[A-Z]:[/\\](?:Users|Project)[/\\]',
            'personal Linux home path': r'/home/(?!<)[A-Za-z0-9_.-]+/',
            'private address': r'\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b',
            'credential literal': r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:OPENSSH|RSA|EC|DSA) PRIVATE KEY-----)',
        }
        for reason, pattern in checks.items():
            if re.search(pattern, body):
                problems.append((name, reason))
        if path.suffix == '.md':
            for target in re.findall(r'(?<!!)\[[^\]]+\]\(([^ )]+)(?: +"[^"]*")?\)', body):
                if re.match(r'(?:https?://|mailto:|#)', target) or '<' in target:
                    continue
                target = target.split('#')[0]
                if target and not (ROOT/path.parent/target).exists():
                    problems.append((name, 'broken documentation link: '+target))
    return {'files_checked': checked, 'problems': problems, 'passed': not problems}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--staged', action='store_true')
    result = audit(p.parse_args().staged)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(not result['passed'])

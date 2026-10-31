"""Probe the actual APP before publishing only its client connection settings."""

import argparse
import json
from pathlib import Path
import shutil
from uuid import uuid4

from colayout_lite.agent_tools.client import AgentClient
from colayout_lite.agent_tools.contract import TOOLS
from colayout_lite.transactions import write_json_atomic


def probe(path):
    original = path.read_bytes()
    client = AgentClient(path)
    result = client.call('tools', {}, wait_seconds=0, _http_timeout=3)
    names = sorted(item['name'] for item in result['tools'])
    if names not in (sorted(TOOLS),sorted(set(TOOLS)-{'route_region'})):
        raise RuntimeError('Running APP tool contract differs from the installed source.')
    if path.read_bytes() != original:
        raise RuntimeError('APP service identity changed during probe; retry publication.')
    return json.loads(original), names


def publish(installation, *, probe_only=False, test_kit=None):
    settings = json.loads(installation.read_text(encoding='utf8'))
    connection = Path(settings['document']).parent / 'agent-connection.json'
    descriptor, names = probe(connection)
    result = {'connected': True, 'url': descriptor['url'], 'tools': names,
              'region_claimed': False, 'published': False}
    if probe_only:
        return result
    kit = Path(test_kit or settings['test_kit']).resolve()
    if not (kit / 'service.py').is_file():
        raise FileNotFoundError(f'Customer kit is missing: {kit}')
    targets = [(kit / 'runtime/agent-connection.json', descriptor),
               (kit / 'installation.json', {
                   'schema_version': 'colayout-customer-runtime-1',
                   'python_executable': settings['python_executable'],
                   'connection_mode': 'local-descriptor'})]
    backup = Path(settings['app_root']) / 'artifacts/customer-publications' / uuid4().hex
    for path, _ in targets:
        if path.exists():
            destination = backup / path.relative_to(kit)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    for path, value in targets:
        write_json_atomic(path, value)
    _, published_names = probe(kit / 'runtime/agent-connection.json')
    if published_names != names:
        raise RuntimeError('Published tools changed; inspect the running APP.')
    result.update(published=True, test_kit=str(kit), previous_settings_backup=str(backup))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation', type=Path, required=True)
    parser.add_argument('--test-kit', type=Path)
    parser.add_argument('--probe-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(publish(args.installation, probe_only=args.probe_only,
                             test_kit=args.test_kit), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

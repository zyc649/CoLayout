"""Test-local connection probe; no APP files, process control, or Bridge access."""
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from colayout_client import AgentClient

KIT = Path(__file__).resolve().parent
CONNECTION = KIT / 'runtime/agent-connection.json'


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    os.replace(temp, path)


def probe(path):
    client = AgentClient(path)
    original = client.opener

    class ShortTimeout:
        def open(self, request, timeout=3):
            return original.open(request, timeout=3)

    client.opener = ShortTimeout()
    tools = client.tools()
    descriptor = json.loads(Path(path).read_text(encoding='utf8'))
    if descriptor['url'] != client.url or descriptor['token'] != client.token:
        raise RuntimeError('探测期间 APP 连接发生变化，请重新连接。')
    return descriptor, tools


def connect():
    if not CONNECTION.is_file():
        raise RuntimeError('缺少包内 runtime/agent-connection.json，请让开发者发布当前 APP 连接；不要到测试目录外寻找配置。')
    descriptor, tools = probe(CONNECTION)
    write_json(KIT / 'runtime/live-tools.json', tools)
    result = {'connected': True, 'url': descriptor['url'],
              'connection_file': str(CONNECTION), 'tools': [t['name'] for t in tools],
              'region_claimed': False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['connect', 'start', 'bridge'])
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.action == 'bridge':
            raise RuntimeError('本测试包只通过 APP HTTP API 操作版图。Virtuoso/Bridge 由开发者维护，本入口不执行原生命令。')
        if args.arguments:
            parser.error('connect/start 不接收额外参数')
        # Preserve the old launcher name as a probe only; never start an APP.
        connect()
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        if args.action != 'bridge':
            print('请反馈给用户，由开发者检查 APP 并刷新包内连接描述。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

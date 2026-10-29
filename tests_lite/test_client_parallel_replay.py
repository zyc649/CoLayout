from io import BytesIO
import json
from colayout_lite.agent_tools.client import AgentClient


def test_replay_never_rewinds_same_lease_but_new_claim_can_change_document_revision(tmp_path):
    path = tmp_path / 'connection.json'
    path.write_text(
        json.dumps(
            {
                'schema_version': 'colayout-agent-connection-2',
                'url': 'http://127.0.0.1:1234',
                'token': 'test',
            }
        )
    )
    client = AgentClient(path)
    replies = iter(
        [
            {'revision': 5, 'result': {'session_token': 'a' * 32}},
            {'revision': 8, 'result': {}},
            {'revision': 5, 'result': {'state': 'queued', 'job_id': 'original'}},
            {'revision': 5, 'result': {'session_token': 'a' * 32}},
            {'revision': 9, 'result': {}},
            {'revision': 1, 'result': {'session_token': 'b' * 32}},
        ]
    )

    class Opener:
        def open(self, *args, **kwargs):
            return BytesIO(json.dumps({'ok': True, **next(replies)}).encode())

    client.opener = Opener()
    client.call('claim_region')
    client.call('inspect_region')
    client.call('edit_region', wait_seconds=0)
    assert client.revision == 8
    client.call('claim_region')  # Replaying this same claim is also historical.
    assert client.revision == 8
    client.call('release_region')
    client.call('claim_region')
    assert client.revision == 1 and client.session_token == 'b' * 32

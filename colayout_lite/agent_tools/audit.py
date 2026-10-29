"""Complete local request/response journal and non-evicting idempotency ledger."""

import json, sqlite3, hashlib
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from .events import observer_payload


class Audit:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / 'calls.jsonl'
        self.listeners = []
        self.recent_events = deque(maxlen=1000)
        self.listener_errors = deque(maxlen=20)
        self._contexts = {}
        self.db = sqlite3.connect(self.folder / 'requests.sqlite3')
        self.db.execute(
            'CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, response TEXT)'
        )
        self.db.commit()

    def emit(self, event):
        row = {'timestamp': datetime.now(timezone.utc).isoformat(), **event}
        text = json.dumps(row, ensure_ascii=False, allow_nan=False, default=str)
        with self.path.open('a', encoding='utf8') as stream:
            stream.write(text + '\n')
            stream.flush()
        preview = observer_payload(row)
        self.recent_events.append(preview)
        for listener in tuple(self.listeners):
            try:
                listener(preview)
            except Exception as exc:
                self.listener_errors.append(str(exc))  # Observers cannot invalidate an audited edit.

    def begin(self, request_id, tool, args, source, context=None):
        fingerprint = hashlib.sha256(
            json.dumps([tool, args], ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        row = self.db.execute(
            'SELECT fingerprint,response FROM requests WHERE id=?', (request_id,)
        ).fetchone()
        if row:
            if row[0] != fingerprint:
                from ..model import LiteError

                self.emit(
                    {
                        'event': 'rejected',
                        'request_id': request_id,
                        'tool': tool,
                        'arguments': args,
                        'source': source,
                        'error': 'REQUEST_ID_REUSED',
                        **(context or {}),
                    }
                )
                raise LiteError('REQUEST_ID_REUSED', '同一 request_id 不能用于不同的调用。')
            self.emit(
                {
                    'event': 'replayed',
                    'request_id': request_id,
                    'tool': tool,
                    'arguments': args,
                    'source': source,
                    **(context or {}),
                }
            )
            return (
                json.loads(row[1])
                if row[1]
                else {
                    'ok': False,
                    'error': {
                        'code': 'OUTCOME_UNKNOWN',
                        'message': '原调用结果待核对；不能重发编辑。',
                    },
                    'request_id': request_id,
                }
            )
        self.emit(
            {
                'event': 'request',
                'request_id': request_id,
                'tool': tool,
                'arguments': args,
                'source': source,
                **(context or {}),
            }
        )
        self.db.execute('INSERT INTO requests VALUES (?,?,NULL)', (request_id, fingerprint))
        self.db.commit()
        self._contexts[request_id] = context or {}
        return None

    def finish(self, request_id, response, elapsed):
        raw = json.dumps(response, ensure_ascii=False, allow_nan=False)
        self.emit(
            {
                'event': 'response',
                'request_id': request_id,
                'duration_ms': round(elapsed * 1000, 3),
                'response': response,
                **self._contexts.get(request_id, {}),
            }
        )
        self.db.execute('UPDATE requests SET response=? WHERE id=?', (raw, request_id))
        self.db.commit()
        self._contexts.pop(request_id, None)

    def close(self):
        self.listeners.clear()
        self.recent_events.clear()
        self._contexts.clear()
        self.db.close()

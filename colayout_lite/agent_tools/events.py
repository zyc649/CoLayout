"""Structured call identity and bounded observer payloads, independent of Qt."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CallIdentity:
    client_id: str
    call_id: str
    source: str

    def fields(self):
        return {
            'audit_event_version': 2,
            'client_id': self.client_id,
            'call_id': self.call_id,
            'source': self.source,
        }

    @classmethod
    def from_event(cls, event):
        if 'client_id' in event:
            return cls(event['client_id'], event.get('call_id', ''), event.get('source', ''))
        # Historical v1 journals encoded these fields into one string.
        parts = event.get('source', '').split(' / ')
        return cls(
            parts[1] if len(parts) > 1 else parts[0],
            parts[-1] if len(parts) > 2 else str(event.get('request_id', '')),
            parts[0],
        )


def observer_payload(value):
    """Full originals remain in the journal/ledger; observers need no image bytes or secrets."""
    if isinstance(value, dict):
        return {
            key: (
                '已隐藏'
                if key in ('token', 'session_token')
                else 'PNG 数据已记录'
                if key == 'image_base64'
                else '接口结构已记录'
                if key == 'input_schema'
                else observer_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [observer_payload(item) for item in value[:80]] + (
            [f'另有 {len(value) - 80} 项，见完整记录'] if len(value) > 80 else []
        )
    return value

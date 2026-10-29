"""Bounded local file retries; never retry a native command or a DRC launch."""

import json
from pathlib import Path
from time import sleep

from ..model import LiteError
from ..transactions import write_json_atomic,write_text_atomic

RETRY_DELAYS = (0.02, 0.05, 0.1, 0.2, 0.4)


def access(path, operation, action):
    path = Path(path)
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return action()
        except PermissionError as exc:
            if attempt < len(RETRY_DELAYS):
                sleep(RETRY_DELAYS[attempt])
                continue
            raise LiteError(
                'DRC_JOB_STORAGE_UNAVAILABLE',
                '检查任务文件暂时无法访问；这不是版图 DRC 违规。',
                failure_kind='job_storage', stage=f'{path.stem}_{operation}',
                file_name=path.name, storage_operation=operation,
                attempts=attempt + 1, errno=exc.errno, winerror=getattr(exc, 'winerror', None),
                drc_completed=None, result_available=None, retryable=False,
                next_action='contact_maintenance',
                guidance='文件访问重试已耗尽；请携带任务 ID 联系维护人员，勿修改版图或自动重复启动检查。',
            ) from exc


def read_json(path):
    path = Path(path)
    return access(path, 'read', lambda: json.loads(path.read_text(encoding='utf8')))


def write_json(path, value):
    return access(path, 'write', lambda: write_json_atomic(path, value))


def write_result(path, result):
    # Preserve every field while avoiding a second large Python object tree
    # and pretty-print whitespace. Durability/retries are the same as before.
    text=result.model_dump_json()
    return access(path,'write',lambda:write_text_atomic(Path(path),text))


def read_result(path):
    from .models import Result
    path=Path(path)
    return access(path,'read',lambda:Result.model_validate_json(path.read_text(encoding='utf8')))

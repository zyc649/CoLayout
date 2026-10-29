from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import sleep
import json
import os
import subprocess
import sys
import pytest
from colayout_lite.native_lane import channel, key_for
from colayout_lite.model import LiteError


def config(tmp_path):
    p = tmp_path / 'connection.json'
    p.write_text(
        json.dumps({'bridge_env': 'lane-test.env', 'allowed_remote_root': '/test'}), encoding='utf8'
    )
    return p


def test_shared_connection_serializes_threads_and_cancelled_waiter_never_enters(tmp_path):
    p = config(tmp_path)
    entered = Event()
    cancel = Event()
    messages = []

    def wait():
        with channel(p, lock_root=tmp_path, cancelled=cancel.is_set, progress=messages.append):
            entered.set()

    with ThreadPoolExecutor(1) as pool:
        with channel(p, lock_root=tmp_path):
            # Compound operations must be reentrant on their owning thread.
            with channel(p, lock_root=tmp_path):
                pass
            future = pool.submit(wait)
            for _ in range(100):
                if messages:
                    break
                sleep(0.01)
            assert messages and not entered.is_set()
            cancel.set()
            with pytest.raises(LiteError, match='NATIVE_REQUEST_CANCELLED'):
                future.result(timeout=3)
        assert not entered.is_set()
        cancel.clear()
        pool.submit(wait).result(timeout=3)
        assert entered.is_set()


def test_lock_is_shared_with_drc_worker_process_and_released_normally(tmp_path):
    p = config(tmp_path)
    entered = tmp_path / 'entered'
    code = 'from pathlib import Path; import sys; from colayout_lite.native_lane import channel\nwith channel(sys.argv[1],lock_root=sys.argv[2]): Path(sys.argv[3]).write_text("entered")'
    with channel(p, lock_root=tmp_path):
        process = subprocess.Popen(
            [sys.executable, '-c', code, str(p), str(tmp_path), str(entered)],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        )
        sleep(0.25)
        assert process.poll() is None and not entered.exists()
    assert process.wait(timeout=10) == 0 and entered.exists()

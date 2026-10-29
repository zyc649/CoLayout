"""Exercise file transport failures and configuration before any connection."""

import json
from types import SimpleNamespace

import pytest

from colayout_lite.model import LiteError
from colayout_lite.transport import NativeTransport, load_connection


def result(status="success", errors=None, output="nil"):
    return SimpleNamespace(
        status=SimpleNamespace(value=status),
        errors=errors or [],
        output=output,
        warnings=[],
    )


def transport(tmp_path, client):
    native = NativeTransport.__new__(NativeTransport)
    native.state = tmp_path
    native.client = client
    return native


@pytest.mark.parametrize("reply", [None, [], False, ["relative.sexpr"], [123]])
def test_invalid_export_never_starts_download(tmp_path, reply):
    native = transport(tmp_path, SimpleNamespace())
    with pytest.raises(LiteError, match="INVALID_NATIVE_RESPONSE"):
        native._download_export(reply, "out.sexpr")


def test_failed_download_with_empty_errors_is_not_success(tmp_path):
    native = transport(
        tmp_path, SimpleNamespace(download_file=lambda *_: result("error"))
    )
    with pytest.raises(LiteError, match="DOWNLOAD_FAILED"):
        native._download_export(["/remote/file"], "out.sexpr")


def test_successful_download_must_produce_file(tmp_path):
    native = transport(tmp_path, SimpleNamespace(download_file=lambda *_: result()))
    with pytest.raises(LiteError, match="DOWNLOAD_FAILED"):
        native._download_export(["/remote/file"], "out.sexpr")


def test_partial_file_is_rejected(tmp_path):
    path = tmp_path / "partial.sexpr"
    path.write_text("(1 (2", encoding="utf-8")
    with pytest.raises(LiteError, match="TRUNCATED_RESPONSE"):
        NativeTransport._parse_export(path)


def test_failed_upload_never_executes_native_transaction(tmp_path):
    client = SimpleNamespace(load_il=lambda *_: result("error", ["upload failed"]))
    native = transport(tmp_path, client)
    with pytest.raises(LiteError, match="NATIVE_ERROR"):
        native.transact("L", "C", {"request_id": "request"})
    assert len(list((tmp_path / "requests").glob("*.result.json"))) == 1


def test_config_missing_env_fails_before_client_creation(tmp_path, monkeypatch):
    path = tmp_path / "connection.json"
    path.write_text(
        json.dumps(
            {
                "bridge_env": str(tmp_path / "missing.env"),
                "state_directory": str(tmp_path / "state"),
                "allowed_remote_root": "/project",
            }
        )
    )

    def forbidden(*args, **kwargs):
        pytest.fail("must not connect")

    monkeypatch.setattr("colayout_lite.transport.VirtuosoClient.from_env", forbidden)
    with pytest.raises(LiteError, match="BRIDGE_ENV_MISSING"):
        NativeTransport(path)
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize(
    "content", ["null", "[]", "{}", "{", '{"schema_version":"future"}']
)
def test_bad_config_has_actionable_error(tmp_path, content):
    path = tmp_path / "connection.json"
    path.write_text(content)
    with pytest.raises(LiteError, match="INVALID_CONNECTION_CONFIG"):
        load_connection(path)


def test_relative_fields_remain_relative_to_project_root(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("VB_REMOTE_HOST=localhost")
    monkeypatch.setattr("colayout_lite.transport.ROOT", project)
    path = tmp_path / "elsewhere.json"
    path.write_text(
        json.dumps(
            {
                "bridge_env": ".env",
                "state_directory": "state",
                "allowed_remote_root": "/project",
            }
        )
    )
    actual_path, _, env = load_connection(path)
    assert actual_path == path and env == project / ".env"

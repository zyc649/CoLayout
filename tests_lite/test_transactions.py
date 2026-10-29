"""Fault tests of Adapter itself, without SSH, Virtuoso or Qt."""

import json
from pathlib import Path

import pytest

from colayout_lite.adapter import Adapter
from colayout_lite.editor import Editor, projected
from colayout_lite.model import LiteError, Shape, Snapshot, Workspace
from colayout_lite.technology import TechnologyProfile
from colayout_lite.transactions import (
    Receipt,
    TransactionJournal,
    write_json_atomic,
)


class OfflineNative:
    def __init__(self, state):
        self.state = state
        self.receipts = {}
        self.calls = []
        self.submissions = 0
        self.behavior = "saved"
        self.corrupt_receipt = None

    def call(self, name, *values):
        self.calls.append((name, values))
        if name == "ltReceiptRead":
            return self.receipts.get(values[0])
        assert name == "ltRelease"

    def transact(self, library, cell, request):
        self.submissions += 1
        if self.behavior == "lost_before_apply":
            raise TimeoutError("lost before native operation")
        status = "rolled_back" if self.behavior == "rolled_back" else "saved"
        if status == "saved":
            self.current = self.current.model_copy(
                update={"objects": projected(self.draft), "counter": "2"}
            )
        receipt = [
            "colayout-lite-receipt-1",
            request["request_id"],
            request["hash"],
            status,
            library,
            cell,
            request["backup"],
            ["create", "r", 0],
        ]
        self.receipts[request["request_id"]] = receipt
        if self.behavior == "lost_after_apply":
            raise TimeoutError("lost after native operation")
        return self.corrupt_receipt(receipt) if self.corrupt_receipt else receipt


@pytest.fixture
def rig(tmp_path):
    profile = TechnologyProfile(
        id="test",
        label="test",
        native_fingerprint="fp",
        dbu_per_micron=1000,
        grid=1,
        writable_lpps=(("M1", "drawing"),),
        layers=[dict(layer="M1", purpose="drawing", material="metal")],
        vias={},
    )
    baseline = Snapshot(
        library="L",
        cell="C",
        library_path="/test/L",
        session="s",
        counter="1",
        dirty=False,
        dbu_per_micron=1000,
        grid=1,
        objects={},
        routes={},
        fig_groups={},
        technology_fingerprint="fp",
    )
    editor = Editor(Workspace(baseline=baseline, profile_id=profile.id), profile)
    editor.create(
        Shape(kind="rect", lpp=("M1", "drawing"), bbox=((0, 0), (20, 20))), uid="r"
    )
    native = OfflineNative(tmp_path)
    native.current = baseline
    native.draft = editor.w
    adapter = Adapter(native)
    adapter.read = lambda *_: (native.current, profile)
    return adapter, native, editor


def persisted(adapter, workspace):
    return Workspace.model_validate_json(
        (adapter.state / "workspaces" / f"{workspace.id}.json").read_text(
            encoding="utf-8"
        )
    )


def test_saved_commit_and_duplicate_do_not_apply_twice(rig):
    adapter, native, editor = rig
    draft = editor.w
    result = adapter.commit(draft, request_id="request")
    duplicate = adapter.commit(draft, request_id="request")
    assert result.state == duplicate.state == "clean"
    assert result.baseline.semantic() == duplicate.baseline.semantic()
    assert native.submissions == 1


def test_reused_id_preserves_original_snapshot_and_journal(rig):
    adapter, native, editor = rig
    original = editor.w
    adapter.commit(original, request_id="request")
    journal = TransactionJournal(adapter.state, "request")
    before = (journal.path.read_bytes(), journal.workspace_path.read_bytes())
    editor.edit("r", bbox=((0, 0), (40, 20)))
    with pytest.raises(LiteError, match="REQUEST_ID_REUSED"):
        adapter.commit(editor.w, request_id="request")
    assert before == (journal.path.read_bytes(), journal.workspace_path.read_bytes())
    assert native.submissions == 1


@pytest.mark.parametrize("behavior", ["lost_before_apply", "lost_after_apply"])
def test_lost_reply_must_reconcile_before_stale_draft_retry(rig, behavior):
    adapter, native, editor = rig
    native.behavior = behavior
    with pytest.raises(TimeoutError):
        adapter.commit(editor.w, request_id="lost")
    pending = persisted(adapter, editor.w)
    assert pending.state == "indeterminate"
    # The caller still owns the pre-call immutable Workspace. It must not be
    # able to bypass the persisted pending state by simply choosing a new ID.
    with pytest.raises(LiteError, match="RECONCILE_BEFORE_RETRY"):
        adapter.commit(editor.w, request_id="new-id")
    recovered = adapter.reconcile(pending)
    assert recovered.state == ("clean" if behavior == "lost_after_apply" else "editing")
    assert native.submissions == 1
    journal = TransactionJournal(adapter.state, "lost").read()
    assert journal["status"] == recovered.last_result["status"]
    assert journal["reconciled"] is True


def test_rollback_preserves_draft_and_allows_corrected_retry(rig):
    adapter, native, editor = rig
    native.behavior = "rolled_back"
    failed = adapter.commit(editor.w, request_id="rollback")
    assert failed.state == "editing" and failed.operations == editor.w.operations
    assert failed.last_result["status"] == "rolled_back"
    native.behavior = "saved"
    assert adapter.commit(failed, request_id="retry").state == "clean"


@pytest.mark.parametrize(
    "slot,replacement",
    [
        (0, "wrong-version"),
        (1, "wrong-id"),
        (2, "wrong-hash"),
        (3, "unknown-status"),
        (4, "wrong-library"),
        (5, "wrong-cell"),
    ],
)
def test_bad_receipt_never_reports_success(rig, slot, replacement):
    adapter, native, editor = rig

    def corrupt(receipt):
        receipt = list(receipt)
        receipt[slot] = replacement
        return receipt

    native.corrupt_receipt = corrupt
    with pytest.raises(LiteError, match="RECEIPT"):
        adapter.commit(editor.w, request_id="bad-reply")
    assert persisted(adapter, editor.w).state == "indeterminate"


def test_reconcile_rejects_changed_pending_payload_without_native_access(rig):
    adapter, native, editor = rig
    native.behavior = "lost_before_apply"
    with pytest.raises(TimeoutError):
        adapter.commit(editor.w, request_id="lost")
    pending = persisted(adapter, editor.w)
    op = pending.operations[0]
    changed = pending.model_copy(
        update={
            "operations": (
                op.model_copy(
                    update={
                        "shape": op.shape.model_copy(
                            update={"bbox": ((0, 0), (40, 20))}
                        )
                    }
                ),
            )
        }
    )
    calls = len(native.calls)
    with pytest.raises(LiteError, match="RECEIPT_MISMATCH|REQUEST_ID_REUSED"):
        adapter.reconcile(changed)
    assert len(native.calls) == calls


def test_empty_pending_workspace_is_not_a_noop(rig):
    adapter, native, editor = rig
    pending = editor.w.model_copy(update={"operations": (), "state": "indeterminate"})
    with pytest.raises(LiteError, match="RECONCILE_BEFORE_RETRY"):
        adapter.commit(pending)
    assert native.submissions == 0


def test_orphan_snapshot_is_never_overwritten(rig):
    adapter, native, editor = rig
    journal = TransactionJournal(adapter.state, "orphan")
    editor.w.save(journal.workspace_path)
    before = journal.workspace_path.read_bytes()
    editor.edit("r", bbox=((0, 0), (40, 20)))
    with pytest.raises(LiteError, match="REQUEST_ID_REUSED"):
        adapter.commit(editor.w, request_id="orphan")
    assert journal.workspace_path.read_bytes() == before
    assert native.submissions == 0


def test_atomic_journal_replace_failure_preserves_previous_record(
    tmp_path, monkeypatch
):
    path = tmp_path / "journal.json"
    write_json_atomic(path, {"status": "prepared"})

    def fail(*_):
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        write_json_atomic(path, {"status": "saved"})
    assert json.loads(path.read_text()) == {"status": "prepared"}
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("raw", [[], False, "text", ["colayout-lite-receipt-1"]])
def test_malformed_receipt_has_protocol_error(raw):
    with pytest.raises(LiteError, match="INVALID_RECEIPT"):
        Receipt.parse(raw, request_id="r", expected_hash="h", library="L", cell="C")


def test_readback_mismatch_requires_recovery_and_keeps_draft(rig):
    adapter, native, editor = rig
    transact = native.transact

    def wrong_readback(*args):
        receipt = transact(*args)
        native.current = native.current.model_copy(update={"objects": {}})
        return receipt

    native.transact = wrong_readback
    with pytest.raises(LiteError, match="READBACK_OBJECT_SET"):
        adapter.commit(editor.w, request_id="mismatch")
    saved = adapter.load_workspace(editor.w.id)
    assert saved.state == "indeterminate" and saved.operations == editor.w.operations


def test_source_conflict_fails_before_transaction_artifacts(rig):
    adapter, native, editor = rig
    native.current = native.current.model_copy(update={"opaque_counts": {"other": 1}})
    with pytest.raises(LiteError, match="SOURCE_CONFLICT"):
        adapter.commit(editor.w, request_id="conflict")
    assert native.submissions == 0
    assert not (adapter.state / "transactions").exists()


def test_original_error_survives_recovery_disk_failure(rig, monkeypatch):
    adapter, native, editor = rig
    native.behavior = "lost_before_apply"
    original_save = adapter.save
    calls = 0

    def fail_recovery_save(workspace):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("disk unavailable")
        original_save(workspace)

    monkeypatch.setattr(adapter, "save", fail_recovery_save)
    with pytest.raises(TimeoutError) as error:
        adapter.commit(editor.w, request_id="disk")
    assert any("disk unavailable" in note for note in error.value.__notes__)
    assert adapter.load_workspace(editor.w.id).state == "submitting"


def test_release_failure_is_diagnostic_not_a_failed_commit(rig):
    adapter, native, editor = rig
    original = native.call

    def call(name, *values):
        if name == "ltRelease":
            raise RuntimeError("release unavailable")
        return original(name, *values)

    native.call = call
    assert adapter.commit(editor.w, request_id="release").state == "clean"
    assert (
        "release unavailable"
        in TransactionJournal(adapter.state, "release").read()["resource_release_error"]
    )

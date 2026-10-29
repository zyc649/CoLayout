from colayout_lite.temporary_cleanup import candidates
from colayout_lite.transactions import Receipt


def test_cleanup_candidates_require_completed_native_receipts_and_temporary_target():
    temp='COLAYOUT_MVP_LITE_PREVIEW_abc'
    rows=[Receipt('a','hash','saved','L',temp,'backup-a'),
          Receipt('b','hash','saved','L','real_layout','real-backup'),
          Receipt('c','hash','saved','L','COLAYOUT_MVP_LITE_TARGET_user','user-backup'),
          Receipt('d','hash','applying','L',temp,'pending-backup')]
    ready,blocked=candidates(rows)
    assert ('L','real_layout') not in ready and ('L','real-backup') not in ready
    assert ('L','COLAYOUT_MVP_LITE_TARGET_user') not in ready
    assert ('L','user-backup') not in ready
    assert ('L',temp) in blocked and ('L','pending-backup') in blocked
    assert ready[('L','backup-a')]['source']==temp

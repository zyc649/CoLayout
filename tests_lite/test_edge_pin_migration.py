import json
from colayout_lite.document import load_document, save_document
from colayout_lite.pin_placement import center
from colayout_lite.regions.actions import RegionActions
from colayout_lite.human_edit import HumanEdit
from tests_lite.test_regions import region_editor, profile


def test_legacy_interior_pin_moves_to_free_edge_once_with_original_backup(region_editor, tmp_path):
    e = region_editor
    rid = RegionActions(e).create((-1000, -1000, 7000, 7000))
    p = next(iter(e.w.local_data.regions[rid].pins.values()))
    path = tmp_path / 'old.colayout.json'
    save_document(path, e.w, e.profile)
    data = json.loads(path.read_text(encoding='utf8'))
    pin = data['workspace']['local_data']['regions'][rid]['pins'][p.id]
    pin['bbox'] = [[2000, 2500], [3200, 3700]]
    pin['on_edge'] = False
    path.write_text(json.dumps(data), encoding='utf8')
    original = path.read_bytes()
    loaded, profile = load_document(path)
    moved = loaded.local_data.regions[rid].pins[p.id]
    x, y = center(moved)
    assert x in (-1000, 7000) or y in (-1000, 7000)
    assert loaded.operations == e.w.operations and loaded.baseline == e.w.baseline
    backups = list(tmp_path.glob('*.before-edge-pins-*.json'))
    assert (
        len(backups) == 1 and backups[0].read_bytes() == original and path.read_bytes() == original
    )
    assert 'on_edge' not in moved.model_dump()
    save_document(path, loaded, profile)
    assert load_document(path)[0] == loaded


def test_new_position_requests_cannot_keep_pin_inside(region_editor):
    e = region_editor
    rid = RegionActions(e).create((-1000, -1000, 7000, 7000))
    p = next(iter(e.w.local_data.regions[rid].pins.values()))
    HumanEdit(e).adjust_pin(rid, p.id, 2000, 5000)
    x, y = center(e.w.local_data.regions[rid].pins[p.id])
    assert x in (-1000, 7000) or y in (-1000, 7000)

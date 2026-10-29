"""One-time legacy geometry normalization; no interior mode in new edits."""

from pathlib import Path
from hashlib import sha256
from .pin_placement import center
from .model import LiteError


def normalize(workspace, profile, *, path=None):
    pending = []
    for region in workspace.local_data.regions.values():
        (a, b), (c, d) = region.bbox
        for pin in region.pins.values():
            x, y = center(pin)
            if x not in (a, c) and y not in (b, d):
                pending.append((region.id, pin.id))
    if not pending or workspace.state in ('submitting', 'indeterminate', 'conflict'):
        return workspace
    if path is not None:
        path = Path(path)
        raw = path.read_bytes()
        backup = path.with_name(
            path.stem + '.before-edge-pins-' + sha256(raw).hexdigest()[:12] + path.suffix
        )
        if not backup.exists():
            backup.write_bytes(raw)
    from .editor import Editor
    from .human_edit import HumanEdit

    editor = Editor(workspace, profile)
    with editor.transaction() as staged:
        for rid, pid in pending:
            staged.scope_id = rid
            region = staged.w.local_data.regions[rid]
            pin = region.pins[pid]
            x, y = center(pin)
            (a, b), (c, d) = region.bbox
            grid = profile.grid
            hx = (pin.bbox[1][0] - pin.bbox[0][0]) // 2
            hy = (pin.bbox[1][1] - pin.bbox[0][1]) // 2
            xs = {x, a, c}
            ys = {y, b, d}
            for other in region.pins.values():
                xs.update((other.bbox[0][0] - hx - grid, other.bbox[1][0] + hx + grid))
                ys.update((other.bbox[0][1] - hy - grid, other.bbox[1][1] + hy + grid))
            candidates = {(xx, yy) for xx in (a, c) for yy in ys if b <= yy <= d}
            candidates.update((xx, yy) for yy in (b, d) for xx in xs if a <= xx <= c)
            errors = []
            for xx, yy in sorted(
                candidates, key=lambda xy: ((xy[0] - x) ** 2 + (xy[1] - y) ** 2, xy)
            ):
                try:
                    HumanEdit(staged).adjust_pin(rid, pid, xx, yy)
                except LiteError as exc:
                    errors.append(exc.code)
                else:
                    break
            else:
                raise LiteError(
                    'PIN_EDGE_MIGRATION_BLOCKED',
                    '旧内部 PIN 找不到不重叠且未禁布的边缘位置；原文档与备份保留。',
                    region_id=rid,
                    pin_id=pid,
                    reasons=sorted(set(errors)),
                )
        staged.scope_id = editor.scope_id
    return editor.w

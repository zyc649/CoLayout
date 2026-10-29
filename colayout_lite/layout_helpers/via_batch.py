"""Validate the combined geometry of an atomic multi-position via edit."""

from shapely.geometry import box
from shapely.ops import unary_union
from ..model import LiteError
from ..drc.local import run
from ..drc.models import Region
from ..drc.design_warnings import blocking
from ..editor import projected
from .via_candidates import footprints
from .via_checks import checked_candidate


def verify(before, editor, values, rules, cancelled):
    p = editor.profile
    s = p.dbu_per_micron
    roi = unary_union([box(*(v * s for v in row.bounds_um)) for row in values])
    x, y, xx, yy = roi.bounds

    def checkpoint():
        if cancelled.is_set():
            raise LiteError('EDIT_CANCELLED', '整批未采用。')

    baseline = run(
        before,
        p,
        rules,
        Region(bbox=((round(x), round(y)), (round(xx), round(yy)))),
        checkpoint=checkpoint,
        scope_id=editor.scope_id,
    )
    if not baseline.coverage['complete_for_configured_subset']:
        raise LiteError('AUTOVIA_BATCH_CHECK_INCOMPLETE', edit_applied=False)
    old = projected(before)
    new = projected(editor.w)
    layers = {}
    for uid in new.keys() - old.keys():
        for layer, g in footprints(new[uid].shape, p).items():
            layers.setdefault(layer, []).append(g)
    if not layers:
        return {'reused_only': True, 'new_errors': 0}
    layers = {l: unary_union(gs) for l, gs in layers.items()}
    valid, result = checked_candidate(
        before,
        editor.w,
        p,
        rules,
        roi,
        layers,
        {m.id for m in baseline.markers if blocking(m)},
        checkpoint,
        scope_id=editor.scope_id,
    )
    if not valid:
        raise LiteError(
            'AUTOVIA_BATCH_CHECK_FAILED',
            '组合后的几何未通过本地校验；整批未采用。',
            check=result,
            edit_applied=False,
        )
    return result

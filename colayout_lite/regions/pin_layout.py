"""Small deterministic edge-placement helper; never drops or merges ports."""

from math import ceil
from ..pin_placement import candidate, center
from ..interface_layers import overlaps_layers, fully_blocked
from ..model import LiteError
from .models import overlaps


def fit_resized_pins(region,profile,keepouts=()):
    """Retain projected positions where possible; never remove/merge PINs."""
    keepouts=tuple(keepouts);result={}
    for pin in region.pins.values():
        conflict=any(overlaps_layers(pin,p,profile) and overlaps(pin.bbox,p.bbox) for p in result.values())
        conflict|=any(fully_blocked(pin,k.layers,profile) and overlaps(pin.bbox,k.bbox) for k in keepouts)
        if conflict:
            pin=available_position(region,pin,result.values(),profile,keepouts=keepouts,
                                   preferred=center(pin),total=len(region.pins))
        result[pin.id]=pin
    return result


def available_position(region, pin, others, profile, *, keepouts=(), preferred=None, total=1):
    others = list(others)
    (x, y), (xx, yy) = region.bbox
    width = pin.bbox[1][0] - pin.bbox[0][0]
    height = pin.bbox[1][1] - pin.bbox[0][1]
    grid = profile.grid
    sides = ('b', 't', 'l', 'r') if xx - x > 2 * (yy - y) else ('l', 'r', 'b', 't')
    candidates = []
    seen = set()
    for side_index, side in enumerate(sides):
        vertical = side in ('l', 'r')
        lo, hi = (y, yy) if vertical else (x, xx)
        half = (height if vertical else width) / 2
        # Balanced first pass on the two longest/most useful edges. Then test
        # a bounded denser grid and free intervals next to existing ports.
        count = max(1, ceil(total / 2))
        offsets = [lo + (hi - lo) * (i + 1) / (count + 1) for i in range(count)]
        offsets += [lo + (hi - lo) * (i + 1) / 65 for i in range(64)]
        for other in others:
            a, b = other.bbox
            offsets += [
                a[1 if vertical else 0] - half - grid,
                b[1 if vertical else 0] + half + grid,
            ]
        for offset_index, offset in enumerate(offsets):
            offset = round(offset / grid) * grid
            if not lo + half <= offset <= hi - half:
                continue
            point = (
                (x if side == 'l' else xx, offset)
                if vertical
                else (offset, y if side == 'b' else yy)
            )
            if point in seen:
                continue
            seen.add(point)
            phase = (0 if side_index < 2 else 1) if offset_index < count else 2
            candidates.append(((phase, offset_index, side_index), point))
    candidates = [point for _, point in sorted(candidates)]
    if preferred is not None:
        candidates.sort(key=lambda v: (v[0] - preferred[0]) ** 2 + (v[1] - preferred[1]) ** 2)
    for point in candidates:
        placed = candidate(region, pin, *point, grid)
        if any(
            overlaps_layers(placed, o, profile) and overlaps(placed.bbox, o.bbox) for o in others
        ):
            continue
        if any(
            fully_blocked(placed, k.layers, profile) and overlaps(placed.bbox, k.bbox)
            for k in keepouts
        ):
            continue
        return placed
    scale = profile.dbu_per_micron
    raise LiteError(
        'INTERFACE_PIN_CAPACITY',
        '未找到不重叠的默认边缘 PIN 位置；请扩大操作区的可用边长或调整已有 PIN。没有丢弃接口或修改版图。',
        region_id=region.id,
        pin_name=pin.name,
        net=pin.net,
        pin_count=len(others) + 1,
        pin_size_um=[width / scale, height / scale],
        existing_pin_ids=[p.id for p in others],
        suggested_long_edge_um=(ceil((len(others) + 1) / 2) + 1)
        * (max(width, height) + grid)
        / scale,
        suggestion_is_estimate=True,
    )

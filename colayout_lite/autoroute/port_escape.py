"""Reserve a short exit and legal outside via landing for child interfaces.

A boundary marker can be narrower than the wire/via. Reserving its marker
alone lets an earlier net seal the exit before the next net can change layer.
Reservations are routing constraints only, never assumed physical copper.
"""

from math import ceil
from shapely.geometry import box
from .geometry import decode, landing_box


def escapes(problem):
    rules = {r.name: r for r in problem.layers}
    barriers = {}
    for b in problem.barriers:
        barriers.setdefault(b.owner, decode(b.geometry).bounds)
    rows = []
    grid = problem.grid
    for pin in problem.pins:
        if not pin['local'] or pin.get('owner') not in barriers:
            continue
        a, b, c, d = barriers[pin['owner']]
        for f in pin['figures']:
            layer = f['layer']
            if layer not in rules:
                continue
            g = decode(f['geometry'])
            x, y, xx, yy = g.bounds
            cx = (x + xx) / 2
            cy = (y + yy) / 2
            side = (
                'left'
                if xx <= a + grid
                else 'right'
                if x >= c - grid
                else 'bottom'
                if yy <= b + grid
                else 'top'
                if y >= d - grid
                else None
            )
            if side is None:
                continue
            vias = [v for v in problem.via_rules if any(f.layer == layer for f in v.footprints)]
            footprints = [f for v in vias for f in v.footprints if f.layer in rules]
            radius = max(
                [rules[layer].width / 2]
                + [max(abs(n) for n in decode(f.geometry).bounds) for f in footprints]
            )
            # A same-net M2 piece inside an opaque child still needs spacing:
            # the parent cannot bridge to it through a prohibited layer.
            gap = max([rules[layer].spacing] + [rules[f.layer].spacing for f in footprints])
            distance = ceil((radius + gap + grid) / grid) * grid
            if side == 'left':
                cx = a - distance
            elif side == 'right':
                cx = c + distance
            elif side == 'bottom':
                cy = b - distance
            else:
                cy = d + distance
            cx = round(cx / grid) * grid
            cy = round(cy / grid) * grid
            pad = box(cx - radius, cy - radius, cx + radius, cy + radius)
            if not box(*problem.bounds[0], *problem.bounds[1]).covers(pad):
                continue
            lo, hi = landing_box(g, rules[layer].width, grid, problem.bounds)
            # Rectangular union envelope is conservative and tiny compared to
            # the module. All physical route/via checks still run afterwards.
            exit_box = box(
                min(lo[0], pad.bounds[0]),
                min(lo[1], pad.bounds[1]),
                max(hi[0], pad.bounds[2]),
                max(hi[1], pad.bounds[3]),
            )
            rows.append((pin['net'], layer, exit_box, pin['id'], (cx, cy)))
            for other in {f.layer for f in footprints} - {layer}:
                rows.append((pin['net'], other, pad, pin['id'], (cx, cy)))
    return rows

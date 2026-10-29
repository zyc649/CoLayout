"""Orthogonal empty gaps between facing edges of one connected metal polygon."""

from shapely.geometry import LineString, box
from shapely.geometry.polygon import orient
from shapely.strtree import STRtree


def orthogonal_notches(material, limit, direct, roi, checkpoint=lambda: None):
    parts = list(material.geoms) if hasattr(material, 'geoms') else [material]
    seen = set()
    for part in parts:
        if part.is_empty or part.geom_type != 'Polygon':
            continue
        polygon = orient(part, sign=1)
        segments = []
        for ring in (polygon.exterior, *polygon.interiors):
            points = list(ring.coords)
            for a, b in zip(points, points[1:]):
                if a == b or (a[0] != b[0] and a[1] != b[1]):
                    continue
                vertical = a[0] == b[0]
                axis = 0 if vertical else 1
                coordinate = a[axis]
                low, high = sorted((a[1 - axis], b[1 - axis]))
                # All rings have metal to the left; outward points into gaps.
                normal = (1 if b[1] > a[1] else -1) if vertical else (-1 if b[0] > a[0] else 1)
                segments.append((axis, coordinate, low, high, normal, LineString([a, b])))
        if not segments:
            continue
        tree = STRtree([s[-1] for s in segments])
        for i, a in enumerate(segments):
            checkpoint()
            for j in tree.query(a[-1].buffer(limit, cap_style='square')):
                if j <= i:
                    continue
                b = segments[j]
                if a[0] != b[0] or a[4] == b[4]:
                    continue
                left, right = sorted((a, b), key=lambda s: s[1])
                gap = right[1] - left[1]
                lo = max(a[2], b[2])
                hi = min(a[3], b[3])
                if gap <= 1e-6 or gap + 1e-6 >= limit or hi - lo <= 1e-6:
                    continue
                if left[4] != 1 or right[4] != -1:
                    continue
                bounds = (left[1], lo, right[1], hi) if a[0] == 0 else (lo, left[1], hi, right[1])
                zone = box(*bounds)
                if bounds in seen or not zone.intersects(roi):
                    continue
                if zone.intersection(material).area > 1e-6:
                    continue
                if not zone.boundary.intersects(direct):
                    continue
                seen.add(bounds)
                yield zone, gap

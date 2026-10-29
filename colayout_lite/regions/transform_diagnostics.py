"""Actionable hierarchy failures for an atomic rigid transformation."""

from .models import contains, overlaps
from ..model import LiteError


def failure(local, changed, scale):
    def um(bounds):
        return [v / scale for pt in bounds for v in pt]

    ordered = sorted(local.regions.values(), key=lambda r: r.id not in changed)
    for region in ordered:
        parent = local.regions.get(region.parent_id)
        if parent and not contains(parent.bbox, region.bbox):
            return LiteError(
                'REGION_TRANSFORM_INVALID',
                f'“{region.name}”变换后超出上层“{parent.name}”的边界；整批未采用。',
                reason='outside_parent',
                region_id=region.id,
                parent_id=parent.id,
                proposed_bounds_um=um(region.bbox),
                parent_bounds_um=um(parent.bbox),
            )
        for other in ordered:
            if (
                other.id != region.id
                and other.parent_id == region.parent_id
                and overlaps(region.bbox, other.bbox)
            ):
                return LiteError(
                    'REGION_TRANSFORM_INVALID',
                    f'“{region.name}”变换后与“{other.name}”重叠；整批未采用。',
                    reason='sibling_overlap',
                    region_id=region.id,
                    other_region_id=other.id,
                    proposed_bounds_um=um(region.bbox),
                    other_bounds_um=um(other.bbox),
                )
    return LiteError(
        'REGION_TRANSFORM_INVALID',
        '变换后接口或层次不满足约束；整批未采用。',
        region_ids=sorted(changed),
    )

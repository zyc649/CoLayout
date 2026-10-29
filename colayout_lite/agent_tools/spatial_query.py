"""Authorized read filters over exact existing geometry, with no DRC or halo."""

from math import isfinite
from shapely.geometry import box
from ..geometry import shape_figure, via_figures
from ..materials import polygon_from_figure
from ..model import LiteError
from ..regions.query import object_bounds


class SpatialQuery:
    def __init__(self, workspace, profile, region_id, bounds_um=None, layers=None):
        self.scale = profile.dbu_per_micron
        self.bounds_um = bounds_um
        self.layers = set(layers) if layers is not None else None
        self.active = bounds_um is not None or layers is not None
        self.roi = None
        self.warnings = []
        if self.layers is not None:
            unknown = self.layers - {row['layer'] for row in profile.layers}
            if unknown:
                raise LiteError(
                    'QUERY_LAYER_UNKNOWN', '查询图层未在当前工艺中声明。', layers=sorted(unknown)
                )
        if bounds_um is not None:
            if (
                not all(isfinite(v) for v in bounds_um)
                or bounds_um[0] >= bounds_um[2]
                or bounds_um[1] >= bounds_um[3]
            ):
                raise LiteError(
                    'INVALID_QUERY_BOUNDS',
                    '范围须为有限且有序的 [xmin,ymin,xmax,ymax]，宽高必须为正。',
                    bounds_um=list(bounds_um),
                )
            (a, b), (c, d) = workspace.local_data.regions[region_id].bbox
            x, y, xx, yy = (v * self.scale for v in bounds_um)
            if not (a <= x < xx <= c and b <= y < yy <= d):
                raise LiteError(
                    'QUERY_OUTSIDE_REGION',
                    '查询范围必须完全位于已接入操作区内。',
                    bounds_um=list(bounds_um),
                    region_bounds_um=[
                        a / self.scale,
                        b / self.scale,
                        c / self.scale,
                        d / self.scale,
                    ],
                )
            self.roi = box(x, y, xx, yy)

    def matches(self, layer, geometry):
        return (
            (self.layers is None or layer in self.layers)
            and not geometry.is_empty
            and (self.roi is None or geometry.intersects(self.roi))
        )

    def bounds_match(self, bounds):
        return bounds is not None and (
            self.roi is None or box(*bounds[0], *bounds[1]).intersects(self.roi)
        )

    def figures_match(self, figures):
        return sorted({layer for layer, g in figures if self.matches(layer, g)})

    def object_match(self, workspace, profile, obj):
        if obj.kind in ('inst', 'mosaic') or not (obj.shape or obj.mpp):
            if not self.bounds_match(object_bounds(workspace, obj, profile)):
                return None
            return {
                'basis': 'native_bounds_context',
                'layer_independent': True,
                'meaning': '整体原生对象定位；不代表所选层存在内部金属，不展开内部。',
            }
        if not self.bounds_match(object_bounds(workspace, obj, profile)):
            return None
        try:
            if obj.shape:
                fs = (
                    via_figures(obj.shape, profile)
                    if obj.kind == 'stdVia'
                    else [shape_figure(obj.shape)]
                )
                figures = [(f['lpp'][0], polygon_from_figure(f)) for f in fs]
            else:
                from ..mpp_geometry import rows

                figures = rows(workspace, profile, obj)
            matched = self.figures_match(figures)
            return {'basis': 'physical_geometry', 'layers': matched} if matched else None
        except (ValueError, KeyError, TypeError, LiteError) as exc:
            self.warnings.append(
                {'uid': obj.uid, 'kind': 'query_geometry_unavailable', 'message': str(exc)}
            )
            return {
                'basis': 'bounds_only',
                'geometry_available': False,
                'meaning': '精确几何不可用，保守保留外框相交对象，不能据此确认图层。',
            }

    def describe(self):
        return {
            'bounds_um': list(self.bounds_um) if self.bounds_um is not None else None,
            'layers': sorted(self.layers) if self.layers is not None else None,
            'predicate': 'actual geometry intersects closed ROI, including boundary contact',
            'geometry_returned': 'whole objects and whole PIN figures; never editable clipped fragments',
            'via_layers': 'cut and both enclosure metals participate; any matching figure selects the whole via',
            'context': 'native/child bounding boxes and markups are layer-independent context; no internal geometry expansion',
            'halo_um': 0,
            'drc_coverage': False,
            'warnings': self.warnings,
            'selection_complete': not self.warnings,
        }

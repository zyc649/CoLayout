"""Electrical landing of a local interface as seen from one construction level.

The canonical marker straddles the boundary; each side owns only its half.
This does not move a PIN, alter membership or grant edits beyond the boundary.
"""
from shapely.geometry import box


def scoped_figures(workspace, scope_id, pin):
    figures = pin['figures']
    if not pin.get('local'):return figures
    owner = workspace.local_data.regions.get(pin.get('owner'))
    if owner is None:return figures
    boundary = box(*owner.bbox[0], *owner.bbox[1])
    if owner.id == scope_id:
        return [(layer, g.intersection(boundary)) for layer,g in figures if g.intersection(boundary).area]
    if owner.parent_id == scope_id:
        return [(layer, g.difference(boundary)) for layer,g in figures if g.difference(boundary).area]
    return figures

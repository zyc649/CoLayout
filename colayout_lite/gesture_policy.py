"""Pointer preferences only; never restrict Editor permissions or deletion."""
from .editor import projected
from .conduction_rules import ConductionRules


def movable_selection(window,ids):
    if window.selection_ui.move_conductors:return True
    objects=projected(window.editor.w);metals=ConductionRules(window.editor.profile).metals
    for uid in ids:
        obj=objects.get(uid)
        if obj and obj.shape and (obj.kind=='stdVia' or obj.kind in ('rect','path','pathSeg','line','polygon') and obj.shape.lpp[0] in metals):
            return False
    return True

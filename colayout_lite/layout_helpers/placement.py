"""Exact ordered placement using the same body bounds as human transforms."""

from ..actions import dbu
from ..model import Operation, Placement, LiteError, digest
from ..regions.query import object_bounds
from .common import direct_objects, report_bounds, reference_bounds


def objects_and_bounds(editor, uids, orientation=None):
    objects = direct_objects(editor, uids)
    bounds = {}
    placed = {}
    for uid, obj in objects.items():
        if obj.kind != 'inst' or not obj.placement:
            raise LiteError('ARRANGE_REQUIRES_INSTANCE', uid=uid)
        placement = (
            obj.placement.model_copy(update={'orientation': orientation})
            if orientation
            else obj.placement
        )
        placed[uid] = placement
        bounds[uid] = object_bounds(
            editor.w, obj.model_copy(update={'placement': placement}), editor.profile
        )
        if not bounds[uid]:
            raise LiteError('OBJECT_BOUNDS_MISSING', uid=uid)
    return objects, bounds, placed


def publish(editor, objects, placements, bounds, targets):
    operations = []
    grid = editor.profile.grid
    for uid, (x, y) in targets.items():
        original = placements[uid]
        a, b = bounds[uid][0]
        coordinates = (original.origin[0] + x - a, original.origin[1] + y - b)
        origin = tuple(round(v / grid) * grid for v in coordinates)
        if any(abs(v - rounded) > 1e-6 for v, rounded in zip(coordinates, origin)):
            raise LiteError(
                'ALIGNMENT_OFF_GRID', '精确对齐要求落在制造网格之间；请调整对齐基准。', uid=uid
            )
        placement = Placement(origin=origin, orientation=original.orientation)
        operations.append(
            Operation(
                action='transform',
                uid=uid,
                before=digest(objects[uid].semantic()),
                placement=placement,
            )
        )
    editor.apply(operations)
    return {'created_uids': [], 'moved_uids': list(targets), **report_bounds(editor, targets)}


def arrange(editor, args):
    rows = args.rows if args.rows is not None else [args.uids]
    slots = [slot for row in rows for slot in row]
    uids = [s for s in slots if isinstance(s, str)]
    if not uids:
        raise LiteError('ARRANGE_NO_INSTANCES')
    objects, bounds, placements = objects_and_bounds(editor, uids, args.orientation)

    def size(slot):
        if isinstance(slot, str):
            (a, b), (c, d) = bounds[slot]
            return c - a, d - b
        return dbu(slot.width, editor.profile), dbu(slot.height, editor.profile)

    x = dbu(args.x, editor.profile) if args.x is not None else min(b[0][0] for b in bounds.values())
    y = dbu(args.y, editor.profile) if args.y is not None else min(b[0][1] for b in bounds.values())
    gap = dbu(args.spacing, editor.profile)
    row_gap = dbu(args.row_spacing, editor.profile)
    targets = {}
    empty = []
    if args.rows is None and args.direction == 'vertical':
        width = max(size(slot)[0] for slot in slots)
        cy = y
        for slot in slots:
            w, h = size(slot)
            cx = x + ({'left': 0, 'right': width - w, 'center': (width - w) / 2}[args.align])
            if isinstance(slot, str):
                targets[slot] = (cx, cy)
            else:
                empty.append([cx, cy, cx + w, cy + h])
            cy += h + gap
    else:
        heights = [max(size(slot)[1] for slot in row) for row in rows]
        cy = y + sum(heights) + row_gap * (len(rows) - 1)
        for row, height in zip(rows, heights):
            cy -= height
            cx = x
            for slot in row:
                w, h = size(slot)
                py = cy + ({'bottom': 0, 'top': height - h, 'center': (height - h) / 2}[args.align])
                if isinstance(slot, str):
                    targets[slot] = (cx, py)
                else:
                    empty.append([cx, py, cx + w, py + h])
                cx += w + gap
            cy -= row_gap
    result = publish(editor, objects, placements, bounds, targets)
    result.update(
        edge_spacing_um=args.spacing,
        row_spacing_um=args.row_spacing,
        empty_slots_um=[[v / editor.profile.dbu_per_micron for v in b] for b in empty],
        order='rows top to bottom, each row left to right; vertical list bottom to top',
        boundary_basis='shared native body bounds; associated display labels excluded',
    )
    return result


def align(editor, args):
    requested = list(args.uids)
    objects, bounds, placements = objects_and_bounds(editor, requested)
    axis = 0 if args.edge in ('left', 'right', 'center_x') else 1

    def position(b):
        return (
            (b[0][axis] + b[1][axis]) / 2
            if args.edge.startswith('center')
            else b[1][axis]
            if args.edge in ('top', 'right')
            else b[0][axis]
        )

    value = (
        dbu(args.coordinate, editor.profile)
        if args.coordinate is not None
        else position(reference_bounds(editor, args.reference_uid))
    )
    targets = {}
    for uid in args.uids:
        target = list(bounds[uid][0])
        target[axis] += value - position(bounds[uid])
        targets[uid] = target
    result = publish(editor, objects, placements, bounds, targets)
    result.update(edge=args.edge, coordinate_um=value / editor.profile.dbu_per_micron)
    return result

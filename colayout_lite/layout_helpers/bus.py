"""Same-layer parallel paths with exact edge-to-edge spacing."""

from ..actions import Actions, dbu
from ..wire_defaults import default_width
from ..regions.query import metals
from ..model import LiteError
from .common import report_bounds


def create(editor, args):
    if args.lpp[0] not in metals(editor.profile):
        raise LiteError('BUS_REQUIRES_WRITABLE_METAL')
    width = args.width if args.width is not None else default_width(editor.profile, args.lpp[0])
    for value in (width, args.spacing, args.length, args.x, args.y):
        dbu(value, editor.profile)
    created = []
    scale = editor.profile.dbu_per_micron
    start_x, start_y, length = (dbu(v, editor.profile) for v in (args.x, args.y, args.length))
    step = dbu(width, editor.profile) + dbu(args.spacing, editor.profile)
    with editor.transaction() as staged:
        for index in range(args.count):
            x, y = (
                start_x + (index * step if args.direction == 'vertical' else 0),
                start_y + (index * step if args.direction == 'horizontal' else 0),
            )
            end = (x + length, y) if args.direction == 'horizontal' else (x, y + length)
            result = Actions(staged).execute(
                'create_path90',
                {
                    'lpp': args.lpp,
                    'points': [(x / scale, y / scale), (end[0] / scale, end[1] / scale)],
                    'width': width,
                    'style': 'truncateExtend',
                    'net_intent': args.nets[index] if args.nets is not None else args.net_intent,
                },
            )
            created.append(result.uid)
    return {
        'created_uids': created,
        'count': len(created),
        'width_um': width,
        'edge_spacing_um': args.spacing,
        'length_um': args.length,
        'direction': args.direction,
        **report_bounds(editor, created),
    }

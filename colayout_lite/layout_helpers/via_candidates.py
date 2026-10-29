"""Bounded rectangular standard-via search using actual profile footprints."""

from collections import deque
from math import floor, ceil
from shapely.geometry import box
from shapely.ops import unary_union
from ..model import Shape, LiteError
from ..geometry import via_figures
from ..materials import polygon_from_figure
from ..regions.query import metals


def footprints(shape, profile):
    layers = {}
    for figure in via_figures(shape, profile):
        layers.setdefault(figure['lpp'][0], []).append(polygon_from_figure(figure))
    return {layer: unary_union(rows) for layer, rows in layers.items()}


def chain(profile, rules, start, end, definitions=None):
    if start == end:
        raise LiteError('VIA_REQUIRES_DIFFERENT_LAYERS')
    allowed = set(metals(profile))
    available = {}
    rejected = []
    from ..routing_rules import _via_template

    for name, definition in profile.vias.items():
        if definition.get('kind') != 'stdViaDef' or definition.get('cut_pattern'):
            continue
        if not {definition['layer1'], definition['layer2']} <= allowed:
            continue
        try:
            # Explicit path/landing helpers use frozen native dimensions and
            # still run configured local DRC. They are not the grid autorouter,
            # which needs a complete width/spacing/enclosure search rule set.
            _via_template(profile, rules, name, single_default=False, require_complete_rules=False)
        except LiteError as error:
            rejected.append({'definition':name,'code':error.code,'details':error.details})
            continue
        available[name] = (definition['layer1'], definition['layer2'])
    if definitions:
        layer = start
        result = []
        for name in definitions:
            if name not in available or layer not in available[name]:
                raise LiteError('VIA_CHAIN_INVALID', definition=name, rejected_vias=rejected)
            other = next(x for x in available[name] if x != layer)
            result.append((name, layer, other))
            layer = other
        if layer != end:
            raise LiteError('VIA_CHAIN_INVALID')
        return result
    queue = deque([(start, [])])
    seen = {start}
    names = sorted(available, key=lambda n: (n != profile.editor_defaults.get('via_definition'), n))
    while queue:
        layer, path = queue.popleft()
        for name in names:
            if layer not in available[name]:
                continue
            other = next(x for x in available[name] if x != layer)
            if other in seen:
                continue
            route = path + [(name, layer, other)]
            if other == end:
                return route
            seen.add(other)
            queue.append((other, route))
    raise LiteError(
        'VIA_CHAIN_UNAVAILABLE',
        '没有几何完整、可编辑且满足已配置规则的标准金属过孔链。请检查 rejected_vias 和工艺过孔定义。',
        start_layer=start,
        end_layer=end,
        rejected_vias=rejected,
    )


def arrays(profile, name, roi, minimum, budget, net):
    parameters = profile.vias[name]['defaults']
    grid = profile.grid
    base = Shape(
        kind='stdVia',
        origin=(0, 0),
        via_definition=name,
        via_parameters={'cutRows': 1, 'cutColumns': 1},
        net_intent=net,
    )
    bounds = unary_union(list(footprints(base, profile).values())).bounds
    x, y, xx, yy = roi.bounds
    pitch_x = parameters['cutWidth'] + parameters['cutSpacing'][0]
    pitch_y = parameters['cutHeight'] + parameters['cutSpacing'][1]
    columns = min(budget, max(0, floor((xx - x - (bounds[2] - bounds[0])) / pitch_x) + 1))
    rows = min(budget, max(0, floor((yy - y - (bounds[3] - bounds[1])) / pitch_y) + 1))
    if not rows or not columns:
        return

    def sizes(n):
        return {
            v
            for v in (
                n,
                n - 1,
                n - 2,
                int(n * 0.75),
                int(n * 0.5),
                int(n * 0.5) - 1,
                int(n * 0.25),
                2,
                1,
            )
            if 1 <= v <= n
        }

    pairs = {(r, c) for r in sizes(rows) for c in sizes(columns) if minimum <= r * c <= budget}
    pairs.update(
        (r, min(columns, budget // r))
        for r in sizes(rows)
        if r <= budget and r * min(columns, budget // r) >= minimum
    )
    pairs.update(
        (min(rows, budget // c), c)
        for c in sizes(columns)
        if c <= budget and c * min(rows, budget // c) >= minimum
    )
    yielded = set()
    for r, c in sorted(pairs, key=lambda rc: (-rc[0] * rc[1], -rc[1])):
        xmin = bounds[0] - (c - 1) * pitch_x / 2
        xmax = bounds[2] + (c - 1) * pitch_x / 2
        ymin = bounds[1] - (r - 1) * pitch_y / 2
        ymax = bounds[3] + (r - 1) * pitch_y / 2
        for fx, fy in (
            (0.5, 0.5),
            (0, 0),
            (1, 1),
            (0, 1),
            (1, 0),
            (0.25, 0.5),
            (0.75, 0.5),
            (0.5, 0),
            (0.5, 1),
        ):
            ox = round((x - xmin + fx * ((xx - xmax) - (x - xmin))) / grid) * grid
            oy = round((y - ymin + fy * ((yy - ymax) - (y - ymin))) / grid) * grid
            key = (r, c, ox, oy)
            if key in yielded:
                continue
            yielded.add(key)
            if not roi.covers(box(ox + xmin, oy + ymin, ox + xmax, oy + ymax)):
                continue
            shape = base.model_copy(
                update={'origin': (ox, oy), 'via_parameters': {'cutRows': r, 'cutColumns': c}}
            )
            yield shape, r * c


def single_row_arrays(profile,name,roi,minimum,budget,net,direction):
    """Descending cut counts, exhaustive legal-grid origins inside bbox.

    Consumers must enforce a work budget and refuse an unproven smaller result.
    The full footprint is validated by the consumer before DRC/adoption.
    """
    base=Shape(kind='stdVia',origin=(0,0),via_definition=name,
        via_parameters={'cutRows':1,'cutColumns':1},net_intent=net)
    bounds=unary_union(list(footprints(base,profile).values())).bounds
    x,y,xx,yy=roi.bounds;defaults=profile.vias[name]['defaults'];grid=profile.grid
    px=defaults['cutWidth']+defaults['cutSpacing'][0];py=defaults['cutHeight']+defaults['cutSpacing'][1]
    horizontal=direction=='horizontal'
    capacity=min(budget,max(0,floor(((xx-x)-(bounds[2]-bounds[0]))/px)+1) if horizontal else
        max(0,floor(((yy-y)-(bounds[3]-bounds[1]))/py)+1))
    for count in range(capacity,minimum-1,-1):
        r,c=(1,count) if horizontal else (count,1)
        xmin,xmax=bounds[0]-(c-1)*px/2,bounds[2]+(c-1)*px/2
        ymin,ymax=bounds[1]-(r-1)*py/2,bounds[3]+(r-1)*py/2
        lo_x,hi_x=ceil((x-xmin)/grid),floor((xx-xmax)/grid)
        lo_y,hi_y=ceil((y-ymin)/grid),floor((yy-ymax)/grid)
        if lo_x>hi_x or lo_y>hi_y:continue
        seen=set()
        def origins():
            for a,b in ((.5,.5),(0,0),(1,1),(0,1),(1,0),(.25,.5),(.75,.5)):
                yield round(lo_x+a*(hi_x-lo_x)),round(lo_y+b*(hi_y-lo_y))
            for ix in range(lo_x,hi_x+1):
                for iy in range(lo_y,hi_y+1):yield ix,iy
        for ix,iy in origins():
            if (ix,iy) in seen:continue
            seen.add((ix,iy))
            yield base.model_copy(update={'origin':(ix*grid,iy*grid),'via_parameters':{'cutRows':r,'cutColumns':c}}),count

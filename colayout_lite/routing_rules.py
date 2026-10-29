"""Shared routing-layer and frozen standard-via rule discovery."""

from shapely.geometry import box
from .geometry import via_figures
from .model import LiteError, Shape
from .routing_widths import default_width_um

MAX_GRID_NODES = 160000
MAX_SEARCH_STATES = 350000
MAX_VIAS = 2


def _threshold(profile, kind, layer, other=None):
    return max(
        [
            r.value
            for r in profile.rules
            if r.enabled
            and r.kind == kind
            and r.layer == layer
            and (other is None or r.other_layer == other)
        ]
        or [0]
    )


def _via_template(technology, drc, name, *, single_default=True, require_complete_rules=True):
    definition = technology.vias.get(name)
    if not definition or definition.get('kind') != 'stdViaDef':
        raise LiteError('UNSUPPORTED_VIA', str(name))
    if definition.get('cut_pattern') or definition.get('implant1') or definition.get('implant2'):
        raise LiteError(
            'ROUTE_VIA_UNSUPPORTED',
            'Only non-patterned metal-to-metal standard vias are supported.',
            definition=name,
        )
    defaults = definition.get('defaults', {})
    if single_default and (defaults.get('cutRows') != 1 or defaults.get('cutColumns') != 1):
        raise LiteError(
            'ROUTE_VIA_UNSUPPORTED',
            'This router uses one default 1x1 standard via per transition.',
            definition=name,
        )
    shape = Shape(kind='stdVia', origin=(0, 0), via_definition=name,
                  via_parameters={} if single_default else {'cutRows':1,'cutColumns':1})
    try:
        technology.check(shape)
        parameters=technology.effective_via(shape)
        if parameters['cutWidth']<=0 or parameters['cutHeight']<=0:
            raise LiteError('ROUTE_VIA_GEOMETRY_MISSING','Native cut dimensions must be positive.',definition=name)
        figures = via_figures(shape, technology)
    except (KeyError, TypeError, ValueError) as error:
        raise LiteError('ROUTE_VIA_GEOMETRY_MISSING', str(error), definition=name) from error
    footprints = {f['lpp'][0]: box(*f['bbox'][0], *f['bbox'][1]) for f in figures}
    lower, upper, cut = (definition[k] for k in ('layer1', 'layer2', 'cut_layer'))
    for layer in (lower, upper, cut):
        if require_complete_rules and (not _threshold(drc, 'spacing', layer) or (
            layer != cut and not _threshold(drc, 'width', layer)
        )):
            raise LiteError(
                'ROUTE_RULES_MISSING',
                'Via metal width/spacing and cut spacing must be configured.',
                layer=layer,
                definition=name,
            )
        width = min(
            footprints[layer].bounds[2] - footprints[layer].bounds[0],
            footprints[layer].bounds[3] - footprints[layer].bounds[1],
        )
        if width < _threshold(drc, 'width', layer) * technology.dbu_per_micron:
            raise LiteError(
                'ROUTE_VIA_RULE_VIOLATION',
                'Default via primitive is narrower than its configured rule.',
                layer=layer,
                definition=name,
            )
    for layer in (lower, upper):
        enclosure = _threshold(drc, 'enclosure', cut, layer)
        if not enclosure and require_complete_rules:
            raise LiteError(
                'ROUTE_RULES_MISSING',
                'Both via enclosure rules must be configured.',
                cut_layer=cut,
                layer=layer,
                definition=name,
            )
        if enclosure and not footprints[layer].covers(
            footprints[cut].buffer(enclosure * technology.dbu_per_micron, join_style='mitre')
        ):
            raise LiteError(
                'ROUTE_VIA_RULE_VIOLATION',
                'Default via fails configured enclosure.',
                layer=layer,
                definition=name,
            )
    return definition, footprints


def routing_capabilities(technology, drc_profile):
    """JSON-only discovery contract, including unavailable pairs and reasons."""
    drc_profile.check_technology(technology)
    scale = technology.dbu_per_micron
    layers = []
    for name in dict.fromkeys(
        r['layer']
        for r in technology.layers
        if r.get('material') == 'metal' and r.get('purpose') == 'drawing'
    ):
        if (name, 'drawing') not in technology.writable_lpps:
            continue
        width, spacing = (_threshold(drc_profile, kind, name) for kind in ('width', 'spacing'))
        layers.append(
            dict(
                layer=name,
                supported=bool(width and spacing),
                minimum_width_um=width,
                minimum_spacing_um=spacing,
                default_width_um=default_width_um(technology, name, width),
                editor_default_width_um=technology.editor_defaults.get('widths_um', {}).get(name),
                missing_rules=[k for k, v in [('width', width), ('spacing', spacing)] if not v],
            )
        )
    names = {r['layer'] for r in layers if r['supported']}
    pairs = []
    for name, definition in sorted(technology.vias.items()):
        a, b = definition.get('layer1'), definition.get('layer2')
        if a not in names or b not in names:
            continue
        row = dict(layers=[a, b], via_definition=name, supported=True)
        try:
            _, footprints = _via_template(technology, drc_profile, name)
            row['footprints_um'] = {
                layer: [
                    [g.bounds[0] / scale, g.bounds[1] / scale],
                    [g.bounds[2] / scale, g.bounds[3] / scale],
                ]
                for layer, g in footprints.items()
            }
            row['cut_width_rule_checked'] = bool(
                _threshold(drc_profile, 'width', definition['cut_layer'])
            )
            row['cut_geometry_basis'] = (
                'Frozen technology 1x1 standard-via defaults; cut dimensions cannot be changed by this router.'
            )
        except LiteError as error:
            row.update(supported=False, code=error.code, details=error.details, message=str(error))
        pairs.append(row)
    return dict(
        schema_version='colayout-agent-routing-1',
        units='um; component IDs are revision-scoped',
        layers=layers,
        layer_pairs=pairs,
        default_layers=[r['layer'] for r in layers if r['supported']][:1],
        limits=dict(
            max_layers=2,
            max_vias=MAX_VIAS,
            max_grid_nodes=MAX_GRID_NODES,
            max_search_states=MAX_SEARCH_STATES,
            default_via_orientation='R0',
            via_array='1x1 defaults only',
        ),
        parameters=dict(
            start='Intent endpoint, e.g. instance.terminal or $local_pin',
            net='Optional; must match the endpoint intent',
            target_component='Optional current query_net component ID; omitted chooses another physical component',
            layers='One metal, or two connected by one supported standard via definition',
            via_definition='Required only if a two-layer pair has ambiguous supported definitions',
            widths='Optional {layer:width_um}; defaults follow the confirmed per-layer technology widths, with minimum-rule fallback only for old profiles without defaults',
            margin='Optional clearance_um, cannot be lower than any selected spacing rule',
            region='Optional [xmin,ymin,xmax,ymax] in um, whole generated footprints must fit',
            max_vias='Integer 0..2; zero disables layer changes',
        ),
        limitations=[
            'Finite sparse Manhattan search is not a complete autorouter.',
            'Metal and declared metal-to-metal cuts only; no device, poly or diffusion routing.',
            'Local DRC checks the configured subset; detailed coverage is returned.',
            'Routing does not alter instances or claim LVS/signoff.',
            'Unowned conductors remain obstacles even if net_intent matches.',
        ],
        failure_codes={
            'PIN_ACCESS_BLOCKED': 'Try another legal width/layer or move the reported blockers; inspect positions and blocking_object_ids.',
            'NO_ROUTE': 'Enlarge region or enable a supported second layer; finite search does not prove impossibility.',
            'ROUTE_BUDGET_EXCEEDED': 'Reduce region/geometry complexity; no edit is applied.',
            'ROUTE_GEOMETRY_INCOMPLETE': 'Load missing geometry and resolve the reported endpoint identities.',
            'ROUTE_DRC_FAILED': 'Inspect new markers and change route width, region or placement; candidate was not applied.',
            'ROUTE_RULES_MISSING': 'Load confirmed process rules; thresholds are never guessed.',
            'EXISTING_SHORT': 'Repair the reported physical short before routing.',
            'UNKNOWN_COMPONENT': 'Refresh query_net; component IDs are revision-scoped.',
            'ROUTE_TARGET_NOT_REACHED': 'Inspect endpoint landing geometry and partial coverage.',
        },
    )

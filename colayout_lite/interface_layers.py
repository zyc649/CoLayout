"""Alternative metal access for virtual region ports, never electrical bridges."""

ANY_METAL = 'any_metal'
ANY_METAL_LABEL = '任意金属（任选一层）'


def layers(pin, profile):
    if getattr(pin, 'layer_mode', 'single') == ANY_METAL:
        from .regions.query import metals

        return metals(profile)
    return (pin.lpp[0],)


def choice(pin):
    return ANY_METAL if pin.layer_mode == ANY_METAL else pin.lpp[0]


def label(pin):
    return ANY_METAL_LABEL if pin.layer_mode == ANY_METAL else pin.lpp[0]


def overlaps_layers(a, b, profile):
    return bool(set(layers(a, profile)) & set(layers(b, profile)))


def fully_blocked(pin, blocked, profile):
    return set(layers(pin, profile)) <= set(blocked)


def covered(pin, coverage):
    values = list(coverage)
    return bool(values) and (any(values) if pin.get('layer_mode') == ANY_METAL else all(values))

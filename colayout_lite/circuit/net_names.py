"""Native display names never replace the identities of routing groups."""
from collections import defaultdict


def signal_names(connectivity):
    """Resolve only unambiguous, explicitly exported member-to-signal facts."""
    if connectivity is None:
        return {}
    candidates = defaultdict(set)
    terminals = list(connectivity.ports.values())
    for inst in connectivity.instances.values():
        terminals.extend(inst.terminals.values())
    for term in terminals:
        for member, net in term.members.items():
            if net is not None:
                candidates[net].add(term.member_signals.get(member))
    return {net: next(iter(names)) for net, names in candidates.items()
            if len(names) == 1 and None not in names}


def display_net(net, names):
    signal = names.get(net)
    return f'{signal}（连接组 {net}）' if signal and signal != net else net


def pin_signal_names(pins):
    candidates = defaultdict(set)
    for pin in pins:
        if pin.get('net') is not None:
            candidates[pin['net']].add(pin.get('signal'))
    return {net: next(iter(names)) for net, names in candidates.items()
            if len(names) == 1 and None not in names}

"""One helper dispatch used by the region adapter, with shared Editor checks."""

import json
from pydantic import ValidationError
from ..model import LiteError
from .contracts import MODELS


def execute(editor, action, params, *, rules=None, cancelled=None):
    if action not in MODELS:
        raise LiteError('ACTION_NOT_ALLOWED')
    if action == 'create_guard':
        raise LiteError('NATIVE_GUARD_REQUIRES_ASYNC_CONTEXT')
    try:
        args = MODELS[action].model_validate(params)
    except ValidationError as exc:
        raise LiteError('INVALID_ARGUMENTS', str(exc), fields=json.loads(exc.json())) from exc
    if action == 'create_bus':
        from .bus import create

        return create(editor, args)
    if action == 'create_auto_vias':
        from .auto_vias import create

        return create(editor, args, rules, cancelled=cancelled)
    if action == 'create_multilayer_path':
        from .multilayer_path import create

        return create(editor, args, rules, cancelled=cancelled)
    from .placement import arrange, align

    return (arrange if action == 'arrange' else align)(editor, args)

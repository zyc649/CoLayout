"""One human layer selection, committed independently of position-field drafts."""

from ..human_edit import HumanEdit
from ..interface_layers import label
from ..model import LiteError
from ..pin_placement import center


def save_layer(window, region_id, pin_id, layer):
    if window.busy:
        raise LiteError('WORKSPACE_BUSY', '工作区正在处理任务，图层未更改。')
    editor = window.editor
    pin = editor.w.local_data.regions[region_id].pins[pin_id]
    HumanEdit(editor).adjust_pin(region_id, pin_id, *center(pin), layer=layer)
    current = editor.w.local_data.regions[region_id].pins[pin_id]
    # Publication updates the view, but its observer catches disk errors.
    # Explicitly verify persistence before saying the selection was saved.
    try:
        window.save_local()
    except Exception as exc:
        raise LiteError(
            'PIN_SAVE_FAILED',
            '当前设置：' + label(current) + '；保存失败，请重试保存工作区。',
            error=str(exc),
        ) from exc
    return '已保存：' + label(current) + '；可撤销。'

"""Inspector widget sections. Commands and selection remain owned by the inspector."""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QDoubleSpinBox,
    QListWidget,
)
from ..regions.query import metals
from .panel_helpers import _button


def build_region(panel, form):
    panel.name_box = QWidget()
    row = QHBoxLayout(panel.name_box)
    row.setContentsMargins(0, 0, 0, 0)
    panel.name = QLineEdit()
    panel.name.setObjectName('studioRegionName')
    row.addWidget(panel.name, 1)
    panel.rename = _button('重命名', 'studioRenameRegion', panel.rename_region)
    row.addWidget(panel.rename)
    form.addWidget(panel.name_box)
    panel.pin_mode = QComboBox()
    panel.pin_mode.setObjectName('studioRegionPinMode')
    panel.pin_mode.addItem('固定 PIN：连接到指定接口', 'fixed')
    panel.pin_mode.addItem('方位 PIN：先完成内部主体', 'directional')
    panel.pin_mode.setToolTip(
        '方位模式只免除本操作区边缘标记的接入；内部 PIN 和子模块真实接口仍须连接。Agent 接入期间锁定。'
    )
    panel.pin_mode.currentIndexChanged.connect(panel.change_pin_mode)
    form.addWidget(panel.pin_mode)


def build_geometry(panel, form):
    panel.transforms = QWidget()
    row = QHBoxLayout(panel.transforms)
    row.setContentsMargins(0, 0, 0, 0)
    panel.transform_buttons = {}
    for text, action in [
        ('旋转 90°', 'rotate'),
        ('水平镜像', 'mirror_h'),
        ('垂直镜像', 'mirror_v'),
    ]:
        button = _button(
            text, 'studio' + action.title(), lambda checked=False, a=action: panel.command(a)
        )
        row.addWidget(button)
        panel.transform_buttons[action] = button
    form.addWidget(panel.transforms)
    panel.frame_actions = QWidget()
    row = QHBoxLayout(panel.frame_actions)
    row.setContentsMargins(0, 0, 0, 0)
    panel.resize = _button('调整边界', 'studioResizeFrame', panel.toggle_resize)
    panel.resize.setCheckable(True)
    panel.enter = _button('进入模块', 'studioEnterRegion', panel.enter_region)
    row.addWidget(panel.enter)
    row.addWidget(panel.resize)
    panel.tighten = _button('收紧操作区', 'studioTightenRegion', panel.tighten_region)
    panel.tighten.setToolTip('按已有内容收紧外框，保留 PIN 和模式；可撤销。')
    row.addWidget(panel.tighten)
    form.addWidget(panel.frame_actions)
    panel.rect_size = QWidget()
    sizes = QFormLayout(panel.rect_size)
    sizes.setContentsMargins(0, 0, 0, 0)
    panel.rect_width = QDoubleSpinBox()
    panel.rect_height = QDoubleSpinBox()
    for name, field in [('rectWidth', panel.rect_width), ('rectHeight', panel.rect_height)]:
        field.setObjectName(name)
        field.setDecimals(6)
        field.setRange(0.000001, 1e9)
        field.setSuffix(' µm')
    sizes.addRow('宽度', panel.rect_width)
    sizes.addRow('高度', panel.rect_height)
    panel.apply_rect = _button('应用尺寸', 'studioApplyRectSize', panel.apply_rect_size)
    sizes.addRow(panel.apply_rect)
    sizes.addRow(QLabel('以中心为基准；也可开启调整边界拖动。'))
    form.addWidget(panel.rect_size)
    panel.remove = _button('解散操作区', 'studioRemoveObject', panel.remove_object)
    panel.remove.setObjectName('studioRemoveObject')
    panel.remove.setToolTip('解散本地模块保留内部器件、导线和子模块，可撤销。')
    form.addWidget(panel.remove)
    panel.region_checks = QWidget()
    check_row = QHBoxLayout(panel.region_checks)
    check_row.setContentsMargins(0, 0, 0, 0)
    panel.check_local = _button(
        '本地 DRC', 'studioRegionLocalDrc', lambda: panel.check_region('local')
    )
    panel.check_remote = _button(
        '服务器全规则 DRC', 'studioRegionRemoteDrc', lambda: panel.check_region('calibre')
    )
    check_row.addWidget(panel.check_local)
    check_row.addWidget(panel.check_remote)
    form.addWidget(panel.region_checks)
    panel.cleanup_box = QWidget()
    cleanup = QVBoxLayout(panel.cleanup_box)
    cleanup.setContentsMargins(0, 0, 0, 0)
    panel.clear_metal = _button(
        '清除本层金属和过孔', 'studioClearMetal', lambda: panel.clear_routing(False)
    )
    panel.clear_guards = _button(
        '清除本层金属、过孔、保护环及 NWELL', 'studioClearGuards', lambda: panel.clear_routing(True)
    )
    cleanup.addWidget(panel.clear_metal)
    cleanup.addWidget(panel.clear_guards)
    note = QLabel('仅此操作区这一层；保留子模块、器件内部和接口 PIN。可一次撤销。')
    note.setWordWrap(True)
    note.setObjectName('studioMuted')
    cleanup.addWidget(note)
    form.addWidget(panel.cleanup_box)


def build_pin(panel, form):
    panel.pin_box = QWidget()
    pins = QVBoxLayout(panel.pin_box)
    pins.setContentsMargins(0, 0, 0, 0)
    label = QLabel('接口 PIN')
    label.setObjectName('studioSection')
    pins.addWidget(label)
    panel.pin_details = QWidget()
    panel.pin_details.setObjectName('studioPinDetails')
    pin_details = QVBoxLayout(panel.pin_details)
    pin_details.setContentsMargins(0, 0, 0, 0)
    fields = QFormLayout()
    panel.pin_layer = QComboBox()
    panel.pin_layer.setObjectName('studioPinLayer')
    panel.pin_layer.setToolTip(
        '选择图层后立即保存，可撤销。任意金属表示任选一层完整接入，不是跨层短接。'
    )
    panel.pin_layer.activated.connect(panel.change_pin_layer)
    fields.addRow('金属层', panel.pin_layer)
    pin_details.addLayout(fields)
    panel.copy_pin_button = _button('复制 PIN', 'studioCopyPin', panel.copy_pin)
    pin_details.addWidget(panel.copy_pin_button)
    pins.addWidget(panel.pin_details)
    form.addWidget(panel.pin_box)


def build_policy(panel, form):
    window = panel.window
    panel.policy_box = QWidget()
    policy = QVBoxLayout(panel.policy_box)
    policy.setContentsMargins(0, 0, 0, 0)
    label = panel.policy_title = QLabel('此模块上方禁止布线层')
    label.setObjectName('studioSection')
    policy.addWidget(label)
    panel.layers = QListWidget()
    panel.layers.setObjectName('studioBlockedLayers')
    panel.layers.setMaximumHeight(152)
    panel.layers.itemChanged.connect(panel.change_layers)
    policy.addWidget(panel.layers)
    row = QHBoxLayout()
    panel.block_all = _button(
        '全部禁止',
        'studioBlockAll',
        lambda: panel.write_layers(metals(panel.window.editor.profile)),
    )
    panel.allow_all = _button('全部开放', 'studioAllowAll', lambda: panel.write_layers(()))
    row.addWidget(panel.block_all)
    row.addWidget(panel.allow_all)
    policy.addLayout(row)
    label = panel.policy_hint = QLabel('勾选的金属层禁止在此模块上方布线，修改立即保存。')
    label.setObjectName('studioMuted')
    label.setWordWrap(True)
    policy.addWidget(label)
    form.addWidget(panel.policy_box)
    from ..native_routing_window_panel import NativeRoutingWindowPanel

    panel.native_windows = NativeRoutingWindowPanel(window)
    form.addWidget(panel.native_windows)

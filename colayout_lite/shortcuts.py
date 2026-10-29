"""One registry for configurable view shortcuts and fixed editing keys."""
import json
from pathlib import Path
from PySide6.QtCore import Qt,QObject,QEvent
from PySide6.QtGui import QShortcut,QKeySequence
from PySide6.QtWidgets import (QApplication,QVBoxLayout,QFormLayout,QKeySequenceEdit,
    QComboBox,QDialogButtonBox,QLabel,QPushButton,QLineEdit,QTextEdit,QPlainTextEdit,QAbstractSpinBox)
from .transactions import write_json_atomic
from .presentation.dark_dialog import DarkDialog

DEFAULTS={'fit':'F','up':'Ctrl+E','peek':'Ctrl','undo':'Ctrl+Z','undo_alt':'U','redo':'Ctrl+Y','redo_alt':'Ctrl+Shift+Z','rotate':'Ctrl+R'}
KEY_ACTIONS={'fit':'适合窗口','up':'返回上层','undo':'撤销','undo_alt':'撤销（第二快捷键，可留空）','redo':'重做','redo_alt':'重做（兼容键）','rotate':'旋转 90°'}
WHEEL_MODIFIERS={'Ctrl':Qt.KeyboardModifier.ControlModifier,'Alt':Qt.KeyboardModifier.AltModifier,
    'Shift':Qt.KeyboardModifier.ShiftModifier,'Ctrl+Shift':Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier}
EDIT_KEYS={'Delete','Backspace'}


def validate(values):
    if set(values)-set(DEFAULTS) or not {'fit','up','peek'}<=set(values):raise ValueError('快捷键配置不完整')
    # Do not steal U from an existing custom binding when upgrading a profile.
    alternate=values.get('undo_alt','' if any(QKeySequence(v)==QKeySequence('U') for k,v in values.items() if k!='peek') else 'U')
    values={**DEFAULTS,**values,'undo_alt':alternate}
    if values['peek'] not in WHEEL_MODIFIERS:raise ValueError('滚轮修饰键无效')
    result={'peek':values['peek']};used=set()
    for key in KEY_ACTIONS:
        seq=QKeySequence(values[key]);text=seq.toString(QKeySequence.SequenceFormat.PortableText)
        if key=='undo_alt' and seq.isEmpty():result[key]='';continue
        if seq.isEmpty() or seq.count()!=1 or text in EDIT_KEYS or text=='Esc':raise ValueError('请输入一个有效按键组合；Delete、Backspace、Esc 为编辑保留键')
        if text in used:raise ValueError('快捷键不能重复')
        used.add(text);result[key]=text
    return result


class ShortcutManager(QObject):
    def __init__(self,window,path):
        super().__init__(window);self.window=window;self.path=Path(path);self.bindings=[];self.callbacks={};self.values=dict(DEFAULTS)
        if self.path.exists():
            try:self.values=validate(json.loads(self.path.read_text(encoding='utf8'))['shortcuts'])
            except (ValueError,KeyError,TypeError):window.status.setText('快捷键配置无效，暂用默认值；可在快捷键页面重新保存。')
        QApplication.instance().installEventFilter(self)

    def close(self):
        # A closed Qt window can remain alive through Python references. Its
        # application-wide filter must not process every future window's events.
        app=QApplication.instance()
        if app:app.removeEventFilter(self)

    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.ShortcutOverride:
            focus=QApplication.focusWidget()
            if focus and (focus.window() is self.window or self.window.isAncestorOf(focus)) and isinstance(focus,(QLineEdit,QTextEdit,QPlainTextEdit,QAbstractSpinBox)):
                if event.modifiers()==Qt.KeyboardModifier.NoModifier or (event.key() in (Qt.Key.Key_Z,Qt.Key.Key_Y,Qt.Key.Key_R) and event.modifiers() in (Qt.KeyboardModifier.ControlModifier,Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier)):
                    event.accept();return True  # Typing F/Delete in a text field remains text editing.
        return False

    def bind(self,callbacks):self.callbacks=callbacks;self.apply(self.values)

    def apply(self,values,*,save=False):
        values=validate(values)
        if save:write_json_atomic(self.path,{'schema_version':'colayout-shortcuts-1','shortcuts':values})
        for binding in self.bindings:binding.setEnabled(False);binding.deleteLater()
        self.bindings=[];self.values=values
        for action in KEY_ACTIONS:
            if not values[action]:continue
            shortcut=QShortcut(QKeySequence(values[action]),self.window);shortcut.activated.connect(lambda a=('undo' if action=='undo_alt' else action):self.callbacks.get(a,lambda:None)());self.bindings.append(shortcut)
        for key in EDIT_KEYS:
            shortcut=QShortcut(QKeySequence(key),self.window)
            shortcut.activated.connect(lambda:self.callbacks.get('delete',lambda:None)());self.bindings.append(shortcut)
        self.window.undo_button.setToolTip('撤销 · '+' / '.join(values[k] for k in ('undo','undo_alt') if values[k]))
        self.window.redo_button.setToolTip('重做 · '+values['redo']+' / '+values['redo_alt'])
        self.window.canvas.peek_modifiers=WHEEL_MODIFIERS[values['peek']]
        self.window.fit_button.setToolTip('适合当前编辑层 · '+values['fit'])
        self.window.fit_button.setText('适合窗口 · '+values['fit'])
        self.window.region_panel.up_button.setText('返回上层 · '+values['up'])
        self.window.region_button.setToolTip(f"操作区工具；{values['up']} 返回上层，{values['peek']}+滚轮切换透视。")
        self.window.view_state_changed.emit()

    def edit(self):
        dialog=DarkDialog(self.window);dialog.setWindowTitle('快捷键');layout=QVBoxLayout(dialog);form=QFormLayout();layout.addLayout(form)
        fields={key:QKeySequenceEdit(QKeySequence(self.values[key])) for key in KEY_ACTIONS}
        for key,label in KEY_ACTIONS.items():form.addRow(label,fields[key])
        wheel=QComboBox();wheel.addItems(WHEEL_MODIFIERS);wheel.setCurrentText(self.values['peek'])
        form.addRow('三档透视（修饰键 + 滚轮）',wheel)
        message=QLabel('输入框内仍是文字编辑。Delete / Backspace 删除当层互连、保护环、定位框和禁布区；操作区只能解散。Esc 取消操作。');message.setWordWrap(True);layout.addWidget(message)
        reset=QPushButton('恢复默认');layout.addWidget(reset)
        reset.clicked.connect(lambda:([field.setKeySequence(QKeySequence(DEFAULTS[key])) for key,field in fields.items()],wheel.setCurrentText(DEFAULTS['peek'])))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);layout.addWidget(buttons)
        buttons.rejected.connect(dialog.reject)
        def save():
            try:self.apply({**{key:field.keySequence().toString() for key,field in fields.items()},'peek':wheel.currentText()},save=True);dialog.accept()
            except Exception as exc:message.setText(str(exc))
        buttons.accepted.connect(save);dialog.exec()

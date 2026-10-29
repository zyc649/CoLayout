"""Small library manager over persistent paired snapshots, separate from editing."""
import base64
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
                              QPushButton, QLabel, QInputDialog, QMessageBox, QFormLayout,
                              QLineEdit, QDialogButtonBox, QPlainTextEdit)
from .reference_cases import ReferenceCases, read_native_case, make_preview


class ReferenceCasesDialog(QDialog):
    def __init__(self, window, store=None):
        super().__init__(window)
        self.window = window
        self.store = store or ReferenceCases()
        self.setWindowTitle('参考案例库')
        self.resize(760, 520)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        label = QLabel('保存服务器原理图与版图的配对快照，供人和 Agent 查看参考。')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.items = QListWidget()
        self.items.itemDoubleClicked.connect(self.preview)
        layout.addWidget(self.items, 1)
        row = QHBoxLayout()
        self.buttons = {}
        for key, title, action in [('add', '添加案例…', self.add_case),
                                   ('rename', '重命名…', self.rename),
                                   ('delete', '删除', self.delete),
                                   ('preview', '预览', self.preview)]:
            button = QPushButton(title)
            button.clicked.connect(action)
            self.buttons[key] = button
            row.addWidget(button)
        layout.addLayout(row)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.items.currentItemChanged.connect(lambda *_: self.controls())
        self.refresh()

    def selected(self):
        item = self.items.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def controls(self):
        for key in ('rename', 'delete', 'preview'):
            self.buttons[key].setEnabled(bool(self.selected()) and not self.window.busy)
        self.buttons['add'].setEnabled(not self.window.busy and getattr(self.window, 'remote_enabled', True))

    def refresh(self, selected=None):
        selected = selected or self.selected()
        self.items.clear()
        for row in self.store.list(limit=100000)['cases']:
            source = row['layout_source']
            item = QListWidgetItem(f"{row['name']}  ·  {source['library']}/{source['cell']}")
            item.setData(Qt.ItemDataRole.UserRole, row['id'])
            item.setToolTip(row['note'])
            self.items.addItem(item)
            if row['id'] == selected:
                self.items.setCurrentItem(item)
        self.controls()

    def add_case(self):
        if self.window.busy:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('添加参考案例')
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        fields = {}
        for key, title, default in [('name', '案例名称', self.window.cell.text()),
                                    ('library', 'Layout 库', self.window.library.text()),
                                    ('cell', 'Layout 单元', self.window.cell.text()),
                                    ('sch_library', '原理图库（可留空）', ''),
                                    ('sch_cell', '原理图单元（可留空）', '')]:
            fields[key] = QLineEdit(default)
            fields[key].setObjectName('reference_' + key)
            form.addRow(title, fields[key])
        layout.addLayout(form)
        note = QLabel('原理图留空时读取原生绑定的源原理图；填写时请同时填写库和单元。')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = {key: widget.text().strip() for key, widget in fields.items()}
        try:
            self.store.check_name(values['name'])
            if not values['library'] or not values['cell']:
                raise ValueError('请填写 Layout 库和单元。')
            if bool(values['sch_library']) != bool(values['sch_cell']):
                raise ValueError('请同时填写原理图库和单元，或同时留空。')
        except Exception as exc:
            self.message.setText(str(exc))
            return
        schematic = (values['sch_library'], values['sch_cell'], 'schematic') if values['sch_cell'] else None
        # Keep this dialog alive until its callback completes.
        self.setEnabled(False)
        self.message.setText('正在读取原理图和版图…')
        def finished(pair):
            workspace, profile = pair
            saved = self.store.add(values['name'], workspace, profile,
                                   preview=make_preview(workspace, profile))
            self.refresh(saved['id'])
            self.message.setText('案例已保存在本机，可离线预览和通过 API 查询。')
        self.window.task(lambda: read_native_case(self.window.native(), values['library'],
                                                  values['cell'], schematic), finished)
        job = self.window.job
        if job:
            job.failed.connect(lambda error: self.message.setText(error[0]))
            job.finished.connect(lambda: (self.setEnabled(True), self.controls()))

    def rename(self):
        ident = self.selected()
        if not ident:
            return
        name, ok = QInputDialog.getText(self, '重命名案例', '名称', text=self.store.load(ident)['name'])
        if ok:
            try:
                self.store.rename(ident, name)
                self.refresh(ident)
            except Exception as exc:
                self.message.setText(str(exc))

    def delete(self):
        ident = self.selected()
        if ident and QMessageBox.question(self, '删除参考案例', '删除本机案例？服务器设计保持不变。') == QMessageBox.StandardButton.Yes:
            self.store.delete(ident)
            self.refresh()

    def preview(self, *_):
        ident = self.selected()
        if not ident:
            return
        data = self.store.load(ident)
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowTitle(data['name'])
        dialog.resize(920, 760)
        layout = QVBoxLayout(dialog)
        image = QLabel()
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if data.get('preview'):
            pixmap = QPixmap()
            pixmap.loadFromData(base64.b64decode(data['preview']['image_base64']))
            image.setPixmap(pixmap.scaled(880, 500, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))
        else:
            image.setText('此案例没有预览图片')
        layout.addWidget(image)
        w, _ = self.store.document(ident)
        schematic = QPlainTextEdit()
        schematic.setReadOnly(True)
        schematic.setMaximumHeight(170)
        lines = ['原理图：' + '/'.join((w.circuit.source.library, w.circuit.source.cell, w.circuit.source.view))]
        lines += [inst.name + '  ' + '/'.join(inst.master[:2]) + '  ' +
                  ', '.join(t.name + '=' + (t.net or '未连接') for t in inst.terminals.values())
                  for inst in w.circuit.instances.values()]
        schematic.setPlainText('\n'.join(lines))
        layout.addWidget(schematic)
        dialog.show()
        self.preview_dialog = dialog

    def closeEvent(self, event):
        if not self.isEnabled():
            event.ignore()
        else:
            super().closeEvent(event)


def show(window):
    from shiboken6 import isValid
    dialog = getattr(window, 'reference_cases_dialog', None)
    if dialog is None or not isValid(dialog):
        dialog = window.reference_cases_dialog = ReferenceCasesDialog(window)
    dialog.refresh()
    dialog.show()
    dialog.raise_()

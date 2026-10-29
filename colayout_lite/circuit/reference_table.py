"""Bounded native text exposure over complete, read-only reference rows."""
from PySide6.QtCore import QAbstractTableModel,QModelIndex,Qt
from PySide6.QtGui import QKeySequence,QShortcut
from PySide6.QtWidgets import QApplication,QAbstractItemView,QTableView


class ReferenceRows(QAbstractTableModel):
    def __init__(self,headers,parent=None):
        super().__init__(parent);self.headers=tuple(headers);self.rows=()

    def replace(self,rows):
        values=tuple(tuple(str(v) if v is not None else '' for v in row) for row in rows)
        if any(len(row)!=len(self.headers) for row in values):raise ValueError('Reference column count')
        self.beginResetModel();self.rows=values;self.endResetModel()

    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def columnCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.headers)

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.rows) or not 0<=index.column()<len(self.headers):return None
        value=self.rows[index.row()][index.column()]
        if role==Qt.ItemDataRole.UserRole:return value
        if role in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.AccessibleTextRole):
            text=' '.join(value.splitlines())
            return text if len(text)<=512 else text[:512]+'…'
        if role==Qt.ItemDataRole.ToolTipRole:
            return value if len(value)<=1024 else value[:1024]+'…\nCtrl+C 可复制完整行。'
        return None

    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if role==Qt.ItemDataRole.DisplayRole and orientation==Qt.Orientation.Horizontal and 0<=section<len(self.headers):
            return self.headers[section]
        return None

    def flags(self,index):
        return Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable if index.isValid() else Qt.ItemFlag.NoItemFlags


class ReferenceTable(QTableView):
    def __init__(self,headers,parent=None):
        super().__init__(parent);self.rows_model=ReferenceRows(headers,self);self.setModel(self.rows_model)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setWordWrap(False);self.setShowGrid(False);self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(28);self.horizontalHeader().setStretchLastSection(True)
        self.setToolTip('Ctrl+C 复制选中行的完整内容。')
        self.copy_shortcut=QShortcut(QKeySequence.StandardKey.Copy,self)
        self.copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.copy_shortcut.activated.connect(self.copy_rows)

    def set_rows(self,rows):self.rows_model.replace(rows)

    def copy_rows(self):
        indexes=sorted({index.row() for index in self.selectionModel().selectedRows()})
        QApplication.clipboard().setText('\n'.join('\t'.join(self.rows_model.rows[row]) for row in indexes))

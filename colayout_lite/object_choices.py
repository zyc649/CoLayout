"""Indexed object choices: one model reset for bulk membership changes."""
from PySide6.QtCore import QAbstractListModel,QModelIndex,Qt


class ObjectChoices(QAbstractListModel):
    def __init__(self,parent=None):
        super().__init__(parent);self.rows=[(None,'— 未选择对象 —')];self.indices={None:0}

    def rowCount(self,parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.rows):return None
        uid,label=self.rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.ToolTipRole):return label
        if role==Qt.ItemDataRole.UserRole:return uid

    def index_of(self,uid):return self.indices.get(uid,-1)

    def replace(self,rows):
        self.beginResetModel()
        self.rows=[(None,'— 未选择对象 —'),*rows];self.indices={uid:i for i,(uid,label) in enumerate(self.rows)}
        self.endResetModel()

    def update_label(self,uid,label):
        row=self.index_of(uid)
        if row<1 or self.rows[row][1]==label:return
        self.rows[row]=(uid,label);index=self.index(row,0)
        self.dataChanged.emit(index,index,[Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.ToolTipRole])

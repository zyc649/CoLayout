"""Unified policy access; native/local boxes keep their existing canonical records."""
from PySide6.QtCore import Qt,QSignalBlocker
from PySide6.QtWidgets import QWidget,QVBoxLayout,QComboBox,QLabel,QListWidget,QListWidgetItem,QPushButton,QHBoxLayout
from .regions.query import metals
from .regions.actions import RegionActions


def policy_targets(w):
    rows=[('area',r.id,'本地模块 · '+r.name) for r in w.local_data.regions.values()]
    rows += [('keepout',k.id,'禁布范围 · '+k.id[:20]) for k in w.local_data.keepouts.values()]
    if w.layout_connectivity:rows += [('native',uid,'Virtuoso 模块 · '+i.name) for uid,i in w.layout_connectivity.instances.items() if i.black_box]
    return rows


def blocked_layers(w,p,kind,ident):
    if kind=='area':return w.local_data.regions[ident].blocked_layers
    if kind=='keepout':return w.local_data.keepouts[ident].layers
    return w.local_data.native_blocked_layers.get(ident,metals(p))


def set_blocked_layers(editor,kind,ident,layers):
    api=RegionActions(editor)
    if kind=='area':
        r=editor.w.local_data.regions[ident];api.update_details(ident,r.name,r.note,layers)
    elif kind=='keepout':api.update_box(ident,editor.w.local_data.keepouts[ident].note,layers)
    elif kind=='native':api.native_policy(ident,layers)
    else:raise ValueError('Unknown routing policy target')


class RoutingPolicyPanel(QWidget):
    def __init__(self,window):
        super().__init__(window);self.owner=window;self.loading=False
        form=QVBoxLayout(self);form.setContentsMargins(0,0,0,0)
        form.addWidget(QLabel('统一管理：原生模块、本地模块、自画禁布范围'))
        self.targets=QComboBox();form.addWidget(self.targets);self.targets.currentIndexChanged.connect(self.load)
        self.identity=QLabel();self.identity.setWordWrap(True);self.identity.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);form.addWidget(self.identity)
        form.addWidget(QLabel('勾选 = 禁止布线；取消勾选 = 该层开放。修改立即保存。'))
        self.layers=QListWidget();form.addWidget(self.layers);self.layers.itemChanged.connect(self.changed)
        row=QHBoxLayout();form.addLayout(row);self.all_button=QPushButton('全部禁止');self.none_button=QPushButton('全部开放')
        row.addWidget(self.all_button);row.addWidget(self.none_button)
        self.all_button.clicked.connect(lambda:self.write(metals(self.owner.editor.profile)))
        self.none_button.clicked.connect(lambda:self.write(()))
        self.message=QLabel();self.message.setWordWrap(True);form.addWidget(self.message)
        self.refresh()

    def refresh(self):
        if not self.owner.editor:return
        selected=self.targets.currentData()
        with QSignalBlocker(self.targets):
            self.targets.clear()
            for kind,ident,label in policy_targets(self.owner.editor.w):self.targets.addItem(label,(kind,ident))
            index=next((i for i in range(self.targets.count()) if tuple(self.targets.itemData(i))==tuple(selected)), -1) if selected else -1
            self.targets.setCurrentIndex(index)
        self.load()

    def select_id(self,ident):
        index=next((i for i in range(self.targets.count()) if self.targets.itemData(i)[1]==ident),-1)
        self.targets.setCurrentIndex(index);self.load()

    def load(self):
        if not self.owner.editor:return
        target=self.targets.currentData();self.loading=True
        try:
            self.identity.setText(target[1] if target else '请选择需要设置的模块或禁布范围')
            current=blocked_layers(self.owner.editor.w,self.owner.editor.profile,*target) if target else ()
            self.message.setText(('当前设置：'+(', '.join(current)+' 禁布' if current else '全部开放')) if target else '')
            self.layers.clear()
            for name in metals(self.owner.editor.profile):
                item=QListWidgetItem(name);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if name in current else Qt.CheckState.Unchecked);self.layers.addItem(item)
            for widget in (self.layers,self.all_button,self.none_button):widget.setEnabled(bool(target) and not self.owner.busy)
        finally:self.loading=False

    def changed(self,*_):
        if not self.loading:self.write(tuple(self.layers.item(i).text() for i in range(self.layers.count()) if self.layers.item(i).checkState()==Qt.CheckState.Checked))

    def write(self,layers):
        target=self.targets.currentData()
        if not target or self.owner.busy:return
        try:set_blocked_layers(self.owner.editor,*target,layers);self.owner.save_local();self.message.setText('已保存：'+(', '.join(layers)+' 禁布' if layers else '全部开放'))
        except Exception as exc:self.load();self.message.setText(str(exc))

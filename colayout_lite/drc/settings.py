"""Edit a saved DRC profile; shares all fields with unified onboarding."""
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QLineEdit,QTabWidget,QDialogButtonBox,QScrollArea
from .fields import DrcFields
from . import config


class DrcSettings(QDialog):
    def __init__(self,technology,profile,parent=None):
        super().__init__(parent);self.technology=technology;self.original=profile
        self.setWindowTitle('DRC 工艺配置 · '+technology.label);self.resize(960,650)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('新工艺通过“工艺库 → 待确认”统一配置；这里可单独维护已保存的 DRC 参数。'))
        self.label=QLineEdit(profile.id if profile else technology.label+' DRC');layout.addWidget(self.label)
        self.fields=DrcFields();self.fields.set_profile(technology,profile);tabs=QTabWidget();layout.addWidget(tabs,1)
        for widget,title in ((self.fields.local,'本地 DRC'),(self.fields.server,'服务器 DRC')):
            scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(widget);widget.setAutoFillBackground(False)
            scroll.viewport().setAutoFillBackground(False);tabs.addTab(scroll,title)
        # Existing callers access these public controls.
        for name in ['rules','halo','enabled','remote_fields']:setattr(self,name,getattr(self.fields,name))
        self.message=QLabel('配置文件：'+str(config.path_for(technology)));self.message.setWordWrap(True);layout.addWidget(self.message)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);layout.addWidget(buttons)
        buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject)

    def showEvent(self,event):
        super().showEvent(event)
        if not getattr(self,'_placed_on_screen',False):
            self._placed_on_screen=True
            area=self.screen().availableGeometry()
            self.resize(min(960,area.width()-40),min(720,area.height()-60))
            self.move(area.center()-self.rect().center())

    def save(self):
        try:
            p=self.fields.value();p=p.model_copy(update={'id':self.label.text().strip(),'provenance':{**p.provenance,'validation':'user_edited_requires_revalidation'}})
            config.save(p,self.technology);self.accept()
        except Exception as exc:self.message.setText('未保存：'+str(exc))

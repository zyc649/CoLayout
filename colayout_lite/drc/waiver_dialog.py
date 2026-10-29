from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QCheckBox,QPlainTextEdit,QPushButton,QDialogButtonBox
from .waivers import WaiverPolicy


class WaiverDialog(QDialog):
    def __init__(self,policy,parent=None):
        super().__init__(parent);self.policy=policy;self.setWindowTitle('服务器 DRC · Waive 设置');self.resize(580,530)
        layout=QVBoxLayout(self)
        note=QLabel('按工艺保存，UI、Agent API 和区域完成验收共用。原始报告保留，可查看已忽略项。匹配不区分大小写。');note.setWordWrap(True);layout.addWidget(note)
        self.enabled=QCheckBox('启用 Waive');self.enabled.setChecked(policy.enabled);layout.addWidget(self.enabled)
        layout.addWidget(QLabel('规则类型：每行一个完整规则 ID（精确匹配）'))
        self.rules=QPlainTextEdit('\n'.join(policy.rule_ids));layout.addWidget(self.rules)
        layout.addWidget(QLabel('关键词：每行一个，匹配规则名称或说明中的文字（非正则）'))
        self.keywords=QPlainTextEdit('\n'.join(policy.keywords));layout.addWidget(self.keywords)
        preset=QPushButton('加入顶层规则关键词：BORDER / density / seal ring');layout.addWidget(preset)
        preset.clicked.connect(lambda:self.keywords.setPlainText('\n'.join(dict.fromkeys(self.keywords.toPlainText().splitlines()+['BORDER','density','seal ring']))))
        self.message=QLabel('这里只忽略匹配项；Convention 等其他规则不会自动忽略。');self.message.setWordWrap(True);layout.addWidget(self.message)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);layout.addWidget(buttons)
        buttons.accepted.connect(self.accept_policy);buttons.rejected.connect(self.reject)

    def accept_policy(self):
        try:
            self.policy=WaiverPolicy(technology_fingerprint=self.policy.technology_fingerprint,configuration_id=self.policy.configuration_id,enabled=self.enabled.isChecked(),
                rule_ids=tuple(v.strip() for v in self.rules.toPlainText().splitlines() if v.strip()),
                keywords=tuple(v.strip() for v in self.keywords.toPlainText().splitlines() if v.strip()))
            self.accept()
        except Exception as exc:self.message.setText(str(exc))

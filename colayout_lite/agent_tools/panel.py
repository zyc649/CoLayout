"""Human observer of Agent ownership and calls, not a manual API console."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QApplication, QAbstractItemView, QSplitter, QTabBar,
)
from .activity import ActivityFeed, details, label


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.verticalHeader().hide()
    widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    widget.setHorizontalHeaderLabels(headers)
    widget.setShowGrid(False)
    widget.setWordWrap(False)
    widget.verticalHeader().setDefaultSectionSize(30)
    return widget


class AgentPanel(QWidget):
    def __init__(self, hub):
        super().__init__(hub.window)
        self.hub = hub
        self.feed = ActivityFeed(self.region_name)
        self._version = -1
        self._lease_key = None
        self._disposed = False
        self._selected_region = None
        self._calls_scope = None
        self._call_selections = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        row = QHBoxLayout()
        self.region = QLabel()
        self.region.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(self.region, 1)
        self.copy_id = QPushButton('复制操作区 ID')
        self.copy_id.clicked.connect(self.copy_region)
        row.addWidget(self.copy_id)
        layout.addLayout(row)
        self.summary = QLabel('暂无 Agent 接入')
        self.summary.setStyleSheet('font-weight: 600; padding-top: 6px;')
        layout.addWidget(self.summary)
        self.empty = QLabel('将操作区 ID 和任务交给 Agent，接入后会显示在这里。')
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.leases = table(['Agent', '操作区', '状态'])
        self.leases.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.leases.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.leases.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.leases.setMaximumHeight(145)
        self.leases.itemSelectionChanged.connect(self.update_release)
        layout.addWidget(self.leases)
        self.release = QPushButton('结束所选接入')
        self.release.clicked.connect(self.revoke)
        self.release.setEnabled(False)
        layout.addWidget(self.release, 0, Qt.AlignmentFlag.AlignRight)
        title = QLabel('调用记录')
        title.setStyleSheet('font-weight: 600;')
        calls_header = QHBoxLayout()
        calls_header.addWidget(title, 1)
        self.clear_calls = QPushButton('清空显示')
        self.clear_calls.setToolTip('只隐藏当前文档、当前操作区已有记录；原始日志和请求账本保留。')
        self.clear_calls.clicked.connect(self.clear_display)
        calls_header.addWidget(self.clear_calls)
        layout.addLayout(calls_header)
        self.call_scopes = QTabBar()
        self.call_scopes.setObjectName('agentCallScopes')
        self.call_scopes.setExpanding(True)
        self.call_scopes.setDocumentMode(True)
        self.call_scopes.addTab('当前操作区')
        self.call_scopes.addTab('未接入调用')
        self.call_scopes.currentChanged.connect(lambda _: self.refresh_calls())
        layout.addWidget(self.call_scopes)
        self.scope_note = QLabel()
        self.scope_note.setObjectName('studioMuted')
        self.scope_note.setWordWrap(True)
        layout.addWidget(self.scope_note)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.calls = table(['时间', 'Agent / 操作区', '工具', '结果'])
        self.calls.setColumnWidth(0, 65)
        self.calls.setColumnWidth(1, 145)
        self.calls.setColumnWidth(3, 70)
        self.calls.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.calls.itemSelectionChanged.connect(self.show_call)
        splitter.addWidget(self.calls)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.detail.setPlaceholderText('选择一条调用，查看具体工具、参数和执行结果。')
        splitter.addWidget(self.detail)
        splitter.setSizes([330, 260])
        layout.addWidget(splitter, 1)
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        self.message.hide()
        layout.addWidget(self.message)
        footer = QHBoxLayout()
        self.record_count = QLabel('等待 Agent 调用；记录自动更新')
        footer.addWidget(self.record_count, 1)
        self.copy_call = QPushButton('复制调用详情')
        self.copy_call.clicked.connect(self.copy_call_details)
        self.copy_call.setEnabled(False)
        footer.addWidget(self.copy_call)
        layout.addLayout(footer)
        audit = hub.runtime.audit
        for event in audit.recent_events:
            self.feed.add(event)
        audit.listeners.append(self.append)
        self.refresh()

    def region_name(self, rid):
        editor = self.hub.runtime.editor
        region = editor.w.local_data.regions.get(rid) if editor else None
        return region.name if region else rid

    def append(self, event):
        try:
            self.feed.add(event)
        except Exception:
            # A display projection must never change an audited API outcome.
            self.message.setText('有一条记录暂时无法显示，原始调用已保存在完整日志中。')
            self.message.show()

    def dispose(self):
        if not self._disposed:
            self._disposed = True
            listeners = self.hub.runtime.audit.listeners
            if self.append in listeners:
                listeners.remove(self.append)

    def refresh(self):
        runtime = self.hub.runtime
        from ..region_tools import target_region
        rid = target_region(self.hub.window)
        regions = runtime.editor.w.local_data.regions if runtime.editor else {}
        self._selected_region = rid if rid in regions else None
        self.region.setText('当前操作区：' + (self.region_name(rid) if self._selected_region else '未选择'))
        self.copy_id.setEnabled(bool(self._selected_region))
        key = []
        for lease in runtime.leases.values():
            status = '已接入'
            for job in runtime.jobs.values():
                if job.lease is lease and job.state in ('queued', 'running'):
                    status = '正在布线' if job.kind == 'route' else '正在检查'
            if lease.editor is not runtime.editor:
                status = '已失效'
            name = lease.editor.w.local_data.regions.get(lease.region_id)
            key.append((lease.token, lease.owner, name.name if name else lease.region_id, status, lease.region_id))
        if key != self._lease_key:
            selected = self.selected_lease()
            self._lease_key = key
            self.leases.setRowCount(len(key))
            self.leases.setFixedHeight(self.leases.horizontalHeader().height() + min(4, len(key)) * 30 + 4)
            for i, (token, owner, name, status, region_id) in enumerate(key):
                for j, value in enumerate((owner, name, status)):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.ItemDataRole.UserRole, token)
                    item.setToolTip(region_id if j == 1 else value)
                    self.leases.setItem(i, j, item)
                if token == selected:
                    self.leases.selectRow(i)
        self.summary.setText(f'{len(key)} 位 Agent 已接入' if key else '暂无 Agent 接入')
        self.empty.setVisible(not key)
        self.leases.setVisible(bool(key))
        self.release.setVisible(bool(key))
        self.update_release()
        if runtime.audit_failure:
            self.message.setText('调用记录保存失败，接口已暂停。请结束占用并联系开发者核对。')
            self.message.show()
        self.refresh_calls()

    def refresh_calls(self):
        editor = self.hub.runtime.editor
        document = editor.w.id if editor else ''
        mode = self.call_scopes.currentIndex()
        current_rows = self.feed.visible(document, self._selected_region) if self._selected_region else []
        unclaimed_rows = self.feed.visible(document, '')
        self.call_scopes.setTabText(0, f'当前操作区 · {len(current_rows)}')
        self.call_scopes.setTabText(1, f'未接入调用 · {len(unclaimed_rows)}')
        scope = (document, mode, self._selected_region if mode == 0 else '')
        version = (self.feed.version, scope)
        if self._version == version:
            return
        old_key = self.selected_call()
        if self._calls_scope is not None:
            self._call_selections[self._calls_scope] = old_key
        if scope != self._calls_scope:
            old_key = self._call_selections.get(scope)
        self._calls_scope = scope
        follow_latest = old_key is None or (self.calls.rowCount() and old_key == self.calls.item(0, 0).data(Qt.ItemDataRole.UserRole))
        self._version = version
        self.calls.blockSignals(True)
        rows = current_rows if mode == 0 else unclaimed_rows
        self.scope_note.setText(
            ('仅显示 '+self.region_name(self._selected_region)+' 的调用。' if self._selected_region else
             '请选择操作区，或切换到“未接入调用”查看工具和案例查询。') if mode == 0 else
            '当前工作区中，尚未接入操作区时的请求；切换操作区不会隐藏这些记录。')
        self.clear_calls.setEnabled(bool(rows))
        self.clear_calls.setToolTip('只隐藏当前页已有记录；另一个页面、原始日志和请求账本保留。')
        self.calls.setRowCount(len(rows))
        selection = 0
        for i, row in enumerate(rows):
            agent = row.agent if row.agent != '未接入' else ('客户端 ' + row.client_id[:8] if row.client_id else '未接入客户端')
            values = (row.time, agent + (' · ' + row.region_name if row.region_name else ''),
                      label(row.tool, row.arguments), row.status)
            for j, value in enumerate(values):
                item = self.calls.item(i, j)
                if item is None:
                    item = QTableWidgetItem()
                    self.calls.setItem(i, j, item)
                item.setText(value)
                item.setData(Qt.ItemDataRole.UserRole, row.key)
                item.setToolTip(row.summary if j == 3 else value)
                item.setForeground(QColor('#e28c83' if row.status in ('失败', '未通过', '需处理') else
                                          '#9dbcec' if row.status == '进行中' else '#d8dee5'))
            if row.key == old_key and not follow_latest:
                selection = i
        if rows:
            self.calls.selectRow(selection)
        else:
            self.calls.clearSelection()
            self.calls.setCurrentCell(-1, -1)
        self.calls.blockSignals(False)
        self.record_count.setText(f'最近 {len(rows)} 条活动 · 进度查询已合并，完整记录已保存' if rows else '等待 Agent 调用；记录自动更新')
        self.show_call()

    def clear_display(self):
        editor = self.hub.runtime.editor
        if self.call_scopes.currentIndex() == 0 and not self._selected_region:
            return
        region = self._selected_region if self.call_scopes.currentIndex() == 0 else ''
        self.feed.clear_display(editor.w.id if editor else '', region)
        self.refresh_calls()

    def selected_call(self):
        item = self.calls.item(self.calls.currentRow(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def show_call(self):
        row = self.feed.rows.get(self.selected_call())
        self.copy_call.setEnabled(row is not None)
        value = details(row) if row else ''
        if len(value)>65536:value=value[:65536]+'\n…显示已截断；复制调用详情可取得完整摘要，原始请求和结果在日志中保留。'
        if value != self.detail.toPlainText():
            self.detail.setPlainText(value)

    def copy_call_details(self):
        row=self.feed.rows.get(self.selected_call())
        QApplication.clipboard().setText(details(row) if row else '')

    def selected_lease(self):
        item = self.leases.item(self.leases.currentRow(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def update_release(self):
        self.release.setEnabled(self.selected_lease() in self.hub.runtime.leases)

    def revoke(self):
        token = self.selected_lease()
        if token:
            self.hub.runtime.revoke(token)
            self.refresh()

    def copy_region(self):
        if self._selected_region:
            QApplication.clipboard().setText(self._selected_region)

"""User-triggered communication controller over the existing Adapter.

Owns UI preparation/completion only; native checks and transactions remain
in Adapter. Calling a drawing or selection operation never invokes this class.
"""


class SyncController:
    def __init__(self, window):
        self.window = window

    def pull(self, checked=False, *, fresh=False):
        host = self.window
        if not host.idle_for_replacement():
            return
        if host.busy:
            return
        old = host.editor.w if host.editor else None
        if old and not fresh and old.state in ('submitting', 'indeterminate'):
            from ..sync_recovery import recovery_message

            host.error((recovery_message(old), '当前工作区未修改。'))
            return
        if (
            old
            and not fresh
            and (old.operations or old.state in ('submitting', 'indeterminate', 'conflict'))
        ):
            host.error(
                (
                    '还有本地草稿或未决同步。保留层次的刷新不能丢弃它们；请先同步/核对，或从“文件 → 从 Virtuoso 重新导入”开始新的工作区。',
                    '刷新未执行，当前工作区未修改。',
                )
            )
            return
        backup = None
        if old:
            from ..sync_recovery import backup as save_backup

            backup = save_backup(host, 'before-import')
        lib, cell = host.library.text().strip(), host.cell.text().strip()

        def load():
            import time
            from datetime import datetime,timezone
            from uuid import uuid4
            from ..import_performance import save_report
            start=time.perf_counter();a=None
            report={'library':lib,'cell':cell,'fresh':fresh,'started_at':datetime.now(timezone.utc).isoformat()}
            try:
                a = host.native()
                connected=time.perf_counter()
                report['connection_wait_s']=connected-start
                if not fresh and old and (lib, cell) == (old.baseline.library, old.baseline.cell):
                    result=a.refresh(old)
                else:result=a.open_workspace(lib, cell)
                report.update(status='success',timings=getattr(a,'last_read_timings',{}))
                return result
            except Exception as exc:
                report.update(status='error',error=str(exc));raise
            finally:
                report['total_s']=time.perf_counter()-start
                native=getattr(a,'native',None)
                if native is not None and hasattr(native,'state'):
                    save_report(native.state/'timings'/('import-'+uuid4().hex+'.json'),report)

        def done(result):
            if fresh:
                host.install(*result)
            else:
                host.install_preserving_view(*result)
            host.save_local()
            host.status.setText(
                (
                    '已重新导入服务器版图和原理图；旧工作区已备份。'
                    if fresh
                    else '已刷新服务器数据，并保留本地组织。'
                )
                + (' 备份：' + str(backup) if backup else '')
            )

        host.communication_action = 'refresh'
        host.communication_task(load, done)

    def sync(self):
        host = self.window
        if not host.editor:
            return
        if not host.idle_for_replacement():
            return
        w = host.editor.w
        p = host.editor.profile

        def done(result):
            camera = host.install_preserving_view(result, p)
            host.save_local()
            status = result.last_result.get('status')
            if status == 'saved_verified':
                host.status.setText('同步已完成并通过读回核对 · ' + result.baseline.cell)
                host.diagnostics.set_result(
                    '同步已完成，服务器读回核对通过。\n目标：'
                    + result.baseline.library
                    + '/'
                    + result.baseline.cell
                    + '\n无待同步操作。'
                )
            elif status == 'rolled_back':
                host.status.setText(
                    '同步失败，目标已恢复；本地草稿保留。失败操作：'
                    + str(result.last_result.get('failed_operation'))
                )
            elif status == 'no_op':
                host.status.setText('没有待同步的本地修改。')
            # Status text/docks may change viewport dimensions during readback.
            # Finish that layout before restoring the user's last camera center.
            host.centralWidget().layout().activate()
            from ..camera import restore

            restore(host.canvas, camera)

        host.communication_task(lambda: host.native().commit(w), done)

    def reconcile(self):
        host = self.window
        if not host.idle_for_replacement():
            return
        if not host.editor or host.busy:
            return
        from ..sync_recovery import backup, persisted_pending

        saved = backup(host, 'before-reconcile')
        source = persisted_pending(host.editor.w) or host.editor.w

        def done(result):
            host.install_preserving_view(result, host.editor.profile)
            host.save_local()
            host.status.setText(
                (
                    '已核对：上次同步成功，已恢复正常编辑。'
                    if result.state == 'clean'
                    else '已核对：上次修改未应用或已回滚，本地草稿保留。'
                )
                + ' 备份：'
                + str(saved)
            )

        host.communication_task(lambda: host.native().reconcile(source), done)

    def open_native(self):
        host = self.window
        if host.editor:
            s = host.editor.w.baseline
            host.task(
                lambda: host.native().native.call('ltOpen', s.library, s.cell),
                lambda _: host.status.setText('已打开对应 Virtuoso Layout：' + s.cell),
            )

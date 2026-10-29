"""Exercise only a fresh empty installation; fail before touching an existing design."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import traceback
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    from colayout_lite.bootstrap import settings, installation_path
    from colayout_lite.document import load_document
    cfg = settings()
    workspace, profile = load_document(cfg['document'])
    if (workspace.baseline.objects or workspace.operations or workspace.local_data.regions
            or profile.native_fingerprint != 'unconfigured'):
        raise RuntimeError('Use a new empty installation; existing design was not opened.')
    from PySide6.QtCore import QEventLoop, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from colayout_lite import app_identity
    from colayout_lite.transport import NativeTransport
    from colayout_lite.studio_window import StudioWindow
    from colayout_lite.process_dialog import ProcessDialog
    from colayout_lite.agent_tools.app import enable
    from colayout_lite.agent_tools.client import AgentClient
    from tools.create_layout_agent import create
    app_identity.APPLICATION_ID = 'CoLayout.Lite.OnboardingVerification'
    def forbid(*args, **kwargs):
        raise AssertionError('Smoke test must never access a native server')
    NativeTransport.__init__ = forbid
    app = QApplication([])
    app.setStyle('Fusion')
    app_identity.configure_application(app)
    args.out.mkdir(parents=True, exist_ok=True)
    report = {}
    window = None
    with ThreadPoolExecutor(1) as pool:
        def wait(predicate, timeout=20000):
            loop = QEventLoop()
            timer = QTimer()
            deadline = QTimer()
            timer.setInterval(15)
            deadline.setSingleShot(True)
            timer.timeout.connect(lambda: loop.quit() if predicate() else None)
            deadline.timeout.connect(loop.quit)
            timer.start()
            deadline.start(timeout)
            loop.exec()
            timer.stop()
            deadline.stop()
            assert predicate(), 'GUI/HTTP operation timed out'

        def work(callback):
            future = pool.submit(callback)
            wait(future.done)
            return future.result()
        try:
            window = StudioWindow(cfg['document'], installation_path=installation_path(),
                                  shortcut_path=ROOT/'.colayout/smoke-keys.json')
            window.resize(1200, 780)
            window.show()
            hub = enable(window)
            client = AgentClient(hub.connection_file)
            tools = work(lambda: client.call('tools', {}, wait_seconds=0))
            status = work(lambda: client.call('workspace', {'action': 'status'}, wait_seconds=0))
            requirements = work(lambda: client.call('process_configuration', {'action': 'requirements'}, wait_seconds=0))
            assert len(tools['tools']) == 11
            assert status['active_regions'] == status['pending_operations'] == 0
            folder = Path(cfg['test_kit'])
            result = work(lambda: create(folder, update=(folder/'.colayout-layout-agent.json').exists()))
            assert result['connected'] and result['ready'], result
            cli = work(lambda: subprocess.run(
                [sys.executable, '-E', '-S', '-X', 'utf8', str(folder/'api.py'),
                 '--client', 'onboarding-verification-'+uuid4().hex[:8], 'tools'],
                capture_output=True, text=True, encoding='utf8', timeout=20))
            assert cli.returncode == 0, cli.stderr
            assert len(json.loads(cli.stdout)['result']['tools']) == 11
            dialog = ProcessDialog(window.process_store, window)
            dialog.show()
            wait(dialog.isVisible)
            bar = dialog.tabs.tabBar()
            QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(2).center())
            assert dialog.tabs.currentIndex() == 2
            dialog.grab().save(str(args.out/'process-help.png'))
            dialog.close()
            dialog.deleteLater()
            window.grab().save(str(args.out/'empty-app.png'))
            report.update(status='passed', tools=11, empty_workspace=True, native_access=False,
                          process_connections=len(requirements['connections']),
                          client_ready=True, client_source_isolated=True, qt_tab_click=True,
                          pythonw=Path(sys.executable).stem=='pythonw')
        except Exception:
            report.update(status='failed', error=traceback.format_exc())
        finally:
            if window:
                window.close()
    (args.out/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    return 0 if report.get('status') == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())

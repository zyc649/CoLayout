"""Bridge boundary: explicit project configuration and file-sized messages.

Construction connects; the fixed native kernel loads on first use. Reuse one transport
for a connection; constructing it is not a pure configuration operation.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from uuid import uuid4

from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.env import set_runtime_env_file

from .model import LiteError
from .transactions import write_json_atomic

from .paths import ROOT as ROOT
NATIVE_SCRIPTS = (
    "read.il",
    "display.il",
    "lite.il",
    "routing.il",
    "groups.il",
    "compact.il",
    "guard_recipes.il",
    "mpp.il",
    "circuit.il",
    "process_read.il",
    "temporary.il",
)


def skill(value):
    """Encode data only. Booleans/floats and SKILL fragments are rejected."""
    return _skill_data(value, literal=False)


def skill_literal(value):
    """Data for quote(...), avoiding evaluation of large nested list() calls."""
    return _skill_data(value, literal=True)


def _skill_data(value, *, literal):
    if value is None:
        return "nil"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if type(value) is int:
        return str(value)
    if isinstance(value, dict):
        return _skill_data([[key, item] for key, item in value.items()], literal=literal)
    if isinstance(value, (tuple, list)):
        opening, separator = ("(", "\n") if literal else ("list(", " ")
        return opening + separator.join(_skill_data(item, literal=literal) for item in value) + ")"
    raise TypeError(
        "Only data, exact integers and decimal strings may cross the bridge"
    )


def load_connection(config_path=None, *, require_environment=True):
    """Preserve path semantics: config arguments use cwd, fields use ROOT."""
    path = Path(config_path or ROOT / "config/colayout_lite.json").resolve()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("connection must be an object")
        if (
            config.get("schema_version", "colayout-lite-connection-1")
            != "colayout-lite-connection-1"
        ):
            raise ValueError("unsupported connection schema")
        for field in ("bridge_env", "state_directory", "allowed_remote_root"):
            if not isinstance(config.get(field), str) or not config[field].strip():
                raise ValueError(f"missing/invalid {field}")
        if not config["allowed_remote_root"].startswith("/"):
            raise ValueError("allowed_remote_root must be an absolute server path")
        for field in ("profiles_directory", "preferred_profile"):
            if field in config and not isinstance(config[field], str):
                raise ValueError(f"invalid {field}")
    except (OSError, ValueError) as exc:
        raise LiteError("INVALID_CONNECTION_CONFIG", f"{path}: {exc}") from exc
    env_path = (ROOT / config["bridge_env"]).resolve()
    if require_environment and not env_path.is_file():
        raise LiteError("BRIDGE_ENV_MISSING", str(env_path))
    return path, config, env_path


class NativeTransport:
    requires_circuit_context = True
    def __init__(self, config_path=None, *, progress=None):
        self.progress=progress
        self._kernel_ready=False
        from .native_lane import channel
        with channel(config_path):self._initialize(config_path)

    def _initialize(self, config_path=None):
        self.config_path, self.config, env_path = load_connection(config_path)
        self.state = (ROOT / self.config["state_directory"]).resolve()
        self.state.mkdir(parents=True, exist_ok=True)
        from .streams import resilient
        sys.stdout=resilient(sys.stdout,self.state/'pythonw.log')
        sys.stderr=resilient(sys.stderr,self.state/'pythonw-errors.log')
        set_runtime_env_file(env_path)
        self.note('正在连接 Virtuoso…')
        started=time.perf_counter()
        self.client = VirtuosoClient.from_env(log_to_ciw=False)
        self.connection_seconds=time.perf_counter()-started

    def _ensure_kernel(self):
        if getattr(self,'_kernel_ready',True):return
        from hashlib import sha256
        from .native_lane import channel
        from .transactions import write_text_atomic
        with channel(self.config_path):
            if self._kernel_ready:return
            self.note('正在准备 Virtuoso 读取组件…')
            started=time.perf_counter()
            content='\n'.join((ROOT/'colayout_lite/skill'/name).read_text(encoding='utf8') for name in NATIVE_SCRIPTS)
            path=self.state/'kernels'/('colayout-'+sha256(content.encode('utf8')).hexdigest()+'.il')
            if not path.exists():write_text_atomic(path,content)
            result=self.client.load_il(str(path))
            self._require_success(result,'NATIVE_LOAD_FAILED','Colayout kernel')
            self._initialize_kernel()
            self.kernel_seconds=time.perf_counter()-started
            self._kernel_ready=True

    def _initialize_kernel(self):
        try:
            self._call("ltInit", str(uuid4()), self.config["allowed_remote_root"])
        except LiteError as exc:
            if "Colayout root mismatch" in str(exc):
                raise LiteError(
                    "CONNECTED_PROJECT_MISMATCH",
                    "当前 Virtuoso 仍是另一工程/工艺的会话。请启动所选工艺的工程并连接 Bridge，再拉取；本地工艺切换不会更改服务器 PDK。",
                ) from exc
            raise

    def preflight_layout(self,library,cell):
        """Read metadata before loading kernels or preparing any object IDs."""
        self.note('正在检查目标 Layout…')
        result=self.client.execute_skill(
            'if(ddGetObj('+skill(library)+' '+skill(cell)+' "layout") then t else nil)',timeout=10)
        self._require_success(result,'NATIVE_ERROR','检查目标 Layout')
        answer=result.output.strip()
        if answer=='nil':
            raise LiteError('LAYOUT_NOT_FOUND',f'找不到 {library}/{cell}/layout。请先在 Virtuoso 中创建并保存版图。')
        if answer!='t':raise LiteError('INVALID_NATIVE_RESPONSE','检查目标 Layout')

    @staticmethod
    def _require_success(result, code, operation):
        status = getattr(result.status, "value", result.status)
        if status != "success" or result.errors:
            detail = f"{operation}: {result.errors} {getattr(result, 'output', '')}"
            if "Display primitive budget exceeded" in detail:
                detail = (
                    "显示提取超过100000图元上限；请保留框＋Pin，或只展开更小的模块。 "
                    + detail
                )
            raise LiteError(code, detail, operation=operation)

    def note(self, message):
        callback = getattr(self, "progress", None)
        if callback:
            callback(message)

    def call(self, name, *values, timeout=60):
        """Internal fixed-kernel call, not a public untrusted execution API."""
        self._ensure_kernel()
        return self._call(name,*values,timeout=timeout)

    def _call(self, name, *values, timeout=60):
        from virtuoso_bridge.virtuoso.skill_output import parse_sexpr

        result = self.client.execute_skill(
            name + "(" + " ".join(skill(v) for v in values) + ")", timeout=timeout
        )
        self._require_success(result, "NATIVE_ERROR", name)
        try:
            return parse_sexpr(result.output.strip())
        except ValueError as exc:
            raise LiteError("INVALID_NATIVE_RESPONSE", name) from exc

    def _upload_request(self, token, payload):
        self._ensure_kernel()
        path = self.state / "requests" / f"{token}.il"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            # A file avoids socket limits, but evaluating thousands of nested
            # list() calls still exhausts the SKILL value stack. Load one quoted
            # data literal; transaction identity, order and checks stay intact.
            "ltRequests[" + skill(token) + "]=quote(" + skill_literal(payload) + ")\n",
            encoding="utf-8",
        )
        result = self.client.load_il(str(path))
        write_json_atomic(
            path.with_suffix(".result.json"),
            {
                "output": result.output,
                "errors": result.errors,
                "warnings": result.warnings,
            },
        )
        self._require_success(result, "NATIVE_ERROR", "upload request")

    def _download_export(self, reply, filename):
        if (
            not isinstance(reply, (list, tuple))
            or not reply
            or not isinstance(reply[0], str)
            or not reply[0].startswith("/")
        ):
            raise LiteError("INVALID_NATIVE_RESPONSE", "导出结果缺少服务器绝对路径。")
        path = self.state / "reads" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        from .native_export_transfer import download_text_export
        if download_text_export(self.client,reply[0],path):
            self.last_download_transport='persistent_ssh'
            return path
        self.last_download_transport='bridge_file'
        result = self.client.download_file(reply[0], str(path))
        self._require_success(result, "DOWNLOAD_FAILED", reply[0])
        if not path.is_file():
            raise LiteError("DOWNLOAD_FAILED", f"下载未生成文件：{path}")
        return path

    @staticmethod
    def _parse_export(path):
        from .sexpr import parse_native

        try:
            return parse_native(path.read_text(encoding="utf-8").strip())
        except ValueError as exc:
            raise LiteError("TRUNCATED_RESPONSE", f"{path}: {exc}") from exc

    def read(self, library, cell):
        token = uuid4().hex
        started = time.perf_counter()
        self.note("正在从 Virtuoso 提取 Layout…")
        reply = self.call("ltWriteCompact", library, cell, token)
        exported = time.perf_counter()
        self.note("正在传输版图快照…")
        path = self._download_export(reply, f"{token}.sexpr")
        downloaded = time.perf_counter()
        self.note("正在解析版图数据…")
        result = self._parse_export(path)
        self.last_read_timings = {
            "export_s": exported - started,
            "download_s": downloaded - exported,
            "parse_s": time.perf_counter() - downloaded,
            "bytes": path.stat().st_size,
        }
        return result

    def read_pair(self, library, cell, schematic=None):
        """One fixed native export and one download for both views and bindings."""
        token = uuid4().hex
        source = schematic or (None, None, None)
        if not isinstance(source, (list, tuple)) or len(source) != 3 or (schematic is not None and
                any(not isinstance(value, str) or not value for value in source)):
            raise LiteError('INVALID_SCHEMATIC_SOURCE')
        from datetime import datetime,timezone
        started=time.perf_counter();timings={};stage='export'
        self.last_read_timings=timings
        report={'library':library,'cell':cell,'started_at':datetime.now(timezone.utc).isoformat(),'timings':timings}
        try:
            self.note('正在提取原理图、版图和器件对应关系…')
            reply = self.call('lcWritePaired', library, cell, *source, token, timeout=120)
            exported=time.perf_counter();timings['export_s']=exported-started;stage='download'
            self.note('正在传输版图与原理图快照…')
            path = self._download_export(reply, f'{token}.paired.sexpr')
            downloaded=time.perf_counter();timings['download_s']=downloaded-exported
            timings['transfer']=self.last_download_transport;timings['bytes']=path.stat().st_size;stage='parse'
            self.note('正在解析版图与原理图数据…')
            result = self._parse_export(path);timings['parse_s']=time.perf_counter()-downloaded
            if not isinstance(result, (list, tuple)) or len(result) != 3 or result[0] != 'colayout-paired-native-3':
                raise LiteError('PAIRED_EXPORT_VERSION')
            self.last_paired_export = str(path);report['status']='success'
            return result
        except Exception as exc:
            report.update(status='error',stage=stage,error=str(exc));raise
        finally:
            timings['transport_total_s']=time.perf_counter()-started
            self.last_read_report=self.state/'timings'/f'{token}.json'
            from .import_performance import save_report
            save_report(self.last_read_report,report)

    def instance_display(self, library, cell, uid, counter, dependencies):
        token = "display-" + uuid4().hex
        self._upload_request(
            token, {"uid": uid, "counter": counter, "dependencies": dependencies}
        )
        reply = self.call("ltRunDisplayRequest", library, cell, token)
        return self._parse_export(self._download_export(reply, f"{token}.sexpr"))

    def transact(self, library, cell, request):
        # File-sized requests avoid CIW/socket command-length limits. Execute
        # separately from load so the native error is not hidden by load().
        token = uuid4().hex
        self._upload_request(token, request)
        self.call("ltRunRequest", library, cell, token)
        return self.call("ltReceiptRead", request["request_id"])

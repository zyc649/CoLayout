"""Persistent human-curated, read-only paired design examples."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from .model import LiteError, Workspace
from .technology import TechnologyProfile
from .editor import projected
from .regions.query import object_bounds
from .transactions import write_json_atomic
from .paths import ROOT


class ReferenceCases:
    def __init__(self, folder=None):
        self.folder = Path(folder) if folder is not None else ROOT / 'artifacts/reference-cases'

    def path(self, ident):
        if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident):
            raise LiteError('REFERENCE_CASE_UNKNOWN')
        return self.folder / (ident + '.json')

    def load(self, ident):
        try:
            data = json.loads(self.path(ident).read_text(encoding='utf8'))
        except FileNotFoundError as exc:
            raise LiteError('REFERENCE_CASE_UNKNOWN', '案例已删除或不存在。') from exc
        if data.get('schema_version') != 'colayout-reference-case-1' or data.get('id') != ident:
            raise LiteError('REFERENCE_CASE_INVALID')
        return data

    @staticmethod
    def summary(data):
        return {key: data[key] for key in
                ('id', 'name', 'note', 'created_at', 'layout_source', 'schematic_source',
                 'technology', 'object_count', 'instance_count')}

    def list(self, query='', offset=0, limit=100):
        rows = [self.summary(self.load(path.stem)) for path in self.folder.glob('*.json')
                if re.fullmatch('[a-f0-9]{32}', path.stem)]
        needle = query.casefold().strip()
        rows = [row for row in rows if not needle or needle in
                json.dumps(row, ensure_ascii=False).casefold()]
        rows.sort(key=lambda row: (row['name'].casefold(), row['id']))
        return {'cases': rows[offset:offset + limit], 'total': len(rows), 'offset': offset,
                'has_more': offset + limit < len(rows), 'role': 'read_only_design_examples'}

    def add(self, name, workspace, profile, *, note='', preview=None):
        name = self.check_name(name)
        if workspace.circuit is None or workspace.layout_connectivity is None:
            raise LiteError('REFERENCE_PAIR_REQUIRED', '案例必须同时包含原理图、版图及原生对应关系。')
        if workspace.state != 'clean' or workspace.operations:
            raise LiteError('REFERENCE_SNAPSHOT_REQUIRED', '请添加服务器读取的完整案例快照。')
        ident = uuid4().hex
        data = {'schema_version': 'colayout-reference-case-1', 'id': ident, 'name': name,
                'note': note.strip(), 'created_at': datetime.now(timezone.utc).isoformat(),
                'layout_source': workspace.layout_connectivity.source.model_dump(mode='json'),
                'schematic_source': workspace.circuit.source.model_dump(mode='json'),
                'technology': {'label': profile.label, 'dbu_per_micron': profile.dbu_per_micron,
                               'fingerprint': profile.native_fingerprint},
                'object_count': len(workspace.baseline.objects),
                'instance_count': len(workspace.circuit.instances),
                'workspace': workspace.model_copy(update={'connection_config': None}).model_dump(mode='json'),
                'profile': profile.model_dump(mode='json'),
                'preview': preview}
        self.folder.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.path(ident), data)
        return self.summary(data)

    @staticmethod
    def check_name(name):
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
            raise LiteError('REFERENCE_NAME_INVALID', '案例名称需为1–120个字符。')
        return name.strip()

    def rename(self, ident, name):
        data = self.load(ident)
        data['name'] = self.check_name(name)
        write_json_atomic(self.path(ident), data)
        return self.summary(data)

    def delete(self, ident):
        self.load(ident)
        self.path(ident).unlink()

    def document(self, ident):
        data = self.load(ident)
        return Workspace.model_validate(data['workspace']), TechnologyProfile.model_validate(data['profile'])

    def inspect(self, ident, kind='summary', offset=0, limit=100):
        data = self.load(ident)
        result = {'case': self.summary(data), 'role': 'read_only_design_example',
                  'note': '案例坐标和UID仅属于案例，不能用来编辑当前操作区。'}
        if kind == 'summary':
            return result
        if kind == 'preview':
            if not data.get('preview'):
                raise LiteError('REFERENCE_PREVIEW_UNAVAILABLE')
            return {**result, **data['preview']}
        w, p = self.document(ident)
        result.update(coordinates='example_absolute_um', dbu_per_micron=p.dbu_per_micron)
        if kind == 'schematic':
            rows = sorted(w.circuit.instances.values(), key=lambda item: item.name)
            selected = rows[offset:offset + limit]
            names = {item.name for item in selected}
            result.update(instances=[item.model_dump(mode='json') for item in selected],
                          ports={k: v.model_dump(mode='json') for k, v in w.circuit.ports.items()},
                          bindings=[b.model_dump(mode='json') for b in w.circuit.bindings
                                    if any(path and path[0].instance in names for path in b.schematic_paths)])
        elif kind == 'layout':
            rows = sorted(projected(w).values(), key=lambda item: item.uid)
            objects = []
            for obj in rows[offset:offset + limit]:
                bounds = object_bounds(w, obj, p)
                objects.append({'uid': obj.uid, 'kind': obj.kind, 'name': obj.attributes.get('name'),
                                'bbox_um': [v / p.dbu_per_micron for point in bounds for v in point] if bounds else None,
                                'shape_dbu': obj.shape.model_dump(mode='json') if obj.shape else None,
                                'placement_um': {'origin': [v / p.dbu_per_micron for v in obj.placement.origin],
                                                 'orientation': obj.placement.orientation} if obj.placement else None,
                                'layout_interface': w.layout_connectivity.instances[obj.uid].model_dump(mode='json')
                                if obj.uid in w.layout_connectivity.instances else None})
            result.update(objects=objects,
                          ports={k: v.model_dump(mode='json') for k, v in w.layout_connectivity.ports.items()})
        else:
            raise LiteError('REFERENCE_KIND_INVALID')
        return {**result, 'total': len(rows), 'offset': offset, 'has_more': offset + limit < len(rows)}


def read_native_case(adapter, library, cell, schematic=None):
    # Read both views through the established pairing protocol, without ltPrepare,
    # saving a native design or replacing the user's active workspace.
    snapshot, profile, circuit, connectivity = adapter.read_pair(library, cell, schematic=schematic)
    return Workspace(baseline=snapshot, profile_id=profile.id, circuit=circuit,
                     layout_connectivity=connectivity), profile


def make_preview(workspace, profile):
    from PySide6.QtCore import Qt, QByteArray, QBuffer, QIODevice
    from .presentation.snapshot_canvas import SnapshotCanvas
    view = SnapshotCanvas(workspace, profile, None, 900, 600)
    try:
        view.show()
        view.layout().activate()
        bounds = view.scene.itemsBoundingRect()
        if bounds.isEmpty():
            raise LiteError('REFERENCE_LAYOUT_EMPTY')
        view.canvas.fitInView(bounds.adjusted(-10, -10, 10, 10), Qt.AspectRatioMode.KeepAspectRatio)
        view.refresh_overlay()
        pixels = view.canvas.viewport().grab().toImage()
        raw = QByteArray()
        buffer = QBuffer(raw)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not pixels.save(buffer, 'PNG'):
            raise LiteError('REFERENCE_PREVIEW_FAILED')
        value = bytes(raw)
        return {'mime_type': 'image/png', 'width': pixels.width(), 'height': pixels.height(),
                'sha256': hashlib.sha256(value).hexdigest(),
                'image_base64': base64.b64encode(value).decode('ascii')}
    finally:
        view.close()
        view.deleteLater()

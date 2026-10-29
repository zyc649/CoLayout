"""Explicit compatibility for old process proposals/preferences.

Current UI and HTTP publication go through ProcessConfiguration/process_review.
These adapters preserve old paths, evidence and write/rollback semantics; never
call them to approve a current HTTP proposal. No native operation is run on import.
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
from .model import LiteError,Workspace
from .technology import TechnologyProfile
from .process_library import ProcessLibrary, write_json
from .process_transaction import file_key
from .process_measurements import policy_key
from .adapter import Adapter
from .transport import NativeTransport
from .onboarding import save_profile
from .model import digest


def confirm_legacy(path, profile, *, store=None, progress=lambda s: None, drc_profile=None):
    """Only the human confirmation UI calls this publishing boundary."""
    from . import process_setup as setup

    path = Path(path)
    data = json.loads(path.read_text(encoding='utf8'))
    if data.get('status') == 'confirmed':
        raise LiteError('PROPOSAL_ALREADY_CONFIRMED')
    if data.get('status') == 'superseded':
        raise LiteError('PROPOSAL_SUPERSEDED', '此旧提案已归档，请使用新配置流程。')
    if data['profile']['native_fingerprint'] != profile.native_fingerprint:
        raise LiteError('PROPOSAL_PROCESS_MISMATCH')
    if data.get('schema_version') == 'colayout-process-proposal-2':
        from .process_bundle import complete, publish
        from .drc.models import DrcProfile

        drc = drc_profile or DrcProfile.model_validate(data['drc_profile'])
        data.update(
            profile=profile.model_dump(mode='json'), drc_profile=drc.model_dump(mode='json')
        )
        write_json(path, data)
        data = complete(path, drc, progress=progress)
        profile = TechnologyProfile.model_validate(data['profile'])
        drc = DrcProfile.model_validate(data['drc_profile'])
        a = Adapter(NativeTransport(data['connection']))
        from .codec import decode

        live, actual = decode(a.native.read(data['source']['library'], data['source']['cell']))
        if actual.native_fingerprint != profile.native_fingerprint:
            raise LiteError('CONNECTED_PDK_MISMATCH')
        if data.get('source_semantic') and digest(live.semantic()) != data['source_semantic']:
            raise LiteError(
                'PDK_SAMPLE_CHANGED',
                '样例在测量后发生变化，请让 Agent 重新准备配置；已保存配置未覆盖。',
            )
        return publish(path, data, profile, drc, store or ProcessLibrary())
    if data.get('validation', {}).get('status') != 'passed' or data['validation'].get(
        'policy_key'
    ) != policy_key(profile):
        data = setup.validate(path, profile, progress)
    a = Adapter(NativeTransport(data['connection']))
    # Confirm the currently connected native technology, even when policy is unchanged.
    from .codec import decode

    _, actual = decode(a.native.read(data['source']['library'], data['source']['cell']))
    if actual.native_fingerprint != profile.native_fingerprint:
        raise LiteError('CONNECTED_PDK_MISMATCH')
    saved, pp = save_profile(
        a,
        profile,
        name=profile.id,
        writable_lpps=profile.writable_lpps,
        defaults=profile.editor_defaults,
    )
    saved = saved.model_copy(
        update={
            'validation': {
                'status': 'human-confirmed',
                'report': data['validation']['report'],
                'scope': data['validation']['scope'],
                'width_measurement': data['measurement'],
                'per_layer_width_measurement': data.get('stack_measurement'),
                'confirmed_at': datetime.now(timezone.utc).isoformat(),
            }
        }
    )
    saved.save(pp)
    store = store or ProcessLibrary()
    key = store.register(saved, pp, a.native.config_path, confirmed=True)
    config = {
        **a.native.config,
        'default_library': data['source']['library'],
        'default_source_cell': data['source']['cell'],
    }
    write_json(a.native.config_path, config)
    data.update(status='confirmed', confirmed_profile=str(pp), confirmed_policy=policy_key(saved))
    write_json(path, data)
    return key


def publish_legacy(path, data, profile, drc, store, *, writer):
    """Publish the reviewed files together; rollback caught write failures.

    Manifest/backups remain available for interrupted-process recovery. This
    does not claim OS crash atomicity across multiple files.
    """
    from .process_bundle import targets

    paths = targets({**data, 'profile': profile.model_dump(mode='json')}, store)
    expected = data.get('publication_base', {})
    for file in paths.values():
        if str(file.resolve()) not in expected or file_key(file) != expected[str(file.resolve())]:
            raise LiteError(
                'PROCESS_CONFIGURATION_CHANGED',
                '已保存配置在准备后发生变化，请重新准备，避免覆盖其他修改。',
            )
    now = datetime.now(timezone.utc).isoformat()
    p = profile.model_copy(
        update={
            'validation': {
                'status': 'human-confirmed',
                'report': data['validation']['report'],
                'scope': data['validation']['scope'],
                'width_measurement': data['measurement'],
                'per_layer_width_measurement': data.get('stack_measurement'),
                'drc_report': data['drc_validation']['report'],
                'confirmed_at': now,
            }
        }
    )
    entries = store.entries()
    key = p.key
    previous = entries.get(key, {})
    if previous.get('connection') != str(paths['connection'].resolve()):
        previous = {k: v for k, v in previous.items() if k != 'workspace'}
    entries[key] = {
        **previous,
        'id': p.id,
        'label': p.label,
        'native_fingerprint': p.native_fingerprint,
        'profile': str(paths['technology'].resolve()),
        'connection': str(paths['connection'].resolve()),
        'drc_profile': str(paths['drc'].resolve()),
        'confirmed': True,
        'configured_sections': ['technology', 'local_drc', 'remote_drc'],
    }
    cfg = json.loads(paths['connection'].read_text(encoding='utf8'))
    cfg.update(
        preferred_profile=p.id,
        default_library=data['source']['library'],
        default_source_cell=data['source']['cell'],
    )
    committed = {
        **data,
        'status': 'confirmed',
        'confirmed_at': now,
        'confirmed_profile': str(paths['technology'].resolve()),
        'confirmed_drc': str(paths['drc'].resolve()),
    }
    writes = {
        paths['technology']: p.model_dump(mode='json'),
        paths['drc']: drc.model_dump(mode='json'),
        paths['connection']: cfg,
        paths['registry']: {'schema_version': 'colayout-process-library-1', 'entries': entries},
        Path(path): committed,
    }
    from .process_transaction import publish_files

    publish_files(store, writes, expected, writer)
    return key


def update_preferences(
    store,
    key,
    *,
    width_um,
    layers,
    expected_profile,
    widths_um=None,
    schematic_summary_parameters=None,
):
    """Local preferences only. Never contact Virtuoso or resize geometry."""
    from .permissions import apply_profile_permissions
    from .process_measurements import metal_pair, policy_key

    entry = store.entries()[key]
    path = Path(entry['profile'])
    current = TechnologyProfile.model_validate_json(path.read_text(encoding='utf8'))
    if current != expected_profile:
        raise LiteError(
            'PROFILE_SETTINGS_CONFLICT', '配置已被其他操作更新，请重新打开工艺库后再修改。'
        )
    m1 = tuple(current.editor_defaults.get('layer') or (metal_pair(current)[0], 'drawing'))
    layers = [tuple(p) for p in layers]
    if m1 not in layers:
        raise LiteError(
            'M1_MUST_BE_WRITABLE', '请保留首层默认走线层 ' + '/'.join(m1) + ' 的绘图权限。'
        )
    from .wire_defaults import default_width

    if (
        widths_um is not None
        and width_um == default_width(current, m1)
        and all(v == default_width(current, k) for k, v in widths_um.items())
    ):
        widths_um = None  # Display-only edits must not materialize new geometry defaults.
    defaults = {**current.editor_defaults, 'layer': list(m1), 'width_um': width_um}
    if widths_um is not None or current.editor_defaults.get('widths_um'):
        defaults['widths_um'] = {
            **current.editor_defaults.get('widths_um', {}),
            **(widths_um or {}),
            m1[0]: width_um,
        }
    raw = current.model_dump()
    raw.update(writable_lpps=layers, editor_defaults=defaults)
    if schematic_summary_parameters is not None:
        raw['schematic_summary_parameters'] = schematic_summary_parameters
    candidate = TechnologyProfile.model_validate(raw)
    if candidate.model_dump(mode='json') == current.model_dump(mode='json'):
        return current
    if entry.get('workspace') and Path(entry['workspace']).exists():
        w = Workspace.model_validate_json(Path(entry['workspace']).read_text(encoding='utf8'))
        updated = apply_profile_permissions(w.baseline, candidate)
        closes_pending = any(
            op.shape and op.shape.kind != 'stdVia' and op.shape.lpp not in candidate.writable_lpps
            for op in w.operations
        )
        if closes_pending or (
            (w.operations or w.state in ('submitting', 'indeterminate', 'conflict'))
            and updated.semantic() != w.baseline.semantic()
        ):
            raise LiteError(
                'PROCESS_POLICY_CHANGED_WITH_DRAFT',
                '此工艺还有草稿或未完成同步，收放这些图层权限会影响草稿。请先处理草稿；默认线宽仍可单独修改。',
            )
    if policy_key(candidate) != policy_key(current):
        previous = current.validation.get('previous_validation', current.validation)
        candidate = candidate.model_copy(
            update={
                'validation': {
                    'status': 'settings-updated',
                    'previous_validation': previous,
                    'scope': '已通过本地单位/网格/层检查；新参数未重新执行原生往返验证。',
                }
            }
        )
    backup = store.folder / 'settings-backups' / uuid4().hex / 'profile.json'
    current.save(backup)
    candidate.save(path)
    return candidate

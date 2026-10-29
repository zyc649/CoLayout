"""Shared sample measurements and policy fingerprints; no publication entry."""

import math
from .model import LiteError, digest
from .technology import TechnologyProfile


def metal_pair(profile, explicit=None):
    metals = {
        r['layer'] for r in profile.layers if r['material'] == 'metal' and r['purpose'] == 'drawing'
    }
    edges = {
        (v['layer1'], v['layer2'])
        for v in profile.vias.values()
        if v['layer1'] in metals and v['layer2'] in metals
    }
    if explicit:
        if tuple(explicit) not in edges:
            raise LiteError('METAL_PAIR_NOT_IN_TECHNOLOGY')
        return tuple(explicit)
    bottom = metals - {b for a, b in edges}
    if len(bottom) == 1:
        lower = next(iter(bottom))
        upper = {b for a, b in edges if a == lower}
        if len(upper) == 1:
            return lower, next(iter(upper))
    raise LiteError(
        'METAL_STACK_AMBIGUOUS',
        'Agent 需核对原生层次后用 --metal1/--metal2 指定；不要按字母排序猜层次。',
    )


def measure_single_via(snapshot, profile, pair, via_uid=None):
    from .scene import figures_by_owner

    possible = []
    for uid, o in snapshot.objects.items():
        if o.kind != 'stdVia' or not o.shape or o.group_uid:
            continue
        vd = profile.vias.get(o.shape.via_definition, {})
        if (
            vd.get('kind') != 'stdViaDef'
            or vd.get('cut_pattern')
            or (vd['layer1'], vd['layer2']) != pair
        ):
            continue
        params = profile.effective_via(o.shape)
        if params['cutRows'] == params['cutColumns'] == 1 and (via_uid is None or via_uid == uid):
            possible.append(o)
    figures, _ = (
        figures_by_owner(snapshot, owner_filter={o.uid for o in possible}) if possible else ({}, {})
    )
    measured = []
    for o in possible:
        rectangles = {}
        for layer in pair:
            parts = [
                f
                for f in figures.get(o.uid, [])
                if f['kind'] == 'rect' and f['style'] == layer + '/drawing'
            ]
            if len(parts) != 1:
                break
            b = parts[0]['bbox']
            w = b[1][0] - b[0][0]
            h = b[1][1] - b[0][1]
            if min(w, h) <= 0 or abs(w - round(w)) > 1e-6 or abs(h - round(h)) > 1e-6:
                break
            rectangles[layer] = {
                'bbox_dbu': b,
                'size_dbu': [round(w), round(h)],
                'side_dbu': min(round(w), round(h)),
                'width_basis': 'short_side',
            }
        if len(rectangles) != 2:
            continue
        measured.append(
            {
                'uid': o.uid,
                'definition': o.shape.via_definition,
                'origin_dbu': o.shape.origin,
                'metal_rectangles': rectangles,
                'width_dbu': rectangles[pair[0]]['side_dbu'],
                'effective_via_parameters': profile.effective_via(o.shape),
                'width_um': rectangles[pair[0]]['side_dbu'] / profile.dbu_per_micron,
            }
        )
    if not measured:
        raise LiteError(
            'SAMPLE_SINGLE_VIA_REQUIRED',
            f'样例顶层需一个 {pair[0]}–{pair[1]}、1×1 标准过孔，可读取两层金属矩形；接触孔、器件内部孔或阵列不能代替。',
        )
    signatures = {
        (m['definition'], tuple(tuple(m['metal_rectangles'][l]['size_dbu']) for l in pair))
        for m in measured
    }
    if len(signatures) > 1:
        raise LiteError(
            'SAMPLE_VIA_AMBIGUOUS',
            '存在尺寸或定义不同的单孔，Agent 用 --via-uid 选择明确样例。',
            candidates=measured,
        )
    result = measured[0]
    quantum = math.lcm(profile.grid, 2)
    # The path kernel requires positive even DBU on the manufacturing grid.
    rounded = math.ceil(result['width_dbu'] / quantum) * quantum
    result.update(
        suggested_width_um=rounded / profile.dbu_per_micron,
        rounded_to_path_grid=rounded != result['width_dbu'],
        basis='从实际 via master 的金属矩形短边测量；不是切孔宽度或最小 DRC 阈值。',
        matching_candidates=len(measured),
    )
    return result


def settings_profile(
    proposal, name, width, layers, *, widths_um=None, schematic_summary_parameters=None
):
    p = TechnologyProfile.model_validate(proposal['profile'])
    layer = (proposal['metal_pair'][0], 'drawing')
    if layer not in [tuple(v) for v in layers]:
        raise LiteError('M1_MUST_BE_WRITABLE', '请保留首层默认走线层的写权限。')
    defaults = {
        **p.editor_defaults,
        'layer': layer,
        'width_um': width,
        'via_definition': proposal['measurement']['definition'],
    }
    if widths_um is not None:
        defaults['widths_um'] = {**widths_um, layer[0]: width}
    elif defaults.get('widths_um'):
        defaults['widths_um'] = {**defaults['widths_um'], layer[0]: width}
    data = p.model_dump()
    data.update(id=name.strip(), label=name.strip(), writable_lpps=layers, editor_defaults=defaults)
    if schematic_summary_parameters is not None:
        data['schematic_summary_parameters'] = schematic_summary_parameters
    if not name.strip():
        raise LiteError('PROFILE_NAME_REQUIRED')
    return TechnologyProfile.model_validate(data)


def policy_key(profile):
    data = {
        k: profile.model_dump().get(k)
        for k in [
            'native_fingerprint',
            'native_technology_name',
            'configuration_id',
            'dbu_per_micron',
            'grid',
            'writable_lpps',
            'editor_defaults',
            'guard_templates',
            'guard_recipes',
        ]
    }
    if profile.material_evidence:
        data['materials'] = [profile.layers, profile.model_dump(mode='json')['material_evidence']]
    return digest(data)

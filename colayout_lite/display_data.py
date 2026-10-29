"""Decode native vector data and styles; no Qt or live server access."""

import math
from collections import Counter


def decode_display(raw, *, known_styles=None):
    version, session, handle, counter, bbox, figures, styles, unsupported = raw[:8]
    if version != 'colayout-display-0.1':
        raise ValueError('Unsupported display cache version')

    def point(p):
        values = [float(v) for v in p]
        if len(values) != 2 or not all(math.isfinite(v) for v in values):
            raise ValueError('Invalid display point')
        return values

    result = {
        'schema_version': version,
        'session_id': session,
        'cell_handle': handle,
        'source_counter': counter,
        'bbox': [point(p) for p in bbox],
        'figures': [],
        'styles': {},
        'unsupported': unsupported or [],
    }
    prefs = dict(raw[8] or []) if len(raw) > 8 else {}
    if known_styles is not None:
        result['styles'] = known_styles
    result['preferences'] = {
        'pin_names_visible': bool(prefs.get('pin_names_visible')),
        'native_stop_level': int(prefs.get('native_stop_level') or 0),
    }
    for key, row in styles or []:
        lpp, name, priority, visible, material, packet, fill, outline, stipple, line = row
        result['styles'][key] = {
            'lpp': lpp,
            'packet': name,
            'priority': int(priority or 0),
            'visible': bool(visible),
            'material': material,
            'fill_rgb': [int(round(float(v))) for v in fill[2:5]] if fill else [255, 0, 255],
            'outline_rgb': [int(round(float(v))) for v in outline[2:5]]
            if outline
            else [255, 0, 255],
            'fill_style': packet[6] if packet and len(packet) > 6 else 'outline',
            'stipple_name': packet[2] if packet else 'blank',
            'stipple': [[int(v) for v in r] for r in stipple[4]] if stipple else [],
            'line_width': float(line[2]) if line else 1,
            'line_pattern': [int(v) for v in (line[4] or [1])] if line else [1],
            'is_cut': material == 'cut',
            'definition_found': bool(packet),
        }
    for row in figures or []:
        ident, owner, internal, via, kind, style, box, geom = row
        g = dict(geom or [])
        for key in ('visible', 'pin_label'):
            if key in g:
                g[key] = bool(g[key])
        for k in ('xy',):
            if k in g:
                g[k] = point(g[k])
        for key in ('points', 'boundary'):
            if key in g:
                g[key] = [point(p) for p in g[key] or []]
        for k in ('width', 'height', 'begin_extension', 'end_extension'):
            if k in g:
                g[k] = float(g[k])
        result['figures'].append(
            {
                'id': ident,
                'owner_id': owner,
                'inside_instance': bool(internal),
                'via_occurrence': via,
                'kind': kind,
                'style': style,
                'bbox': [point(p) for p in box],
                'geometry': g,
            }
        )
    result['counts'] = dict(Counter(f['kind'] for f in result['figures']))
    result['cut_count'] = sum(result['styles'][f['style']]['is_cut'] for f in result['figures'])
    return result

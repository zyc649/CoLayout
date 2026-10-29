"""Calibre 2019.3 region directives; also uploaded to the Python 3.6 server.

Installed SVRF reference: Layout Windel / Layout Window Clip. CLIP NO drops
wholly contained input objects and preserves whole boundary-crossing objects.
"""

import hashlib
import json
import math
import re
from decimal import Decimal


def validate_windows(windows):
    if not isinstance(windows, (list, tuple)):
        raise ValueError('waive_regions_um must be an array of rectangles')
    result = []
    for bounds in windows:
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
            raise ValueError('Each waive region must be [xmin,ymin,xmax,ymax] in micrometres')
        if any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in bounds
        ):
            raise ValueError('Waive coordinates must be finite numbers')
        x, y, xx, yy = bounds
        if x >= xx or y >= yy:
            raise ValueError('Waive regions must have positive area and ordered coordinates')
        result.append([float(v) for v in bounds])
    return result


def waiver_receipt(windows):
    windows = validate_windows(windows)
    encoded = json.dumps(windows, separators=(',', ':'), allow_nan=False).encode('ascii')
    return {
        'method': 'calibre_layout_windel',
        'layout_window_clip': False,
        'region_count': len(windows),
        'regions_sha256': hashlib.sha256(encoded).hexdigest(),
    }


def build_deck(data, gds, cell, folder, window_um, maximum, waive_regions_um=()):
    windows = validate_windows(waive_regions_um)
    validate_windows([window_um])
    # Never silently combine an unknown deck's filtering with our scope.
    for pattern in [r'^\s*LAYOUT WINDOW\b', r'^\s*LAYOUT WINDEL\b']:
        if re.search(pattern, data, re.M | re.I):
            raise ValueError('Deck already defines region filtering; configure a clean deck')
    replacements = {
        'LAYOUT PATH': '"' + gds + '"',
        'LAYOUT PRIMARY': '"' + cell + '"',
        'DRC RESULTS DATABASE': '"' + folder + '/drc.results" ASCII',
        'DRC SUMMARY REPORT': '"' + folder + '/drc.summary"',
    }
    for key, value in replacements.items():
        data, count = re.subn(
            r'^\s*' + key + r'\s+[^\n]+$', lambda _: key + ' ' + value, data, flags=re.M | re.I
        )
        if count != 1:
            raise ValueError('Expected one ' + key + ' directive, got ' + str(count))
    data = re.sub(r'^\s*DRC MAXIMUM RESULTS\s+[^\n]+$', '', data, flags=re.M | re.I)

    def coords(bounds):
        return ' '.join(format(Decimal(str(v)), 'f') for v in bounds)

    directives = ['LAYOUT WINDOW ' + coords(window_um), 'LAYOUT WINDOW CLIP NO']
    directives.extend('LAYOUT WINDEL ' + coords(bounds) for bounds in windows)
    directives.append('DRC MAXIMUM RESULTS ' + str(maximum))
    data, count = re.subn(
        r'^\s*LAYOUT SYSTEM GDSII\s*$',
        lambda _: 'LAYOUT SYSTEM GDSII\n' + '\n'.join(directives),
        data,
        flags=re.M | re.I,
    )
    if count != 1:
        raise ValueError('Expected one explicit LAYOUT SYSTEM GDSII in configured deck')
    return data

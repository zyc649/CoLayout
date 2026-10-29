"""Legend layout and letterboxing for narrow snapshots; no geometry expansion."""

from math import ceil
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPen, QImage, QPainter, QFontMetricsF
from .capture_annotations import colors_for, font_for, REASONS


def frame_width(data, width, height):
    x, y, xx, yy = data['bounds']
    natural = min(width, height * (xx - x) / (yy - y))
    minimum = min(width, max(320, min(width, height) * 0.5))
    return min(width, ceil(max(natural, minimum)))


def legend_lines(data):
    summary = data['summary']
    lines = []
    target = summary.get('target')
    if target:
        name = target['id']
        if target['kind'] == 'pin':
            name = next((pin['label'] for pin in data['pins'] if pin['id'] == target['id']), name)
        lines.append(('目标：' + name, None))
    if summary['shorts']:
        names = sorted({net for row in summary['shorts'] for net in row['nets']})
        lines.append(
            ('短接：' + ' / '.join(names) + '。红色 × 是冲突端口，不是实际短接点。', '#ff9b8f')
        )
    for row in summary['pin_issues'][:4]:
        lines.append(
            (
                row.get('pin_name', row['pin_id'])
                + '：'
                + REASONS.get(row['reason'], row['reason']),
                '#ff9b8f',
            )
        )
    if len(summary['pin_issues']) > 4:
        lines.append((f'另有 {len(summary["pin_issues"]) - 4} 个异常，完整诊断见 JSON', '#ff9b8f'))
    ids = sorted(data['components'])
    for i in range(0, min(len(ids), 12), 4):
        lines.append(
            (
                '    '.join(
                    cid
                    + ':'
                    + ','.join(
                        sorted({n['layer'] for n in data['nodes'] if n['component_id'] == cid})
                    )
                    for cid in ids[i : i + 4]
                ),
                None,
            )
        )
    if len(ids) > 12:
        lines.append((f'另有 {len(ids) - 12} 个分量，见 JSON', None))
    if summary['hidden_connection_layers']:
        lines.append(('隐藏连接层：' + ','.join(summary['hidden_connection_layers']), '#f0d886'))
    if summary['coverage_warnings']:
        lines.append(('几何/模型覆盖不足，不能确认全部连接', '#f0d886'))
    lines.append(('物理分量分色 · 黄色为过孔 · 虚线为接口范围 · 同名网络不代表已接通', None))
    return lines


def wrap(text, metrics, width):
    line = ''
    for char in text:
        if line and metrics.horizontalAdvance(line + char) > width:
            yield line
            line = ''
        line += char
    if line:
        yield line


def legend_rows(data, width):
    unit = data.get('legend_unit', max(0.8, width / 1600))
    metrics = QFontMetricsF(font_for(unit))
    available = max(1, width - 20 * unit)
    colors = colors_for(data['components'])
    result = []
    for text, color in legend_lines(data):
        pieces = text.split('    ')
        if all(piece.split(':')[0] in colors for piece in pieces):
            row = []
            used = 0
            for piece in pieces:
                size = metrics.horizontalAdvance(piece) + 24 * unit
                if size > available:
                    if row:
                        result.append(row)
                        row = []
                        used = 0
                    result.extend(
                        [(part, colors[piece.split(':')[0]].name())]
                        for part in wrap(piece, metrics, available)
                    )
                    continue
                if row and used + size > available:
                    result.append(row)
                    row = []
                    used = 0
                row.append((piece, colors[piece.split(':')[0]].name()))
                used += size
            if row:
                result.append(row)
        else:
            # Bounded display only; full names and evidence stay in JSON.
            if len(text) > 600:
                text = text[:600] + '…（完整说明见 JSON）'
            result.extend([(part, color)] for part in wrap(text, metrics, available))
    return result


def footer_height(data, width):
    if data['mode'] == 'none':
        return 0
    unit = data.get('legend_unit', max(0.8, width / 1600))
    return ceil((12 + 24 * len(legend_rows(data, width))) * unit)


def compose(image, data, args, minimum_width):
    width = min(args.width, max(image.width(), minimum_width))
    height = min(args.height // 2, footer_height(data, width))
    available = max(1, args.height - height)
    if image.height() > available or image.width() > width:
        image = image.scaled(
            width,
            available,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    height = min(height, args.height - image.height())
    out = QImage(width, image.height() + height, QImage.Format.Format_ARGB32)
    out.fill(QColor('#11151b'))
    painter = QPainter(out)
    left = (width - image.width()) // 2
    painter.drawImage(left, 0, image)
    shown = []
    if height:
        unit = data.get('legend_unit', max(0.8, width / 1600))
        painter.setFont(font_for(unit))
        metrics = QFontMetricsF(painter.font())
        painter.setPen(QPen(QColor('#495567'), unit))
        painter.drawLine(0, image.height(), width, image.height())
        rows = legend_rows(data, width)
        capacity = max(1, int((height / unit - 12) / 24))
        if len(rows) > capacity:
            rows = rows[: capacity - 1] + [[('更多说明见 JSON', '#f0d886')]]
        for index, row in enumerate(rows):
            x = 10 * unit
            for text, color in row:
                painter.setPen(QColor(color or '#d8e3ef'))
                painter.drawText(
                    QRectF(
                        x,
                        image.height() + (6 + index * 24) * unit,
                        width - x - 10 * unit,
                        24 * unit,
                    ),
                    Qt.AlignmentFlag.AlignVCenter,
                    text,
                )
                x += metrics.horizontalAdvance(text) + 24 * unit
            shown.append('    '.join(text for text, _ in row))
    painter.end()
    return out, [left, 0, image.width(), image.height()], shown

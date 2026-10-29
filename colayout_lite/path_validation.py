"""Reject unstable wire centre-lines before local adoption/native conversion."""

from .model import LiteError


def validate_path_points(points):
    for index, (a, b) in enumerate(zip(points, points[1:])):
        if a == b:
            raise LiteError(
                'INVALID_PATH_SEGMENT',
                f'第 {index + 1}、{index + 2} 个点重复，形成零长度线段；请删除重复点。图形未采用。',
                point_indices=[index, index + 1],
                reason='zero_length',
                edit_applied=False,
            )
    for index, (a, b, c) in enumerate(zip(points, points[1:], points[2:])):
        ab = (b[0] - a[0], b[1] - a[1])
        bc = (c[0] - b[0], c[1] - b[1])
        if ab[0] * bc[1] == ab[1] * bc[0] and ab[0] * bc[0] + ab[1] * bc[1] < 0:
            raise LiteError(
                'PATH_BACKTRACK',
                f'第 {index + 1} 至 {index + 3} 个点共线折返；请按实际连接意图改成直线或不重叠的转弯。图形未采用。',
                point_indices=[index, index + 1, index + 2],
                reason='collinear_reversal',
                points_dbu=[list(a), list(b), list(c)],
                edit_applied=False,
            )

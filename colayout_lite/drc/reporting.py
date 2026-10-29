"""Portable rule evidence with explicit units and advisory/blocking counts."""

from .design_warnings import blocking


def marker_payload(marker, scale):
    row = marker.model_dump(mode='json') if hasattr(marker, 'model_dump') else dict(marker)
    row['bounds_um'] = [v / scale for point in row['bbox'] for v in point]
    row['points_um'] = [[v / scale for v in point] for point in row.get('points', [])]
    row['edges_um'] = [[v / scale for v in edge] for edge in row.get('edges', [])]
    row['coordinates'] = 'workspace_um; original bbox/points/edges remain DBU'
    return row


def counts(markers):
    return {
        'technology_errors': sum(m['severity'] == 'error' and blocking(m) for m in markers),
        'technology_warnings': sum(m['severity'] == 'warning' and blocking(m) for m in markers),
        'design_warnings': sum(not blocking(m) for m in markers),
    }


def report_payload(report):
    result = report.model_dump(mode='json')
    result['markers'] = [marker_payload(m, report.dbu_per_micron) for m in report.markers]
    result['counts'] = counts(result['markers'])
    result['status_meaning'] = (
        'completed means analysis finished; coverage and findings determine the check outcome'
    )
    return result

"""Import diagnostics are evidence, never an extra success/failure condition."""
import logging
from .transactions import write_json_atomic


def save_report(path,report):
    try:write_json_atomic(path,report)
    except OSError:
        logging.getLogger(__name__).exception('Could not save import timing report: %s',path)

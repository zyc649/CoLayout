"""One frozen check per process, with durable outcome and execution diagnostics."""

import sys
import traceback

from . import jobs
from .job_storage import read_json, write_json, write_result
from ..model import Workspace, LiteError
from ..technology import TechnologyProfile
from .models import DrcProfile, Region


def execute(uid):
    folder = jobs.job_folder(uid)
    state = {'job_id': uid, 'stage': 'load_input', 'drc_completed': False,
             'result_available': False}

    def progress(status, message, *, stage=None, drc_completed=None):
        state.update(status=status, message=message)
        if stage is not None:
            state['stage'] = stage
        if drc_completed is not None:
            state['drc_completed'] = drc_completed
        write_json(folder / 'state.json', state)

    def finish(status, message, error=None):
        state.update(status=status, message=message)
        if error is not None:
            state['error'] = error
        # A separate terminal receipt survives contention on the polled file.
        write_json(folder / 'terminal.json', state)
        try:
            write_json(folder / 'state.json', state)
        except LiteError:
            traceback.print_exc()  # The authoritative terminal receipt is durable.

    def checkpoint():
        if (folder / 'cancel.flag').exists():
            raise LiteError('DRC_CANCELLED')

    try:
        request = read_json(folder / 'request.json')
        state['engine'] = request['engine']
        checkpoint()
        w = Workspace.model_validate(read_json(folder / 'workspace.json'))
        p = TechnologyProfile.model_validate(read_json(folder / 'technology.json'))
        profile = DrcProfile.model_validate(read_json(folder / 'profile.json'))
        region = Region.model_validate(request['region'])
        if request['engine'] == 'local':
            from .local import run
            progress('running', '正在本地检查所选区域…', stage='local_check')
            answer = run(w, p, profile, region, job_id=uid, checkpoint=checkpoint,
                         scope_id=request.get('scope_id', ...))
        else:
            from .remote import run
            answer = run(w, p, profile, region, uid, folder, progress,
                         waive_regions_um=request.get('waive_regions_um', ()),
                         scope_info=request.get('scope'), result_limit=request.get('result_limit'))
        state.update(drc_completed=True, stage='result_save')
        checkpoint()
        write_result(folder / 'result.json', answer)
        state.update(result_available=True, stage='completed')
        finish('completed', f'检查完成：{len(answer.markers)} 个标记')
    except Exception as exc:
        trace = traceback.format_exc()
        print(trace, file=sys.stderr)
        try:
            (folder / 'error.txt').write_text(trace, encoding='utf8')
        except OSError:
            pass  # The redirected worker log still contains the full traceback.
        code = getattr(exc, 'code', 'DRC_FAILED')
        cancelled = code in ('DRC_CANCELLED', 'NATIVE_REQUEST_CANCELLED')
        details = {**getattr(exc, 'details', {})}
        details.update(
            stage=details.get('stage', state['stage']), execution_stage=state['stage'],
            drc_completed=state['drc_completed'], result_available=state['result_available'],
            native_job_id=uid,
        )
        if code == 'DRC_JOB_STORAGE_UNAVAILABLE':
            details.update(retryable=False, next_action='contact_maintenance',
                           guidance='任务文件访问失败；请携带任务 ID 联系维护人员。这不是工艺违规，无需修改版图。')
        finish('cancelled' if cancelled else 'failed', str(exc),
               {'code': code, 'message': str(exc), 'details': details})


def main():
    execute(sys.argv[1])


if __name__ == '__main__':
    main()

"""Routing task feedback: animated activity, real phases and persistent outcome."""
from ..task_activity import TaskActivity


class RoutingActivity(TaskActivity):
    def __init__(self,parent=None):
        super().__init__(parent,idle_title='准备布线',running_title='正在生成候选',idle_message='选中一个操作区或进入其内部后生成。')


def blocked_reason(window,target,layers):
    e=window.editor
    if not e:return '请先打开工作区。'
    if e.w.state in ('submitting','indeterminate'):
        return '上次同步结果待核对，暂不能布线。请先核对同步；若以服务器状态重新开始，可备份后重新导入。'
    if e.w.state=='conflict':return '工作区与服务器存在差异，请备份后重新导入或解决同步冲突。'
    if window.busy:return '其他工作区任务正在运行，请等待完成。'
    if target not in e.w.local_data.regions:return '请先选中一个操作区，或双击进入操作区。'
    if reason:=e.work_sessions.readonly_reason(scope_id=target):return reason
    if not layers:return '请至少选择一个可布线金属层。'
    return None

"""Human-readable DRC result summaries; diagnostic payloads stay in job records."""


def failure_text(state):
    details = state.get('error', {}).get('details', {})
    stage = details.get('execution_stage', details.get('stage', state.get('stage', 'unknown')))
    stages = {'queued':'排队', 'load_input':'加载输入', 'native_channel':'等待服务器通道',
              'source_verification':'核对源版图', 'snapshot_preparation':'准备检查副本',
              'snapshot_commit':'应用并核对副本修改', 'remote_launch':'启动服务器任务',
              'export':'导出快照', 'waiting_for_export_verification':'核对导出',
              'calibre':'执行 Calibre', 'report_download':'接收报告',
              'report_validation':'核对报告', 'result_save':'保存结果', 'local_check':'本地检查'}
    yes_no = lambda value: '是' if value is True else '否' if value is False else '未知'
    return '\n'.join([
        '任务未取得检查结论；这不是版图 DRC 违规。',
        '执行阶段：' + stages.get(stage, stage),
        'DRC 已执行完成：' + yes_no(details.get('drc_completed', state.get('drc_completed'))),
        '已有可用结果：' + yes_no(details.get('result_available', state.get('result_available'))),
        '任务 ID：' + state.get('job_id', '未知'),
        details.get('guidance', '请携带任务 ID 联系维护人员；不要依据此错误修改版图。'),
    ])


def summary(result,waived,stale):
    count=len(result.markers)-len(waived)
    active=[m for m in result.markers if m.id not in waived]
    from .design_warnings import blocking
    errors=sum(m.severity=='error' and blocking(m) for m in active)
    advice=sum(not blocking(m) for m in active)
    text=f'检查完成 · 工艺错误 {errors} · 设计 warning {advice} · {count} 项待复核' if count else '检查完成 · 未发现待处理问题'
    if waived:text+=f' · {len(waived)} 项已按现有设置忽略'
    if stale:text='版图或检查配置已变化，请重新检查。\n'+text
    if result.coverage.get('warnings') or result.coverage.get('truncated'):text+='\n检查有未覆盖内容，请查看下方说明。'
    return text


def coverage_text(result):
    from .scope import HIERARCHY_POLICY, SERVER_BOUNDARY_POLICY
    text='点击问题可在画布定位，并查看规则说明。'
    text+='\n本地轻量检查通过仅表示支持的检查项通过。' if result.engine=='local' else '\n已检查所选操作区；区域检查不代表整芯片签核。'
    if result.engine=='calibre' and result.coverage.get('boundary_policy')!=SERVER_BOUNDARY_POLICY:
        text+='\n此为旧版服务器检查报告，未按当前黑盒范围执行；请重新检查。'
    if result.coverage.get('scope'):
        scope=result.coverage['scope']
        if scope.get('selection_policy')!=HIERARCHY_POLICY:
            text+='\n此为旧版层次判定结果，可能误排除普通器件；请重新检查。'
        text+='\n'+scope['meaning']
        text+=f"\n本次排除 {scope['child_regions_excluded']} 个子操作区、{scope['native_instances_excluded']} 个原生层次模块内部。"
        if 'ordinary_instances_included' in scope:
            text+=f"普通器件 {scope['ordinary_instances_included']} 个正常参与检查。"
    for key in ('warnings','limitations'):
        values=result.coverage.get(key,[])
        if isinstance(values,str):values=[values]
        text+=''.join('\n'+str(value) for value in values)
    if result.coverage.get('truncated'):text+='\n结果有截断，不能按完整检查判断。'
    return text

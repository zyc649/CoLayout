"""Completion requires current full-region local and server checks to both pass."""


def _check(registry,lease,kind):
    jobs=[j for j in registry.jobs.values() if j.lease is lease and j.kind==kind]
    tool='check_region' if kind=='check' else 'server_drc_region'
    if not jobs:return {'state':'not_checked','next_action':f'运行 {tool}，等待当前全区检查通过。'}
    job=max(jobs,key=lambda j:j.started);registry.poll(job);current=registry.current(job)
    result=job.result if isinstance(job.result,dict) else {}
    if kind=='server_drc' and job.state=='completed' and current:
        from .server_drc import filtered_report
        from ..model import LiteError
        try:result=filtered_report(result,limit=0)
        except (LiteError,ValueError,OSError) as exc:
            return {'state':'policy_error','job_id':job.id,'job_state':job.state,'current':current,
                    'source_revision':job.source_revision,'summary':'工艺过滤设置无法核验',
                    'next_action':'请由人检查工艺过滤设置；可 handoff 交还操作区，不能标记完成。',
                    'error_code':getattr(exc,'code','REPORT_POLICY_UNAVAILABLE')}
    if job.state in ('queued','running'):
        state,action='running',f'等待 {tool} 任务完成。'
    elif not current:
        state,action='stale','本层相关输入或工艺配置已变化，请重新运行全区本地和服务器检查；推荐先本地后服务器。'
    elif job.state!='completed':
        state,action='failed','检查未完成；先查看任务错误，再决定是否重试。'
    elif not result.get('passed') or not result.get('completion_eligible',False):
        state,action='not_passed',f'修复检查问题并重新运行全区 {tool}；局部检查不能代替全区验收。'
    else:
        state,action='passed',f'当前全区 {tool} 已通过。'
    evidence=({k:result[k] for k in ('report_policy_digest','active_marker_count','suppressed_marker_count')}
              if 'report_policy_digest' in result else {})
    return {**evidence,'state':state,'job_id':job.id,'job_state':job.state,'current':current,
            'source_revision':job.source_revision,'summary':result.get('summary',job.message),'next_action':action}


def local_verification(registry,lease):
    return _check(registry,lease,'check')


def verification(session,lease):
    return verification_registry(session.tasks,lease)


def verification_registry(registry,lease):
    local=local_verification(registry,lease);server=_check(registry,lease,'server_drc')
    if local['state']!='passed':state,action=local['state'],local['next_action']
    elif server['state']!='passed':state,action='server_'+server['state'],server['next_action']
    else:state,action='passed','当前全区连通性、本地 DRC 与服务器 DRC 均已通过。'
    return {**local,'state':state,'next_action':action,'local':local,'server':server,
            'required_order':[],
            'required_checks':['check_region','server_drc_region'],'recommended_order':['check_region','server_drc_region'],
            'scope':'本接入区的当前全区验收；不代表整芯片/黑盒内部或 LVS 签核。'}

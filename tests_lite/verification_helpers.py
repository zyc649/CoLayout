"""Explicit completed worker evidence for orchestration-only tests."""
from threading import Event
from uuid import uuid4
from colayout_lite.agent_tools.jobs import Job


def check_evidence(session,token,*,passed=True,full=True,kind='check',state='completed',prerequisite=None):
    lease=session.leases[token];e=session.editor;rules=session.drc_source();ident=uuid4().hex
    job=Job(ident,lease,kind,e.w,e.profile,rules,session.folder/ident,Event())
    job.state=state;job.result={'passed':passed,'completion_eligible':full,'summary':'controlled worker evidence'}
    if kind=='server_drc':
        job.result.update(engine='calibre',engine_status='completed',
            technology_fingerprint=e.profile.native_fingerprint,configuration_id=e.profile.configuration_id,
            coverage={'rule_checks_executed':1,'truncated':False},
            markers=[] if passed else [{'id':'failure','rule_id':'CONTROLLED_TEST_FAILURE',
                'description':'Controlled blocking failure','suppression_categories':[]}])
    if prerequisite:job.result['prerequisite_local_check_id']=prerequisite
    session.jobs[ident]=job
    if kind=='check' and full and state=='completed':lease.last_check=ident
    return job

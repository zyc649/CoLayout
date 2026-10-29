"""Human-approved server review shared by UI, API and completion checks."""
import re
from typing import Literal
from pydantic import field_validator,Field
from ..model import Record,LiteError,digest
from ..paths import ROOT


class WaiverPolicy(Record):
    schema_version:Literal['colayout-drc-waivers-1']='colayout-drc-waivers-1'
    technology_fingerprint:str
    configuration_id:str|None=Field(default=None,exclude_if=lambda v:v is None)
    enabled:bool=True
    rule_ids:tuple[str,...]=()
    keywords:tuple[str,...]=()

    @field_validator('rule_ids','keywords')
    @classmethod
    def normalize(cls,values):
        if any(not v.strip() for v in values):raise ValueError('Waive 项不能为空')
        return tuple(dict.fromkeys(v.strip() for v in values))

    def reasons(self,marker,engine):
        return self.match(marker.rule_id,marker.message,engine)

    def match(self,rule_id,message,engine):
        if not self.enabled or engine!='calibre':return ()
        found=['rule:'+r for r in self.rule_ids if r.casefold()==rule_id.casefold()]
        # Match visible rule content, not source paths or global deck titles.
        body='\n'.join(s for s in message.splitlines() if not s.lower().startswith(('rule file pathname:','rule file title:')))
        text=re.sub(r'\s+',' ',rule_id+' '+body).casefold()
        found.extend('keyword:'+k for k in self.keywords if re.sub(r'\s+',' ',k).casefold() in text)
        return tuple(found)


def path_for(fingerprint):return ROOT/'config/drc-waivers'/(digest(fingerprint)+'.json')


def load(fingerprint,configuration_id=None):
    path=path_for(configuration_id or fingerprint)
    if not path.exists():return WaiverPolicy(technology_fingerprint=fingerprint,configuration_id=configuration_id)
    result=WaiverPolicy.model_validate_json(path.read_text(encoding='utf8'))
    if result.technology_fingerprint!=fingerprint:raise LiteError('WAIVER_TECHNOLOGY_MISMATCH')
    if (result.configuration_id or fingerprint)!=(configuration_id or fingerprint):raise LiteError('WAIVER_CONFIGURATION_MISMATCH')
    return result


def save(policy):policy.save(path_for(policy.configuration_id or policy.technology_fingerprint))


def assess(rows,policy,engine,coverage,status='completed'):
    """Rows are (id, rule_id, visible message); paging never changes acceptance."""
    waived={};total=0
    for ident,rule_id,message in rows:
        total+=1
        if reasons:=policy.match(rule_id,message,engine):waived[ident]=list(reasons)
    decision={'total_count':total,'active_count':total-len(waived),'waived_count':len(waived),'waived_markers':waived}
    if engine=='calibre':
        complete=(status=='completed' and not coverage.get('warnings') and not coverage.get('truncated',False)
                  and bool(coverage.get('rule_checks_executed')))
        decision.update(coverage_complete=bool(complete),passed=bool(complete and total==len(waived)))
    return decision


def assessment(result,policy=None):
    policy=policy or load(result.technology_fingerprint,result.configuration_id)
    if policy.technology_fingerprint!=result.technology_fingerprint:raise LiteError('WAIVER_TECHNOLOGY_MISMATCH')
    if (policy.configuration_id or policy.technology_fingerprint)!=(result.configuration_id or result.technology_fingerprint):raise LiteError('WAIVER_CONFIGURATION_MISMATCH')
    return assess(((m.id,m.rule_id,m.message) for m in result.markers),policy,result.engine,result.coverage,result.status)


def review(result,policy=None):
    policy=policy or load(result.technology_fingerprint,result.configuration_id)
    decision=assessment(result,policy);waived=decision['waived_markers']
    return {'schema_version':'colayout-drc-review-1','result':result.model_dump(mode='json'),
        'waiver_policy':policy.model_dump(mode='json'),'waiver_policy_digest':digest(policy.model_dump()),
        **decision,
        'active_marker_ids':[m.id for m in result.markers if m.id not in waived],'waived_markers':waived,
        'note':'按人端工艺过滤设置审阅；UI、API 与区域完成验收共用此策略。原始结果保留，不代表整芯片或 LVS 签核。'}

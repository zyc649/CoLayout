"""Region APIs use micrometres; result coordinates are explicit layout DBU."""
from .models import Region,Result,DrcProfile
from .local import run
from . import jobs


def check_local(workspace,technology,drc_profile,region_um):
    return run(workspace,technology,drc_profile,Region.from_um(region_um,technology.dbu_per_micron))


def start_check(workspace,technology,drc_profile,region_um,engine='local',*,scope_id=...):
    return jobs.start(workspace,technology,drc_profile,Region.from_um(region_um,technology.dbu_per_micron),engine,scope_id=scope_id)


get_status=jobs.status
get_result=jobs.result
cancel=jobs.cancel


def review_result(job_id,policy=None):
    from .waivers import review
    return review(jobs.result(job_id),policy)

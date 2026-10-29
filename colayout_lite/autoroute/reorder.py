"""Bounded candidate-only rip-up/reorder; never removes imported/user geometry."""
from .models import PluginResult


def solve(problem,count=2):
    from .builtin import one
    proposals=[]
    for variant in range(count):
        order=None;best=None;best_fail=10**9;history=[];seen=set()
        for step in range(3):
            candidate=one(problem,'pattern',variant,order)
            failed={d['net'] for d in candidate.diagnostics if d.get('code') and d.get('net')}
            history.append({'pass':step+1,'order':candidate.parameters['net_order'],'unrouted_nets':sorted(failed)})
            if len(failed)<best_fail:best=candidate;best_fail=len(failed)
            if not failed:break
            previous=candidate.parameters['net_order'];seen.add(tuple(previous))
            order=[n for n in previous if n in failed]+[n for n in previous if n not in failed]
            if tuple(order) in seen:
                order=list(reversed(order))
                if tuple(order) in seen:break
        proposals.append(best.model_copy(update={'title':('横向' if variant==0 else '纵向')+' · 拥塞重排',
            'parameters':{**best.parameters,'reroute_passes':history}}))
    return PluginResult(request_id=problem.request_id,source_digest=problem.source_digest,candidates=tuple(proposals))

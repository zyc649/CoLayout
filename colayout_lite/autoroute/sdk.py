"""Small public SDK for local Python routing plugins; no Editor or transport.

Plugins may use only JSON and their own solver instead. These helpers merely
reduce boilerplate; the host always validates the returned shapes afterwards.
"""
from pathlib import Path
from .models import RoutingProblem,PluginResult,Proposal
from ..model import Shape


def load_problem(path):return RoutingProblem.model_validate_json(Path(path).read_text(encoding='utf8'))


def save_result(path,result):
    PluginResult.model_validate(result.model_dump() if isinstance(result,PluginResult) else result).save(path)


def solve_rectilinear(problem,*,method='astar',variants=2):
    from .builtin import generate
    if method not in ('astar','pattern'):raise ValueError('Supported methods: astar, pattern')
    return generate(problem,'builtin.'+method,count=variants)

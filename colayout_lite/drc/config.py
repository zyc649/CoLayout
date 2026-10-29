from pathlib import Path
from ..paths import ROOT
from .models import DrcProfile


def path_for(technology):return ROOT/'config/drc'/(technology.key+'.json')


def load(technology):
    path=path_for(technology)
    if not path.exists():return None
    profile=DrcProfile.model_validate_json(path.read_text(encoding='utf8'));profile.check_technology(technology);return profile


def save(profile,technology):
    profile.check_technology(technology);profile.save(path_for(technology))

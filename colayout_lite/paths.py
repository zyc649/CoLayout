"""Project paths shared by local services; importing this never loads a bridge."""

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT
ROOT = APP_ROOT

"""Project skill entry for the maintained client-folder generator."""
from pathlib import Path
import runpy
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[4]))
runpy.run_module('tools.create_layout_agent',run_name='__main__')

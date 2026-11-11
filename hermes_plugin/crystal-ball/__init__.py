"""Load only the private crystal_ball package; leave the host's import path alone."""
import sys
from pathlib import Path

_vendor=str(Path(__file__).resolve().parent/'_vendor')
sys.path.insert(0,_vendor)
try:
    from crystal_ball.hermes import register
finally:
    sys.path.remove(_vendor)

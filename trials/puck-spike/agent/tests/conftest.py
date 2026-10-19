import sys
from pathlib import Path

# The agent package lives beside the tests, outside any installed project.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

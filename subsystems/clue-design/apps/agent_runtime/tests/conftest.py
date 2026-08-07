from __future__ import annotations

import sys
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
for _path in (RUNTIME_ROOT, REPO_ROOT / "apps" / "api", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

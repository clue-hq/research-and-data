"""Moved to :mod:`clue_api.footprint.text`; this path is the same module object."""

import sys

from clue_api.footprint import text as _moved

sys.modules[__name__] = _moved

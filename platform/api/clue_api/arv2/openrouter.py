"""Moved to :mod:`clue_api.footprint.openrouter`; this path is the same module object."""

import sys

from clue_api.footprint import openrouter as _moved

sys.modules[__name__] = _moved

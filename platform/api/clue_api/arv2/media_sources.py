"""Moved to :mod:`clue_api.footprint.media_sources`; this path is the same module object."""

import sys

from clue_api.footprint import media_sources as _moved

sys.modules[__name__] = _moved

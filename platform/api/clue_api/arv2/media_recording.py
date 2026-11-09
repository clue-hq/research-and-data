"""Moved to :mod:`clue_api.footprint.media_recording`; this path is the same module object."""

import sys

from clue_api.footprint import media_recording as _moved

sys.modules[__name__] = _moved

"""Moved to :mod:`clue_api.footprint.deepgram_media_client`; this path is the same module object."""

import sys

from clue_api.footprint import deepgram_media_client as _moved

sys.modules[__name__] = _moved

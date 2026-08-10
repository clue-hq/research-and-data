"""Compatibility re-export of the single-use SSE ``stream_token`` store.

The DAL itself moved to :mod:`clue_execution.stream_tokens` at Part II D7 Round B: the design API
(``lumen_api``) needs the same mint/consume surface and may not import ``clue_api`` (Rule 5 —
nothing imports the composition root), so the token store now lives beside
:mod:`clue_execution.run_events`, the other half of the one-transport / one-auth-model seam.

This module survives so every pre-D7 import path (``from clue_api.stream_tokens import
mint_stream_token, consume_stream_token``) still resolves, and because the SSE app that consumes
these tokens is genuinely composition-root machinery. There is no second implementation here — only
names.
"""

from __future__ import annotations

from clue_execution.stream_tokens import (
    PROJECT_RUN_SUBJECT_KIND,
    consume_stream_token,
    consume_subject_stream_token,
    mint_stream_token,
)

__all__ = [
    "PROJECT_RUN_SUBJECT_KIND",
    "consume_stream_token",
    "consume_subject_stream_token",
    "mint_stream_token",
]

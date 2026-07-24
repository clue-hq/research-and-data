"""Typed C3 failures; raw content is deliberately absent from messages."""

from __future__ import annotations

from clue_research.ingestion.models import IngestionFailureCode


class IngestionError(RuntimeError):
    def __init__(self, code: IngestionFailureCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")

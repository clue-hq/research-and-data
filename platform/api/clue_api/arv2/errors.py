"""The ARV2 lane's typed failures.

Every one of these is raised by :mod:`clue_api.arv2.calls`, the single wrapper every provider
call goes through. A client module never invents its own failure type: a supervisor that has to
distinguish "this provider is out of credit" from "the network flapped" reads these classes, not
a string. Appendix A law 12 — "an exception escaping to the supervisor is a defect" — means a
research tool catches these and turns them into an honest zero-yield outcome; it does not mean
they may be swallowed silently.
"""

from __future__ import annotations


class Arv2Error(Exception):
    """Base class for every failure the ARV2 lane raises."""


class ProviderHalted(Arv2Error):
    """A provider is refusing to sell (master plan §2 item 3: money truth *blocks*).

    Raised when a call's ``halt_rule`` recognises an unknown-spend or out-of-credit state (a 402
    or 403, or a body naming "credit"). The wrapper **latches** the provider: every later call to
    it raises this again with ``latched=True`` and ``reason_code='latched:<original reason>'``,
    without touching the wire and without a ledger row, until ``reset_halt`` is called.

    ``ledger_row_id`` is the result row that recorded the halt; it is ``None`` on a latched raise,
    because a latched call never happened.
    """

    def __init__(
        self,
        provider: str,
        reason_code: str,
        *,
        http_status: int | None = None,
        ledger_row_id: str | None = None,
        latched: bool = False,
    ) -> None:
        super().__init__(f"{provider} halted: {reason_code}")
        self.provider = provider
        self.reason_code = reason_code
        self.http_status = http_status
        self.ledger_row_id = ledger_row_id
        self.latched = latched


class ProviderTransportError(Arv2Error):
    """Every attempt failed below the HTTP layer (Appendix A law 2's ``2·(n+1)`` s backoff).

    No response ever arrived, so there is no raw record for the last attempt and spend is
    *unknown* rather than zero — the caller must not treat this as a clean rejection.
    """

    def __init__(self, provider: str, attempts: int, last_error: str) -> None:
        super().__init__(f"{provider} transport failed after {attempts} attempt(s): {last_error}")
        self.provider = provider
        self.attempts = attempts
        self.last_error = last_error


class RawParseError(Arv2Error):
    """A saved raw body could not be parsed as the caller expected.

    Carries the ``raw_ref`` of the record that *was* written (Appendix A law 1 saves the raw body
    before anything parses it), so the failure is always replayable from disk.
    """

    def __init__(self, raw_ref: str | None, message: str = "raw body is not JSON") -> None:
        super().__init__(f"{message} (raw_ref={raw_ref})")
        self.raw_ref = raw_ref

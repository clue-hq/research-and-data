"""The provider-caller seam's typed failures.

Every one of these is raised by :mod:`clue_spend.calls`, the single wrapper every provider
call goes through. A client module never invents its own failure type: a supervisor that has to
distinguish "this provider is out of credit" from "the network flapped" reads these classes, not
a string. Appendix A law 12 — "an exception escaping to the supervisor is a defect" — means a
research tool catches these and turns them into an honest zero-yield outcome; it does not mean
they may be swallowed silently.
"""

from __future__ import annotations

__all__ = [
    "Arv2Error",
    "ProviderHalted",
    "ProviderTransportError",
    "RawParseError",
    "RawScrubFailed",
    "SpendError",
]


class SpendError(Exception):
    """Base class for every failure the provider-caller seam raises."""


#: The name this base carried while the seam lived in ``clue_api.arv2``. Kept as an alias, not a
#: subclass, so ``except Arv2Error`` and ``except SpendError`` catch the same object.
Arv2Error = SpendError


class ProviderHalted(SpendError):
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


class ProviderTransportError(SpendError):
    """Every attempt failed below the HTTP layer (Appendix A law 2's ``2·(n+1)`` s backoff).

    No response ever arrived, so there is no raw record for the last attempt and spend is
    *unknown* rather than zero — the caller must not treat this as a clean rejection.
    """

    def __init__(self, provider: str, attempts: int, last_error: str) -> None:
        super().__init__(f"{provider} transport failed after {attempts} attempt(s): {last_error}")
        self.provider = provider
        self.attempts = attempts
        self.last_error = last_error


class RawScrubFailed(SpendError):
    """Appendix A law 3's scrubber raised, so no body could be safely persisted or returned.

    The scrubber runs *before* anything else sees the body, and its output replaces the response
    for the rest of the call. When it fails there is therefore no body the wrapper is allowed to
    keep — but the attempt still happened and was still paid for, so the wrapper writes a
    **body-less** raw record (status, redacted headers, body sha256 and byte count) and a result
    ledger row with ``error_code='raw_scrub_failed'`` before raising this. ``raw_ref`` cites that
    record: the money trail and the attempt trail stay complete even though the bytes are gone.
    """

    def __init__(self, provider: str, raw_ref: str | None, reason: str) -> None:
        super().__init__(f"{provider} raw scrubber failed: {reason} (raw_ref={raw_ref})")
        self.provider = provider
        self.raw_ref = raw_ref
        self.reason = reason


class RawParseError(SpendError):
    """A saved raw body could not be parsed as the caller expected.

    Carries the ``raw_ref`` of the record that *was* written (Appendix A law 1 saves the raw body
    before anything parses it), so the failure is always replayable from disk.
    """

    def __init__(self, raw_ref: str | None, message: str = "raw body is not JSON") -> None:
        super().__init__(f"{message} (raw_ref={raw_ref})")
        self.raw_ref = raw_ref

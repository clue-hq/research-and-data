"""What an external provider's answer means for the platform, classified once for everyone.

A provider can stop serving us in two ways. A **refusal** is a decision — the account is out of
credit, the key hit its cap, the key is wrong, the account is suspended — and no retry changes it.
A **failure** is a fault — a 429, a 5xx, a timeout — that usually passes. The two are told apart
here, from an HTTP status and body or from an SDK exception, and nowhere else; the incident
recorder, the ledger rows, the job and turn failure codes and the three inline surfaces all read
this one verdict. Pure: no I/O, no provider SDK import (exceptions are read by duck typing).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, cast

__all__ = [
    "FailureKind",
    "FailureReason",
    "ProviderFailure",
    "classify_exception",
    "classify_http",
    "failure_code",
    "parse_failure_code",
]

FailureKind = Literal["refusal", "failure"]
FailureReason = Literal[
    "credits_exhausted",
    "key_limit",
    "auth_invalid",
    "account_suspended",
    "quota_exhausted",
    "key_missing",
    "rate_limited",
    "server_error",
    "timeout",
]

#: The provider's own sentence is kept, capped, so a Sentry title or an inline message can quote
#: it. Never request content: only the response body (or the exception's message) is read.
MESSAGE_CHARS = 300

_REFUSALS: frozenset[str] = frozenset(
    {
        "credits_exhausted",
        "key_limit",
        "auth_invalid",
        "account_suspended",
        "quota_exhausted",
        "key_missing",
    }
)
#: Every member of ``FailureReason``, written out so ``parse_failure_code`` can check membership at
#: runtime. Keep this set and the ``FailureReason`` alias above in step with each other.
_REASONS: frozenset[str] = _REFUSALS | frozenset({"rate_limited", "server_error", "timeout"})
_CREDIT_WORDS = re.compile(
    # "insufficient" only with what is insufficient: "insufficient permissions" is a key problem,
    # not exhausted credit (final review 2026-10-31).
    r"credit|insufficient.(funds|balance)|no_more_credits|payment.required|top up|billing",
    re.IGNORECASE,
)
#: A quota or usage limit used up, said on a 429 or a 403 (Gemini's ``RESOURCE_EXHAUSTED``,
#: YouTube's ``quotaExceeded``). A 429 without these words is an ordinary rate limit.
_QUOTA_WORDS = re.compile(r"quota|resource_exhausted|usage limit", re.IGNORECASE)
#: A quota counted per second or per minute is throttling, not an exhausted allowance: Gemini says
#: "Quota exceeded … PerMinute" on an ordinary burst. It stays a rate limit (3 in 5 minutes), so a
#: busy minute never opens — and emails — an incident (final review 2026-10-31).
_SHORT_WINDOW_WORDS = re.compile(r"per.?(minute|second)|perminute|persecond", re.IGNORECASE)
_KEY_LIMIT_WORDS = re.compile(r"key limit|spend limit|limit exceeded", re.IGNORECASE)
_SUSPENDED_WORDS = re.compile(r"suspended|disabled|banned", re.IGNORECASE)
_TIMEOUT_CLASS_WORDS = re.compile(r"timeout|timed out|connection", re.IGNORECASE)
_CODE_RE = re.compile(r"^provider_(refused|failed):([a-z0-9_.-]+):([a-z_]+)$")

# A provider states its sentence under one of two keys, in JSON or in a Python repr of it (the
# OpenAI-compatible SDKs stringify their error body). Both are read with the same two patterns
# rather than a JSON parse, because a repr body is not JSON and must not be lost for it.
_BODY_MESSAGE_RE = re.compile(r"""['"]message['"]\s*:\s*['"]([^'"]+)['"]""")
_BODY_ERROR_RE = re.compile(r"""['"]error['"]\s*:\s*['"]([^'"]+)['"]""")


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    provider: str
    kind: FailureKind
    reason: FailureReason
    message: str


def _message(text: str | None, fallback: str) -> str:
    cleaned = " ".join((text or "").split())
    stated = _BODY_MESSAGE_RE.search(cleaned) or _BODY_ERROR_RE.search(cleaned)
    if stated is not None:
        cleaned = stated.group(1).strip()
    return (cleaned or fallback)[:MESSAGE_CHARS]


def _reason_for(status: int | None, body: str) -> tuple[FailureKind, FailureReason] | None:
    if status is None:
        return "failure", "timeout"
    if 200 <= status < 300:
        return None
    if status == 402 or (status in (401, 403) and _CREDIT_WORDS.search(body)):
        return "refusal", "credits_exhausted"
    if status in (403, 429) and _QUOTA_WORDS.search(body):
        if _SHORT_WINDOW_WORDS.search(body):
            return "failure", "rate_limited"
        return "refusal", "quota_exhausted"
    if status == 403 and _KEY_LIMIT_WORDS.search(body):
        return "refusal", "key_limit"
    if status in (401, 403) and _SUSPENDED_WORDS.search(body):
        return "refusal", "account_suspended"
    if status in (401, 403):
        return "refusal", "auth_invalid"
    if status == 429:
        return "failure", "rate_limited"
    if status >= 500:
        return "failure", "server_error"
    # 400, 404, 409, 422 and the rest of 4xx: our request, or nothing there — not the provider
    # refusing to serve.
    return None


def classify_http(provider: str, status: int | None, body: str | None) -> ProviderFailure | None:
    """A provider's HTTP answer as a failure, or ``None`` when it is not one.

    ``status is None`` means no response at all (a transport fault): a timeout-class failure.
    """
    text = body or ""
    verdict = _reason_for(status, text)
    if verdict is None:
        return None
    kind, reason = verdict
    fallback = f"HTTP {status}" if status is not None else "no response"
    return ProviderFailure(provider, kind, reason, _message(text, fallback))


def classify_exception(provider: str, exc: BaseException) -> ProviderFailure | None:
    """An SDK or transport exception as a failure, read by duck typing.

    ``status_code`` (the OpenAI SDK's ``APIStatusError`` family) decides first, with the
    exception's message as the body. Without a status, a class name naming a timeout or a
    connection fault is a ``timeout``; anything else (a malformed reply, a programming error) is
    not a provider failure and returns ``None``.
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    message = str(exc)
    if isinstance(status, int):
        return classify_http(provider, status, message)
    if _TIMEOUT_CLASS_WORDS.search(type(exc).__name__):
        return ProviderFailure(
            provider, "failure", "timeout", _message(message, type(exc).__name__)
        )
    return None


def failure_code(failure: ProviderFailure) -> str:
    """The stable code a job or turn row records: ``provider_refused:<provider>:<reason>``."""
    head = "provider_refused" if failure.kind == "refusal" else "provider_failed"
    return f"{head}:{failure.provider}:{failure.reason}"


def parse_failure_code(code: str | None) -> tuple[str, FailureKind, FailureReason] | None:
    """The inverse of :func:`failure_code`; ``None`` for any other code."""
    if code is None:
        return None
    match = _CODE_RE.match(code)
    if match is None:
        return None
    head, provider, reason = match.groups()
    kind: FailureKind = "refusal" if head == "refused" else "failure"
    if reason not in _REASONS:
        return None
    return provider, kind, cast(FailureReason, reason)

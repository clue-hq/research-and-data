"""Secret + payload + personal-data hygiene for the shared logging chain.

Debug mode captures EVERY detail, but debug NEVER means "leak secrets" — so
redaction is mode-independent and runs in the single shared processor chain
(``clue_obs.config``). Three hazards are handled (Doc R §4's two DSAR-grade
rules plus blob hygiene):

1. Secret-shaped KEYS (``api_key``, ``authorization``, ``*_token``, ``cookie``,
   ``*secret*``, ...) → their value becomes ``"***"``. Always, even in debug.
2. Claim-VALUE-shaped keys (``value_json``, ``evidence_span``, ``claim_value``,
   ``memory_body``, ``creating_quote``) → masked to an ids-only placeholder.
   This is the DSAR ids-never-bodies rule extended to logs: personal-claim
   values never land in a log line, so erasure never becomes log-scrubbing.
   Deliberately coarse — it masks non-personal claim values too; a log line
   carries the claim/field ids, and the value is one query away.
3. Base64 / binary BLOBS (data-URI images, raw ``bytes``) → a compact
   ``<base64 jpeg ~920KB>`` placeholder carrying length + a cheaply-sniffed
   kind.

Everything here is a set of pure functions; ``redact_processor`` is the
structlog adapter.
"""

from __future__ import annotations

import base64
from typing import Any

from structlog.typing import EventDict

# structlog's own event_dict bookkeeping + rendering metadata: leave untouched.
_META_KEYS = frozenset(
    {
        "event",
        "level",
        "timestamp",
        "logger",
        "logger_name",
        "exception",
        "exc_info",
        "stack_info",
        "pathname",
        "lineno",
        "func_name",
        "filename",
        "module",
        "_record",
        "_from_structlog",
    }
)

# Keys whose values are the log message itself — never redacted.
_CONTENT_KEYS = frozenset({"event", "message", "msg"})

# Keys that carry claim/memory VALUES — masked per the ids-only rule (2).
_CLAIM_VALUE_KEYS = frozenset(
    {
        "value_json",
        "claim_value",
        "evidence_span",
        "memory_body",
        "creating_quote",
    }
)
_CLAIM_VALUE_PLACEHOLDER = "<claim-value redacted (ids-only rule)>"

# Base64-ish strings shorter than this are left alone (real payloads are big;
# short tokens are caught by the secret-KEY rule, not the blob rule). The
# alphabet is deliberately WHITESPACE-FREE so long readable prose (which has
# spaces/punctuation) is never mistaken for a blob — prose gets truncated,
# not masked.
_BLOB_MIN_LEN = 256
_BASE64_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")

# Magic-number → kind, sniffed from the first decoded bytes.
_MAGIC = (
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"%PDF", "pdf"),
    (b"RIFF", "riff"),
    (b"\x00\x00\x01\x00", "ico"),
    (b"BM", "bmp"),
)


def _norm(key: str) -> str:
    return key.lower().replace("-", "_")


def is_secret_key(key: str) -> bool:
    """True when a field name looks credential-shaped and must be masked."""
    n = _norm(key)
    if n in _CONTENT_KEYS:
        return False
    if "secret" in n:
        return True
    if "api_key" in n or "apikey" in n:
        return True
    if "authorization" in n or n == "auth":
        return True
    if n == "cookie" or n.endswith("_cookie") or n.startswith("cookie"):
        return True
    if n == "token" or n.endswith("_token"):
        return True
    if "password" in n or n in ("passwd", "pwd"):
        return True
    return n in ("bearer", "credential", "credentials")


def is_claim_value_key(key: str) -> bool:
    """True when a field name carries a claim/memory VALUE (ids-only rule)."""
    return _norm(key) in _CLAIM_VALUE_KEYS


def _human_size(n_bytes: int) -> str:
    if n_bytes >= 1024:
        return f"~{round(n_bytes / 1024)}KB"
    return f"~{n_bytes}B"


def _sniff_kind(head: bytes) -> str | None:
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            if kind == "riff" and b"WEBP" in head[:16]:
                return "webp"
            return kind
    return None


def _placeholder(kind: str | None, n_bytes: int, prefix: str = "base64") -> str:
    size = _human_size(n_bytes)
    if kind:
        return f"<{prefix} {kind} {size}>"
    return f"<{prefix} {size}>"


def _looks_base64(value: str) -> bool:
    if len(value) < _BLOB_MIN_LEN:
        return False
    return all(ch in _BASE64_ALPHABET for ch in value)


def mask_blob(value: str) -> str:
    """Return a size+kind placeholder for a base64/data-URI blob, else the
    string unchanged. Pure; safe to call on any string."""
    stripped = value.strip()
    if stripped.startswith("data:") and ";base64," in stripped:
        header, _, payload = stripped.partition(";base64,")
        mime = header[len("data:") :]
        kind = mime.split("/", 1)[1] if "/" in mime else (mime or None)
        n_bytes = (len(payload) * 3) // 4
        return _placeholder(kind or None, n_bytes)
    if _looks_base64(stripped):
        n_bytes = (len(stripped) * 3) // 4
        kind = None
        try:
            head = base64.b64decode(stripped[:64], validate=False)
            kind = _sniff_kind(head)
        except Exception:
            kind = None
        return _placeholder(kind, n_bytes)
    return value


def _mask_binary(value: bytes | bytearray) -> str:
    head = bytes(value[:16])
    return _placeholder(_sniff_kind(head), len(value), prefix="binary")


def redact_value(value: Any, key: str | None = None) -> Any:
    """Pure recursive redactor. Masks secret-keyed values, claim-value-keyed
    fields (ids-only rule), and base64/binary blobs."""
    if key is not None and _norm(key) in _CONTENT_KEYS:
        return value
    if key is not None and is_secret_key(key):
        return "***"
    if key is not None and is_claim_value_key(key):
        return _CLAIM_VALUE_PLACEHOLDER
    if isinstance(value, bytes | bytearray):
        return _mask_binary(value)
    if isinstance(value, str):
        return mask_blob(value)
    if isinstance(value, dict):
        return {k: redact_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(v) for v in value]
    return value


def redact_processor(logger: Any, method_name: str, event_dict: EventDict) -> EventDict:
    """structlog processor: redact every non-meta field in place."""
    for key in list(event_dict.keys()):
        if key in _META_KEYS:
            continue
        event_dict[key] = redact_value(event_dict[key], key)
    return event_dict

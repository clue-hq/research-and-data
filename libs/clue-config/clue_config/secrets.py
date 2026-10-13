"""Secrets handling — provider API keys and the DB DSN, read from the environment (M0.4).

"Secrets never enter code, logs, or ``_memory/``" (conventions §2; CLAUDE.md session-memory
protocol). Two things live here:

* :class:`Secrets` — a ``pydantic-settings`` ``BaseSettings`` that reads provider API keys
  (Clay / Apollo / ZoomInfo / BuiltWith / Exa / Parallel / Firecrawl / CRM) and the database
  DSN from environment variables. It is loaded once and injected; nothing reads ``os.environ``
  ad hoc. A resolver swap (Clay → direct API) changes *which key is read*, not any caller —
  the secret sits behind the loader, not in the resolver.
* :func:`redact` — the redaction helper the obs layer (M0.5) imports so spans and structured
  logs cannot leak a secret-looking value. It lives **here** (config sits below obs in the
  layering ``obs → config → core``), so obs depends on config, never the reverse.

The DB DSN env var is **``CLUE_DATABASE_URL``** — a shared seam this milestone documents; the
``db/`` package (M0.3) reads the same variable. Provider keys are namespaced ``CLUE_*_API_KEY``.

This module holds **no real values**. ``.env.example`` at the repo root documents the variable
names with placeholders; ``.env`` (the real values) is git-ignored and never committed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# The shared database-DSN environment variable. Owned/documented here (M0.4); the db/ package
# (M0.3) reads the same name. Centralized as a constant so the seam has exactly one spelling; its
# equality with ``db.DATABASE_URL_ENV`` is asserted in tests/test_seams.py (guard against drift).
DB_DSN_ENV_VAR: Final = "CLUE_DATABASE_URL"

# Common provider-key env-var name fragments + the DB DSN var. The redaction helper masks the
# *values* of any key whose name looks like one of these (case-insensitive). This is a
# defense-in-depth name heuristic for logs/spans — the typed Secrets model below is the real
# read path.
_SECRET_NAME_HINTS: Final = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "passwd",
    "dsn",
    "database_url",
    "credential",
    "private_key",
    "access_key",
)

# Mask applied to a redacted value. Keeps a short prefix only when the value is long enough that
# a 4-char hint cannot reconstruct it; otherwise fully masks.
_REDACTED: Final = "***REDACTED***"


class Secrets(BaseSettings):
    """Provider API keys + the DB DSN, read from the environment (never committed/logged).

    Every field is optional (``None`` when unset): M0 ships no live provider integration, so a
    missing key is normal in dev/CI. The owning milestone (M4 resolvers, M0.3 db) asserts
    presence when it actually needs the value. Values are wrapped in :class:`~pydantic.SecretStr`
    so an accidental ``repr``/``str``/log shows ``**********`` instead of the secret.
    """

    model_config = SettingsConfigDict(
        env_prefix="CLUE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # tolerate unrelated env vars (CI/shell noise)
        # A blank line (``CLUE_AI_ARK_API_KEY=``) is "unset", never an empty credential: the
        # env-parity rule keeps every documented key present in ``.env`` with secrets left blank.
        env_ignore_empty=True,
        frozen=True,
    )

    # --- database (shared seam: db/ M0.3 reads CLUE_DATABASE_URL) ---
    # The env_prefix ("CLUE_") + field name ("database_url", upper-cased) resolves to exactly
    # CLUE_DATABASE_URL — the one DSN var name documented in .env.example and read by db/ (M0.3).
    # (No explicit alias needed; that keeps the pydantic-mypy "dynamic alias" rule happy.)
    database_url: SecretStr | None = None

    # Settings invitations and verified email backfill; JWT validation uses public JWKS.
    # Env: CLUE_AUTH_CLERK_SECRET_KEY.
    auth_clerk_secret_key: SecretStr | None = None

    # --- provider API keys (CLUE_<PROVIDER>_API_KEY) ---
    # One field per credentialed source manifest's auth_ref: ``extra="ignore"`` silently drops any
    # CLUE_* env var with no matching field, so a manifest auth_ref without a field here would never
    # resolve (it would look unset even when set). The M4.4 ``test_every_seeded_auth_ref_resolves``
    # drift guard enforces this 1:1 mapping.
    clay_api_key: SecretStr | None = None
    apollo_api_key: SecretStr | None = None
    zoominfo_api_key: SecretStr | None = None
    builtwith_api_key: SecretStr | None = None
    duns_api_key: SecretStr | None = None
    exa_api_key: SecretStr | None = None
    # HMAC secret configured on the Exa Websets webhook, distinct from the API key.
    # Env: CLUE_EXA_WEBSETS_WEBHOOK_SECRET.
    exa_websets_webhook_secret: SecretStr | None = None
    sumble_api_key: SecretStr | None = None
    parallel_api_key: SecretStr | None = None
    firecrawl_api_key: SecretStr | None = None
    crm_api_key: SecretStr | None = None
    # Env: CLUE_AI_ARK_API_KEY. Read by the ARV2 AI Ark client (people/company enrichment); sent
    # as the ``X-TOKEN`` header, which the ARV2 raw sink redacts before any record is written.
    ai_ark_api_key: SecretStr | None = None
    # Env: CLUE_GEMINI_API_KEY. Read by the ARV2 media client's **native** transcribe call only —
    # the one ARV2 model call that bypasses OpenRouter (OpenRouter serves neither the transcribe
    # model nor a file upload). Every other ARV2 model call uses ``openrouter_api_key`` below.
    gemini_api_key: SecretStr | None = None
    # Env: CLUE_PAGES_EDGE_SECRET. Shared with the Cloudflare Worker `pages-edge`; the page origin
    # refuses page traffic that does not carry it in X-Clue-Edge-Auth (spec §5.2). Empty only in
    # dev, together with CLUE_PAGES_TRUST_HOST_HEADER=true.
    pages_edge_secret: SecretStr | None = None
    # Env: CLUE_CLOUDFLARE_API_TOKEN. Zone-scoped token with only "SSL and Certificates: Edit"
    # (spec §7.7); read by the custom-hostnames client and nothing else.
    cloudflare_api_token: SecretStr | None = None
    # Production recording ASR. DEEPGRAM_API_KEY remains a trial-compatible alias.
    deepgram_api_key: SecretStr | None = Field(  # type: ignore[pydantic-alias]
        default=None,
        validation_alias=AliasChoices(
            "CLUE_DEEPGRAM_API_KEY", "DEEPGRAM_API_KEY", "deepgram_api_key"
        ),
    )
    # Env: CLUE_YOUTUBE_DATA_API_KEY. YouTube Data API v3 ``videos.list``: a video's title,
    # channel, date, length and whether it is public. Sent as ``x-goog-api-key`` (redacted).
    youtube_data_api_key: SecretStr | None = None
    # Env: CLUE_PODCAST_INDEX_API_KEY / CLUE_PODCAST_INDEX_API_SECRET. Podcast Index show search;
    # without them only Apple's directory is searched.
    podcast_index_api_key: SecretStr | None = None
    podcast_index_api_secret: SecretStr | None = None

    # --- telemetry roots (lane 3 slice 2) ---
    # Env: CLUE_SENTRY_DSN — the Sentry project DSN (it authorises event ingest, so a secret).
    sentry_dsn: SecretStr | None = None
    # Env: CLUE_OTEL_TRACES_HEADERS — "k=v,k2=v2" sent with every OTLP trace export (Langfuse's
    # basic-auth header in slice 3); a secret because it carries the project keys.
    otel_traces_headers: SecretStr | None = None

    # --- Langfuse (lane 3 slice 3) ---
    # Env: CLUE_LANGFUSE_PUBLIC_KEY / CLUE_LANGFUSE_SECRET_KEY — the project's key pair (the
    # public key is also an identifier, but the pair authorises ingest, so both are secrets).
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None

    # --- durable artifact storage (Phase B2 / REQ-07) ---
    # Credentials for the S3-compatible StorageBackend (AWS S3 / R2 / MinIO). Non-secret knobs
    # (bucket, endpoint, region, backend selector) live in Settings; only the key pair is secret.
    storage_s3_access_key_id: SecretStr | None = None
    storage_s3_secret_access_key: SecretStr | None = None

    # --- LLM gateway (the single OpenRouter egress, conventions §2/§4) ---
    # One key for every *direct* LLM call (judge / planner / synthesizers). Unset in CI: the gateway
    # then runs in deterministic stub mode (no live call). Exa/Parallel above are tier-4 research
    # *resolvers* with their own keys — NOT gateway calls (conventions §2 carve-out).
    openrouter_api_key: SecretStr | None = None

    def for_auth_ref(self, auth_ref: str) -> SecretStr | None:
        """Resolve a ``source_manifest.auth_ref`` (a ``CLUE_*`` env-var *name*) to its secret value.

        The **credential-reference resolver** (M0.2): an ``auth_ref`` stored on a source manifest is
        a *reference* (the env-var name), never the secret itself (the no-secret-in-the-table
        invariant, M4.2). A resolver/adapter calls this at *call time* to obtain the live key. The
        ``CLUE_`` env-prefix is stripped and the remainder lower-cased to find the matching field
        (``CLUE_CLAY_API_KEY`` → :attr:`clay_api_key`). Returns ``None`` when the referenced key is
        unset (normal in dev/CI with no live integration) or when ``auth_ref`` names no field —
        the caller raises a clear "no credential" error rather than calling a provider with no key.
        One place owns the name→field mapping so resolvers never re-implement it (conventions §2).
        """
        value = getattr(self, auth_ref.lower().removeprefix("clue_"), None)
        return value if isinstance(value, SecretStr) else None


def is_secret_name(name: str) -> bool:
    """True if an attribute/key *name* looks like it names a secret (case-insensitive).

    Used by :func:`redact_mapping` to decide which values to mask by their key, independent of
    the value's shape. Intentionally conservative — false positives only over-redact.
    """
    lowered = name.lower()
    return any(hint in lowered for hint in _SECRET_NAME_HINTS)


def redact(value: object) -> str:
    """Redact a single value to a safe string for a log line or trace attribute.

    A :class:`~pydantic.SecretStr` is always fully masked. Containers (mappings, sequences) are
    redacted **element-wise** — otherwise ``str(["x", "sk-secret"])`` would hide the embedded
    secret from the anchored value-shape patterns and it could leak. Any scalar is stringified and
    masked if it *looks* secret-bearing (a long opaque token, a DSN with credentials, or an obvious
    key prefix); otherwise it is returned as-is. The obs layer (M0.5) calls this on every attribute
    it is about to emit, so "no secret ever reaches a span/log" is enforced in one place.
    """
    if isinstance(value, SecretStr):
        return _REDACTED
    if isinstance(value, Mapping):
        return str(redact_mapping({str(k): v for k, v in value.items()}))
    if isinstance(value, list | tuple | set):
        return "[" + ", ".join(redact(item) for item in value) + "]"
    text = value if isinstance(value, str) else str(value)
    return _REDACTED if _looks_secret(text) else text


def redact_mapping(data: dict[str, object]) -> dict[str, str]:
    """Redact a mapping of named values (e.g. span attributes) by name *and* by value shape.

    A value is masked if its key name looks secret (:func:`is_secret_name`) or its value looks
    secret (:func:`_looks_secret`). Non-secret values are passed through as their string form.
    """
    return {
        key: (_REDACTED if is_secret_name(key) else redact(value)) for key, value in data.items()
    }


# A bare token that looks like a credential: a DSN with an embedded password, an sk-/key- style
# prefix, or a long unbroken high-entropy-ish run of token characters.
_DSN_WITH_CREDENTIALS = re.compile(r"^[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE)
_KEYISH_PREFIX = re.compile(r"^(sk|pk|key|api|tok|bearer|ghp|xox[a-z])[-_]", re.IGNORECASE)
_OPAQUE_TOKEN = re.compile(r"^[A-Za-z0-9_\-]{24,}$")


def _looks_secret(text: str) -> bool:
    """Heuristic: does this string look like a credential we must never log?"""
    return bool(
        _DSN_WITH_CREDENTIALS.match(text) or _KEYISH_PREFIX.match(text) or _OPAQUE_TOKEN.match(text)
    )

"""The start-up key check: a missing provider key opens a provider incident.

Design 2026-10-31 §6.3.

Each app role checks, once at start-up, the keys of the providers it calls. A key that is missing
or blank opens a ``key_missing`` incident named ``"<role>:<ENV_NAME>"`` — one Sentry event however
many processes of that role start, because the incident table keeps one open incident per name.
A later start-up of the same role that finds the key closes it. Nothing else closes it: an
ordinary successful call records success under the provider id, which never equals this name.

The registry below is data. ZoomInfo, Clay, Apollo, BuiltWith and Dun & Bradstreet are left out
(no production caller yet, founder ruling 2026-10-31); Firecrawl and Sumble are out of the stack.
Re-adding one is one row.

The check never raises and never puts a key value anywhere: an incident's message names the env
variable only.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core.provider_failures import ProviderFailure
from clue_obs import get_logger

from . import incidents

__all__ = [
    "PROVIDER_KEYS",
    "ROLES",
    "KeyRequirement",
    "check_provider_keys",
    "provider_for_env",
    "startup_environ",
]

log = get_logger("clue_spend.key_check")

#: The three app roles a production deployment runs (``deploy/check_prod_env.py`` ``APP_ROLES``).
ROLES = frozenset({"platform-api", "design-api", "worker"})

PLATFORM, DESIGN, WORKER = "platform-api", "design-api", "worker"


@dataclass(frozen=True)
class KeyRequirement:
    """One key a provider needs. Satisfied when **any** of ``env_names`` is set (a fallback pair,
    like ``CLUE_DEEPGRAM_API_KEY`` / ``DEEPGRAM_API_KEY``); the first name is the one reported."""

    provider: str
    env_names: tuple[str, ...]
    roles: frozenset[str]


def _key(provider: str, *env_names: str, roles: tuple[str, ...]) -> KeyRequirement:
    return KeyRequirement(provider, env_names, frozenset(roles))


PROVIDER_KEYS: tuple[KeyRequirement, ...] = (
    _key(
        "openrouter",
        "CLUE_OPENROUTER_API_KEY",
        "OPENROUTER_API_KEY",
        roles=(PLATFORM, DESIGN, WORKER),
    ),
    _key("openrouter_design", "LUMEN_AGENT_API_KEY", roles=(DESIGN, WORKER)),
    _key("openrouter_design", "IMAGE_MODEL_API_KEY", roles=(DESIGN, WORKER)),
    _key("gemini", "CLUE_GEMINI_API_KEY", roles=(WORKER,)),
    _key("deepgram", "CLUE_DEEPGRAM_API_KEY", "DEEPGRAM_API_KEY", roles=(WORKER,)),
    _key("youtube_data", "CLUE_YOUTUBE_DATA_API_KEY", roles=(WORKER,)),
    _key("podcast_index", "CLUE_PODCAST_INDEX_API_KEY", roles=(WORKER,)),
    _key("podcast_index", "CLUE_PODCAST_INDEX_API_SECRET", roles=(WORKER,)),
    _key("exa", "CLUE_EXA_API_KEY", roles=(PLATFORM, WORKER)),
    _key("ai_ark", "CLUE_AI_ARK_API_KEY", roles=(WORKER,)),
    _key("pdl", "PDL_API_KEY", roles=(WORKER,)),
    _key("adyntel", "ADYNTEL_API_KEY", roles=(WORKER,)),
    _key("adyntel", "ADYNTEL_EMAIL", roles=(WORKER,)),
    _key("brandfetch", "BRANDFETCH_API_KEY", roles=(DESIGN, WORKER)),
    _key("composio", "CLUE_COMPOSIO_API_KEY", roles=(PLATFORM, WORKER)),
    _key("cloudflare", "CLUE_CLOUDFLARE_API_TOKEN", roles=(PLATFORM,)),
    _key("clerk", "CLUE_AUTH_CLERK_SECRET_KEY", roles=(PLATFORM,)),
)

_PROVIDER_BY_ENV = {name: req.provider for req in PROVIDER_KEYS for name in req.env_names}


def provider_for_env(env_name: str) -> str | None:
    """The provider an env name carries a key for, or ``None`` for a name not in the registry."""
    return _PROVIDER_BY_ENV.get(env_name)


def startup_environ(env_files: Sequence[str] = (".env",)) -> dict[str, str]:
    """What the settings loaders see: each env file in order (a later one overrides an earlier),
    then the process environment over all of them — the precedence ``pydantic-settings`` applies.
    The platform reads ``.env`` in the working directory; the design API passes its own
    ``.env`` and ``.env.local``."""
    values: dict[str, str] = {}
    try:
        from dotenv import dotenv_values

        for env_file in env_files:
            values.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    except Exception:  # noqa: BLE001 - no dotenv, no file: the process environment alone
        pass
    values.update(os.environ)
    return values


ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]


async def check_provider_keys(
    conn_factory: ConnFactory,
    *,
    role: str,
    environ: Mapping[str, str],
    now: datetime | None = None,
) -> None:
    """Open a ``key_missing`` incident for every key ``role`` needs and lacks; close the ones it now
    has. Never raises."""
    at = now or datetime.now(UTC)
    try:
        async with conn_factory() as conn:
            wanted: set[str] = set()
            for requirement in PROVIDER_KEYS:
                if role not in requirement.roles:
                    continue
                reported = requirement.env_names[0]
                name = f"{role}:{reported}"
                wanted.add(name)
                present = any((environ.get(env) or "").strip() for env in requirement.env_names)
                if present:
                    await incidents.record_success(conn, name, now=at)
                    continue
                await incidents.record_failure(
                    conn,
                    ProviderFailure(name, "refusal", "key_missing", f"{reported} is not set"),
                    surface="startup",
                    workspace_id=None,
                    now=at,
                )
            for incident in await incidents.open_incidents(conn):
                # A key taken off the registry since its incident opened: this role closes it.
                stale = (
                    incident.reason == "key_missing"
                    and incident.provider.startswith(f"{role}:")
                    and incident.provider not in wanted
                )
                if stale:
                    await incidents.record_success(conn, incident.provider, now=at)
            # Any incident a process without Sentry opened is sent now, whoever's it is.
            await incidents.send_unsent(conn)
    except Exception as error:  # noqa: BLE001 - the check must never stop a start-up
        # By type only, never with a traceback: ``environ`` holds every key, and a renderer that
        # prints a frame's locals (the dev console's) would print them.
        log.error("provider_keys.check_failed", role=role, error=type(error).__name__)

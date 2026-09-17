"""``python -m clue_api.langfuse_check`` — is Langfuse configured and does the host accept the
keys? (lane 3 slice 3, design §3.10). Reads the same settings the roots read, calls the SDK's
auth check with tracing disabled, prints one line, sends no trace. Exit 0 = ok, 1 = misconfigured
or refused, 2 = disabled. ``make langfuse-check`` runs it.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

from clue_config import Secrets, Settings, load_settings
from clue_obs.langfuse import auth_check

__all__ = ["main"]


def _say(line: str) -> None:
    """One operator-facing line on stdout (T20 bans ``print``; the sibling cost CLI does this)."""
    sys.stdout.write(f"{line}\n")


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    secrets: Secrets | None = None,
    check: Callable[..., bool] = auth_check,
) -> int:
    del argv  # no flags: the env is the only input
    resolved = settings if settings is not None else load_settings()
    resolved_secrets = secrets if secrets is not None else Secrets()
    if not resolved.langfuse_enabled:
        _say("langfuse: disabled (CLUE_LANGFUSE_ENABLED=false)")
        return 2
    public_key = (
        resolved_secrets.langfuse_public_key.get_secret_value().strip()
        if resolved_secrets.langfuse_public_key is not None
        else ""
    )
    secret_key = (
        resolved_secrets.langfuse_secret_key.get_secret_value().strip()
        if resolved_secrets.langfuse_secret_key is not None
        else ""
    )
    missing = [
        name
        for name, value in (
            ("CLUE_LANGFUSE_PUBLIC_KEY", public_key),
            ("CLUE_LANGFUSE_SECRET_KEY", secret_key),
        )
        if not value
    ]
    if missing:
        _say(f"langfuse: enabled but missing {', '.join(missing)}")
        return 1
    try:
        accepted = check(public_key=public_key, secret_key=secret_key, host=resolved.langfuse_host)
    except Exception as exc:  # the host unreachable, TLS, DNS — say what, never the keys
        _say(f"langfuse: unreachable ({type(exc).__name__}: {exc})")
        return 1
    if not accepted:
        _say(f"langfuse: refused the key pair ({resolved.langfuse_host})")
        return 1
    _say(
        f"langfuse: ok ({resolved.langfuse_host}, env={resolved.langfuse_environment}, "
        f"public_key={public_key[:8]}…)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

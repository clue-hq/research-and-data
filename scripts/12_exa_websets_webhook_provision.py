#!/usr/bin/env python3
"""Idempotently provision Clue's one team-level Exa Websets webhook.

When Exa creates the endpoint, its signing secret is returned once. This command writes that value
to an operator-chosen, newly created mode-0600 dotenv file; it never prints the secret. Existing
matching endpoints are a zero-change replay and do not touch the output path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from contextlib import suppress
from pathlib import Path

from clue_api.exa_websets_lifecycle import ExaTeamWebhookProvisioner
from clue_config import Secrets
from clue_research.adapters.exa_websets import ExaWebsetsClient


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        required=True,
        help="Public HTTPS URL for /v1/webhooks/exa-websets on the projections service.",
    )
    parser.add_argument(
        "--secret-output",
        required=True,
        type=Path,
        help="New mode-0600 dotenv file used only if Exa creates the endpoint.",
    )
    return parser.parse_args()


def _write_secret_once(path: Path, secret: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(f"CLUE_EXA_WEBSETS_WEBHOOK_SECRET={secret}\n")
    except BaseException:
        # ``fdopen`` owns and closes the descriptor after it succeeds. If it failed before taking
        # ownership, closing an already-closed descriptor is harmlessly ignored.
        with suppress(OSError):
            os.close(descriptor)
        raise


async def _run() -> None:
    args = _args()
    # Fail before the provider call if the one-time secret has nowhere exclusive to land. This
    # avoids creating a webhook and only then discovering that an existing file would discard its
    # non-recoverable signing secret.
    args.secret_output.parent.mkdir(parents=True, exist_ok=True)
    if args.secret_output.exists():
        raise FileExistsError(f"secret output already exists: {args.secret_output}")
    secrets = Secrets()
    if secrets.exa_api_key is None:
        raise RuntimeError("CLUE_EXA_API_KEY is required to provision an Exa webhook")
    async with ExaWebsetsClient(api_key=secrets.exa_api_key, lookup_attempts=1) as client:
        result = await ExaTeamWebhookProvisioner(transport=client).ensure(url=args.url)
    if result.secret is not None:
        _write_secret_once(args.secret_output, result.secret.get_secret_value())
    print(
        json.dumps(
            {
                "webhook_id": result.webhook_id,
                "created": result.created,
                "secret_written": result.secret is not None,
                "secret_output": str(args.secret_output) if result.secret is not None else None,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(_run())

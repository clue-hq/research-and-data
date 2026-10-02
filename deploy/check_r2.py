"""Check the R2 buckets and tokens before anything depends on them (first deployment runbook §1).

Usage: uv run python deploy/check_r2.py <env-file>

The env file holds the app's storage settings and the backup settings, under the names the
services and backup.env use:

    CLUE_STORAGE_S3_BUCKET=clue-prod
    CLUE_STORAGE_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
    CLUE_STORAGE_S3_REGION=auto
    CLUE_STORAGE_S3_ACCESS_KEY_ID=<app token key id>
    CLUE_STORAGE_S3_SECRET_ACCESS_KEY=<app token secret>
    R2_BUCKET=clue-backups
    AWS_ACCESS_KEY_ID=<backup token key id>
    AWS_SECRET_ACCESS_KEY=<backup token secret>

It goes through the app's own S3 code (clue_storage.S3Storage): the app token must write, read,
list, presign and delete in its bucket; the backup token must write, read and delete in its own;
and each token must be REFUSED on the other bucket. Probe objects live under _r2-check/ and are
always deleted. Prints no secret.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import urllib.request
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

APP_KEYS = (
    "CLUE_STORAGE_S3_BUCKET",
    "CLUE_STORAGE_S3_ENDPOINT_URL",
    "CLUE_STORAGE_S3_ACCESS_KEY_ID",
    "CLUE_STORAGE_S3_SECRET_ACCESS_KEY",
)
BACKUP_KEYS = ("R2_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")


class CheckFailed(Exception):
    """One step did not behave; the message starts with the step's name."""


def parse(text: str) -> dict[str, str]:
    """KEY=VALUE lines; blank lines and # comments skipped, surrounding quotes dropped."""
    env: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def missing(env: dict[str, str]) -> list[str]:
    return [name for name in (*APP_KEYS, *BACKUP_KEYS) if not env.get(name)]


def _probe() -> tuple[str, bytes]:
    token = uuid.uuid4().hex
    return f"_r2-check/{token}.txt", f"clue r2 check {token}\n".encode()


async def exercise_bucket(store: Any, *, fetch: Callable[[str], bytes]) -> list[str]:
    """Everything the app does to its bucket, in order; raises CheckFailed at the first wrong step.
    The probe object is deleted whatever happens."""
    key, body = _probe()

    async def put() -> bool:
        await store.put(key, body, media_type="text/plain")
        return True

    async def exists() -> bool:
        return bool(await store.exists(key))

    async def get() -> bool:
        return bool(await store.get(key) == body)

    async def listed() -> bool:
        return any([k async for k, _ in store.list_blobs() if k == key])

    async def presigned() -> bool:
        url = await store.presign(key, expires_in=300)
        return bool(await asyncio.to_thread(fetch, url) == body)

    async def delete() -> bool:
        await store.delete(key)
        return True

    async def gone() -> bool:
        return not await store.exists(key)

    steps: list[tuple[str, Callable[[], Awaitable[bool]]]] = [
        ("put", put),
        ("exists", exists),
        ("get", get),
        ("list", listed),
        ("presigned fetch", presigned),
        ("delete", delete),
        ("gone", gone),
    ]
    done: list[str] = []
    try:
        for name, action in steps:
            try:
                ok = await action()
            except Exception as exc:  # noqa: BLE001 - every provider error is a failed step
                raise CheckFailed(f"{name}: {type(exc).__name__}: {exc}") from exc
            if not ok:
                raise CheckFailed(f"{name}: unexpected result")
            done.append(name)
    finally:
        with contextlib.suppress(Exception):  # best effort; a refused delete was already reported
            await store.delete(key)
    return done


async def expect_refused(store: Any, label: str) -> None:
    """The token must NOT be able to write to this bucket."""
    key, body = _probe()
    try:
        await store.put(key, body, media_type="text/plain")
    except Exception:  # noqa: BLE001 - refused, as required
        return
    await store.delete(key)
    raise CheckFailed(f"{label}: was ALLOWED — scope this token to its own bucket only")


async def _backup_round_trip(store: Any) -> None:
    key, body = _probe()
    try:
        await store.put(key, body, media_type="text/plain")
        if await store.get(key) != body:
            raise CheckFailed("backup token on its bucket: read back different bytes")
    except CheckFailed:
        raise
    except Exception as exc:  # noqa: BLE001
        raise CheckFailed(f"backup token on its bucket: {type(exc).__name__}: {exc}") from exc
    finally:
        with contextlib.suppress(Exception):
            await store.delete(key)


def _https_fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - our presigned URL
        return bytes(response.read())


async def run(env: dict[str, str]) -> None:
    from clue_storage import S3Storage

    endpoint = env["CLUE_STORAGE_S3_ENDPOINT_URL"]
    region = env.get("CLUE_STORAGE_S3_REGION") or "auto"
    app_key = (env["CLUE_STORAGE_S3_ACCESS_KEY_ID"], env["CLUE_STORAGE_S3_SECRET_ACCESS_KEY"])
    backup_key = (env["AWS_ACCESS_KEY_ID"], env["AWS_SECRET_ACCESS_KEY"])
    app_bucket, backup_bucket = env["CLUE_STORAGE_S3_BUCKET"], env["R2_BUCKET"]

    def store(bucket: str, key: tuple[str, str]) -> Any:
        return S3Storage(
            bucket,
            endpoint_url=endpoint,
            region=region,
            access_key_id=key[0],
            secret_access_key=key[1],
        )

    steps = await exercise_bucket(store(app_bucket, app_key), fetch=_https_fetch)
    sys.stdout.write(f"ok: app token on {app_bucket}: {', '.join(steps)}\n")
    await _backup_round_trip(store(backup_bucket, backup_key))
    sys.stdout.write(f"ok: backup token on {backup_bucket}: put, get, delete\n")
    await expect_refused(store(backup_bucket, app_key), f"app token on {backup_bucket}")
    sys.stdout.write(f"ok: app token refused on {backup_bucket}\n")
    await expect_refused(store(app_bucket, backup_key), f"backup token on {app_bucket}")
    sys.stdout.write(f"ok: backup token refused on {app_bucket}\n")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write(f"{__doc__}\n")
        return 2
    env = parse(Path(argv[1]).read_text(encoding="utf-8"))
    if gaps := missing(env):
        sys.stdout.write(f"FAILED: missing from {argv[1]}: {', '.join(gaps)}\n")
        return 1
    if env["CLUE_STORAGE_S3_BUCKET"] == env["R2_BUCKET"]:
        sys.stdout.write("FAILED: the app bucket and the backup bucket must differ\n")
        return 1
    try:
        asyncio.run(run(env))
    except CheckFailed as exc:
        sys.stdout.write(f"FAILED: {exc}\n")
        return 1
    sys.stdout.write("R2 CHECK PASSED\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

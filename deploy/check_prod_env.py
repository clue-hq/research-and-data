"""Refuse a production env that still carries a lane default (first deployment spec §10).

Usage: python3 deploy/check_prod_env.py {platform-api|design-api|worker} <env-file>

Standard library only — the worker VM runs it with its system python3 before every deploy.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROLES = ("platform-api", "design-api", "worker")

#: name -> the only acceptable production value.
EXACT = {
    "CLUE_STORAGE_BACKEND": "s3",
    "CLUE_PAGES_SYSTEM_SUFFIX": "pages.cluehq.ai",
    "CLUE_PAGES_PUBLIC_SCHEME": "https",
    "CLUE_PAGES_TRUST_HOST_HEADER": "false",
    "CLUE_SCRAPE_BACKEND": "scrapling",
    "CLUE_STAGE0_PAGE_FETCHER": "scrapling",
}
#: names that must be set to something non-empty.
REQUIRED = (
    "CLUE_DATABASE_URL",
    "CLUE_REDIS_URL",
    "CLUE_STORAGE_S3_BUCKET",
    "CLUE_STORAGE_S3_ENDPOINT_URL",
    "CLUE_STORAGE_S3_ACCESS_KEY_ID",
    "CLUE_STORAGE_S3_SECRET_ACCESS_KEY",
    "CLUE_PAGES_EDGE_SECRET",
)


def parse(text: str) -> dict[str, str]:
    """Read KEY=VALUE lines; blank lines and # comments are skipped, surrounding quotes dropped."""
    env: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def problems(env: dict[str, str], role: str) -> list[str]:
    """Every way ``env`` falls short of production for ``role``; empty means it is fine."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")
    found: list[str] = []
    for name, wanted in EXACT.items():
        if env.get(name, "") != wanted:
            found.append(f"{name} must be {wanted!r} in production (is {env.get(name)!r})")
    for name in REQUIRED:
        if not env.get(name):
            found.append(f"{name} must be set")
    if env.get("CLUE_CHAT_REASONING_TRACE_MODE", "") == "raw":
        found.append("CLUE_CHAT_REASONING_TRACE_MODE=raw is dev-only")
    for name in ("CLUE_DATABASE_URL", "CLUE_REDIS_URL"):
        value = env.get(name, "")
        if "localhost" in value or "127.0.0.1" in value:
            found.append(f"{name} points at localhost")
    if role == "design-api" and env.get("LUMEN_EMBEDDED_FLEET_WORKER") != "0":
        found.append(
            "LUMEN_EMBEDDED_FLEET_WORKER must be 0 on Railway (design jobs belong to the VM)"
        )
    if role == "worker" and env.get("CLUE_FLEET_WORKER_KINDS"):
        found.append(
            "CLUE_FLEET_WORKER_KINDS must not be set in the shared env file "
            "(compose.yaml sets it per pool)"
        )
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write(f"{__doc__}\n")
        return 2
    role, path = argv[1], Path(argv[2])
    found = problems(parse(path.read_text(encoding="utf-8")), role)
    for problem in found:
        sys.stdout.write(f"PROBLEM: {problem}\n")
    sys.stdout.write("OK\n" if not found else f"{len(found)} problem(s)\n")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

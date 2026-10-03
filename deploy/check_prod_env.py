"""Refuse a production env that still carries a lane default (first deployment spec §10).

Usage: python3 deploy/check_prod_env.py {platform-api|design-api|worker|page-origin} <env-file>

Standard library only — the worker VM runs it with its system python3 before every deploy.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROLES = ("platform-api", "design-api", "worker", "page-origin")
#: The roles that run application code; page-origin only serves published pages.
APP_ROLES = ("platform-api", "design-api", "worker")

#: name -> the only acceptable production value, for every role.
EXACT = {
    "CLUE_STORAGE_BACKEND": "s3",
    "CLUE_PAGES_SYSTEM_SUFFIX": "pages.cluehq.ai",
    "CLUE_PAGES_PUBLIC_SCHEME": "https",
    "CLUE_PAGES_TRUST_HOST_HEADER": "false",
}
#: ... and for the application roles. CLUE_AUTH_ENVIRONMENT=production is also what makes a process
#: refuse the two development lenses at startup, which is why the VM workers need it too.
APP_EXACT = {
    "CLUE_SCRAPE_BACKEND": "scrapling",
    "CLUE_STAGE0_PAGE_FETCHER": "scrapling",
    "CLUE_AUTH_ENABLED": "true",
    "CLUE_AUTH_ENVIRONMENT": "production",
    "CLUE_AUTH_MODE": "clerk",
    # Settings refuses the in-memory metrics sink in production (first deploy, 2026-10-03).
    "CLUE_METRICS_EXPORTER": "otlp",
}
#: names that must be set to something non-empty, for every role.
REQUIRED = (
    "CLUE_DATABASE_URL",
    "CLUE_STORAGE_S3_BUCKET",
    "CLUE_STORAGE_S3_ENDPOINT_URL",
    "CLUE_STORAGE_S3_REGION",
    "CLUE_STORAGE_S3_ACCESS_KEY_ID",
    "CLUE_STORAGE_S3_SECRET_ACCESS_KEY",
)
APP_REQUIRED = ("CLUE_REDIS_URL", "CLUE_OPENROUTER_API_KEY", "CLUE_METRICS_OTLP_ENDPOINT")
#: Sumble switches that make a service refuse to start without CLUE_SUMBLE_API_KEY, and whether
#: CLUE_PRODUCT_PATH=integration_pilot turns them on when unset (clue_config.settings overlay).
SUMBLE_SWITCHES = {
    "CLUE_SUMBLE_ACCOUNT_GAP_ENRICHMENT_ENABLED": True,
    "CLUE_SUMBLE_DISCOVERY_GAP_ENRICHMENT_ENABLED": False,
    "CLUE_SUMBLE_COMMITTEE_ACQUISITION_ENABLED": True,
}
#: Paths the backend image sets (docker/backend/Dockerfile ENV) to what is actually inside it. A
#: production env must leave them out: .env.example's values are lane values (a blank
#: LUMEN_CORE_HELPER falls back to `cargo run`, which the image lacks; a relative
#: CLUE_ARV2_RAW_ROOT lands under the root-owned /app; the font path is a checkout placeholder).
IMAGE_OWNED = {
    "CLUE_ARV2_RAW_ROOT": "podcast downloads, writable by uid 1000",
    "LUMEN_CORE_HELPER": "the design engine helper binary",
    "LUMEN_FONT_LIBRARY_MANIFEST_PATH": "the font library manifest",
}
#: Telemetry labels that must say production when present (the lane writes its own name there).
PRODUCTION_LABELS = ("CLUE_SENTRY_ENVIRONMENT", "CLUE_LANGFUSE_ENVIRONMENT")
#: Settings that must not point at this machine.
NOT_LOCAL = (
    "CLUE_DATABASE_URL",
    "CLUE_REDIS_URL",
    "CLUE_APP_ORIGIN",
    "CLUE_DESIGN_API_BASE_URL",
    "LUMEN_API_ORIGIN",
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


def _local(value: str) -> bool:
    return "localhost" in value or "127.0.0.1" in value


def problems(env: dict[str, str], role: str) -> list[str]:
    """Every way ``env`` falls short of production for ``role``; empty means it is fine."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")
    app = role in APP_ROLES
    found: list[str] = []
    for name, wanted in {**EXACT, **(APP_EXACT if app else {})}.items():
        if env.get(name, "") != wanted:
            found.append(f"{name} must be {wanted!r} in production (is {env.get(name)!r})")
    required = (*REQUIRED, *(APP_REQUIRED if app else ("CLUE_PAGES_EDGE_SECRET",)))
    for name in required:
        if not env.get(name):
            found.append(f"{name} must be set")
    for name in NOT_LOCAL:
        if _local(env.get(name, "")):
            found.append(f"{name} points at localhost")
    for name, value in env.items():
        # ${{…}} is a Railway reference and is resolved; a bare ${…} is a shell expansion that
        # neither Railway nor docker's env_file performs — the process would get the literal text.
        if "${" in value.replace("${{", ""):
            found.append(
                f"{name} contains an unexpanded ${{…}} reference ({value!r}): write the value, or "
                "on Railway a ${{shared.NAME}} reference"
            )
    for name, reason in IMAGE_OWNED.items():
        if name in env:
            found.append(
                f"{name} must not be set: the backend image sets it ({reason}), and any env "
                f"line — even an empty one — overrides it (is {env[name]!r})"
            )
    if app:
        if env.get("CLUE_CHAT_REASONING_TRACE_MODE", "summary") != "summary":
            found.append("CLUE_CHAT_REASONING_TRACE_MODE must be 'summary' (raw is dev-only)")
        if env.get("CLUE_CHAT_DEV_INSPECTOR_ENABLED", "false").lower() in ("1", "true", "yes"):
            found.append("CLUE_CHAT_DEV_INSPECTOR_ENABLED is a development lens; set it false")
        for name in PRODUCTION_LABELS:
            if name in env and env[name] != "production":
                found.append(f"{name} must be 'production' (is {env[name]!r})")
        if not env.get("CLUE_SUMBLE_API_KEY"):
            pilot = env.get("CLUE_PRODUCT_PATH") == "integration_pilot"
            for name, pilot_default in SUMBLE_SWITCHES.items():
                value = env.get(name)
                on = value.lower() in ("1", "true", "yes") if value else pilot and pilot_default
                if on:
                    found.append(
                        f"{name} is on but CLUE_SUMBLE_API_KEY is not set: the service refuses "
                        "to start; set it false or provide the key"
                    )
    if role == "platform-api":
        found.extend(_platform_api_problems(env))
    if role == "design-api" and env.get("LUMEN_EMBEDDED_FLEET_WORKER") != "0":
        found.append(
            "LUMEN_EMBEDDED_FLEET_WORKER must be 0 on Railway (design jobs belong to the VM)"
        )
    if role == "worker":
        found.extend(_worker_problems(env))
    return found


def _platform_api_problems(env: dict[str, str]) -> list[str]:
    found: list[str] = []
    if env.get("CLUE_PROJECTIONS_AUTH_MODE") != "authenticated_principal":
        found.append("CLUE_PROJECTIONS_AUTH_MODE must be 'authenticated_principal'")
    for name in ("CLUE_AUTH_CLERK_JWKS_URL", "CLUE_AUTH_CLERK_ISSUER"):
        value = env.get(name, "")
        if not value:
            found.append(f"{name} must be set (the production Clerk instance)")
        elif "clerk.accounts.dev" in value:
            found.append(f"{name} is a Clerk DEVELOPMENT instance; use the production one")
    parties = env.get("CLUE_AUTH_CLERK_AUTHORIZED_PARTIES", "")
    if not parties or _local(parties):
        found.append("CLUE_AUTH_CLERK_AUTHORIZED_PARTIES must list only https://app.cluehq.ai")
    if not env.get("CLUE_APP_ORIGIN", "").startswith("https://"):
        found.append("CLUE_APP_ORIGIN must be the https app origin")
    return found


def _worker_problems(env: dict[str, str]) -> list[str]:
    found: list[str] = []
    controller = env.get("LUMEN_INGESTION_CONTROLLER_DATABASE_URL", "")
    if not controller:
        found.append(
            "LUMEN_INGESTION_CONTROLLER_DATABASE_URL must be set (the direct Railway proxy "
            "URL: the ingestion controller's session lock cannot go through PgBouncer)"
        )
    elif "pgbouncer" in controller or ":6432" in controller:
        found.append("LUMEN_INGESTION_CONTROLLER_DATABASE_URL must bypass PgBouncer")
    elif _local(controller):
        found.append("LUMEN_INGESTION_CONTROLLER_DATABASE_URL points at localhost")
    redis = env.get("CLUE_REDIS_URL", "")
    if redis and not (redis.startswith("rediss://") and "ssl_cert_reqs=none" in redis):
        found.append(
            "CLUE_REDIS_URL must be rediss://…?ssl_cert_reqs=none: the VM reaches Redis over "
            "Railway's public TCP proxy (TLS on port 6379, self-signed certificate)"
        )
    origin = env.get("LUMEN_API_ORIGIN", "")
    if not origin.startswith("https://") or ".railway.internal" in origin:
        found.append(
            "LUMEN_API_ORIGIN must be the public asset proxy "
            "(https://app.cluehq.ai/api/clue/design-public): the VM's preview renders fetch "
            "images from it, and the design API has no public domain"
        )
    if env.get("CLUE_FLEET_WORKER_KINDS"):
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

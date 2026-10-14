"""Refuse a production env that still carries a lane default (first deployment spec §10).

Usage: python3 deploy/check_prod_env.py <role> <env-file>
         role: platform-api | design-api | worker | page-origin | frontend
       python3 deploy/check_prod_env.py site-editor <site-editor-env-file> <frontend-env-file>

The site editor is always checked against the app it serves: both must name the same editor domain
and the same app origin, or every site loads forever (review finding S7-2).

Standard library only — the worker VM runs it with its system python3 before every deploy.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROLES = ("platform-api", "design-api", "worker", "page-origin", "frontend", "site-editor")
#: The roles that run application code; page-origin only serves published pages.
APP_ROLES = ("platform-api", "design-api", "worker")

#: name -> the only acceptable production value, for every role.
EXACT = {
    "CLUE_STORAGE_BACKEND": "s3",
    "CLUE_PAGES_PUBLIC_SCHEME": "https",
    "CLUE_PAGES_TRUST_HOST_HEADER": "false",
}
#: Where published pages lived before they moved to their own registrable domain (Wave 2
#: Contract 9). A production suffix is this one, or a hostname off cluehq.ai.
LEGACY_PAGES_SUFFIX = "pages.cluehq.ai"
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
    "CLUE_PAGES_SYSTEM_SUFFIX",
)
APP_REQUIRED = ("CLUE_REDIS_URL", "CLUE_OPENROUTER_API_KEY", "CLUE_METRICS_OTLP_ENDPOINT")
#: ... and for the design API alone. Wave 2 Contract 4: without it every editor section load
#: answers 503 site_section_links.unconfigured.
DESIGN_API_REQUIRED = ("CLUE_SITE_SECTION_LINK_SECRET",)
#: Review finding S7-4: a literal section-link secret shorter than this is a placeholder, not a
#: secret. (A Railway ${{shared.…}} reference cannot be seen from a file; the design API itself
#: refuses to start in production without a secret this long — lumen_api.site_section_links.)
SECTION_LINK_SECRET_MIN = 32
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
    # Review finding S7-1: .env.example's 1 (right on a Mac) breaks every site render in a
    # container.
    "LUMEN_SITE_RENDER_CHROMIUM_SANDBOX": (
        "0: the containers cannot give the site renderer's Chromium its own sandbox; see "
        "docs/specs/2026-10-14-site-render-chromium-sandbox-decision.md"
    ),
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
    "CLUE_PAGES_SYSTEM_SUFFIX",
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
    # The two Node services carry none of the backend's settings: they have their own checks.
    if role == "frontend":
        return _frontend_problems(env)
    if role == "site-editor":
        return _site_editor_problems(env)
    app = role in APP_ROLES
    found: list[str] = []
    for name, wanted in {**EXACT, **(APP_EXACT if app else {})}.items():
        if env.get(name, "") != wanted:
            found.append(f"{name} must be {wanted!r} in production (is {env.get(name)!r})")
    required = (
        *REQUIRED,
        *(APP_REQUIRED if app else ("CLUE_PAGES_EDGE_SECRET",)),
        *(DESIGN_API_REQUIRED if role == "design-api" else ()),
    )
    for name in required:
        if not env.get(name):
            found.append(f"{name} must be set")
    secret = env.get("CLUE_SITE_SECTION_LINK_SECRET", "")
    literal = secret and not secret.startswith("${{")
    if role == "design-api" and literal and len(secret) < SECTION_LINK_SECRET_MIN:
        found.append(
            f"CLUE_SITE_SECTION_LINK_SECRET must be at least {SECTION_LINK_SECRET_MIN} "
            "characters (a placeholder is not a secret; e.g. `openssl rand -hex 32`)"
        )
    for name in NOT_LOCAL:
        if _local(env.get(name, "")):
            found.append(f"{name} points at localhost")
    suffix = env.get("CLUE_PAGES_SYSTEM_SUFFIX", "").strip().lower()
    if suffix and suffix != LEGACY_PAGES_SUFFIX:
        if suffix == "cluehq.ai" or suffix.endswith(".cluehq.ai"):
            found.append(
                "CLUE_PAGES_SYSTEM_SUFFIX must be pages.cluehq.ai or a hostname on the published "
                f"pages' own domain, never another cluehq.ai name (is {suffix!r})"
            )
        legacy = env.get("CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES")
        if legacy is not None and LEGACY_PAGES_SUFFIX not in [
            part.strip().lower() for part in legacy.split(",")
        ]:
            found.append(
                "CLUE_PAGES_LEGACY_SYSTEM_SUFFIXES must keep pages.cluehq.ai once published pages "
                "move to their own domain (the custom-domain reservation depends on it)"
            )
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
        # Langfuse is on unless switched off, and an unset label is NOT production: the code
        # default is Langfuse's `default`, where every development lane's traces land.
        langfuse_on = env.get("CLUE_LANGFUSE_ENABLED", "true").lower() in ("1", "true", "yes")
        if langfuse_on and "CLUE_LANGFUSE_ENVIRONMENT" not in env:
            found.append(
                "CLUE_LANGFUSE_ENVIRONMENT must be set to 'production' (unset, traces are "
                "filed under the development environment 'default')"
            )
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


#: What the site editor service must never carry: it serves agent-written code on its own domain
#: and holds no login, no secret and no database access (apps/frontend/docs/railway-deployment.md).
_EDITOR_FORBIDDEN = re.compile(
    r"(SECRET|API_KEY|PASSWORD|TOKEN|DATABASE_URL|REDIS_URL|CLERK)", re.IGNORECASE
)
_DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def _editor_suffix_problems(env: dict[str, str]) -> list[str]:
    suffix = env.get("CLUE_SITE_EDITOR_SUFFIX", "").strip()
    if not suffix:
        return [
            "CLUE_SITE_EDITOR_SUFFIX must be set (the site editor's domain, e.g. "
            "edit.deeppresence.ai)"
        ]
    if _local(suffix) or "localhost" in suffix or not _DOMAIN.match(suffix.lower()):
        return [
            "CLUE_SITE_EDITOR_SUFFIX must be a bare domain name — no scheme, port or path, never "
            f"localhost (is {suffix!r})"
        ]
    return []


def _app_origin_problems(env: dict[str, str]) -> list[str]:
    origin = env.get("CLUE_APP_ORIGIN", "").strip()
    if not re.match(r"^https://[a-z0-9.-]+$", origin) or _local(origin):
        return [f"CLUE_APP_ORIGIN must be the app's https origin, with no path (is {origin!r})"]
    return []


def _frontend_problems(env: dict[str, str]) -> list[str]:
    """The app (review finding S7-2): without the editor's domain, every site shows 'not
    configured'."""
    return [*_editor_suffix_problems(env), *_app_origin_problems(env)]


def _site_editor_problems(env: dict[str, str]) -> list[str]:
    found = [*_editor_suffix_problems(env), *_app_origin_problems(env)]
    design_api = env.get("LUMEN_API_BASE_URL", "")
    if not design_api or _local(design_api):
        found.append(
            "LUMEN_API_BASE_URL must be the design API's private address "
            "(http://design-api.railway.internal:8010)"
        )
    for name in sorted(env):
        if _EDITOR_FORBIDDEN.search(name):
            found.append(
                f"{name} must not be set: the site editor serves agent-written code and holds no "
                "login, secret or database access"
            )
    return found


def editor_pair_problems(frontend: dict[str, str], editor: dict[str, str]) -> list[str]:
    """The app and the editor service it frames must agree, or the frame never answers: the app
    mints addresses on its suffix, and the editor only lets its configured app origin frame it."""
    found: list[str] = []
    for name in ("CLUE_SITE_EDITOR_SUFFIX", "CLUE_APP_ORIGIN"):
        if frontend.get(name, "").strip().lower() != editor.get(name, "").strip().lower():
            found.append(
                f"{name} differs between the frontend ({frontend.get(name)!r}) and the site "
                f"editor ({editor.get(name)!r}); they must be the same"
            )
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
    role = argv[1] if len(argv) > 1 else ""
    if len(argv) != (4 if role == "site-editor" else 3):
        sys.stderr.write(f"{__doc__}\n")
        return 2
    env = parse(Path(argv[2]).read_text(encoding="utf-8"))
    found = problems(env, role)
    if role == "site-editor":
        found += editor_pair_problems(parse(Path(argv[3]).read_text(encoding="utf-8")), env)
    for problem in found:
        sys.stdout.write(f"PROBLEM: {problem}\n")
    sys.stdout.write("OK\n" if not found else f"{len(found)} problem(s)\n")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

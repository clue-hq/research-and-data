"""deploy/check_prod_env.py refuses a production env that still carries a lane default
(first deployment spec §10)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "deploy" / "check_prod_env.py"
_spec = importlib.util.spec_from_file_location("check_prod_env", _PATH)
assert _spec is not None and _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

#: What every role needs: the database, the R2 file store, and the public-pages settings.
GOOD_COMMON = {
    "CLUE_DATABASE_URL": "postgresql+asyncpg://u:p@db.internal:5432/clue",
    "CLUE_STORAGE_BACKEND": "s3",
    "CLUE_STORAGE_S3_BUCKET": "clue-prod",
    "CLUE_STORAGE_S3_ENDPOINT_URL": "https://acct.r2.cloudflarestorage.com",
    "CLUE_STORAGE_S3_REGION": "auto",
    "CLUE_STORAGE_S3_ACCESS_KEY_ID": "k",
    "CLUE_STORAGE_S3_SECRET_ACCESS_KEY": "s",
    "CLUE_PAGES_SYSTEM_SUFFIX": "pages.cluehq.ai",
    "CLUE_PAGES_PUBLIC_SCHEME": "https",
    "CLUE_PAGES_TRUST_HOST_HEADER": "false",
}
#: The three roles that run application code (APIs and workers).
GOOD_APP = {
    **GOOD_COMMON,
    "CLUE_REDIS_URL": "redis://default:p@redis.internal:6379/0",
    "CLUE_SCRAPE_BACKEND": "scrapling",
    "CLUE_STAGE0_PAGE_FETCHER": "scrapling",
    "CLUE_AUTH_ENABLED": "true",
    "CLUE_AUTH_ENVIRONMENT": "production",
    "CLUE_AUTH_MODE": "clerk",
    "CLUE_CHAT_REASONING_TRACE_MODE": "summary",
    "CLUE_CHAT_DEV_INSPECTOR_ENABLED": "false",
    "CLUE_OPENROUTER_API_KEY": "${{shared.CLUE_OPENROUTER_API_KEY}}",
    "CLUE_SENTRY_ENVIRONMENT": "production",
    "CLUE_LANGFUSE_ENVIRONMENT": "production",
}
GOOD_PLATFORM = {
    **GOOD_APP,
    "CLUE_PROJECTIONS_AUTH_MODE": "authenticated_principal",
    "CLUE_AUTH_CLERK_JWKS_URL": "https://clerk.cluehq.ai/.well-known/jwks.json",
    "CLUE_AUTH_CLERK_ISSUER": "https://clerk.cluehq.ai",
    "CLUE_AUTH_CLERK_AUTHORIZED_PARTIES": "https://app.cluehq.ai",
    "CLUE_APP_ORIGIN": "https://app.cluehq.ai",
    "CLUE_DESIGN_API_BASE_URL": "http://design-api.railway.internal:8010",
}
GOOD_DESIGN = {**GOOD_APP, "LUMEN_EMBEDDED_FLEET_WORKER": "0"}
GOOD_WORKER = {
    **GOOD_APP,
    "CLUE_REDIS_URL": "rediss://default:p@proxy.example:41235/0?ssl_cert_reqs=none",
    "LUMEN_INGESTION_CONTROLLER_DATABASE_URL": (
        "postgresql+asyncpg://clue_worker:p@proxy.example:41234/railway?ssl=require"
    ),
    "LUMEN_API_ORIGIN": "https://app.cluehq.ai/api/clue/design-public",
}
GOOD_PAGE_ORIGIN = {**GOOD_COMMON, "CLUE_PAGES_EDGE_SECRET": "edge"}
GOOD = {
    "platform-api": GOOD_PLATFORM,
    "design-api": GOOD_DESIGN,
    "worker": GOOD_WORKER,
    "page-origin": GOOD_PAGE_ORIGIN,
}
APP_ROLES = ("platform-api", "design-api", "worker")


@pytest.mark.parametrize("role", list(GOOD))
def test_a_correct_env_has_no_problems(role: str) -> None:
    assert check.problems(GOOD[role], role) == []


def test_a_correct_worker_env_has_no_problems() -> None:
    assert check.problems(GOOD_WORKER, "worker") == []


def test_the_embedded_design_worker_must_be_off_on_railway() -> None:
    for value in ("1", "true", ""):
        env = {**GOOD_DESIGN, "LUMEN_EMBEDDED_FLEET_WORKER": value}
        assert any("LUMEN_EMBEDDED_FLEET_WORKER" in p for p in check.problems(env, "design-api"))


def test_lane_defaults_are_caught() -> None:
    env = {
        **GOOD_PLATFORM,
        "CLUE_STORAGE_BACKEND": "fs",
        "CLUE_CHAT_REASONING_TRACE_MODE": "raw",
        "CLUE_PAGES_TRUST_HOST_HEADER": "true",
        "CLUE_DATABASE_URL": "postgresql+asyncpg://clue:clue@localhost:55040/clue_lane",
        "CLUE_REDIS_URL": "redis://127.0.0.1:6379/0",
    }
    found = " ".join(check.problems(env, "platform-api"))
    for name in (
        "CLUE_STORAGE_BACKEND",
        "CLUE_CHAT_REASONING_TRACE_MODE",
        "CLUE_PAGES_TRUST_HOST_HEADER",
        "CLUE_DATABASE_URL points at localhost",
        "CLUE_REDIS_URL points at localhost",
    ):
        assert name in found


def test_missing_secrets_are_caught() -> None:
    env = {k: v for k, v in GOOD_PLATFORM.items() if k != "CLUE_STORAGE_S3_SECRET_ACCESS_KEY"}
    assert any(
        "CLUE_STORAGE_S3_SECRET_ACCESS_KEY must be set" in p
        for p in check.problems(env, "platform-api")
    )


def test_the_worker_env_needs_the_ingestion_controllers_direct_url() -> None:
    env = {k: v for k, v in GOOD_WORKER.items() if k != "LUMEN_INGESTION_CONTROLLER_DATABASE_URL"}
    assert any(
        "LUMEN_INGESTION_CONTROLLER_DATABASE_URL must be set" in p
        for p in check.problems(env, "worker")
    )


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://clue_worker:p@pgbouncer:6432/railway",
        "postgresql+asyncpg://clue_worker:p@localhost:5432/railway",
    ],
)
def test_the_controllers_url_must_be_direct_and_remote(url: str) -> None:
    env = {**GOOD_WORKER, "LUMEN_INGESTION_CONTROLLER_DATABASE_URL": url}
    assert any(
        "LUMEN_INGESTION_CONTROLLER_DATABASE_URL" in p for p in check.problems(env, "worker")
    )


def test_the_railway_services_do_not_need_the_controller_url() -> None:
    assert check.problems(GOOD_DESIGN, "design-api") == []
    assert check.problems(GOOD_PLATFORM, "platform-api") == []


IMAGE_OWNED = ("CLUE_ARV2_RAW_ROOT", "LUMEN_CORE_HELPER", "LUMEN_FONT_LIBRARY_MANIFEST_PATH")


@pytest.mark.parametrize("role", list(GOOD))
@pytest.mark.parametrize("name", IMAGE_OWNED)
@pytest.mark.parametrize(
    "value",
    [
        "",  # LUMEN_CORE_HELPER= as in .env.example: blank means `cargo run`
        ".artifacts/arv2",  # relative: lands under the root-owned /app
        "/absolute/path/to/your/checkout/subsystems/clue-design/apps/api/font-library/manifest.json",
        "/opt/somewhere/else",  # a path the image does not have
    ],
)
def test_an_env_line_for_an_image_owned_path_is_refused(role: str, name: str, value: str) -> None:
    """Any env line, even an empty one, overrides the image's ENV; the image's value is the
    only one that matches what is actually inside it."""
    env = {**GOOD[role], name: value}
    assert any(p.startswith(f"{name} must not be set") for p in check.problems(env, role))


def test_leaving_the_image_owned_paths_out_is_fine() -> None:
    assert check.problems(GOOD_WORKER, "worker") == []


def test_the_image_sets_every_path_the_check_keeps_out_of_env_files() -> None:
    dockerfile = (_PATH.parents[1] / "docker" / "backend" / "Dockerfile").read_text("utf-8")
    for name in IMAGE_OWNED:
        assert f"{name}=/" in dockerfile, name
    assert set(check.IMAGE_OWNED) == set(IMAGE_OWNED)


def test_workers_must_not_pick_their_own_kinds_in_the_shared_env_file() -> None:
    """Pool kinds live in compose.yaml; a kinds line in the shared env file would override them."""
    env = {**GOOD_WORKER, "CLUE_FLEET_WORKER_KINDS": "agent_turn"}
    assert any("CLUE_FLEET_WORKER_KINDS" in p for p in check.problems(env, "worker"))


# --- the edge secret lives only where it is read -------------------------------------------------


def test_page_origin_needs_the_edge_secret() -> None:
    env = {k: v for k, v in GOOD_PAGE_ORIGIN.items() if k != "CLUE_PAGES_EDGE_SECRET"}
    assert any(
        "CLUE_PAGES_EDGE_SECRET must be set" in p for p in check.problems(env, "page-origin")
    )


@pytest.mark.parametrize("role", APP_ROLES)
def test_no_other_service_needs_the_edge_secret(role: str) -> None:
    """Only page-origin reads it; a secret lives in as few places as possible."""
    assert "CLUE_PAGES_EDGE_SECRET" not in GOOD[role]
    assert check.problems(GOOD[role], role) == []


@pytest.mark.parametrize("role", list(GOOD))
def test_every_role_needs_the_r2_region(role: str) -> None:
    env = {k: v for k, v in GOOD[role].items() if k != "CLUE_STORAGE_S3_REGION"}
    assert any("CLUE_STORAGE_S3_REGION" in p for p in check.problems(env, role))


# --- production auth, and the two development lenses -------------------------------------------


@pytest.mark.parametrize("role", APP_ROLES)
@pytest.mark.parametrize(
    ("name", "lane_value"),
    [
        ("CLUE_AUTH_ENVIRONMENT", "local"),
        ("CLUE_AUTH_ENABLED", "false"),
        ("CLUE_AUTH_MODE", "local_fixture"),
    ],
)
def test_app_roles_must_run_production_auth(role: str, name: str, lane_value: str) -> None:
    """CLUE_AUTH_ENVIRONMENT=production is also what makes a process REFUSE the dev lenses at
    startup (Settings._production_refuses_dev_lenses), so the VM workers need it too."""
    env = {**GOOD[role], name: lane_value}
    assert any(name in p for p in check.problems(env, role))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CLUE_PROJECTIONS_AUTH_MODE", "local_header"),
        (
            "CLUE_AUTH_CLERK_JWKS_URL",
            "https://precise-lamb-56.clerk.accounts.dev/.well-known/jwks.json",
        ),
        ("CLUE_AUTH_CLERK_ISSUER", "https://precise-lamb-56.clerk.accounts.dev"),
        ("CLUE_AUTH_CLERK_AUTHORIZED_PARTIES", "http://localhost:3033,https://app.cluehq.ai"),
        ("CLUE_APP_ORIGIN", "http://localhost:3033"),
        ("CLUE_DESIGN_API_BASE_URL", "http://127.0.0.1:8013"),
    ],
)
def test_the_platform_api_needs_the_production_clerk_instance_and_real_origins(
    name: str, value: str
) -> None:
    env = {**GOOD_PLATFORM, name: value}
    assert any(name in p for p in check.problems(env, "platform-api"))


@pytest.mark.parametrize("role", APP_ROLES)
def test_the_turn_context_inspector_must_be_off(role: str) -> None:
    env = {**GOOD[role], "CLUE_CHAT_DEV_INSPECTOR_ENABLED": "true"}
    assert any("CLUE_CHAT_DEV_INSPECTOR_ENABLED" in p for p in check.problems(env, role))


@pytest.mark.parametrize("role", APP_ROLES)
def test_app_roles_need_the_openrouter_key(role: str) -> None:
    env = {k: v for k, v in GOOD[role].items() if k != "CLUE_OPENROUTER_API_KEY"}
    assert any("CLUE_OPENROUTER_API_KEY must be set" in p for p in check.problems(env, role))


@pytest.mark.parametrize("name", ["CLUE_SENTRY_ENVIRONMENT", "CLUE_LANGFUSE_ENVIRONMENT"])
def test_telemetry_is_labelled_production(name: str) -> None:
    env = {**GOOD_PLATFORM, name: "lane-san-salvador"}
    assert any(name in p for p in check.problems(env, "platform-api"))


# --- values a shell would have expanded, but Railway and docker's env_file do not ---------------


@pytest.mark.parametrize("role", list(GOOD))
def test_an_unexpanded_shell_reference_is_refused(role: str) -> None:
    """.env.example's OPENROUTER_API_KEY="${CLUE_OPENROUTER_API_KEY}" would reach the process as
    those literal characters — an invalid key — on Railway and through docker's env_file."""
    env = {**GOOD[role], "IMAGE_MODEL_API_KEY": "${CLUE_OPENROUTER_API_KEY}"}
    assert any("IMAGE_MODEL_API_KEY" in p and "${" in p for p in check.problems(env, role))


def test_a_railway_reference_is_fine() -> None:
    env = {**GOOD_PLATFORM, "IMAGE_MODEL_API_KEY": "${{shared.CLUE_OPENROUTER_API_KEY}}"}
    assert check.problems(env, "platform-api") == []


# --- the VM's preview renders fetch images over the public, narrow asset proxy ------------------


@pytest.mark.parametrize(
    "value",
    ["", "http://127.0.0.1:8013", "http://design-api.railway.internal:8010"],
)
def test_the_workers_asset_origin_must_be_public_https(value: str) -> None:
    """The VM is not on Railway's private network; the design API has no public domain. Workers
    reach /asset-store/<digest> through the frontend's public proxy."""
    env = {**GOOD_WORKER, "LUMEN_API_ORIGIN": value}
    assert any("LUMEN_API_ORIGIN" in p for p in check.problems(env, "worker"))


@pytest.mark.parametrize(
    "url",
    ["redis://default:p@proxy.example:41235/0", "rediss://default:p@proxy.example:41235/0"],
)
def test_the_workers_redis_goes_over_tls_to_a_self_signed_server(url: str) -> None:
    """The VM reaches Redis over Railway's public TCP proxy: plain redis:// would send the password
    and lock traffic in clear text, and the Railway Redis TLS port serves a self-signed
    certificate, so redis-py must be told not to verify it (ssl_cert_reqs=none), as Postgres'
    sslmode=require does not verify either."""
    env = {**GOOD_WORKER, "CLUE_REDIS_URL": url}
    assert any("CLUE_REDIS_URL" in p for p in check.problems(env, "worker"))


def test_an_unknown_role_is_refused() -> None:
    with pytest.raises(ValueError):
        check.problems(GOOD_PLATFORM, "frontend")


def test_parse_reads_an_env_file_with_comments_quotes_and_blank_values() -> None:
    parsed = check.parse("# comment\n\nA=1\nB=\"two\"\nC='three'\nD=\nE=x=y\n")
    assert parsed == {"A": "1", "B": "two", "C": "three", "D": "", "E": "x=y"}


def test_the_cli_exits_1_and_names_each_problem(tmp_path: Path) -> None:
    env_file = tmp_path / "env"
    env_file.write_text("CLUE_STORAGE_BACKEND=fs\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(_PATH), "platform-api", str(env_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "PROBLEM: CLUE_STORAGE_BACKEND" in result.stdout


def test_the_cli_exits_0_on_a_clean_file(tmp_path: Path) -> None:
    env_file = tmp_path / "env"
    env_file.write_text("".join(f"{k}={v}\n" for k, v in GOOD_WORKER.items()), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(_PATH), "worker", str(env_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert result.stdout.strip().endswith("OK")

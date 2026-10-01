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

GOOD_COMMON = {
    "CLUE_DATABASE_URL": "postgresql+asyncpg://u:p@db.internal:5432/clue",
    "CLUE_REDIS_URL": "redis://default:p@redis.internal:6379/0",
    "CLUE_STORAGE_BACKEND": "s3",
    "CLUE_STORAGE_S3_BUCKET": "clue-prod",
    "CLUE_STORAGE_S3_ENDPOINT_URL": "https://acct.r2.cloudflarestorage.com",
    "CLUE_STORAGE_S3_ACCESS_KEY_ID": "k",
    "CLUE_STORAGE_S3_SECRET_ACCESS_KEY": "s",
    "CLUE_PAGES_SYSTEM_SUFFIX": "pages.cluehq.ai",
    "CLUE_PAGES_PUBLIC_SCHEME": "https",
    "CLUE_PAGES_TRUST_HOST_HEADER": "false",
    "CLUE_PAGES_EDGE_SECRET": "edge",
    "CLUE_SCRAPE_BACKEND": "scrapling",
    "CLUE_STAGE0_PAGE_FETCHER": "scrapling",
    "CLUE_CHAT_REASONING_TRACE_MODE": "",
}
GOOD_WORKER = {
    **GOOD_COMMON,
    "LUMEN_INGESTION_CONTROLLER_DATABASE_URL": (
        "postgresql+asyncpg://clue_worker:p@proxy.example:41234/railway?ssl=require"
    ),
}


def test_a_correct_design_api_env_has_no_problems() -> None:
    env = {**GOOD_COMMON, "LUMEN_EMBEDDED_FLEET_WORKER": "0"}
    assert check.problems(env, "design-api") == []


def test_a_correct_worker_env_has_no_problems() -> None:
    assert check.problems(GOOD_WORKER, "worker") == []


def test_the_embedded_design_worker_must_be_off_on_railway() -> None:
    for value in ("1", "true", ""):
        env = {**GOOD_COMMON, "LUMEN_EMBEDDED_FLEET_WORKER": value}
        assert any("LUMEN_EMBEDDED_FLEET_WORKER" in p for p in check.problems(env, "design-api"))


def test_lane_defaults_are_caught() -> None:
    env = {
        **GOOD_COMMON,
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
    env = {k: v for k, v in GOOD_COMMON.items() if k != "CLUE_STORAGE_S3_SECRET_ACCESS_KEY"}
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
    assert check.problems({**GOOD_COMMON, "LUMEN_EMBEDDED_FLEET_WORKER": "0"}, "design-api") == []
    assert check.problems(GOOD_COMMON, "platform-api") == []


IMAGE_OWNED = ("CLUE_ARV2_RAW_ROOT", "LUMEN_CORE_HELPER", "LUMEN_FONT_LIBRARY_MANIFEST_PATH")


@pytest.mark.parametrize("role", ["platform-api", "design-api", "worker"])
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
    env = {**GOOD_WORKER, "LUMEN_EMBEDDED_FLEET_WORKER": "0", name: value}
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
    env = {**GOOD_COMMON, "CLUE_FLEET_WORKER_KINDS": "agent_turn"}
    assert any("CLUE_FLEET_WORKER_KINDS" in p for p in check.problems(env, "worker"))


def test_an_unknown_role_is_refused() -> None:
    with pytest.raises(ValueError):
        check.problems(GOOD_COMMON, "frontend")


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

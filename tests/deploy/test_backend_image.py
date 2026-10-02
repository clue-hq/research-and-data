"""The backend image's own guarantees that the smoke test cannot check offline (first deployment
§9.1). docker/backend/smoke.sh proves them against the built image in CI; these pin the source."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "docker" / "backend" / "Dockerfile").read_text(encoding="utf-8")
SMOKE = (ROOT / "docker" / "backend" / "smoke.sh").read_text(encoding="utf-8")


def _arv2_raw_root() -> str:
    match = re.search(r"CLUE_ARV2_RAW_ROOT=(\S+)", DOCKERFILE)
    assert match is not None, "the image must set CLUE_ARV2_RAW_ROOT"
    return match.group(1)


def test_the_image_points_the_arv2_raw_root_at_an_absolute_path() -> None:
    """The settings default (.artifacts/arv2) is relative, so in the image it lands under the
    root-owned /app, where uid 1000 cannot create the podcast download folder."""
    assert _arv2_raw_root().startswith("/")


def test_the_arv2_raw_root_is_created_for_uid_1000_before_the_user_switch() -> None:
    root = _arv2_raw_root()
    user_switch = DOCKERFILE.index("USER 1000:1000")
    created = [
        m.start() for m in re.finditer(rf"mkdir -p [^\n]*{re.escape(root)}[^\n]*", DOCKERFILE)
    ]
    assert created and created[0] < user_switch, "create it while still root"
    chown = re.search(rf"chown[^\n]*1000[^\n]*{re.escape(root)}", DOCKERFILE)
    assert chown is not None and chown.start() < user_switch


def test_the_smoke_test_writes_to_the_arv2_raw_root_as_the_image_user() -> None:
    assert "CLUE_ARV2_RAW_ROOT" in SMOKE
    assert "ok: arv2 raw root writable" in SMOKE


def test_release_prs_run_every_image_check_but_only_a_push_to_main_moves_the_tags() -> None:
    """A release PR into main proves its images build, handshake and boot before the merge; the
    `production` tags the VM pulls move only once the code is on main."""
    import yaml

    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "deploy-images.yml").read_text(encoding="utf-8")
    )
    triggers = workflow[True]  # YAML 1.1 reads the bare key `on` as True
    assert triggers["push"]["branches"] == ["main"]
    assert triggers["pull_request"]["branches"] == ["main"]
    steps = workflow["jobs"]["images"]["steps"]
    movers = [s for s in steps if "production" in s.get("run", "") and "imagetools" in s["run"]]
    assert len(movers) == 1 and movers[0] is steps[-1]
    assert movers[0]["if"] == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    for step in steps[:-1]:
        assert "if" not in step, f"every check must run on PRs too: {step.get('name')}"


def test_both_apis_listen_on_a_configurable_host_defaulting_to_ipv4() -> None:
    """The design API is reachable ONLY over Railway's private network, which is IPv6, so its
    Railway service sets CLUE_BIND_HOST=:: (IPv6-only under uvicorn — measured). Unset, nothing
    changes: 0.0.0.0 as before (the platform API on Railway, CI's boot smoke)."""
    entrypoint = (ROOT / "docker" / "backend" / "entrypoint.sh").read_text(encoding="utf-8")
    for command in ("clue_api.projections_main:app", "lumen_api.main:app"):
        line = next(line for line in entrypoint.splitlines() if command in line)
        assert '--host "${CLUE_BIND_HOST:-0.0.0.0}"' in line, line


def test_the_bind_host_is_documented() -> None:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "CLUE_BIND_HOST=0.0.0.0" in lines

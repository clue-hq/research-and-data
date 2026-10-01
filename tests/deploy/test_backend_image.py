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

"""Lane C task C0: every frontend image installs every npm workspace package.

`npm ci` runs in the image's dependencies stage before the sources are copied, so each workspace
package's manifest must be copied first or the package is silently missing from node_modules.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PACKAGES = REPO / "apps/frontend/packages"
DOCKERFILES = ["apps/frontend/Dockerfile.railway"]


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_every_workspace_manifest_is_copied_before_npm_ci(dockerfile: str) -> None:
    text = (REPO / dockerfile).read_text(encoding="utf-8")
    assert "RUN npm ci" in text, f"{dockerfile} no longer runs npm ci"
    before_install = text.split("RUN npm ci", 1)[0]
    manifests = sorted(PACKAGES.glob("*/package.json"))
    assert manifests, "no workspace packages found"
    for manifest in manifests:
        relative = manifest.relative_to(REPO).as_posix()
        assert f"COPY {relative} " in before_install, (
            f"{dockerfile} does not copy {relative} before npm ci"
        )

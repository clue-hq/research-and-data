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
    assert 'check "arv2 raw root writable"' in SMOKE


def test_the_image_runs_the_site_renderer_without_chromiums_own_sandbox() -> None:
    """Review finding S7-1, option A (the decision:
    docs/specs/2026-10-14-site-render-chromium-sandbox-decision.md). Under Docker's default seccomp
    profile Chromium cannot create the user namespace its sandbox needs ("No usable sandbox!"), so
    the image sets the renderer's sandbox off; Macs keep the code default (on)."""
    assert re.search(r"^\s*LUMEN_SITE_RENDER_CHROMIUM_SANDBOX=0\b", DOCKERFILE, re.MULTILINE)


def test_the_smoke_test_launches_the_site_renderer_exactly_as_the_image_runs_it() -> None:
    """The smoke check used to launch Chromium with the sandbox hard-coded on, which the image
    cannot give and its own setting could not change, so it blocked every release (S7-1). It now
    opens the renderer's own hardened page, which reads the image's setting."""
    assert 'check "site renderer launches"' in SMOKE
    assert "hardened_page" in SMOKE
    assert "chromium_sandbox=True" not in SMOKE


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
    assert len(movers) == 1
    on_main = "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    at = steps.index(movers[0])
    for step in steps[:at]:
        assert "if" not in step, f"every check must run on PRs too: {step.get('name')}"
    # The tag move and what follows it (the Railway redeploy) happen only on main.
    for step in steps[at:]:
        assert step.get("if") == on_main, step.get("name")


def test_railway_redeploys_after_the_tags_move_platform_api_first() -> None:
    """Railway runs the image CI tagged; platform-api goes first so its pre-deploy migration
    lands before design-api and page-origin start on the schema."""
    import yaml

    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "deploy-images.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["images"]["steps"]
    names = [s.get("name", "") for s in steps]
    mover = next(i for i, s in enumerate(steps) if "imagetools" in s.get("run", ""))
    redeploy = next(i for i, n in enumerate(names) if n.startswith("Redeploy the Railway"))
    assert redeploy > mover
    run = steps[redeploy]["run"]
    order = [
        run.index(f"railway_redeploy.sh {s}") for s in ("platform-api", "design-api", "page-origin")
    ]
    assert order == sorted(order)
    assert steps[redeploy]["env"]["RAILWAY_TOKEN"] == "${{ secrets.RAILWAY_TOKEN }}"


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


def test_the_release_deploys_the_vm_last_with_a_pinned_host_and_only_the_sha() -> None:
    """After Railway (platform-api migrates first), CI deploys the worker VM over SSH: the host
    key is pinned, nothing interactive, and the only thing sent is the commit sha — on the VM the
    key is forced to deploy/vm/ci_deploy.sh, which accepts nothing else. Unconfigured, it warns
    and skips."""
    import yaml

    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "deploy-images.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["images"]["steps"]
    names = [s.get("name", "") for s in steps]
    vm = names.index("Deploy the worker VM")
    assert vm == len(steps) - 1
    assert vm > next(i for i, n in enumerate(names) if n.startswith("Redeploy the Railway"))
    step = steps[vm]
    assert step["if"] == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    run = step["run"]
    assert "StrictHostKeyChecking=yes" in run and "BatchMode=yes" in run
    assert 'clue@"$VM_HOST" "${{ github.sha }}"' in run
    assert "::warning::" in run and "exit 0" in run
    assert step["env"]["VM_SSH_KEY"] == "${{ secrets.VM_SSH_KEY }}"
    assert step["env"]["VM_SSH_KNOWN_HOSTS"] == "${{ secrets.VM_SSH_KNOWN_HOSTS }}"


def test_the_image_builds_and_ships_the_site_kit_bundles() -> None:
    """Puck sites render and validate with site-kit's built files (Wave 2 Lane A); the runtime has
    no apps/frontend/node_modules, so the bundles are built in their own stage and copied in."""
    assert "FROM node:24-bookworm-slim AS sitekit" in DOCKERFILE
    assert "npm run build -w @clue/site-kit" in DOCKERFILE
    assert (
        "COPY --from=sitekit /src/apps/frontend/packages/site-kit/dist"
        " /app/apps/frontend/packages/site-kit/dist" in DOCKERFILE
    )
    assert 'check "site-kit bundles"' in SMOKE


def test_the_smoke_check_finds_the_site_runtime_and_its_shims() -> None:
    """A live site page imports site-kit's runtime and its shims, published from the image's
    site-kit dist (publishing live sites, phase 1); the smoke check names both files."""
    bundles = next(line for line in SMOKE.splitlines() if 'check "site-kit bundles"' in line)
    assert "-a -f /app/apps/frontend/packages/site-kit/dist/site-runtime.js" in bundles
    assert "-a -f /app/apps/frontend/packages/site-kit/dist/site-runtime-shims/react.js" in bundles


def test_the_image_ships_the_section_compile_toolchain() -> None:
    """Agent-written sections are checked and bundled at run time (Wave 2 Lane B, Contract 4)."""
    assert (
        "COPY --from=sitekit /src/apps/frontend/node_modules /app/apps/frontend/node_modules"
        in DOCKERFILE
    )
    assert 'check "site-kit section toolchain"' in SMOKE


def test_the_runtime_user_can_create_the_section_check_folder() -> None:
    """The section compiler type-checks in a throwaway folder inside site-kit; the image's uid 1000
    must be able to create it (Wave 2 Lane B, Contract 4)."""
    assert (
        "mkdir -p /app/apps/frontend/packages/site-kit/.section-check"
        " && chown 1000:1000 /app/apps/frontend/packages/site-kit/.section-check" in DOCKERFILE
    )
    assert DOCKERFILE.index("site-kit/.section-check") < DOCKERFILE.index("USER 1000:1000")
    assert (
        'check "site-kit section check folder writable" run test -w'
        " /app/apps/frontend/packages/site-kit/.section-check" in SMOKE
    )

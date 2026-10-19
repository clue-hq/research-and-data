"""site-kit's command-line tools, called from Python (Wave 2: one runner for every caller).

The Puck site's validator, catalog builder and section compiler are TypeScript in
``apps/frontend/packages/site-kit``. Two kinds of entry exist:

* **bundles** — ``dist/<name>.mjs``, single files Lane A builds (``npm run build -w @clue/site-kit``)
  so the backend image needs no ``node_modules`` for them: the validator and the catalog;
* **scripts** — ``bin/<name>.ts`` run with ``node --import tsx``, for the one tool that needs the
  whole toolchain at run time (the section compiler: tsc, esbuild, Tailwind's inputs).

Each reads ONE JSON request on stdin and prints ONE JSON answer (the last line of stdout). Node
only transforms or scans agent-written code here — never imports or runs it (D2) — and it gets a
stripped environment so no platform secret is visible to the toolchain. Every failure to answer is
a typed ``SiteKitCliError``, never a crash, so a caller can turn it into an honest sentence.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

__all__ = [
    "SITE_KIT_DIR",
    "SiteKitCliError",
    "build_site_catalog",
    "compile_section_source",
    "run_site_kit_bundle",
    "run_site_kit_script",
    "section_toolchain_missing",
    "site_kit_toolchain_missing",
    "validate_site_files",
]

#: lumen_api/site_kit_cli.py -> parents[5] is the repository root.
SITE_KIT_DIR = Path(__file__).resolve().parents[5] / "apps" / "frontend" / "packages" / "site-kit"
#: npm hoists the frontend workspace's dependencies to apps/frontend/node_modules.
_NODE_MODULES = SITE_KIT_DIR.parent.parent / "node_modules"
#: What the section compiler needs installed (Task 15; contract conflict 8 for the image).
_SECTION_TOOLCHAIN = ("tsx", "typescript", "esbuild", "zod", "react")


class SiteKitCliError(RuntimeError):
    """A site-kit CLI could not answer: ``code`` is machine-readable, ``detail`` is for a human."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _dist() -> Path:
    from .site_render import site_kit_dist

    return site_kit_dist()


def site_kit_toolchain_missing(node_bin: str = "node") -> str | None:
    """Why the site-kit bundles cannot run here, or ``None`` when they can."""

    if shutil.which(node_bin) is None:
        return f"node is not on PATH (looked for {node_bin!r})"
    if not (_dist() / "validate-site.mjs").is_file():
        return f"site-kit is not built (no {_dist() / 'validate-site.mjs'}; run `npm run build -w @clue/site-kit` in apps/frontend)"
    return None


def section_toolchain_missing(node_bin: str = "node") -> str | None:
    """Why the section compiler cannot run here, or ``None`` when it can."""

    if shutil.which(node_bin) is None:
        return f"node is not on PATH (looked for {node_bin!r})"
    for package in _SECTION_TOOLCHAIN:
        if not (_NODE_MODULES / package).is_dir():
            return f"the section toolchain is not installed (no {_NODE_MODULES / package}; run npm ci in apps/frontend)"
    return None


def _child_env() -> dict[str, str]:
    """The only environment Node gets: enough to find binaries, a home and a temp folder."""

    return {key: os.environ[key] for key in ("PATH", "HOME", "TMPDIR") if key in os.environ}


def _run_node(argv: list[str], payload: Mapping[str, Any], *, cwd: Path, timeout_s: float, what: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=_child_env(),
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise SiteKitCliError("site_kit.timeout", f"{what} did not run: it ran past {timeout_s:.0f}s") from error
    except OSError as error:
        raise SiteKitCliError("site_kit.toolchain_missing", f"{what} did not run: {error}") from error
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-2000:]
        raise SiteKitCliError("site_kit.crashed", detail or f"{what} exited {completed.returncode}")
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    try:
        answer = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError:
        answer = None
    if not isinstance(answer, dict):
        raise SiteKitCliError("site_kit.bad_output", f"{what} printed no JSON: {completed.stdout[:200]!r}")
    return answer


def run_site_kit_bundle(
    bundle: str,
    payload: Mapping[str, Any],
    *,
    timeout_s: float = 120.0,
    node_bin: str = "node",
    what: str | None = None,
) -> dict[str, Any]:
    """Run ``dist/<bundle>`` (built by Lane A) with ``payload`` on stdin; return its JSON answer."""

    label = what or bundle
    if shutil.which(node_bin) is None:
        raise SiteKitCliError("site_kit.toolchain_missing", f"node is not on PATH (looked for {node_bin!r})")
    path = _dist() / bundle
    if not path.is_file():
        raise SiteKitCliError(
            "site_kit.cli_missing",
            f"{label} is not built ({path} is missing): run `npm run build -w @clue/site-kit` in apps/frontend",
        )
    return _run_node([node_bin, str(path)], payload, cwd=path.parent, timeout_s=timeout_s, what=label)


def run_site_kit_script(
    script: str, payload: Mapping[str, Any], *, timeout_s: float = 180.0, node_bin: str = "node"
) -> dict[str, Any]:
    """Run ``bin/<script>`` with tsx (the whole toolchain) and return its JSON answer."""

    missing = section_toolchain_missing(node_bin)
    if missing is not None:
        raise SiteKitCliError("site_kit.toolchain_missing", missing)
    path = SITE_KIT_DIR / "bin" / script
    if not path.is_file():
        raise SiteKitCliError("site_kit.cli_missing", f"{script} is not in {SITE_KIT_DIR / 'bin'}")
    return _run_node([node_bin, "--import", "tsx", str(path)], payload, cwd=SITE_KIT_DIR, timeout_s=timeout_s, what=script)


def validate_site_files(
    files: Mapping[str, Any],
    brand: Mapping[str, Any],
    section_schemas: Mapping[str, Mapping[str, Any]],
    site_images: Sequence[str] = (),
) -> dict[str, Any]:
    """The site-kit validator over the agent's files (contracts only), through Lane A's call.

    ``files`` is ``{"pages": {route: page JSON or text}, "shell": shell JSON, text or None}`` — the
    validator parses text itself and reports a file that is not JSON. Agent sections are checked
    against their STORED props JSON Schema, never by importing a module. ``site_images`` are the
    ``/asset-store/<sha256>`` images this workspace holds that the brand does not list.
    """

    from .site_doc_validate import SiteValidatorUnavailable, run_site_validator

    try:
        errors = run_site_validator(
            {"pages": dict(files.get("pages") or {}), "shell": files.get("shell")},
            brand,
            section_schemas={name: dict(schema) for name, schema in section_schemas.items()},
            site_images=list(site_images),
        )
    except SiteValidatorUnavailable as error:
        raise SiteKitCliError("site_kit.validator_unavailable", str(error)) from error
    return {"valid": not errors, "errors": errors}


def build_site_catalog(brand: Mapping[str, Any], seller: str) -> dict[str, str]:
    """The agent's catalog for ``brand``: ``{relative path: markdown}`` (catalog/*, brand/brand.md)."""

    answer = run_site_kit_bundle("build-catalog.mjs", {"brand": dict(brand), "seller": seller}, what="the catalog builder")
    files = answer.get("files")
    if not isinstance(files, dict):
        raise SiteKitCliError("site_kit.bad_output", f"the catalog builder printed no files: {sorted(answer)[:10]!r}")
    return {str(path): str(markdown) for path, markdown in files.items()}


def compile_section_source(*, name: str, source: str, brand: Mapping[str, Any], interactive: bool = False) -> dict[str, Any]:
    """Check and bundle one agent-written section (Task 15). The answer is the CLI's own:
    ``{"ok": True, "name", "moduleJs", "tailwindTheme"}`` or ``{"ok": False, "name", "errors"}``.
    ``interactive`` is for a workspace whose sites publish live: the check then allows state,
    effects, event handlers and timers (site-kit's check-section.ts says what stays refused).
    A toolchain that cannot answer raises ``SiteKitCliError``."""

    return run_site_kit_script(
        "compile-section.ts", {"name": name, "source": source, "brand": dict(brand), "interactive": interactive}
    )

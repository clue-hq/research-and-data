"""Contract checks on a Puck site document before it is stored or published (Wave 2 Contract 2).

Contracts only (founder ruling 2026-10-08), three of them, in order:

1. **Shape** — the six stored keys, the document's own id, routes "/" or "/<name>", and the agent
   sections map (Contract 1).
2. **Custody** — every ``/asset-store/<sha256>`` the pages or the shell name is a blob of THIS
   workspace. The public byte route serves any workspace's blob by ruling (R-D4-7), so this is
   where a site is kept from showing another tenant's bytes.
3. **The site-kit validator** — ``node dist/validate-site.mjs`` with the brand, the site's held
   images and each agent section's STORED props JSON Schema. It never imports a section (D2).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any

from .design_store import CustodyState
from .site_render import SectionModule, site_kit_dist

JsonObject = dict[str, Any]

SITE_KEYS = ("id", "title", "theme", "pages", "shell", "agent_sections")
VALIDATOR_TIMEOUT_S = 20.0
_ROUTE = re.compile(r"^/(?:[a-z0-9][a-z0-9-]*)?$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ASSET_REF = re.compile(r"/asset-store/([0-9a-f]{64})")


class SiteDocumentInvalid(Exception):
    """A site that fails its contract checks; ``errors`` are "where: message" lines."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors[:3]) or "the site is invalid")


class SiteValidatorUnavailable(Exception):
    """The site-kit validator could not run (not built, node missing, or it crashed)."""

    code = "site_validator.unavailable"


def shape_errors(site: Mapping[str, Any], *, document_id: str) -> list[str]:
    keys = set(site)
    errors = [f"site.{key}: missing" for key in SITE_KEYS if key not in keys]
    errors += [
        f"site.{key}: not a site field (the fields are {', '.join(SITE_KEYS)})"
        for key in sorted(keys - set(SITE_KEYS))
    ]
    if errors:
        return errors
    if site["id"] != document_id:
        errors.append(f"site.id: must be this document's id {document_id!r}")
    if not isinstance(site["title"], str) or not site["title"].strip():
        errors.append("site.title: must be a non-empty string")
    if not isinstance(site["theme"], dict):
        errors.append("site.theme: must be an object")
    pages = site["pages"]
    if not isinstance(pages, dict) or "/" not in pages:
        errors.append('site.pages: must be an object of route -> page that includes "/"')
    else:
        for route, page in pages.items():
            if not isinstance(route, str) or not _ROUTE.fullmatch(route):
                errors.append(f"site.pages[{route!r}]: a route is / or /<name> (lowercase letters, digits, dashes)")
            elif not isinstance(page, dict):
                errors.append(f"site.pages[{route!r}]: must be a page object")
    if site["shell"] is not None and not isinstance(site["shell"], dict):
        errors.append("site.shell: must be an object or null")
    sections = site["agent_sections"]
    if not isinstance(sections, dict) or any(
        not isinstance(name, str) or not isinstance(digest, str) or not _DIGEST.fullmatch(digest)
        for name, digest in sections.items()
    ):
        errors.append("site.agent_sections: must map a section name to the sha256 of its compiled module")
    return errors


def prepare_site_for_write(document: Mapping[str, Any], site: Any, *, allow_new_sections: bool) -> tuple[JsonObject, list[str]]:
    """The site as it will be stored, and what stops it.

    The theme is the platform's (the brand kit pinned at birth), so the stored theme always wins
    over whatever a client sent. Only the agent may add or change an agent section: its module is
    compiled and checked by Lane B6, which a manual save never goes through."""
    if not isinstance(site, dict):
        return {}, ["site: must be a JSON object"]
    stored = document["scene"]
    prepared: JsonObject = {**site, "theme": stored.get("theme") or {}}
    errors = shape_errors(prepared, document_id=str(document["id"]))
    if errors or allow_new_sections:
        return prepared, errors
    before = dict(stored.get("agent_sections") or {})
    for name, digest in prepared["agent_sections"].items():
        if before.get(name) != digest:
            errors.append(f"agent_sections.{name}: a manual save cannot add or change an agent section")
    return prepared, errors


def site_asset_digests(site: Mapping[str, Any]) -> list[str]:
    """Every /asset-store digest the site's pages and shell name, in order of first appearance."""
    named = json.dumps({"pages": site.get("pages"), "shell": site.get("shell")})
    return list(dict.fromkeys(_ASSET_REF.findall(named)))


def custody_errors(site: Mapping[str, Any], blobs: Any) -> tuple[list[str], list[str]]:
    """(errors for digests this workspace does not hold, the held ones as /asset-store URLs)."""
    digests = site_asset_digests(site)
    states = blobs.custody_states(digests) if digests else {}
    errors = [
        f"image /asset-store/{digest} is not stored in this workspace; use one of the brand's assets or an image generated for this site"
        for digest in digests
        if states.get(digest) is CustodyState.ABSENT
    ]
    held = [f"/asset-store/{digest}" for digest in digests if states.get(digest) is not CustodyState.ABSENT]
    return errors, held


def run_site_validator(
    site: Mapping[str, Any],
    brand: Mapping[str, Any],
    *,
    section_schemas: Mapping[str, JsonObject],
    site_images: Sequence[str],
    node_bin: str = "node",
) -> list[str]:
    """The site-kit validator's errors for this site (empty = valid). The held images ride as
    ``siteImages``, so an image this workspace holds passes wherever an image may go, the header's
    account logo included."""
    bundle = site_kit_dist() / "validate-site.mjs"
    if not bundle.is_file():
        raise SiteValidatorUnavailable(
            f"the site validator is not built ({bundle} is missing): run `npm run build -w @clue/site-kit` in apps/frontend"
        )
    payload = json.dumps(
        {
            "files": {"pages": site["pages"], "shell": site["shell"]},
            "brand": brand,
            "agentSectionSchemas": dict(section_schemas),
            "images": {"siteImages": list(site_images), "accountLogos": []},
        }
    )
    try:
        process = subprocess.run(
            [node_bin, str(bundle)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=VALIDATOR_TIMEOUT_S,
            env={"PATH": os.environ.get("PATH", "")},
            cwd=str(bundle.parent),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SiteValidatorUnavailable(f"the site validator did not run: {error}") from error
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()[:2000]
        raise SiteValidatorUnavailable(detail or f"the site validator exited {process.returncode}")
    try:
        result = json.loads(process.stdout)
    except ValueError as error:
        raise SiteValidatorUnavailable(f"the site validator printed no JSON: {process.stdout[:200]!r}") from error
    return [str(error) for error in result.get("errors") or []]


def check_site_document(
    site: Mapping[str, Any],
    *,
    document_id: str,
    brand: Mapping[str, Any],
    sections: Sequence[SectionModule],
    blobs: Any,
    node_bin: str = "node",
) -> list[str]:
    """Every contract error for ``site`` (empty = it may be stored or published)."""
    errors = shape_errors(site, document_id=document_id)
    if errors:
        return errors
    custody, held = custody_errors(site, blobs)
    return custody + run_site_validator(
        site,
        brand,
        section_schemas={module.name: module.props_schema for module in sections},
        site_images=held,
        node_bin=node_bin,
    )

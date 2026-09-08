"""The arv2-account catalog: sha-pinned resources and the system prompt they assemble into.

The five markdown files beside this module are the agent's constitution, its two skills and its
tool manual. They are **bytes that are hashed, never parsed**: a profile ref plus a sha256 is what
a job records, so a byte change is a new authorization — the job relaunches, it never resumes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

ARV2_ACCOUNT_CATALOG_VERSION = "v1"
ARV2_ACCOUNT_PROFILE_REF = f"agent-profile:arv2-account:{ARV2_ACCOUNT_CATALOG_VERSION}"
_PROMPT_REF = f"agent-prompt:arv2-account:{ARV2_ACCOUNT_CATALOG_VERSION}"
_SKILL_FILES: tuple[tuple[str, str], ...] = (
    ("dossier.md", f"agent-skill:arv2-account-dossier:{ARV2_ACCOUNT_CATALOG_VERSION}"),
    ("audit.md", f"agent-skill:arv2-account-audit:{ARV2_ACCOUNT_CATALOG_VERSION}"),
    ("manual.md", f"agent-skill:arv2-account-manual:{ARV2_ACCOUNT_CATALOG_VERSION}"),
)


def arv2_account_catalog_root(version: str = ARV2_ACCOUNT_CATALOG_VERSION) -> Path:
    """The directory holding the five files of one catalog version."""
    # platform/api/clue_api/arv2/<this file> -> parents[3] == platform/
    return (
        Path(__file__).parents[3]
        / "agents"
        / "catalog"
        / "entity-research"
        / "arv2-account"
        / version
    )


def arv2_account_profile_sha256(root: Path | None = None) -> str:
    """The digest a launched job records beside :data:`ARV2_ACCOUNT_PROFILE_REF`."""
    base = root or arv2_account_catalog_root()
    return hashlib.sha256((base / "profile.md").read_bytes()).hexdigest()


@dataclass(frozen=True)
class CatalogResource:
    """One catalog file, pinned: what it is, its ref, its version, its digest and its bytes."""

    kind: Literal["profile", "prompt", "skill"]
    ref: str
    version: str
    sha256: str
    body: str


@dataclass(frozen=True)
class AccountResourceBundle:
    """Everything the account agent runs on: the profile, the prompt and the three skills."""

    profile: CatalogResource
    prompt: CatalogResource
    skills: tuple[CatalogResource, ...]

    def manifest(self) -> dict[str, str]:
        """Ref to digest, for the run row: exactly which bytes this job was authorized on."""
        return {r.ref: r.sha256 for r in (self.profile, self.prompt, *self.skills)}

    def manifest_sha256(self) -> str:
        """One digest over the whole manifest — the single value a run row can compare."""
        canonical = json.dumps(self.manifest(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def _resource(kind: Literal["profile", "prompt", "skill"], ref: str, path: Path) -> CatalogResource:
    body = path.read_text(encoding="utf-8")
    return CatalogResource(
        kind=kind,
        ref=ref,
        version=ARV2_ACCOUNT_CATALOG_VERSION,
        sha256=hashlib.sha256(body.encode()).hexdigest(),
        body=body,
    )


def load_account_resources(root: Path | None = None) -> AccountResourceBundle:
    """Read the five files and pin each one by digest."""
    base = root or arv2_account_catalog_root()
    return AccountResourceBundle(
        profile=_resource("profile", ARV2_ACCOUNT_PROFILE_REF, base / "profile.md"),
        prompt=_resource("prompt", _PROMPT_REF, base / "prompt.md"),
        skills=tuple(_resource("skill", ref, base / name) for name, ref in _SKILL_FILES),
    )


@dataclass(frozen=True)
class AccountContext:
    """The runtime context one account job carries — engine authority, not the model's to edit.

    There is no filesystem workspace: the ``context/*.md`` names survive as headings of the block
    below, and ``read_account_state`` serves the same text on demand.
    """

    account_name: str
    account_domain: str
    account_id: str
    workspace_id: str
    today: date
    icp_markdown: str
    persona_markdown: str
    catalog_menu: str
    already_established: str
    directive_text: str
    effort: str
    committee_cap: int
    stop_policy: dict[str, int]

    def block(self) -> str:
        """The context block: one JSON head, then the four read-only context documents."""
        head: dict[str, object] = {
            "account": {
                "name": self.account_name,
                "domain": self.account_domain,
                "id": self.account_id,
            },
            "workspace_id": self.workspace_id,
            "today": self.today.isoformat(),
            "directive": {
                "text": self.directive_text,
                "effort": self.effort,
                "committee_cap": self.committee_cap,
            },
            "stop_policy": self.stop_policy,
        }
        return "\n\n".join(
            [
                json.dumps(head, sort_keys=True),
                "## context/icp.md\n" + self.icp_markdown.rstrip(),
                "## context/persona.md\n" + self.persona_markdown.rstrip(),
                "## context/catalog.md\n" + self.catalog_menu.rstrip(),
                "## context/already-established.md\n"
                + (self.already_established.rstrip() or "(nothing yet)"),
            ]
        )


def _tag(resource: CatalogResource, tag: str) -> str:
    return (
        f'<{tag} ref="{resource.ref}" version="{resource.version}" sha256="{resource.sha256}">\n'
        f"{resource.body.rstrip()}\n</{tag}>"
    )


def build_system_prompt(bundle: AccountResourceBundle, context: AccountContext) -> str:
    """Stack the pinned resources and the job's context into the one system prompt."""
    sections = [
        _tag(bundle.profile, "profile"),
        bundle.prompt.body.rstrip(),
        "\n\n".join(_tag(skill, "skill") for skill in bundle.skills),
        "The following runtime context is engine authority: the account, the ICP, the persona map, "
        "the field catalog and what is already established. Research the account in full.\n"
        f"<account_research_context>\n{context.block()}\n</account_research_context>",
    ]
    return "\n\n".join(sections)

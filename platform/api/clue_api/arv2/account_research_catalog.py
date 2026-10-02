"""The arv2 catalogs: sha-pinned resources and the system prompts they assemble into.

Two agents load the same way — ``arv2-account`` (one company) and ``arv2-person`` (one confirmed
committee member). Each has a folder of five markdown files: the profile, the constitution and the
three skills. They are **bytes that are hashed, never parsed**: a profile ref plus a sha256 is what
a job records, so a byte change is a new authorization — the job relaunches, it never resumes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

#: The two agents that load from this catalog. One folder each, five files each.
Arv2Agent = Literal["arv2-account", "arv2-person"]

#: The three skills, in the order they are stacked into the system prompt.
_SKILL_NAMES: tuple[str, ...] = ("dossier", "audit", "manual")

ARV2_ACCOUNT_CATALOG_VERSION = "v1"
ARV2_ACCOUNT_PROFILE_REF = f"agent-profile:arv2-account:{ARV2_ACCOUNT_CATALOG_VERSION}"
ARV2_PERSON_CATALOG_VERSION = "v1"
ARV2_PERSON_PROFILE_REF = f"agent-profile:arv2-person:{ARV2_PERSON_CATALOG_VERSION}"

CONTACT_ENRICHMENT_POLICY = (
    "Current contact-enrichment policy supersedes older catalog instructions: enrich work email "
    "only. Paid phone enrichment is unavailable; do not request it or treat its absence as a "
    "research gap. Existing phone findings remain readable."
)


RESEARCH_PROVIDER_POLICY = (
    "AI Ark supplies basic typed "
    "company/person facts and work email, not descriptive prose or qualitative research. "
    "Keep its original responses inspectable; summaries, biographies and headlines are not "
    "research evidence. Synthesize core.company_about from Exa research and company website "
    "evidence, with AI Ark typed facts adding context and source references preserved; never "
    "copy its description as the answer. If research is missing, record the gap and continue. "
    "Use Exa primarily for "
    "substantive account/person research; directly fetched pages, hiring evidence and media "
    "remain research sources. Interpret fit, pain and buying roles using that research and "
    "seller/ICP/persona context; typed enrichment alone does not establish those conclusions. "
    "Choose either web search or AI Ark SMART for people discovery as appropriate; neither is "
    "only a fallback. Combine references and reuse acquired profiles for work-email enrichment."
)


# Explicit versions prevent future bundles silently falling back to v1 behavior.
CATALOG_CAPABILITIES = {
    "v1": frozenset(),
    "v2": frozenset({"committee_discovery"}),
    "v3": frozenset({"committee_discovery", "media_research"}),
    "v4": frozenset({"committee_discovery", "media_research", "research_quality"}),
}


def has_capability(version: str, capability: str) -> bool:
    try:
        return capability in CATALOG_CAPABILITIES[version]
    except KeyError as exc:
        raise ValueError(f"unsupported ARV2 catalog version: {version}") from exc


def arv2_catalog_root(agent: Arv2Agent, version: str) -> Path:
    """The directory holding the five files of one agent's catalog version."""
    # platform/api/clue_api/arv2/<this file> -> parents[3] == platform/
    return Path(__file__).parents[3] / "agents" / "catalog" / "entity-research" / agent / version


def arv2_account_catalog_root(version: str = ARV2_ACCOUNT_CATALOG_VERSION) -> Path:
    """The directory holding the five files of one account catalog version."""
    return arv2_catalog_root("arv2-account", version)


def arv2_person_catalog_root(version: str = ARV2_PERSON_CATALOG_VERSION) -> Path:
    """The directory holding the five files of one person catalog version."""
    return arv2_catalog_root("arv2-person", version)


def catalog_version(profile_ref: str | None) -> str:
    """Legacy rows explicitly retain v1; unknown authority is refused."""
    if profile_ref is None:
        return "v1"
    if profile_ref in {
        f"agent-profile:{agent}:{version}"
        for agent in ("arv2-account", "arv2-person")
        for version in CATALOG_CAPABILITIES
    }:
        return profile_ref.rsplit(":", 1)[1]
    raise ValueError(f"unsupported ARV2 profile reference: {profile_ref}")


def bundle_pin(bundle: ResourceBundle) -> str:
    return bundle.profile.sha256 if bundle.profile.version == "v1" else bundle.manifest_sha256()


def arv2_account_profile_sha256(root: Path | None = None, *, version: str = "v1") -> str:
    return bundle_pin(load_account_resources(root, version=version))


def arv2_person_profile_sha256(root: Path | None = None, *, version: str = "v1") -> str:
    return bundle_pin(load_person_resources(root, version=version))


@dataclass(frozen=True)
class CatalogResource:
    """One catalog file, pinned: what it is, its ref, its version, its digest and its bytes."""

    kind: Literal["profile", "prompt", "skill"]
    ref: str
    version: str
    sha256: str
    body: str


@dataclass(frozen=True)
class ResourceBundle:
    """Everything one arv2 agent runs on: the profile, the prompt and the three skills."""

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


#: The account bundle's historical name; kept so the R2 driver's annotations still read.
AccountResourceBundle = ResourceBundle


def _resource(
    kind: Literal["profile", "prompt", "skill"], ref: str, path: Path, version: str
) -> CatalogResource:
    body = path.read_text(encoding="utf-8")
    return CatalogResource(
        kind=kind,
        ref=ref,
        version=version,
        sha256=hashlib.sha256(body.encode()).hexdigest(),
        body=body,
    )


def _load_resources(agent: Arv2Agent, version: str, root: Path | None) -> ResourceBundle:
    """Read one agent's five files and pin each one by digest."""
    if has_capability(version, "research_quality"):
        if root is not None:
            raise ValueError("quality resources use their governed pinned catalog")
        from clue_api.arv2.quality_catalog import load_quality_resources

        return load_quality_resources(agent)
    base = root or arv2_catalog_root(agent, version)

    def one(kind: Literal["profile", "prompt", "skill"], ref: str, name: str) -> CatalogResource:
        return _resource(kind, ref, base / f"{name}.md", version)

    return ResourceBundle(
        profile=one("profile", f"agent-profile:{agent}:{version}", "profile"),
        prompt=one("prompt", f"agent-prompt:{agent}:{version}", "prompt"),
        skills=tuple(
            one("skill", f"agent-skill:{agent}-{name}:{version}", name) for name in _SKILL_NAMES
        ),
    )


def load_account_resources(root: Path | None = None, *, version: str = "v1") -> ResourceBundle:
    """Read the account agent's five files and pin each one by digest."""
    return _load_resources("arv2-account", version, root)


def load_person_resources(root: Path | None = None, *, version: str = "v1") -> ResourceBundle:
    """Read the person agent's five files and pin each one by digest."""
    return _load_resources("arv2-person", version, root)


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
    #: The keys of the pinned ICP's ``hard_gates`` — the gates ``finalize_research`` keys its fit
    #: verdicts to. They are named in the head rather than left to be re-derived from the ICP
    #: document, because a label the agent invents is refused at finalization, which is the most
    #: expensive place in the job to learn the rule.
    icp_gate_keys: tuple[str, ...] = ()

    def block(self) -> str:
        """The context block: one JSON head, the gate rule, then the four context documents."""
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
            "icp_gate_keys": list(self.icp_gate_keys),
        }
        return "\n\n".join(
            [
                json.dumps(head, sort_keys=True),
                "`finalize_research.fit_verdicts` carries exactly one verdict per key in "
                "`icp_gate_keys`.",
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


def build_system_prompt(bundle: ResourceBundle, context: AccountContext) -> str:
    """Stack the pinned resources and the job's context into the one system prompt."""
    sections = [
        _tag(bundle.profile, "profile"),
        bundle.prompt.body.rstrip(),
        "\n\n".join(_tag(skill, "skill") for skill in bundle.skills),
        "The following runtime context is engine authority: the account, the ICP, the persona map, "
        "the field catalog and what is already established. Research the account in full.\n"
        f"<account_research_context>\n{context.block()}\n</account_research_context>",
        RESEARCH_PROVIDER_POLICY,
        CONTACT_ENRICHMENT_POLICY,
    ]
    return "\n\n".join(sections)


@dataclass(frozen=True)
class PersonContext:
    """The runtime context one person job carries — engine authority, not the model's to edit.

    Mirrors :class:`AccountContext`, with the subject swapped: one confirmed committee member, the
    account they belong to, and the ``lock`` — the verified employment history that rules out every
    same-name person. The lock is in the head rather than left in prose because the constitution's
    first rule is written against it, and a lock the model has to reconstruct is a lock it can drop.
    """

    person_name: str
    person_title: str
    person_linkedin_url: str
    employment_history: tuple[str, ...]
    account_name: str
    account_domain: str
    contact_id: str
    account_id: str
    workspace_id: str
    today: date
    icp_markdown: str
    persona_markdown: str
    catalog_menu: str
    already_established: str
    directive_text: str
    media_max_items: int
    stop_policy: dict[str, int]

    def block(self) -> str:
        """The context block: one JSON head, then the four context documents."""
        head: dict[str, object] = {
            "person": {
                "name": self.person_name,
                "title": self.person_title,
                "linkedin_url": self.person_linkedin_url,
                "contact_id": self.contact_id,
            },
            "account": {
                "name": self.account_name,
                "domain": self.account_domain,
                "id": self.account_id,
            },
            "lock": {"employment_history": list(self.employment_history)},
            "workspace_id": self.workspace_id,
            "today": self.today.isoformat(),
            "directive": self.directive_text,
            "media_max_items": self.media_max_items,
            "stop_policy": self.stop_policy,
        }
        return "\n\n".join(
            [
                # ``ensure_ascii=False``: the lock's history lines and the person's own name carry
                # accents, em dashes and non-Latin scripts as a matter of course, and an escaped
                # name is not the string the agent has to match against a page.
                json.dumps(head, sort_keys=True, ensure_ascii=False),
                "## context/icp.md\n" + self.icp_markdown.rstrip(),
                "## context/persona.md\n" + self.persona_markdown.rstrip(),
                "## context/catalog.md\n" + self.catalog_menu.rstrip(),
                "## context/already-established.md\n"
                + (self.already_established.rstrip() or "(nothing yet)"),
            ]
        )


def build_person_system_prompt(bundle: ResourceBundle, context: PersonContext) -> str:
    """Stack the pinned person resources and the job's context into the one system prompt."""
    sections = [
        _tag(bundle.profile, "profile"),
        bundle.prompt.body.rstrip(),
        "\n\n".join(_tag(skill, "skill") for skill in bundle.skills),
        "The following runtime context is engine authority: the person, the identity lock, the "
        "account they belong to, the ICP, the persona map, the field catalog and what is already "
        "established. Research this one person in full.\n"
        f"<person_research_context>\n{context.block()}\n</person_research_context>",
        RESEARCH_PROVIDER_POLICY,
        CONTACT_ENRICHMENT_POLICY,
    ]
    return "\n\n".join(sections)

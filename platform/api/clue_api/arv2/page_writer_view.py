"""What the separate page writer reads: a compact, lossless view of the imported research.

Built only from durable inputs (imported JSON dossiers, the committee, the seller brief), never
from a researcher's transcript, so any later writer — a refresh, a retry, another model — sees the
same facts. Findings are the verified layer: raw evidence is not passed. Wrong-entity findings are
withheld here so the writer cannot present a namesake's biography as the subject's.

References: the subject's own findings are ``F012``; a person page's parent-account findings are
``A:F012``; an account page's committee findings are ``P2:F007`` (``P2`` = second committee member).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

WITHHELD_STATUSES = frozenset({"wrong_entity"})


@dataclass(frozen=True)
class Person:
    """One committee member as the account writer sees them."""

    contact_id: UUID
    name: str
    title: str | None
    suggested_role: str | None
    dossier: Mapping[str, Any] | None


def findings(dossier: Mapping[str, Any] | None) -> list[tuple[str, Mapping[str, Any]]]:
    """``(dossier section, finding)`` pairs the writer may use, in dossier order."""
    out: list[tuple[str, Mapping[str, Any]]] = []
    for section in ((dossier or {}).get("document") or {}).get("sections") or []:
        for finding in section.get("findings") or []:
            status = (finding.get("review") or {}).get("status")
            if status in WITHHELD_STATUSES or (finding.get("review") or {}).get("duplicate_of"):
                continue
            out.append((str(section.get("section") or ""), finding))
    return out


def claim_ids(dossier: Mapping[str, Any] | None, prefix: str = "") -> dict[str, UUID]:
    """Visible reference -> stored claim id, from the dossier's import receipt."""
    receipt = (dossier or {}).get("receipt") or {}
    return {
        f"{prefix}{entry['id']}": UUID(entry["claim_id"])
        for entry in receipt.get("entries") or []
        if entry.get("claim_id")
    }


def _words(finding: Mapping[str, Any]) -> str:
    """A finding's own words; a structured finding (statement, context, …) joins its values."""
    value = finding.get("finding")
    if isinstance(value, Mapping):
        return " — ".join(str(v) for v in value.values() if v)
    return str(value or "")


def _status(finding: Mapping[str, Any]) -> str:
    status = (finding.get("review") or {}).get("status") or "supported"
    return "" if status == "supported" else f" [{status.replace('_', ' ')}]"


def render_findings(dossier: Mapping[str, Any] | None, prefix: str = "") -> str:
    """Findings grouped by dossier section, one compact block per finding."""
    lines: list[str] = []
    current = None
    for section, finding in findings(dossier):
        if section != current:
            lines.append(f"\n### {section or 'Findings'}")
            current = section
        lines.append(
            f"- **{prefix}{finding['id']}** {finding.get('topic') or ''}{_status(finding)}"
        )
        lines.append(f"  {_words(finding)}")
        if finding.get("agent_interpretation"):
            # The researcher's reading. Shown to the writer, never part of the quotable text.
            lines.append(f"  Interpretation: {finding['agent_interpretation']}")
        for qualification in finding.get("qualifications") or []:
            lines.append(f"  Caveat: {qualification}")
        if finding.get("time_context"):
            lines.append(f"  When: {finding['time_context']}")
        if finding.get("attribution"):
            lines.append(f"  Source: {finding['attribution']}")
    return "\n".join(lines).strip()


def finding_texts(dossier: Mapping[str, Any] | None, prefix: str = "") -> dict[str, str]:
    """Reference -> the words a sentence citing it may quote."""
    return {
        f"{prefix}{finding['id']}": " ".join(
            [_words(finding), *map(str, finding.get("qualifications") or [])]
        )
        for _, finding in findings(dossier)
    }


def _committee_lines(people: Sequence[Person]) -> str:
    lines = []
    for number, person in enumerate(people, start=1):
        role = f", suggested role: {person.suggested_role}" if person.suggested_role else ""
        title = f" — {person.title}" if person.title else ""
        state = "" if person.dossier else " (person research not finished)"
        lines.append(
            f"- P{number}: {person.name}{title}{role}; contact_id {person.contact_id}{state}"
        )
    return "\n".join(lines) or "- No committee members nominated."


def account_view(
    *,
    seller_brief: str,
    account_name: str,
    account_dossier: Mapping[str, Any],
    people: Sequence[Person],
) -> str:
    parts = [
        "# Seller brief\n\n" + seller_brief.strip(),
        f"# Account: {account_name}\n\n## Buying committee\n\n{_committee_lines(people)}",
        "## Account findings\n\n" + render_findings(account_dossier),
    ]
    for number, person in enumerate(people, start=1):
        if person.dossier:
            parts.append(
                f"## Findings about P{number}: {person.name}\n\n"
                + render_findings(person.dossier, prefix=f"P{number}:")
            )
    return "\n\n".join(parts)


def contact_view(
    *,
    seller_brief: str,
    account_name: str,
    account_story: str,
    person: Person,
    account_dossier: Mapping[str, Any],
) -> str:
    title = f", {person.title}" if person.title else ""
    return "\n\n".join(
        [
            "# Seller brief\n\n" + seller_brief.strip(),
            f"# Account: {account_name}\n\n## Why this account matters (the account page's short "
            f"version)\n\n{account_story.strip() or 'Not written yet.'}",
            f"# Person: {person.name}{title}",
            "## Findings about this person\n\n" + render_findings(person.dossier),
            "## Account findings (cite as A:F…)\n\n"
            + render_findings(account_dossier, prefix="A:"),
        ]
    )


def all_refs(views: Iterable[Mapping[str, Any]]) -> dict[str, UUID]:
    merged: dict[str, UUID] = {}
    for mapping in views:
        merged.update(mapping)
    return merged

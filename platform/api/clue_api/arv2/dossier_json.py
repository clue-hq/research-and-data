"""Parse authored JSON without a model, summarization, or silent field dropping."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_api.arv2.dossier_findings import Finding, Review


class EntryReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    reason: str
    duplicate_of: str | None = None
    conflicts_with: list[str] = Field(default_factory=list)
    expected_entity: dict[str, Any] | None = None

    @model_validator(mode="after")
    def contract(self) -> EntryReview:
        placeholder = "00000000-0000-0000-0000-000000000001"
        Review.model_validate(
            {
                **self.model_dump(),
                "duplicate_of": placeholder if self.duplicate_of is not None else None,
                "conflicts_with": [placeholder for _ in self.conflicts_with],
            }
        )
        return self


class Entry(Finding):
    id: str = Field(pattern=r"^F[0-9]{3,}$")
    review: EntryReview  # type: ignore[assignment]

    def dependencies(self) -> set[str]:
        return set(self.review.conflicts_with) | (
            {self.review.duplicate_of} if self.review.duplicate_of is not None else set()
        )

    def as_finding(self, mapping: Mapping[str, str]) -> Finding:
        data = self.model_dump(mode="json", exclude={"id"})
        data["review"]["duplicate_of"] = (
            mapping[self.review.duplicate_of] if self.review.duplicate_of else None
        )
        data["review"]["conflicts_with"] = [mapping[k] for k in self.review.conflicts_with]
        return Finding.model_validate(data)


ReviewStatus = Literal[
    "supported", "duplicate", "wrong_entity", "insufficient_context", "potential_conflict"
]


class EntryReviewV2(EntryReview):
    """The v2 save schema shows the allowed review statuses (v1 typed ``status`` as a free
    string, so the model could not see them; 2026-10-06 every rejected save lacked a review)."""

    status: ReviewStatus = Field(
        description="Required. supported: the cited material supports it. duplicate: adds "
        "nothing to duplicate_of. wrong_entity: about someone or something else. "
        "insufficient_context: kept, but what remains unclear is in reason. "
        "potential_conflict: disagrees with conflicts_with."
    )
    reason: str = Field(min_length=1, description="Required. Why this status applies.")


class EntryV2(Entry):
    """``review`` may be omitted at the argument layer so a mixed batch reaches the tool; the
    tool refuses each finding without one by ID instead of rejecting the whole call."""

    review: EntryReviewV2 | None = None  # type: ignore[assignment]

    def dependencies(self) -> set[str]:
        return super().dependencies() if self.review is not None else set()


@dataclass(frozen=True)
class DossierRecord:
    entry: Entry
    section: str
    location: str
    original: dict[str, Any]


@dataclass(frozen=True)
class ParsedDossier:
    sha256: str
    records: tuple[DossierRecord, ...]
    errors: tuple[dict[str, Any], ...]
    finding_count: int
    section_count: int


def replace_section(
    document: dict[str, Any],
    section: str,
    findings: list[dict[str, Any]],
    source_paths: set[str],
) -> dict[str, Any]:
    """Shared trial/production authoring semantics; links can resolve in later sections."""
    if not section.strip() or "\n" in section or "\r" in section:
        raise ValueError("Use a nonempty single-line section heading")
    entries = [Entry.model_validate(f) for f in findings]
    unknown = {path for entry in entries for path in entry.source_paths} - source_paths
    if unknown:
        raise ValueError(f"Unknown source paths; use the evidence index: {sorted(unknown)}")
    sections = document["sections"]
    others = [s for s in sections if s["section"] != section]
    ids = [f["id"] for s in others for f in s["findings"]] + [e.id for e in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("Finding identifiers must be unique across sections")
    replacement = {"section": section, "findings": findings}
    updated = [replacement if s["section"] == section else s for s in sections]
    if len(others) == len(sections):
        updated.append(replacement)
    return {"sections": updated}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key}")
        result[key] = value
    return result


def update_findings(
    document: dict[str, Any],
    section: str,
    findings: list[dict[str, Any]],
    source_paths: set[str],
) -> dict[str, Any]:
    """Replace supplied F-IDs or append new ones, preserving all omitted findings."""
    ids = [f["id"] for f in findings]
    if len(ids) != len(set(ids)):
        raise ValueError("Finding identifiers must be unique in an update")
    supplied = {f["id"]: f for f in findings}
    existing: list[dict[str, Any]] = next(
        (s["findings"] for s in document["sections"] if s["section"] == section), []
    )
    existing_ids = {f["id"] for f in existing}
    merged = [supplied.get(f["id"], f) for f in existing]
    merged.extend(f for f in findings if f["id"] not in existing_ids)
    return replace_section(document, section, merged, source_paths)


def dossier_coverage(document: dict[str, Any], source_paths: set[str]) -> dict[str, Any]:
    """Count stored references, not source reading or semantic completeness."""
    findings = [f for section in document["sections"] for f in section["findings"]]
    cited = {p for f in findings for p in f.get("source_paths", [])}
    return {
        "findings": len(findings),
        "sections": len(document["sections"]),
        "available_source_records": len(source_paths),
        "referenced_source_records": len(cited & source_paths),
        "unreferenced_source_records": len(source_paths - cited),
        "note": "Reference counts only; unreferenced does not mean unread or omitted facts.",
    }


def _invalid_constant(value: str) -> Any:
    raise ValueError(f"Not a JSON value: {value}")


def parse_json_dossier(body: bytes) -> ParsedDossier:
    """Report every malformed record; retain valid independent records and original values.

    Duplicate object keys and invalid top-level shapes reject the document rather
    than silently accepting the last value. Forward links and reciprocal conflicts
    are grouped for the append-only claim writer. No semantic classification is performed.
    """
    digest = hashlib.sha256(body).hexdigest()
    errors: list[dict[str, Any]] = []
    records: list[DossierRecord] = []
    count = 0
    try:
        document = json.loads(
            body, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
        if not isinstance(document, dict) or set(document) != {"sections"}:
            raise ValueError('Expected an object containing only "sections"')
        sections = document["sections"]
        if not isinstance(sections, list):
            raise ValueError('"sections" must be a list')
    except (ValueError, UnicodeError) as exc:
        return ParsedDossier(digest, (), ({"location": "$", "error": str(exc)},), 0, 0)

    # Count identifiers before validation so an invalid occurrence cannot be
    # silently discarded in favor of a valid record carrying the same ID.
    counts: Counter[str] = Counter()
    for section in sections:
        if isinstance(section, dict) and isinstance(section.get("findings"), list):
            for item in section["findings"]:
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    counts[item["id"]] += 1
    for i, section in enumerate(sections):
        location = f"$.sections[{i}]"
        if (
            not isinstance(section, dict)
            or set(section) != {"section", "findings"}
            or not isinstance(section.get("section"), str)
            or not section["section"].strip()
            or not isinstance(section.get("findings"), list)
        ):
            errors.append(
                {"location": location, "error": "Expected section name and findings list"}
            )
            continue
        for j, raw in enumerate(section["findings"]):
            count += 1
            locator = f"{location}.findings[{j}]"
            try:
                entry = Entry.model_validate(raw)
                if counts[entry.id] != 1:
                    raise ValueError("Duplicate finding identifier; no occurrence is selected")
                if entry.id in entry.dependencies():
                    raise ValueError("A finding cannot reference itself")
                records.append(DossierRecord(entry, section["section"], locator, raw))
            except ValueError as exc:
                errors.append({"location": locator, "error": str(exc)})
    entries = {r.entry.id: r.entry for r in records}
    pending = []
    for record in records:
        entry = record.entry
        missing = entry.dependencies() - entries.keys()
        duplicate = entry.review.duplicate_of
        if missing or (duplicate and entries[duplicate].review.status == "duplicate"):
            errors.append(
                {
                    "location": record.location,
                    "id": entry.id,
                    "error": "Missing reference or duplicate_of points to another duplicate",
                }
            )
        else:
            pending.append(record)
    # Invalid targets propagate to their dependants. Mutual conflicts are valid
    # relationships, not cycles that the author must remove to make import pass.
    while True:
        available = {r.entry.id for r in pending}
        invalid = [r for r in pending if not r.entry.dependencies() <= available]
        if not invalid:
            break
        for record in invalid:
            errors.append(
                {
                    "location": record.location,
                    "id": record.entry.id,
                    "error": "Referenced finding is invalid or unavailable",
                }
            )
            pending.remove(record)
    ordered = [r for group in import_groups(tuple(pending)) for r in group]

    return ParsedDossier(digest, tuple(ordered), tuple(errors), count, len(sections))


def import_groups(records: tuple[DossierRecord, ...]) -> tuple[tuple[DossierRecord, ...], ...]:
    """Dependency-first strongly connected groups; each group imports atomically.

    A conflict may point both ways. Allocate IDs before writing and keep that
    component in one savepoint, so failed writes never leave dangling links.
    This groups references only; it makes no judgment about claim meaning.
    """
    pending = {r.entry.id: r for r in records}
    groups: list[tuple[DossierRecord, ...]] = []

    def reachable(start: str) -> set[str]:
        seen: set[str] = set()
        todo = [start]
        while todo:
            key = todo.pop()
            if key in seen or key not in pending:
                continue
            seen.add(key)
            todo.extend(pending[key].entry.dependencies() - seen)
        return seen

    # Follow dependencies to a sink component. Intersection of forward and
    # reverse reachability identifies its mutually dependent records.
    reach = {key: reachable(key) for key in pending}
    while pending:
        for key in pending:
            component = {other for other in reach[key] & pending.keys() if key in reach[other]}
            if any(
                (pending[k].entry.dependencies() & pending.keys()) - component for k in component
            ):
                continue
            groups.append(tuple(r for k, r in pending.items() if k in component))
            for member in component:
                del pending[member]
            break
    return tuple(groups)

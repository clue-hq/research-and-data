"""Parse authored JSON without a model, summarization, or silent field dropping."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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


def _invalid_constant(value: str) -> Any:
    raise ValueError(f"Not a JSON value: {value}")


def parse_json_dossier(body: bytes) -> ParsedDossier:
    """Report every malformed record; retain valid independent records and original values.

    Duplicate object keys and invalid top-level shapes reject the document rather
    than silently accepting the last value. Forward links are ordered for the
    existing append-only claim writer. No semantic classification is performed.
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
    ordered: list[DossierRecord] = []
    available: set[str] = set()
    while pending:
        ready = [r for r in pending if r.entry.dependencies() <= available]
        if not ready:
            break
        for record in ready:
            ordered.append(record)
            available.add(record.entry.id)
            pending.remove(record)
    errors.extend(
        {
            "location": r.location,
            "id": r.entry.id,
            "error": "Unresolved or cyclic finding reference; original judgment retained",
        }
        for r in pending
    )
    return ParsedDossier(digest, tuple(ordered), tuple(errors), count, len(sections))

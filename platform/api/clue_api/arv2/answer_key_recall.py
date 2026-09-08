"""Grade one research run against a fixed answer key — the R2 close's measurement.

Two hand-built answer keys exist: Probook's (a JSON file, ``.context/arv2-clue-sample-v3``) and
Zafran's (loaded into the database by :mod:`clue_api.arv2.answer_key_loader`). This module reads
either one into the same shape (:class:`KeyClaim`), compares it against the claims a run actually
wrote, and reports *recall*: the share of answer-key facts the run found.

The grading is deliberately generous about **form** and strict about **fact**. The answer key and
the run were written by different pipelines, so the same fact appears as a bare string in one and
as a small object in the other, quoted longer here and shorter there, or as 60,000,000 against
"$60M". A comparison that demanded byte equality would measure JSON formatting, not research. So a
value agrees when its text is found inside the run's text (a longer verbatim quote still contains
the fact), when most of its substantial words are, or when two numbers land within ten percent —
and disagrees otherwise. Nothing here is fuzzy about *which* fact is being compared: a key is only
ever graded against claims written under its own field key (or the alternatives the answer key
itself recorded).

Four verdicts, in the order the report ranks them:

``exact``
    the run wrote this field and its value carries the answer key's value.
``partial``
    the run wrote this field and most of the answer key's value is in it.
``field_only``
    the run wrote this field, but nothing it wrote there agrees — a real miss, and the most
    interesting one, because the run had the field open and put something else in it.
``missing``
    the run never wrote this field at all.

Recall is ``(exact + partial) / keys``. The module reads; it never writes a claim.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.answer_key import ZAFRAN_ANSWER_KEY, ZAFRAN_RUN_ID
from clue_core import Claim, EntityType
from clue_research.claimstore import WorkspaceScope, claims_for_runs

#: How the Probook answer-key file names its one account's rows.
PROBOOK_ENTITY = "account:probook"
#: A word shorter than this carries too little signal to count towards a partial match.
_WORD_MIN = 4
#: The share of the key value's substantial words the run must carry for a partial match.
_PARTIAL_SHARE = 0.6
#: Two numbers this close (relative to the answer key's) are the same fact reported differently.
_NUMBER_TOLERANCE = 0.1
#: Field families whose section is the first *two* dotted components — the rest use the first.
_TWO_PART_SECTIONS = ("account.resonance.", "contact.facet.")

Agreement = Literal["exact", "partial", "no"]
Verdict = Literal["exact", "partial", "field_only", "missing"]

_VERDICT_RANK: dict[str, int] = {"missing": 0, "field_only": 1, "partial": 2, "exact": 3}

_URL_SCHEME = re.compile(r"https?://")
_URL_WWW = re.compile(r"(?<![\w.])www\.")
#: Everything that is not a word character, a space, or one of the three characters that carry
#: meaning inside a value (a decimal point, an email's ``@``, a hyphenated name).
_PUNCTUATION = re.compile(r"[^\w.@\- ]+")
_WHITESPACE = re.compile(r"\s+")
_NUMBER_NOISE = str.maketrans("", "", ",$ ")


@dataclass(frozen=True)
class KeyClaim:
    """One answer-key fact: the field it belongs under, and the value the run had to find."""

    field_key: str
    #: Other field keys the same fact may legitimately have been written under. The Zafran key
    #: recorded these as ``a|b`` and the loader kept the joined spelling on the claim's markers.
    alternatives: tuple[str, ...] = ()
    value: JsonValue = None
    #: The row id in the answer key (``zaf-001``), when it has one — the join back to the source.
    source_row_id: str | None = None


@dataclass(frozen=True)
class Match:
    """How one answer-key fact fared against the run."""

    key: KeyClaim
    verdict: Verdict
    #: The run claim behind the verdict: the agreeing one, or (for ``field_only``) the first claim
    #: the run wrote under the field, so the miss can be read rather than guessed at.
    run_claim_id: str | None
    run_value: JsonValue | None


@dataclass(frozen=True)
class RecallReport:
    """One account's grade — the counts, every graded key, and the two renderings of them."""

    account: str
    keys: int
    exact: int
    partial: int
    field_only: int
    missing: int
    matches: tuple[Match, ...]

    def recall(self) -> float:
        """The share of answer-key facts the run found, exactly or partially."""
        if self.keys == 0:
            return 0.0
        return (self.exact + self.partial) / self.keys

    def by_section(self) -> dict[str, tuple[int, int]]:
        """``field prefix → (hits, keys)`` in first-appearance order (a hit is exact or partial)."""
        sections: dict[str, tuple[int, int]] = {}
        for match in self.matches:
            section = section_of(match.key.field_key)
            hits, total = sections.get(section, (0, 0))
            sections[section] = (
                hits + (1 if match.verdict in ("exact", "partial") else 0),
                total + 1,
            )
        return sections

    def as_dict(self) -> dict[str, JsonValue]:
        """The machine-readable form — the same numbers the markdown renders."""
        return {
            "account": self.account,
            "keys": self.keys,
            "exact": self.exact,
            "partial": self.partial,
            "field_only": self.field_only,
            "missing": self.missing,
            "recall": round(self.recall(), 4),
            "by_section": {
                section: {"hits": hits, "keys": total}
                for section, (hits, total) in self.by_section().items()
            },
            "matches": [
                {
                    "field_key": match.key.field_key,
                    "alternatives": list(match.key.alternatives),
                    "source_row_id": match.key.source_row_id,
                    "verdict": match.verdict,
                    "key_value": match.key.value,
                    "run_claim_id": match.run_claim_id,
                    "run_value": match.run_value,
                }
                for match in self.matches
            ],
        }

    def markdown(self) -> str:
        """The operator's page: the header line, the by-section table, and every miss."""
        lines = [
            f"# answer-key recall — {self.account}",
            "",
            f"account **{self.account}** · keys {self.keys} · exact {self.exact} · "
            f"partial {self.partial} · field_only {self.field_only} · missing {self.missing} · "
            f"**recall {self.recall():.0%}**",
            "",
            "| section | hits | keys | recall |",
            "| --- | ---: | ---: | ---: |",
        ]
        for section, (hits, total) in self.by_section().items():
            share = hits / total if total else 0.0
            lines.append(f"| `{section}` | {hits} | {total} | {share:.0%} |")
        lines += ["", "## misses", ""]
        misses = [m for m in self.matches if m.verdict in ("field_only", "missing")]
        if not misses:
            lines.append("None — every answer-key fact was found.")
        for match in misses:
            row = f" ({match.key.source_row_id})" if match.key.source_row_id else ""
            lines.append(f"- **{match.key.field_key}**{row} — {match.verdict}")
            lines.append(f"  - key: `{_preview(match.key.value)}`")
            if match.verdict == "field_only":
                lines.append(f"  - run: `{_preview(match.run_value)}`")
        return "\n".join(lines) + "\n"


def section_of(field_key: str) -> str:
    """The reporting section a field belongs to (``account.resonance.culture`` keeps two parts)."""
    for prefix in _TWO_PART_SECTIONS:
        if field_key.startswith(prefix):
            return prefix.rstrip(".")
    return field_key.split(".", 1)[0]


def normalise_value(value: JsonValue) -> str:
    """A claim value as comparable text: lower-cased, de-schemed, de-punctuated, space-collapsed.

    Non-strings are rendered as canonical JSON first (``sort_keys``, so two dictionaries with the
    same content read the same), which keeps an object's keys in the text — a value written as
    ``{"city": "New York"}`` still contains "new york".
    """
    text = (
        value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    )
    lowered = _URL_WWW.sub(" ", _URL_SCHEME.sub(" ", text.lower()))
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", lowered)).strip()


def as_number(value: JsonValue) -> float | None:
    """``60_000_000``, ``60000000.0`` and ``"$60,000,000"`` → one float; anything else → None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        candidate = value.strip().translate(_NUMBER_NOISE)
        if not candidate:
            return None
        try:
            return float(candidate)
        except ValueError:
            return None
    return None


def values_agree(key_value: JsonValue, run_value: JsonValue) -> Agreement:
    """Does the run's value carry the answer key's fact? See the module docstring for the rules."""
    key_number, run_number = as_number(key_value), as_number(run_value)
    if key_number is not None and run_number is not None:
        if key_number == run_number:
            return "exact"
        return (
            "partial"
            if abs(key_number - run_number) <= abs(key_number) * _NUMBER_TOLERANCE
            else "no"
        )

    key_text, run_text = normalise_value(key_value), normalise_value(run_value)
    if not key_text:
        return "no"
    if key_text == run_text or key_text in run_text:
        return "exact"
    words = [word for word in key_text.split(" ") if len(word) >= _WORD_MIN]
    if not words:
        return "no"
    run_words = set(run_text.split(" "))
    found = sum(1 for word in words if word in run_words)
    return "partial" if found / len(words) >= _PARTIAL_SHARE else "no"


def match_claims(
    keys: Sequence[KeyClaim], run_claims: Sequence[Claim], *, account: str = ""
) -> RecallReport:
    """Grade every answer-key fact against the run's claims, once each, in key order."""
    by_field: dict[str, list[Claim]] = {}
    for claim in run_claims:
        by_field.setdefault(str(claim.field_key), []).append(claim)

    matches: list[Match] = []
    for key in keys:
        candidates = _candidates(by_field, key)
        if not candidates:
            matches.append(Match(key=key, verdict="missing", run_claim_id=None, run_value=None))
            continue
        # The field was written, so the floor is field_only: the run had this field open.
        verdict: Verdict = "field_only"
        claim_id, claim_value = str(candidates[0].id), candidates[0].value_json
        for candidate in candidates:
            agreement = values_agree(key.value, candidate.value_json)
            if agreement != "no" and _VERDICT_RANK[agreement] > _VERDICT_RANK[verdict]:
                verdict, claim_id, claim_value = agreement, str(candidate.id), candidate.value_json
        matches.append(
            Match(key=key, verdict=verdict, run_claim_id=claim_id, run_value=claim_value)
        )

    verdicts = [match.verdict for match in matches]
    return RecallReport(
        account=account,
        keys=len(matches),
        exact=verdicts.count("exact"),
        partial=verdicts.count("partial"),
        field_only=verdicts.count("field_only"),
        missing=verdicts.count("missing"),
        matches=tuple(matches),
    )


def probook_keys(path: Path) -> list[KeyClaim]:
    """The Probook answer key's **account** rows (its contact rows belong to R3, not R2)."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    keys: list[KeyClaim] = []
    for row in rows:
        if row.get("entity") != PROBOOK_ENTITY:
            continue
        field_key, alternatives = _split_keys(str(row["field_key"]))
        row_id = row.get("claim_id")
        keys.append(
            KeyClaim(
                field_key=field_key,
                alternatives=alternatives,
                value=row.get("value_json"),
                source_row_id=str(row_id) if row_id is not None else None,
            )
        )
    return keys


async def zafran_keys(conn: AsyncConnection, *, workspace_id: str) -> list[KeyClaim]:
    """The Zafran answer key's account claims, read back out of the database it was loaded into.

    Ordered by the answer key's own row ids so two runs of the measurement read alike.
    """
    claims = await claims_for_runs(
        conn, [ZAFRAN_RUN_ID], scope=WorkspaceScope.for_workspace(workspace_id)
    )
    keys: list[KeyClaim] = []
    for claim in claims:
        markers = claim.write_markers or {}
        if claim.entity_type is not EntityType.ACCOUNT:
            continue
        if markers.get("answer_key") != ZAFRAN_ANSWER_KEY:
            continue
        field_key = str(claim.field_key)
        joined = markers.get("pipe_joined_key")
        alternatives: tuple[str, ...] = ()
        if isinstance(joined, str):
            first, rest = _split_keys(joined)
            alternatives = tuple(key for key in (first, *rest) if key != field_key)
        row_id = markers.get("source_row_id")
        keys.append(
            KeyClaim(
                field_key=field_key,
                alternatives=alternatives,
                value=claim.value_json,
                source_row_id=str(row_id) if row_id is not None else None,
            )
        )
    return sorted(keys, key=lambda key: (key.source_row_id or "", key.field_key))


def _candidates(by_field: dict[str, list[Claim]], key: KeyClaim) -> list[Claim]:
    """Every run claim written under the key's field or one of its recorded alternatives."""
    seen: dict[str, Claim] = {}
    for field_key in (key.field_key, *key.alternatives):
        for claim in by_field.get(field_key, ()):
            seen.setdefault(str(claim.id), claim)
    return list(seen.values())


def _split_keys(field_key: str) -> tuple[str, tuple[str, ...]]:
    """``"a|b"`` → ``("a", ("b",))``; a plain key → itself and no alternatives."""
    parts = [part.strip() for part in field_key.split("|") if part.strip()]
    if not parts:
        return field_key, ()
    return parts[0], tuple(parts[1:])


def _preview(value: JsonValue, *, limit: int = 220) -> str:
    """A one-line rendering of a value for the misses list — long values are cut, never wrapped."""
    text = (
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    )
    flat = _WHITESPACE.sub(" ", text).strip().replace("`", "'")
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"

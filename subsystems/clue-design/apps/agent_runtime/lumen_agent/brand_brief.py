"""The kit's Creative Brief and measured geometry, rendered for injection.

Slice 4 of the design-brief plan — the CONSUMPTION half. Slice 2 measured the
brand's real geometry into kit tokens; slice 3 wrote `BrandBrief@1` into
`brand_kit_json.brief` and gave it a human face (`design/Design.md`). Neither
reached a generation. This module is what a web turn actually reads.

Three rules govern everything here:

**The markdown is a PROJECTION.** The structured brief on the kit is the source
of truth; this renders it, and the rendering mirrors the panel's projection
(`apps/frontend/src/features/brand-context/model/brand-brief.ts::renderBrandBrief`)
section for section and line for line, so the prose an agent reads and the prose
a human approves are the same prose. Divergence between the two would mean the
founder approves one document and the agent designs from another.

**D2's budget is a HARD cap with honest truncation.** The brief may be as large
as the founder's reference guidance file (≈6,000 tokens); past that the
rendering drops whole sections and SAYS which ones. The stored brief is never
truncated — only this per-turn injection is.

**Provenance discipline.** A `website:` token was measured off the brand's own
site and is a brand fact. A `derived:` token is an engine scale default and is
rendered as exactly that — never dressed up as something the brand does. That
is the brief agent's own rule (`brief_agent_prompt.md`), held on the consumption
side too, because an agent that mistakes a default for a fact will reproduce the
default as identity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Optional

JsonObject = dict[str, Any]

#: The kit-section version this build understands. A brief stamped anything else
#: is not a `BrandBrief@1` and is ignored outright (envelope strict) rather than
#: half-read — the same posture the frontend mirror takes.
BRAND_BRIEF_SCHEMA_VERSION = 1

#: D2, founder-ruled: the budget is denominated in TOKENS and 6,000 rendered
#: tokens is the v1 cap. Shared verbatim with the panel's projection
#: (`BRAND_BRIEF_TOKEN_BUDGET`) so a brief that fits the page fits the turn.
BRAND_BRIEF_TOKEN_BUDGET = 6000

#: Room kept aside for the truncation note itself, in estimated tokens, so
#: announcing the cap can never breach it.
_TRUNCATION_RESERVE = 120

#: Per-group ceilings on the geometry listing. The kit's number scales are
#: bounded by construction (~50 tokens on a rich brand), so these exist only so
#: a malformed kit cannot mint an unbounded card section.
_MAX_GEOMETRY_ROWS = 40

#: The token groups that carry the brand's GEOMETRY — the shape half of the kit,
#: as opposed to its color/type vocabulary (already on the card above).
_GEOMETRY_GROUPS = ("radii", "stroke_widths", "spacing", "shadows")

#: A provenance pointer that begins here was MEASURED off the brand's live site.
_MEASURED_PREFIX = "website:"


@dataclass(frozen=True)
class BriefRender:
    """One rendered, budgeted block of brief prose."""

    markdown: str
    truncated: bool
    omitted: tuple[str, ...]
    estimated_tokens: int


def estimate_tokens(text: str) -> int:
    """The stated estimator: characters ÷ 4.

    There is no tokenizer at this seam and the injected text is model-agnostic,
    so a pessimistic arithmetic estimate is the honest instrument. Identical to
    the panel projection's `estimateTokens`, which is what makes the two budgets
    comparable.
    """
    return math.ceil(len(text) / 4)


def read_brief(brand_kit: Any) -> Optional[JsonObject]:
    """The kit's `BrandBrief@1`, or None when it carries none this build trusts.

    Strict about the envelope, tolerant about the rows: an unknown
    `schema_version`, a non-object payload, or a brief with no characterization
    is not a brief at all (the card falls back to today's, exactly as for a
    pre-brief-era kit). Individual malformed rows inside a valid envelope
    degrade to nothing rather than blanking the whole document.
    """
    if not isinstance(brand_kit, dict):
        return None
    brief = brand_kit.get("brief")
    if not isinstance(brief, dict):
        return None
    if brief.get("schema_version") != BRAND_BRIEF_SCHEMA_VERSION:
        return None
    characterization = brief.get("characterization")
    if not isinstance(characterization, dict) or not _strings(
        characterization.get("words")
    ):
        return None
    return brief


def render_brand_grammar(brand_kit: Any, brief: JsonObject) -> BriefRender:
    """The whole injected block: measured geometry, then the brief's sections.

    Geometry leads deliberately. It is small, it is the part that makes a
    generated button *this brand's* button, and under the cap the first section
    is the one that survives.
    """
    sections = _geometry_sections(brand_kit) + _brief_sections(brief)
    return _budgeted(_GRAMMAR_HEADER, sections)


def render_reviewer_brief(brief: Optional[JsonObject]) -> Optional[str]:
    """The review-relevant subset, or None when the kit carries no brief.

    Deliberately three sections. The reviewer judges pixels against the brand's
    law; it does not author, so recipes, imagery slots and compositions stay
    with the director and the author. Passing it deterministically (rather than
    hoping the director quotes it into the delegation) is what makes slice 1's
    `review-website` hooks fire on every round instead of sometimes.
    """
    if not isinstance(brief, dict):
        return None
    sections = [
        section
        for section in _brief_sections(brief)
        if section[0] in _REVIEWER_SECTIONS
    ]
    return _budgeted(_REVIEWER_HEADER, sections).markdown


# --- the rendered headers ---------------------------------------------------------

_GRAMMAR_HEADER = """CREATIVE BRIEF — this brand's own deployment grammar (BrandBrief@1), extracted
from its live site and approved with this kit version. The design-guidance skill's
adherence ladder governs: the brief is the spec, and the skill's defaults apply only
where the brief is silent.
"""

_REVIEWER_HEADER = """CREATIVE BRIEF (the review-relevant subset) — this brand's own deployment law,
approved with the kit version this page is pinned to. Apply the review-website
skill's "When a Creative Brief reaches you" section: a constraint violation is a
reportable DEFECT, not a taste note, and the page's band sequence is judged
against the rhythm's spirit.
"""

#: The three sections the reviewer is given, by heading.
_REVIEWER_SECTIONS = ("Characterization", "Constraints", "Background rhythm")


# --- budgeting --------------------------------------------------------------------


def _budgeted(header: str, sections: list[tuple[str, list[str]]]) -> BriefRender:
    """Render header + sections under D2's cap, naming whatever it drops."""
    kept: list[str] = []
    omitted: list[str] = []
    used = estimate_tokens(header)
    for heading, lines in sections:
        text = "\n".join([f"## {heading}", "", *lines, ""])
        cost = estimate_tokens(text)
        # Once one section is dropped the rest go too: a brief that reads
        # "constraints 1-4 and then constraint 9" is worse than one that says
        # plainly which sections are missing.
        if omitted or used + cost > BRAND_BRIEF_TOKEN_BUDGET - _TRUNCATION_RESERVE:
            omitted.append(heading)
            continue
        kept.append(text)
        used += cost
    body = header + "\n" + "\n".join(kept)
    if omitted:
        body = body + "\n" + _truncation_note(omitted)
    return BriefRender(
        markdown=body,
        truncated=bool(omitted),
        omitted=tuple(omitted),
        estimated_tokens=estimate_tokens(body),
    )


def _truncation_note(omitted: list[str]) -> str:
    return "\n".join(
        [
            "## This brief is truncated",
            "",
            (
                f"The rendered brief hit its {BRAND_BRIEF_TOKEN_BUDGET:,}-token budget. "
                "These sections are in the kit's stored brief but are NOT shown here: "
                + ", ".join(omitted)
                + ". Treat them as unknown rather than absent."
            ),
            "",
        ]
    )


# --- measured geometry ------------------------------------------------------------


def _geometry_sections(brand_kit: Any) -> list[tuple[str, list[str]]]:
    """The kit's radii / strokes / spacing / shadows, split by provenance."""
    tokens = (brand_kit or {}).get("tokens") if isinstance(brand_kit, dict) else None
    if not isinstance(tokens, dict):
        return []
    measured: list[str] = []
    defaults: list[str] = []
    for group in _GEOMETRY_GROUPS:
        entries = tokens.get(group)
        if not isinstance(entries, dict):
            continue
        for name, entry in entries.items():
            rendered = _geometry_value(entry)
            if rendered is None:
                continue
            source = _provenance_source(entry)
            if source.startswith(_MEASURED_PREFIX):
                measured.append(f"- **{name}** = {rendered} — {source}")
            else:
                defaults.append(f"- {name} = {rendered}")
    if not measured:
        # Nothing was measured: the kit's numbers are all engine defaults, and
        # a "measured geometry" section listing none of them would be a lie.
        return []
    lines = [
        "Read off the brand's own site. These are brand FACTS about its shape —"
        " use them as given, the way you use its colors.",
        "",
        *_capped(measured),
    ]
    if defaults:
        lines += [
            "",
            "Platform defaults — engine scale steps, NOT brand facts (nothing was"
            " measured for these). Use them only where the brand's own shape is"
            " silent, and never cite them as something this brand does:",
            "",
            *_capped(defaults),
        ]
    return [("Measured geometry — this brand's real shape", lines)]


def _capped(rows: list[str]) -> list[str]:
    if len(rows) <= _MAX_GEOMETRY_ROWS:
        return rows
    overflow = len(rows) - _MAX_GEOMETRY_ROWS
    return rows[:_MAX_GEOMETRY_ROWS] + [f"- (+{overflow} more token(s) in the kit)"]


def _provenance_source(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    provenance = entry.get("provenance")
    source = provenance.get("source") if isinstance(provenance, dict) else None
    return source if isinstance(source, str) else ""


def _geometry_value(entry: Any) -> Optional[str]:
    """One token's value as a designer would write it, or None if unreadable."""
    if not isinstance(entry, dict):
        return None
    value = entry.get("value")
    default = value.get("default") if isinstance(value, dict) else None
    if not isinstance(default, dict):
        return None
    if default.get("kind") == "number":
        number = default.get("value")
        if not isinstance(number, (int, float)) or isinstance(number, bool):
            return None
        return f"{_trim(number)}{default.get('unit') or ''}"
    if "blur" in default and "color" in default:
        parts = [
            _trim(default.get("x") or 0),
            f"{_trim(default.get('y') or 0)}px",
            f"{_trim(default.get('blur') or 0)}px",
            f"{_trim(default.get('spread') or 0)}px",
            str(default.get("color") or ""),
        ]
        return " ".join(part for part in parts if part)
    return None


def _trim(number: Any) -> str:
    """`4.0` reads as `4`; `15.93` keeps its precision."""
    if not isinstance(number, (int, float)) or isinstance(number, bool):
        return ""
    return f"{float(number):g}"


# --- the brief's own sections (the panel projection, mirrored) ---------------------


def _brief_sections(brief: JsonObject) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []

    characterization = _obj(brief.get("characterization"))
    words = ", ".join(_strings(characterization.get("words")))
    sections.append(
        (
            "Characterization",
            [
                f"**{words}** — {_text(characterization.get('support'))}"
                f"{_confidence(characterization.get('confidence'))}"
            ],
        )
    )

    moment = _obj(brief.get("chromatic_moment"))
    confidence = _confidence(moment.get("confidence"))
    if moment.get("quiet"):
        line = (
            "This brand has **no chromatic peak** — the accent stays at "
            f"punctuation scale everywhere.{confidence}"
        )
    else:
        element = _text(moment.get("element")) or "The saturated moment"
        token = _text(moment.get("token"))
        surrounding = _text(moment.get("surrounding"))
        line = (
            f"{element}"
            f"{f', in **{token}**' if token else ''}"
            f"{f'. {surrounding}' if surrounding else ''}"
            f"{confidence}"
        )
    sections.append(("Chromatic moment", [line]))

    _push(
        sections,
        "Signature compositions",
        [
            f"**{_text(entry.get('strength'))}** — {_text(entry.get('name'))}: "
            f"{_text(entry.get('structure'))}{_confidence(entry.get('confidence'))}"
            for entry in _objs(brief.get("signature_compositions"))
        ],
    )

    _push(
        sections,
        "Palette application",
        [
            f"**{_text(entry.get('token'))}** — {_text(entry.get('scope'))}: "
            f"{_text(entry.get('evidence'))}{_confidence(entry.get('confidence'))}"
            for entry in _objs(brief.get("palette_application"))
        ],
    )

    rhythm = _obj(brief.get("background_rhythm"))
    rhythm_lines: list[str] = []
    summary = _text(rhythm.get("ratio_summary"))
    differentiation = _text(rhythm.get("differentiation"))
    if summary or differentiation:
        head = ". ".join(
            part
            for part in (
                summary,
                f"Differentiation is {differentiation}." if differentiation else "",
            )
            if part
        )
        rhythm_lines.append(head + _confidence(rhythm.get("confidence")))
        rhythm_lines.append("")
    for band in _objs(rhythm.get("bands")):
        index = band.get("index")
        position = index + 1 if isinstance(index, int) and not isinstance(index, bool) else "?"
        note = _text(band.get("note"))
        token = _text(band.get("token")) or "no kit token"
        rhythm_lines.append(
            f"- Band {position}: **{token}**{f' — {note}' if note else ''}"
        )
    if rhythm_lines:
        sections.append(("Background rhythm", rhythm_lines))

    posture = _obj(brief.get("typographic_posture"))
    posture_tokens = _strings(posture.get("tokens"))
    _push(
        sections,
        "Typographic posture",
        [
            line
            for line in (
                f"Case: {_text(posture.get('case_posture'))}"
                if _text(posture.get("case_posture"))
                else "",
                f"Scale: {_text(posture.get('scale_temperament'))}"
                if _text(posture.get("scale_temperament"))
                else "",
                "Tokens: " + ", ".join(f"**{token}**" for token in posture_tokens)
                if posture_tokens
                else "",
                *_strings(posture.get("signature_moves")),
            )
            if line
        ],
    )

    imagery = _obj(brief.get("imagery_posture"))
    _push(
        sections,
        "Imagery posture",
        [
            line
            for line in (
                f"Diet: {_text(imagery.get('diet'))}" if _text(imagery.get("diet")) else "",
                *_strings(imagery.get("slots")),
                *[f"**Absent** — {absence}" for absence in _strings(imagery.get("absences"))],
            )
            if line
        ],
    )

    _push(
        sections,
        "Constraints",
        [_constraint_line(entry) for entry in _objs(brief.get("constraints"))],
    )

    _push(
        sections,
        "Component recipes",
        [_recipe_line(recipe) for recipe in _objs(brief.get("component_recipes"))],
    )

    _push(
        sections,
        "Observations with no token",
        [
            f"{_text(entry.get('observation'))} — {_text(entry.get('reason'))}"
            for entry in _objs(brief.get("diagnostics"))
        ],
    )

    return sections


def _constraint_line(entry: JsonObject) -> str:
    rule = _text(entry.get("rule"))
    scope = _text(entry.get("scope"))
    if not rule:
        return ""
    return f"{rule}{f' ({scope})' if scope else ''}{_confidence(entry.get('confidence'))}"


def _recipe_line(recipe: JsonObject) -> str:
    slots = ", ".join(
        f"{slot} **{_text(recipe.get(slot))}**"
        for slot in ("radius", "padding", "border", "shadow", "background", "text")
        if _text(recipe.get(slot))
    )
    unmapped = _strings(recipe.get("unmapped"))
    trailer = f" — untokenized: {'; '.join(unmapped)}" if unmapped else ""
    return (
        f"**{_text(recipe.get('component'))} / {_text(recipe.get('variant'))}** — "
        f"{slots or 'no tokenized slots'}{trailer}"
        f"{_confidence(recipe.get('confidence'))}"
    )


def _push(
    sections: list[tuple[str, list[str]]], heading: str, items: Iterable[str]
) -> None:
    """An empty section is OMITTED, not stubbed — absence is a correct answer in
    this schema, and a "Component recipes: none" row would be the first invented
    sentence in the card."""
    rows = [item for item in items if item]
    if rows:
        sections.append((heading, [f"- {item}" for item in rows]))


def _confidence(level: Any) -> str:
    return f" ({_text(level) or 'low'} confidence)"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _obj(value: Any) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _objs(value: Any) -> list[JsonObject]:
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [entry.strip() for entry in value if isinstance(entry, str) and entry.strip()]

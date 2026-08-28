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

ONE divergence is deliberate, and it is the only one: on the agent side a
geometry slot renders the WEB CLASS beside its token (`radius
**rounded-button** (radius.button)`), and the measured-geometry section says
those numbers render through those utilities. The panel keeps naming kit tokens
alone, because a class name is authoring vocabulary — the founder is approving
the brand's shape, not the markup that will express it. `GEOMETRY_TOKEN_UTILITIES`
below is the whole mechanism and carries the same note. So: do NOT "restore
parity" by reverting it, and do NOT mirror it into the panel; every OTHER change
here still belongs in both projections.

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

#: KIT TOKEN -> the web class that renders it. The ten chain HEADS of
#: `GEOMETRY_UTILITIES` (crates/lumen-web/src/theme.rs) and nothing else: the
#: fallback rungs of a chain (`radius.md`, `shadow.sm`, `space.lg`) are the
#: engine's business and have no class of their own to name.
#:
#: This exists because a recipe is a brand FACT the author must deploy, and
#: until G3 it named only kit tokens — "radius **radius.button**" left the
#: author to invent a class, which is exactly where a brand's measured 4px
#: became someone's `rounded-2xl`. With the class rendered beside the token the
#: recipe is copyable.
#:
#: Deliberately agent-side only: the frontend's mirror of this projection
#: (`apps/frontend/src/features/brand-context/model/brand-brief.ts`) shows the
#: founder the same brief, and a web class name is authoring vocabulary that
#: means nothing on that panel. Drift from the Rust table fails
#: `test_web_geometry_vocabulary.py`.
GEOMETRY_TOKEN_UTILITIES = {
    "radius.button": "rounded-button",
    "radius.card": "rounded-card",
    "radius.badge": "rounded-badge",
    "shadow.brand": "shadow-brand",
    "shadow.card": "shadow-card",
    "stroke.width.card": "border-w-card",
    "stroke.width.divider": "border-w-divider",
    "space.section": "py-section",
    "space.stack.default": "gap-stack",
    "space.card.padding": "p-card",
}


#: `BrandGrammarAudit@1` (clone-fidelity F2.4) — the kit's OTHER grammar section.
#: Same envelope discipline as the brief: an unknown version is not an audit.
GRAMMAR_AUDIT_SCHEMA_VERSION = 1

#: The audit's budget is denominated in CHARACTERS, not tokens: unlike the brief
#: (whose size is whatever a model wrote) every line of it is a short, templated
#: rule, so the honest instrument is the one that needs no estimator. 4,000 chars
#: is ~1,000 tokens — a sixth of the brief's ceiling — which is the right size for
#: a block that rides in EVERY web role prompt beside the brief and the card.
GRAMMAR_AUDIT_CHAR_BUDGET = 4000

#: The five fields, in reading order, with the heading each renders under.
#: `anti_patterns` reads as "Never" because that is what the agent must do with
#: it — the exclusions are instructions, not a taxonomy.
GRAMMAR_AUDIT_FIELDS: tuple[tuple[str, str], ...] = (
    ("type_treatment", "Type treatment"),
    ("cadence", "Cadence"),
    ("color_frequency", "Color frequency"),
    ("surface_language", "Surface language"),
    ("anti_patterns", "Never — this brand's exclusions"),
)

#: What a non-measured rule is marked with. A rule with no marker was read off
#: the brand's own site; these two were not, and an agent that mistakes an engine
#: default for a brand fact reproduces the default as identity.
_BASIS_MARKERS = {
    "derived": " [engine default, not a brand fact]",
    "default": " [house default, not measured on this brand]",
}


@dataclass(frozen=True)
class BriefRender:
    """One rendered, budgeted block of brief prose."""

    markdown: str
    truncated: bool
    omitted: tuple[str, ...]
    estimated_tokens: int


@dataclass(frozen=True)
class GrammarAuditRender:
    """One rendered, budgeted block of grammar-audit prose."""

    markdown: str
    truncated: bool
    #: How many whole rules did not fit.
    dropped_rules: int
    #: The headings they came from, in reading order.
    dropped_from: tuple[str, ...]
    characters: int


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


def read_grammar_audit(brand_kit: Any) -> Optional[JsonObject]:
    """The kit's `BrandGrammarAudit@1`, or None when it carries none.

    Strict about the envelope for the same reason `read_brief` is: a section this
    build cannot read whole is not a section it may read half of. A kit from
    before F2.4 simply has no key, and the card renders exactly as it did.
    """
    if not isinstance(brand_kit, dict):
        return None
    audit = brand_kit.get("grammar_audit")
    if not isinstance(audit, dict):
        return None
    if audit.get("schema_version") != GRAMMAR_AUDIT_SCHEMA_VERSION:
        return None
    if any(not isinstance(audit.get(name), dict) for name, _ in GRAMMAR_AUDIT_FIELDS):
        return None
    return audit


def render_grammar_audit(audit: JsonObject) -> GrammarAuditRender:
    """The whole injected block, under the character budget.

    Overflow drops WHOLE RULES, lowest-value first, and says so. "Lowest value"
    is defined structurally: each field emits its rules strongest-first, so a
    field's fifth rule is worth less than any field's first, and the cut walks
    that order from the tail. The consequence is the one that matters — every
    field keeps its strongest rule while any field still holds a weaker one, so
    no field silently vanishes to make room for another's tail. A rule is never
    cut in half: half a rule is a rule the agent cannot follow.
    """
    entries: list[tuple[int, str, int, str]] = []
    absences: dict[str, str] = {}
    for position, (name, heading) in enumerate(GRAMMAR_AUDIT_FIELDS):
        field = _obj(audit.get(name))
        rules = _objs(field.get("rules"))
        lines = [line for line in (_audit_rule_line(rule) for rule in rules) if line]
        for index, line in enumerate(lines):
            entries.append((position, heading, index, line))
        if not lines:
            # A field with no rules is an absence — the extractor guarantees a
            # reason, and a payload that arrives without one still says NOT KNOWN
            # rather than inventing a cause.
            absences[heading] = (
                _text(field.get("absent")) or "no rule was recorded for this field."
            )

    # The drop order: latest rule within a field first, later field breaking ties.
    order = sorted(
        range(len(entries)), key=lambda index: (-entries[index][2], -entries[index][0])
    )
    dropped: set[int] = set()
    while True:
        markdown, dropped_from = _assemble_audit(entries, dropped, absences)
        if len(markdown) <= GRAMMAR_AUDIT_CHAR_BUDGET or len(dropped) == len(entries):
            break
        dropped.add(next(index for index in order if index not in dropped))
    return GrammarAuditRender(
        markdown=markdown,
        truncated=bool(dropped),
        dropped_rules=len(dropped),
        dropped_from=dropped_from,
        characters=len(markdown),
    )


def _audit_rule_line(rule: Any) -> str:
    """One rule as the agent reads it: the law, then what it is worth."""
    entry = _obj(rule)
    text = _text(entry.get("rule"))
    if not text:
        return ""
    return f"- {_with_utilities(text)}{_BASIS_MARKERS.get(_text(entry.get('basis')), '')}"


def _with_utilities(text: str) -> str:
    """`radius.button` -> `rounded-button` (radius.button).

    The audit is stored in kit TOKEN names (the token law — a class name is
    authoring vocabulary and does not belong in a durable kit section). This is
    the same agent-side divergence `_slot_value` makes for a component recipe,
    and for the same reason: a rule the author cannot deploy is a rule that gets
    approximated.
    """
    for token, utility in GEOMETRY_TOKEN_UTILITIES.items():
        text = text.replace(f"`{token}`", f"`{utility}` ({token})")
    return text


def _assemble_audit(
    entries: list[tuple[int, str, int, str]],
    dropped: set[int],
    absences: dict[str, str],
) -> tuple[str, tuple[str, ...]]:
    parts = [_AUDIT_HEADER]
    dropped_from: list[str] = []
    for _, heading in GRAMMAR_AUDIT_FIELDS:
        kept = [
            entry[3]
            for index, entry in enumerate(entries)
            if entry[1] == heading and index not in dropped
        ]
        lost = [
            entry
            for index, entry in enumerate(entries)
            if entry[1] == heading and index in dropped
        ]
        if lost:
            dropped_from.append(heading)
        if kept:
            body = kept
        elif heading in absences:
            body = [f"NOT KNOWN — {absences[heading]}"]
        else:
            # The field HAD rules and the budget took all of them. Saying NOT
            # KNOWN here would be a lie: the kit knows, this rendering does not.
            body = [
                "(every rule in this field was dropped to fit the budget — treat it as "
                "unknown, not as absent)"
            ]
        parts.append("\n".join([f"## {heading}", "", *body, ""]))
    if dropped:
        parts.append(_audit_truncation_note(len(dropped), dropped_from))
    return "\n".join(parts), tuple(dropped_from)


def _audit_truncation_note(count: int, headings: list[str]) -> str:
    return "\n".join(
        [
            "## This audit is truncated",
            "",
            (
                f"{count} rule(s) did not fit the "
                f"{GRAMMAR_AUDIT_CHAR_BUDGET:,}-character budget and are NOT shown, from: "
                + ", ".join(headings)
                + ". Treat them as unknown rather than absent."
            ),
            "",
        ]
    )


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

#: DRAFT WORDING — pending founder review (F2.4). The machinery around it is
#: settled; these six sentences are a proposal. Two of them are load-bearing and
#: should survive any rewrite: the SCOPE line (this governs composed sections,
#: and the reuse ladder — not this block — governs a cloned one, so the two laws
#: never contradict each other) and the NOT KNOWN line (an empty field is a
#: finding, and filling it from habit is the failure this artifact exists to
#: prevent).
_AUDIT_HEADER = """BRAND GRAMMAR AUDIT — the law for the sections you COMPOSE. It was extracted
from this brand's own site and approved with this kit version, so it is evidence,
not taste: a line carrying no marker was measured, and a line marked as an engine
or house default was not. It governs NEW sections only — a cloned section lifted
from the client's site is governed by the reuse ladder in your prompt, never by
this. Where a field says NOT KNOWN, nothing was measured to support a rule; leave
the gap rather than filling it from habit.
"""


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
        "You do not hand-write these numbers: they render through the web"
        " geometry utilities (BRAND GEOMETRY in your prompt, the full block in"
        " the create-website skill) — "
        + ", ".join(GEOMETRY_TOKEN_UTILITIES.values())
        + ".",
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
        f"{slot} {_slot_value(_text(recipe.get(slot)))}"
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


def _slot_value(token: str) -> str:
    """One recipe slot: the class the author writes, then the token behind it.

    A slot with no geometry utility (a color or a non-head spacing step) renders
    exactly as it always did — the token name alone.
    """
    utility = GEOMETRY_TOKEN_UTILITIES.get(token)
    return f"**{utility}** ({token})" if utility else f"**{token}**"


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

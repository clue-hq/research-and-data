"""The format-skill library (fast-loop spec §6): the pilot plus the R6 wave.

A format skill sits ABOVE the craft skills: it pre-makes one artifact format's
decisions (surface, skeletons, type floors, brevity budgets, named self-audit
tests) so the author stops rediscovering them. That only pays off if the skill is
**loadable**, **discoverable**, and **true about this repo** — a skill citing a
phantom token or a knowledge file that does not exist sends the author hunting,
which is exactly the cost §6 exists to kill. So this suite guards, for EVERY
format skill in the tree:

- it loads the way its siblings do (frontmatter `name`/`description`, one dir);
- the description carries the trigger phrases the orchestrator matches on, and
  stays on ONE line (`parse_frontmatter` is a `key: value` line reader — a wrapped
  description silently loses everything after the first line);
- §6.1's composition rule: it names the craft skills it composes with and the
  knowledge files to pin, and **every one of those paths resolves**;
- **every `$token`, DSL form, and archetype name it cites exists in the repo**;
- §5.7's required-decisions contract is machine-readable (`required_decisions:`
  frontmatter) AND matches the human-readable table;
- §6.1's `selection_policy:` is declared with the value the format intends;
- the §8 self-audit tests are all present;
- the agent's root doc (`AGENT.md`) indexes it and routes its triggers.

Ruling R6 sequenced four follow-on formats after the pilot's metrics. §7 of this
file is the deliberate decision to land them: the absence assertion is now a
PRESENCE assertion.
"""

from __future__ import annotations

import re
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

from lumen_agent.knowledge import (
    DEFAULT_SELECTION_POLICY,
    SELECTION_POLICIES,
    parse_frontmatter,
    required_decision_keys,
    selection_policy,
)
from lumen_agent.materialize import materialize_agent_workspace

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DOCS = RUNTIME_ROOT / "knowledge_docs"
SKILLS_DIR = KNOWLEDGE_DOCS / "skills"
SKILL_NAME = "linkedin-square-ad"
SKILL_FILE = SKILLS_DIR / SKILL_NAME / "SKILL.md"


@dataclass(frozen=True)
class FormatSkill:
    """One format skill's declared contract, as this suite checks it.

    `triggers` are the phrases the orchestrator's progressive-disclosure match runs
    against. They live in the `description` because that (plus `name`) is ALL a
    subagent sees until it opens the skill — see `harness.py`'s SkillsMiddleware
    wiring note — and they are mirrored into `AGENT.md` so the doc-level route
    matches the frontmatter-level one.
    """

    name: str
    triggers: tuple[str, ...]
    decisions: tuple[str, ...]
    policy: str
    composes: tuple[str, ...]
    pinned: tuple[str, ...]
    archetypes: tuple[str, ...]
    faces: tuple[str, ...]
    audit_tests: tuple[str, ...]

    @property
    def path(self) -> Path:
        return SKILLS_DIR / self.name / "SKILL.md"

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def meta_and_body(self) -> tuple[dict[str, str], str]:
        return parse_frontmatter(self.text())


# Added 2026-08-24 (colour-craft wave): `skills/color-and-contrast` joins the
# shared roster after acceptance run #2 shipped a black `$text.primary` headline
# on a full-strength `$surface.brand` ground. Picking a legal token was treated
# as the end of colour thinking; nothing in the format layer asked how the
# combination actually reads. Every format skill composes with it, so the guard
# below fails if one of them ever drops the pointer.
_SHARED_COMPOSES = (
    "skills/brand-and-tokens",
    "skills/color-and-contrast",
    "skills/brand-imagery",
    "skills/clarify-design-brief",
)
_IMPACT_FACES = ("Anton", "Bebas Neue", "Archivo Black", "Bricolage Grotesque")

PILOT = FormatSkill(
    name=SKILL_NAME,
    triggers=("linkedin ad", "feed ad", "square social ad", "1:1 paid social"),
    decisions=("audience", "offer_cta", "tone", "brand_adherence"),
    policy="llm_selectable",
    composes=_SHARED_COMPOSES,
    pinned=(
        "knowledge/design/layout-recipes",  # the archetype canon it selects from
        "knowledge/design/blocks/patterns",  # the validated 1080² proportions
        "knowledge/design/blocks/actions",  # the validated CTA plate geometry
        "knowledge/design/foundations",  # squint test + contrast floors
        "knowledge/design/font-library",  # the display voices it names
    ),
    archetypes=("split-panel", "vertical-poster", "numeral-hero"),
    faces=_IMPACT_FACES,
    audit_tests=(
        "single-focal-point",
        "first-second-ordering",
        "headline-budget",
        "cta-thumbnail-legibility",
        "distinctive-asset-at-real-scale",
        "safe-margins",
        # Added 2026-08-24 after acceptance run #1 shipped a headline sitting on
        # its body copy. No engine diagnostic covers content colliding with
        # content, so this eyes test is the only thing that catches the class.
        "no-collisions",
        # Added 2026-08-24 after acceptance run #2 shipped a black headline on a
        # full-strength brand ground with a saturated CTA plate on top of it. The
        # engine's LUMB0807 caught the 16pt body at 3.39:1 and let the 77pt
        # headline through on the large-text floor, so the defect that actually
        # sank the render was reported by nothing. Only an eyes test covers it.
        "on-color-pairing",
        "brand-adherence-followed",
    ),
)

STORY = FormatSkill(
    name="story-ad-9x16",
    triggers=("story ad", "reel ad", "9:16", "vertical social ad", "full-screen mobile ad"),
    decisions=("audience", "offer_cta", "tone", "brand_adherence"),
    policy="llm_selectable",
    composes=_SHARED_COMPOSES,
    pinned=(
        "knowledge/design/layout-recipes",
        "knowledge/design/foundations",
        "knowledge/design/blocks/patterns",
        "knowledge/design/font-library",
        "knowledge/images/placement",  # the scrim rule, which a photo story lives on
    ),
    archetypes=("vertical-poster", "image-hero", "numeral-hero"),
    faces=_IMPACT_FACES,
    audit_tests=(
        "single-focal-point",
        "safe-zone-clearance",
        "thumb-stop-in-the-top-third",
        "headline-budget",
        "cta-legibility",
        "distinctive-asset-at-real-scale",
        "on-color-pairing",
        "brand-adherence-followed",
    ),
)

BANNERS = FormatSkill(
    name="web-display-banners",
    triggers=(
        "display banner",
        "web banner",
        "display ad",
        "banner ad",
        "leaderboard",
        "skyscraper",
    ),
    decisions=("banner_size", "offer_cta", "brand_adherence"),
    policy="llm_selectable",
    composes=_SHARED_COMPOSES,
    pinned=(
        "knowledge/design/foundations",
        "knowledge/design/blocks/actions",  # the validated button structure
        "knowledge/design/layout-recipes",
        "knowledge/design/font-library",
    ),
    archetypes=("vertical-poster", "banded"),
    faces=_IMPACT_FACES,
    audit_tests=(
        "single-message",
        "edge-clearance",
        "type-floor-held",
        "cta-is-the-contrast-peak",
        "cta-copy-is-an-action",
        "wordmark-legible",
        "on-color-pairing",
        "brand-adherence-followed",
    ),
)

POSTER = FormatSkill(
    name="a4-poster",
    triggers=("a4 poster", "a4 flyer", "printed poster", "print flyer", "leaflet"),
    decisions=("poster_kind", "offer_cta", "bleed_route", "brand_adherence"),
    policy="deterministic",
    composes=(*_SHARED_COMPOSES, "skills/print-bleed-marks"),
    pinned=(
        "knowledge/export/print-geometry",  # trim / bleed / safe area, and the gate
        "knowledge/design/blocks/patterns",  # the validated A4 one-pager proportions
        "knowledge/design/layout-recipes",
        "knowledge/design/foundations",
        "knowledge/design/font-library",
    ),
    archetypes=("vertical-poster", "banded"),
    faces=(*_IMPACT_FACES, "Fraunces", "Playfair Display"),
    audit_tests=(
        "single-focal-point",
        "arms-length-legibility",
        "safe-area-clearance",
        "edge-art-reaches-the-bleed",
        "press-safe-color",
        "one-ask-with-its-standing-detail",
        "on-color-pairing",
        "brand-adherence-followed",
    ),
)

BANNER = FormatSkill(
    name="linkedin-banner",
    triggers=(
        "linkedin banner",
        "linkedin cover",
        "profile banner",
        "company page cover",
        "linkedin header",
    ),
    decisions=("banner_surface", "positioning_line", "brand_adherence"),
    policy="llm_selectable",
    composes=_SHARED_COMPOSES,
    pinned=(
        "knowledge/design/layout-recipes",
        "knowledge/design/foundations",
        "knowledge/design-systems/logo-and-assets",  # mark variants + minimum size
        "knowledge/design/font-library",
    ),
    archetypes=("vertical-poster", "split-panel", "emblem"),
    faces=(*_IMPACT_FACES, "Syne"),
    audit_tests=(
        "photo-overlap-clear",
        "single-band-composition",
        "no-cta-pretence",
        "wordmark-at-real-scale",
        "one-line-budget",
        "calm-contrast",
        "on-color-pairing",
        "brand-adherence-followed",
    ),
)

FORMAT_SKILLS = (PILOT, STORY, BANNERS, POSTER, BANNER)
FORMAT_SKILL_NAMES = frozenset(skill.name for skill in FORMAT_SKILLS)

#: `pytest.mark.parametrize` over the whole library, with readable ids.
every_format_skill = pytest.mark.parametrize(
    "skill", FORMAT_SKILLS, ids=[skill.name for skill in FORMAT_SKILLS]
)


def _skill_text() -> str:
    return SKILL_FILE.read_text(encoding="utf-8")


def _meta_and_body() -> tuple[dict[str, str], str]:
    return parse_frontmatter(_skill_text())


def _corpus() -> str:
    """Every authored knowledge doc EXCEPT the format skills, concatenated — the
    oracle for "does this token / archetype / DSL form actually exist".

    Format skills are excluded as a group, not one at a time: if they taught each
    other, a phantom token invented in the R6 wave would validate itself the moment
    two skills repeated it. The oracle has to be the corpus the format layer sits
    on top of."""

    format_files = {skill.path for skill in FORMAT_SKILLS}
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(KNOWLEDGE_DOCS.rglob("*.md"))
        if path not in format_files
    )


def _read(*parts: str) -> str:
    return (KNOWLEDGE_DOCS.joinpath(*parts)).read_text(encoding="utf-8")


# ============================================================================
# 1. It loads (registration is implicit, by directory)
# ============================================================================


@every_format_skill
def test_the_format_skill_is_a_directory_in_the_authored_tree(skill: FormatSkill) -> None:
    assert skill.path.is_file()


@every_format_skill
def test_the_skill_parses_with_a_name_matching_its_directory(skill: FormatSkill) -> None:
    meta, body = skill.meta_and_body()

    assert meta.get("name") == skill.name
    assert meta.get("description")
    assert body.strip()


def test_the_materializer_serves_every_format_skill_to_the_agent(tmp_path) -> None:
    """The load smoke over the REAL tree: each skill lands on both surfaces the agent
    reads — `/.deepagent/skills/` (the SkillsMiddleware source) and the
    `/knowledge_docs/` copy that intra-doc references resolve against."""

    ws = tmp_path / "ws"
    materialize_agent_workspace(types.SimpleNamespace(workspace_root=ws))

    for skill in FORMAT_SKILLS:
        served = ws / ".deepagent" / "skills" / skill.name / "SKILL.md"
        assert served.is_file(), skill.name
        assert served.read_text(encoding="utf-8") == skill.text()
        assert (ws / "knowledge_docs" / "skills" / skill.name / "SKILL.md").is_file()


# ============================================================================
# 2. It is discoverable — trigger phrases, on one line
# ============================================================================


@every_format_skill
def test_the_description_carries_every_trigger_phrase(skill: FormatSkill) -> None:
    description = skill.meta_and_body()[0]["description"].lower()

    for phrase in skill.triggers:
        assert phrase in description, f"{skill.name} does not trigger on {phrase!r}"


@every_format_skill
def test_the_description_survives_the_frontmatter_line_reader(skill: FormatSkill) -> None:
    """`parse_frontmatter` splits on the FIRST colon of each line and keeps no
    continuations, so a description wrapped across lines silently loses its tail —
    and with it the trigger phrases. Guard the whole declaration, not just the
    parsed value: assert the raw frontmatter holds `description:` exactly once and
    that no wrapped continuation line follows it."""

    raw = skill.text().split("---", 2)[1]
    lines = [line for line in raw.splitlines() if line.strip()]
    description_lines = [i for i, line in enumerate(lines) if line.startswith("description:")]

    assert len(description_lines) == 1
    for line in lines:
        assert line == line.lstrip(), f"wrapped frontmatter line is dropped: {line!r}"

    # The parsed value is the whole declaration, tail included — every description
    # closes on its trigger sentence, so the tail is exactly what a wrap would eat.
    assert skill.meta_and_body()[0]["description"].rstrip().endswith(".")


def test_the_pilot_description_keeps_its_tail_verbatim() -> None:
    """One literal spot-check behind the generic rule above, so a regression that
    truncates mid-sentence (rather than mid-word) still has something to trip."""

    assert _meta_and_body()[0]["description"].endswith("creative.")


@every_format_skill
def test_the_root_agent_doc_indexes_the_skill_with_its_triggers(skill: FormatSkill) -> None:
    text = _read("AGENT.md")
    lowered = text.lower()

    # Both surfaces a reader lands on: the §4 knowledge map and the §5 skills index.
    assert f"skills/{skill.name}" in text
    assert f"skills/{skill.name}/SKILL.md" in text
    for phrase in skill.triggers:
        assert phrase in lowered, f"AGENT.md does not route {phrase!r} to {skill.name}"


def test_the_agent_doc_carries_one_format_routing_table() -> None:
    """§4's format row points at a routing table rather than naming one format, so
    adding a format is a table row and never an edit to the rule itself."""

    text = _read("AGENT.md")

    assert "### Format skills — which one the brief matches" in text
    assert "| The brief asks for | Read |" in text
    assert "No match is normal" in text


# ============================================================================
# 3. §6.1 composition — it names what it composes with, and those paths RESOLVE
# ============================================================================


@every_format_skill
def test_the_skill_names_the_craft_skills_it_composes_with(skill: FormatSkill) -> None:
    body = skill.meta_and_body()[1]

    for pointer in skill.composes:
        assert pointer in body, f"{skill.name} does not compose with {pointer}"
    # Every format skill sits ABOVE create-design, so it must not silently duplicate
    # the craft layer's job: the composition pointers are the seam.
    assert "skills/brand-and-tokens" in body
    assert "skills/clarify-design-brief" in body


@every_format_skill
def test_every_skill_and_knowledge_path_the_skill_cites_exists(skill: FormatSkill) -> None:
    """The anti-phantom test. A pointer to a file that is not there is the exact
    failure this work kills — the author greps for it and burns calls."""

    body = skill.meta_and_body()[1]
    missing: list[str] = []

    for ref in sorted(set(re.findall(r"`(skills/[a-z0-9-]+)`", body))):
        if not (KNOWLEDGE_DOCS / f"{ref}/SKILL.md").is_file():
            missing.append(f"{ref}/SKILL.md")

    for ref in sorted(set(re.findall(r"`(knowledge/[a-z0-9/-]+)`", body))):
        if not (KNOWLEDGE_DOCS / f"{ref}.md").is_file():
            missing.append(f"{ref}.md")

    assert not missing, f"{skill.name} points at files that do not exist: {missing}"


@every_format_skill
def test_the_pinned_knowledge_files_are_the_ones_the_format_actually_needs(
    skill: FormatSkill,
) -> None:
    body = skill.meta_and_body()[1]

    for pinned in skill.pinned:
        assert pinned in body, f"{skill.name} does not pin {pinned}"


# ============================================================================
# 4. Every token / DSL form / archetype it cites is real
# ============================================================================


@every_format_skill
def test_every_token_the_skill_cites_exists_elsewhere_in_the_corpus(
    skill: FormatSkill,
) -> None:
    """A `$token` the tree never teaches is a phantom: the author cannot resolve it
    and preflight will not either. Every token here must already appear in another
    authored doc (the taxonomy, the ramp, or a validated block)."""

    body = skill.meta_and_body()[1]
    corpus = _corpus()
    ramp = _read("knowledge", "lumen-dsl", "text.md")

    tokens = sorted(set(re.findall(r"\$[a-z]+(?:\.[a-z0-9]+)+", body)))
    assert tokens, f"{skill.name} cites no tokens at all — it stopped being concrete"

    def _taught(token: str) -> bool:
        if token in corpus:
            return True
        # The size ramp is published once, in shorthand — `$type.size.xs=12  sm=14
        # … 9xl=128` — so a legitimate step like `$type.size.9xl` never appears
        # fully qualified. Resolve those against the ramp's own declaration.
        step = token.removeprefix("$type.size.")
        return step != token and re.search(rf"\b{re.escape(step)}=\d+", ramp) is not None

    unknown = [token for token in tokens if not _taught(token)]
    assert not unknown, f"{skill.name} cites phantom tokens: {unknown}"


@every_format_skill
def test_the_named_archetypes_are_the_canon_ones(skill: FormatSkill) -> None:
    body = skill.meta_and_body()[1].lower()
    recipes = _read("knowledge", "design", "layout-recipes.md")

    for archetype in skill.archetypes:
        assert archetype in body, f"{skill.name} does not name {archetype}"
        assert archetype in recipes, f"{archetype} is not in the archetype canon"


@every_format_skill
def test_the_named_display_faces_are_in_the_font_library(skill: FormatSkill) -> None:
    body = skill.meta_and_body()[1]
    library = _read("knowledge", "design", "font-library.md")

    for face in skill.faces:
        assert face in body, f"{skill.name} does not name {face}"
        assert f"| {face} |" in library, f"{face} is not a library family"


@every_format_skill
def test_the_generic_face_ban_names_families_that_really_do_not_resolve(
    skill: FormatSkill,
) -> None:
    """Every format skill bans the same four system faces. That ban is only honest
    while none of them is a library family — the moment one is added, the skills
    would be telling the author a resolvable face does not resolve."""

    body = skill.meta_and_body()[1]
    library = _read("knowledge", "design", "font-library.md")

    assert "Arial/Helvetica/Roboto/Open Sans do not resolve" in body
    for banned in ("Arial", "Helvetica", "Roboto", "Open Sans"):
        assert f"| {banned} |" not in library, f"{banned} IS a library family now"


def test_the_pilot_surface_command_is_the_canonical_one() -> None:
    """`page linkedin_square size(1080,1080,px)` is the exact line every validated
    1080² skeleton opens with; a variant page id would drift the format away from
    the canon it tells the author to recompose."""

    body = _meta_and_body()[1]
    surface = "page linkedin_square size(1080,1080,px)"

    assert surface in body
    assert surface in _read("knowledge", "design", "layout-recipes.md")


@every_format_skill
def test_the_slot_repair_line_matches_the_grammar_where_a_skill_teaches_it(
    skill: FormatSkill,
) -> None:
    """P0.2 gave image-like slots a born default policy AND the
    `#slot:key image_policy(...)` modify line. Any skill that teaches the LUMV0820
    repair must match that grammar — the modify-line form, the `fit=`/`focal_x=`
    field spelling, and the 'never delete the slot' rule. A skill that never
    mentions the code is not required to carry the repair."""

    body = skill.meta_and_body()[1]
    if "LUMV0820" not in body:
        return

    grammar = _read("knowledge", "lumen-dsl", "grammar.md")

    assert "#slot:account.logo image_policy(fit=cover," in body
    assert "never delete the slot" in body.lower()
    # The grammar this is written against: the modify-line form and the kwarg spelling.
    assert "#slot:account.logo image_policy(fit=cover" in grammar
    assert "born with the default policy" in grammar


def test_the_pilot_still_teaches_the_slot_repair() -> None:
    """The generic guard above skips a skill that never names the code, so pin the
    pilot's own coverage: it authors image slots and must keep the repair."""

    assert "LUMV0820" in _meta_and_body()[1]


# ============================================================================
# 4b. Per-format surface anchors — the numbers each skill is built on
# ============================================================================


def test_the_story_surface_command_is_the_one_the_grammar_publishes() -> None:
    """`page story size(1080,1920,px)` is the grammar reference's own vertical
    example, so the format skill and the grammar cannot drift apart."""

    body = STORY.meta_and_body()[1]
    surface = "page story size(1080,1920,px)"

    assert surface in body
    assert surface in _read("knowledge", "lumen-dsl", "grammar.md")


def test_the_story_safe_zone_arithmetic_is_internally_consistent() -> None:
    """The whole format rests on one content band. If the padding and the band size
    ever disagree, the author lays out against a box that is not there."""

    body = STORY.meta_and_body()[1]

    assert "pad(250,96,340,96)" in body
    # 1080 - 96 - 96 = 888 wide; 1920 - 250 - 340 = 1330 tall.
    assert "888 × 1330 pt" in body
    assert "64pt is the hard side floor" in body
    # And the allowance is presented as an allowance, not as a measured spec.
    assert "conservative platform-chrome" in body


def test_the_banner_family_lists_the_iab_sizes_with_a_content_box_each() -> None:
    """Six units, and for each one the padded content box the author designs into.
    A size with no content box would leave the edge-clearance rule unactionable."""

    body = BANNERS.meta_and_body()[1]

    for size, box in (
        ("728 × 90", "708 × 70"),
        ("970 × 250", "950 × 230"),
        ("300 × 250", "280 × 230"),
        ("300 × 600", "280 × 580"),
        ("160 × 600", "144 × 584"),
        ("320 × 50", "310 × 40"),
    ):
        assert size in body, f"{size} is missing from the banner family"
        assert box in body, f"{size} has no content box"

    assert "MPU 300 × 250" in body  # the stated default when the brief is silent


def test_the_banner_skill_is_honest_about_the_preset_list() -> None:
    """It tells the author that no preset fits a display unit. That claim is only
    true while the compiler's preset list stays these five, so pin it to source."""

    body = BANNERS.meta_and_body()[1]
    dsl = (RUNTIME_ROOT.parents[1] / "crates" / "lumen-core" / "src" / "dsl.rs").read_text(
        encoding="utf-8"
    )

    assert "page <id> size(w,h,px)" in body
    assert "page banner_mpu size(300,250,px)" in body
    assert '`a4`, `us_letter`,\n  `linkedin_ad`, `envelope_dl`, and `custom`' in body
    # The compiler's own error message enumerates the accepted presets.
    assert "Use a4, us_letter, linkedin_ad, envelope_dl, or custom." in dsl


def test_the_banner_type_floor_is_the_bottom_of_the_published_ramp() -> None:
    """12pt is the floor the skill enforces, and `$type.size.xs` is the ramp step
    that resolves to it — if the ramp ever moves, this claim has to move with it."""

    body = BANNERS.meta_and_body()[1]
    ramp = _read("knowledge", "lumen-dsl", "text.md")

    assert "`$type.size.xs` (12) is the hard floor" in body
    assert "xs=12" in ramp
    # The banner family inverts the pilot's step-UP rule; say so, or the author
    # carries the 1080-canvas habit onto a 300pt surface.
    assert "Banners invert the usual rule" in body


def test_the_poster_page_size_matches_the_engine_and_the_canon() -> None:
    """A4 is 210×297mm and the engine converts at 72/25.4, so the layout bounds are
    595.28 × 841.89pt — written 595 × 842 everywhere in the corpus. Pin all three:
    the preset's mm source, the conversion constants, and the corpus rounding."""

    body = POSTER.meta_and_body()[1]
    geometry = (
        RUNTIME_ROOT.parents[1] / "crates" / "lumen-core" / "src" / "page_geometry.rs"
    ).read_text(encoding="utf-8")

    assert "page poster_a4 preset(a4,portrait)" in body
    assert "595 x 842 pt" in body
    assert "595.28 x 841.89 pt" in body

    assert "PagePreset::A4 => (210.0, 297.0, Unit::Mm)" in geometry
    assert "POINTS_PER_INCH: f64 = 72.0" in geometry
    assert "MM_PER_INCH: f64 = 25.4" in geometry
    assert "595×842pt" in _read("knowledge", "design", "blocks", "patterns.md")


def test_the_poster_bleed_lines_are_the_ones_print_geometry_publishes() -> None:
    """Bleed syntax is never invented here. The metadata route's two lines are
    lifted verbatim from `knowledge/export/print-geometry` for a 595×842 page."""

    body = POSTER.meta_and_body()[1]
    print_geometry = _read("knowledge", "export", "print-geometry.md")

    assert "bleed(-8.5,-8.5,612,859) safe_area(14,14,567,814)" in body
    assert "bleed(-8.5,-8.5,612,859) safe_area(14,14,567,814)" in print_geometry
    assert "bleed(true)" in body and "bleed(true)" in print_geometry
    assert "LUMV0801" in body


def test_the_poster_baked_route_defers_to_the_bleed_marks_skill() -> None:
    """The baked route is `skills/print-bleed-marks`' transform, restated only as a
    summary. Its three numbers must match that skill's own arithmetic for A4:
    +36pt per axis, a (+18,+18) child shift, and the bleed line at [9,9,W+18,H+18]."""

    body = POSTER.meta_and_body()[1]
    baked = _read("skills", "print-bleed-marks", "SKILL.md")

    assert "skills/print-bleed-marks" in body
    assert "631 x 878" in body  # 595+36 × 842+36
    assert "`[18,18,595,842]`" in body  # trim rect after the shift
    assert "`[9,9,613,860]`" in body  # bleed line = [9, 9, W+18, H+18]
    assert "(+18, +18)" in body

    # The source of those numbers, in the skill that owns them.
    assert "sheet** = `(W+36) × (H+36)` pt" in baked
    assert "**bleed line** = `[9, 9, W+18, H+18]`" in baked
    # And the two routes are still mutually exclusive per page.
    assert "mutually exclusive" in body and "mutually exclusive" in baked


def test_the_poster_press_colour_rules_come_from_print_geometry() -> None:
    """Near-black over pure black is a press fact this repo already states; the
    skill must quote the same hex rather than inventing one."""

    body = POSTER.meta_and_body()[1]
    print_geometry = _read("knowledge", "export", "print-geometry.md")

    assert "#0a0a0f" in body
    assert "#0a0a0f" in print_geometry
    assert "Never `#000000` for a large dark field" in body
    # The screen-only-effects rule leans on the vector-PDF advisory.
    assert "rasterize" in body
    assert "rasterize locally at the profile dpi" in _read(
        "knowledge", "lumen-dsl", "diagnostics.md"
    )


def test_the_poster_body_role_is_the_one_that_fits_an_a4_column() -> None:
    """`$type.body` overflows a 499pt column; the calibrated fact and its
    consequence both live in the block catalog, so the skill must not contradict it."""

    body = POSTER.meta_and_body()[1]
    patterns = _read("knowledge", "design", "blocks", "patterns.md")

    assert "`$type.body` overflows a 499pt column" in body
    assert "$type.body.small" in body
    assert "overflows a 499pt A4 column" in patterns
    # The headline width trap, with the corpus's own worked pair.
    assert "Recover every missed patient call." in body
    assert "Recover missed patient calls." in body
    assert "Recover missed patient calls." in patterns


def test_the_linkedin_banner_states_both_platform_sizes_as_page_lines() -> None:
    body = BANNER.meta_and_body()[1]

    assert "page linkedin_banner size(1584,396,px)" in body
    assert "page linkedin_cover size(1128,191,px)" in body
    assert "the platform's published sizes" in body


def test_the_linkedin_banner_overlap_allowance_is_consistent_and_conservative() -> None:
    """The profile photo eats the left of a personal banner. The reserved zone, the
    root padding, and the stated content box have to agree, or the author designs
    into a box the platform covers."""

    body = BANNER.meta_and_body()[1]

    assert "left of x = 480" in body
    assert "below y = 300" in body
    # 1584 - 480 - 64 = 1040 wide; 396 - 64 - 96 = 236 tall.
    assert "1040 x 236 pt" in body
    assert "pad(64,64,96,480)" in body
    assert "deliberately generous" in body


def test_the_linkedin_banner_refuses_the_cta_pretence() -> None:
    """It is ambient brand canvas. Nothing on it is clickable, so a button shape is
    a lie — and that is the one rule separating it from every other format here."""

    body = BANNER.meta_and_body()[1]

    assert "## No CTA, and why" in body
    assert "Nothing on a banner is clickable" in body
    assert "no-cta-pretence" in body
    # It also refuses the big type steps a feed ad reaches for.
    assert "Never step to `$type.size.7xl` (80) here" in body


# ============================================================================
# 5. §5.7 required decisions — machine-readable, and matching the table
# ============================================================================


@every_format_skill
def test_the_skill_declares_its_required_decisions_in_frontmatter(
    skill: FormatSkill,
) -> None:
    """The §5.7 consumer interface: a flat comma-separated `required_decisions:`
    list, deliberately the same shape as `assumes:` so the existing line reader
    parses it with no new machinery."""

    assert required_decision_keys(skill.text()) == list(skill.decisions)


@every_format_skill
def test_every_declared_decision_has_a_table_row_with_a_default(
    skill: FormatSkill,
) -> None:
    """The declaration and the table are two halves of one contract: the ids gate
    the clarification round, the rows supply the question text and the default an
    unanswered question falls back to. A declared id with no row would make the
    orchestrator ask a question it cannot phrase."""

    body = skill.meta_and_body()[1]
    rows = {
        match.group(1): match.group(0)
        for match in re.finditer(r"^\| `([a-z_]+)` \|.*\|$", body, re.MULTILINE)
    }

    for decision in required_decision_keys(skill.text()):
        assert decision in rows, f"`{decision}` is declared but has no table row"
        cells = [cell.strip() for cell in rows[decision].strip("|").split("|")]
        # id | question | why_it_matters | options | default
        assert len(cells) == 5, f"`{decision}` row has {len(cells)} cells, expected 5"
        assert cells[1].endswith("?"), f"`{decision}` question is not a question"
        assert cells[2], f"`{decision}` has no why_it_matters"
        assert cells[4], f"`{decision}` has no default — an unanswered question blocks"


@every_format_skill
def test_the_decision_table_columns_are_the_clarification_question_fields(
    skill: FormatSkill,
) -> None:
    """So the orchestrator can lift a row straight into `request_clarification`."""

    from lumen_agent.models.schemas import ClarificationQuestion

    body = skill.meta_and_body()[1]
    header = "| id | question | why_it_matters | options | default |"

    assert header in body
    columns = [cell.strip() for cell in header.strip("|").split("|")]
    assert set(columns) <= set(ClarificationQuestion.model_fields)


@every_format_skill
def test_the_skill_states_the_batched_clarification_contract(skill: FormatSkill) -> None:
    """One round, or proceed on the default and record the assumption. A format
    skill that declares decisions but not this protocol invites a question drip."""

    body = re.sub(r"\s+", " ", skill.meta_and_body()[1])

    assert "a single batched `request_clarification` round" in body
    assert 'record_gap(area="agent_protocol"' in body


def test_a_skill_with_no_declaration_gates_on_nothing() -> None:
    """Every craft skill returns `[]`, so "no declaration" is safely "nothing to
    ask about" rather than a crash or a false gate."""

    for skill_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        if skill_dir.name in FORMAT_SKILL_NAMES:
            continue
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        assert required_decision_keys(text) == [], skill_dir.name


# ============================================================================
# 5b. §6.1 `selection_policy` — declared, defaulted, and honest about being inert
# ============================================================================


@every_format_skill
def test_every_format_skill_declares_its_selection_policy(skill: FormatSkill) -> None:
    """Each format declares the value explicitly rather than leaning on the default,
    so the field records the intended mode while the dispatcher is still unbuilt.
    Four are chosen by trigger-phrase matching (`llm_selectable`); `a4-poster` is the
    §6.1 print case, where a page size plus a bleed requirement settles the format
    outright, so it declares `deterministic`."""

    meta = skill.meta_and_body()[0]

    assert meta.get("selection_policy") == skill.policy
    assert selection_policy(skill.text()) == skill.policy


def test_exactly_one_format_skill_is_deterministic_and_it_is_the_print_one() -> None:
    deterministic = [s.name for s in FORMAT_SKILLS if s.policy == "deterministic"]

    assert deterministic == ["a4-poster"]


def test_selection_policy_defaults_to_llm_selectable_when_undeclared() -> None:
    """Every craft skill declares nothing, and must keep today's behavior. "No
    declaration" has to mean "the orchestrator picks it", never a crash and never a
    silent switch to deterministic dispatch."""

    for skill_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        if skill_dir.name in FORMAT_SKILL_NAMES:
            continue
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        assert "selection_policy" not in parse_frontmatter(text)[0], skill_dir.name
        assert selection_policy(text) == DEFAULT_SELECTION_POLICY, skill_dir.name


def test_selection_policy_reads_deterministic_and_degrades_a_bad_value() -> None:
    """`deterministic` is the other real value (§6.1's print case). Anything else —
    a typo, an empty value — degrades to the default rather than failing a turn,
    because the field is advisory and no turn should die on it."""

    def _doc(declared: str) -> str:
        return f"---\nname: x\nselection_policy: {declared}\n---\n\nbody\n"

    assert selection_policy(_doc("deterministic")) == "deterministic"
    assert set(SELECTION_POLICIES) == {"llm_selectable", "deterministic"}

    for bad in ("", "  ", "Deterministic", "always", "llm-selectable"):
        assert selection_policy(_doc(bad)) == DEFAULT_SELECTION_POLICY, bad

    # A skill with no frontmatter at all is still safe to ask about.
    assert selection_policy("no frontmatter here") == DEFAULT_SELECTION_POLICY


def test_the_spec_documents_selection_policy_as_not_yet_consumed() -> None:
    """The field is declared ahead of its consumer. If that stops being true the
    spec text must change with it — a reader who believes `deterministic` already
    routes anything would be wrong today."""

    spec = (
        RUNTIME_ROOT.parents[1] / "docs" / "deepagent-fast-loop-v1-spec.md"
    ).read_text(encoding="utf-8")

    assert "`selection_policy:`" in spec
    for value in SELECTION_POLICIES:
        assert value in spec
    assert "Document-only in v1 — nothing consumes this field yet." in spec

    # And it really is unconsumed: the reader has no caller outside its own module
    # and this suite.
    agent_pkg = RUNTIME_ROOT / "lumen_agent"
    callers = [
        path.name
        for path in agent_pkg.rglob("*.py")
        if path.name != "knowledge.py" and "selection_policy" in path.read_text(encoding="utf-8")
    ]
    assert not callers, f"selection_policy now has production callers: {callers}"


# ============================================================================
# 6. The §8 self-audit checklist — every named test survives
# ============================================================================


@every_format_skill
def test_every_named_self_audit_test_is_present(skill: FormatSkill) -> None:
    """These names are the §5.3 rubric `critique.json` scores against; dropping one
    silently drops a defect class the retired reviewer used to catch."""

    body = skill.meta_and_body()[1]

    for named_test in skill.audit_tests:
        assert named_test in body, f"{skill.name} lost self-audit test {named_test!r}"
    assert len(skill.audit_tests) >= 7, f"{skill.name} scores fewer than seven tests"


def test_the_collision_test_says_why_geometry_cannot_score_it() -> None:
    """`no-collisions` is an eyes test, and the reason is mechanical rather than
    a matter of taste: the engine measures a line as font size x line height, so
    tight leading shrinks the measured box in step with the text and the spill is
    never reported. Without that explanation the author will try to score it from
    `inspect` and find nothing wrong."""

    body = _meta_and_body()[1]

    assert "no-collisions" in body
    assert "font size times line height" in body
    assert "preflight perfectly clean" in body
    # It must also say what to do, or it is only a complaint.
    assert "more line height, more gap, or fewer words" in body


@every_format_skill
def test_the_self_audit_writes_the_real_critique_shape(skill: FormatSkill) -> None:
    """`VisualCritique` has no numeric per-test score field, so the 0–2 scores must
    land in fields that exist — `acceptance_notes` and `issues[]` — or the author
    invents a key that fails validation."""

    from lumen_agent.models.schemas import CritiqueCategory, VisualCritique

    body = skill.meta_and_body()[1]

    assert "critique.json" in body
    for field in ("acceptance_notes", "issues", "accepted=false"):
        assert field in body
    assert set(VisualCritique.model_fields) >= {"accepted", "acceptance_notes", "issues"}

    # The categories it routes failures to are real enum members.
    cited = set(re.findall(r"\(`([a-z_]+)`\)$", body, re.MULTILINE))
    assert cited, f"{skill.name} cites no critique categories"
    assert cited <= {member.value for member in CritiqueCategory}, (
        f"not CritiqueCategory members: {sorted(cited - {m.value for m in CritiqueCategory})}"
    )
    # One category per named test, so no test lands in `issues[]` uncategorized.
    assert len(re.findall(r"\(`[a-z_]+`\)$", body, re.MULTILINE)) == len(skill.audit_tests)


@every_format_skill
def test_the_self_audit_is_render_gated_not_geometry_gated(skill: FormatSkill) -> None:
    """§5.2: geometry says nothing about how the artifact READS. Both baseline
    failures (cropped baked-in text, unreadable CTA) were visible in one render."""

    # Prose wraps, so compare against whitespace-collapsed text — otherwise the
    # assertion passes or fails on where the paragraph happens to break.
    body = re.sub(r"\s+", " ", skill.meta_and_body()[1].lower())

    assert "after looking at the render" in body
    assert "never from geometry" in body


@every_format_skill
def test_the_self_audit_scores_with_measurements_not_adjectives(
    skill: FormatSkill,
) -> None:
    """A score written as an adjective is not a score. "Looks clean" is how a weak
    design passes its own audit, so the skill has to demand a fact against the named
    test — and show what one looks like."""

    body = re.sub(r"\s+", " ", skill.meta_and_body()[1].lower())

    assert "never with adjectives" in body
    assert "looks clean" in body
    # It does not just ban the bad form; it shows the good one.
    assert "facts and measurements" in body


@every_format_skill
def test_the_override_clause_is_last_and_records_the_gap(skill: FormatSkill) -> None:
    body = skill.meta_and_body()[1]

    assert "## Override" in body
    assert body.rstrip().endswith("`record_gap`.")


# ============================================================================
# 7. Ruling R6 — the follow-on formats have LANDED (this is the decision)
# ============================================================================


def test_the_r6_follow_on_formats_are_present_and_guarded() -> None:
    """R6 sequenced four follow-on formats after the pilot. The predecessor of this
    test asserted their ABSENCE so that shipping one early would be a decision
    rather than a drift. **This wave is that decision**: `story-ad-9x16`,
    `web-display-banners`, `a4-poster`, and `linkedin-banner` are now in the tree
    and every guard above runs over all five.

    One deliberate deviation from the spec's §6.2 wording: the spec names
    `banner-2x1`, a single aspect ratio. The shipped skill is
    `web-display-banners`, which carries the whole IAB family (728×90, 970×250,
    300×250, 300×600, 160×600, 320×50) in one place, because a display brief
    almost never arrives as one ratio and the six units share every rule except
    their type floors. Recorded here rather than silently renamed."""

    present = {p.name for p in SKILLS_DIR.iterdir() if p.is_dir()}

    assert FORMAT_SKILL_NAMES <= present
    # Nothing that R6 sequenced is still missing under its spec name either.
    assert "banner-2x1" not in present, "two banner skills would split the format"


def test_the_format_layer_is_exactly_the_declared_roster() -> None:
    """A format skill added to the tree without a row in `FORMAT_SKILLS` would ship
    unguarded — no path check, no token check, no self-audit check. Detect it by the
    one thing only a format skill declares."""

    declaring: set[str] = set()
    for skill_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        meta = parse_frontmatter(text)[0]
        if "required_decisions" in meta or "selection_policy" in meta:
            declaring.add(skill_dir.name)

    assert declaring == set(FORMAT_SKILL_NAMES)


# ============================================================================
# 8. The craft docs' engine claims are pinned to the engine
# ============================================================================

CRATES = RUNTIME_ROOT.parents[1] / "crates" / "lumen-core" / "src"
FOUNDATIONS = KNOWLEDGE_DOCS / "knowledge" / "design" / "foundations.md"


def test_the_slack_guidance_matches_the_layout_solver() -> None:
    """`foundations`' "Spend the slack" block tells the author what the engine does
    with leftover main-axis space. That is a claim about code, not taste, so it goes
    stale silently if the solver changes. Pin the two load-bearing facts to source:
    the anchor set really is these five, and `space_between` really is the only one
    that puts space BETWEEN children."""

    body = FOUNDATIONS.read_text(encoding="utf-8")
    scene = (CRATES / "scene.rs").read_text(encoding="utf-8")
    layout = (CRATES / "layout.rs").read_text(encoding="utf-8")

    # The doc says the anchor set is exactly s / c / e / sb / st and nothing else.
    assert "no space-around and no space-evenly" in body
    assert "The anchor set is `s`, `c`, `e`, `sb`, `st`" in body
    anchors = re.search(r"pub enum LayoutAnchor \{(.*?)\}", scene, re.S)
    assert anchors, "LayoutAnchor enum not found — the pin needs re-pointing"
    assert [v.strip().rstrip(",") for v in anchors.group(1).strip().splitlines()] == [
        "Start",
        "Center",
        "End",
        "SpaceBetween",
        "Stretch",
    ]

    # …and the main-axis mapping the doc describes: SpaceBetween is the only
    # distributing value, and Stretch degrades to Start rather than distributing.
    main_axis = re.search(
        r"fn main_axis_alignment\(.*?\) -> JustifyContent \{(.*?)\n\}", layout, re.S
    )
    assert main_axis, "main_axis_alignment not found — the pin needs re-pointing"
    arms = main_axis.group(1)
    assert "LayoutAnchor::Start | LayoutAnchor::Stretch => JustifyContent::Start" in arms
    assert "LayoutAnchor::SpaceBetween => JustifyContent::SpaceBetween" in arms
    assert "SpaceAround" not in arms and "SpaceEvenly" not in arms


def test_the_slack_guidance_names_the_right_axis_and_the_default() -> None:
    """The two facts an author gets wrong first: in `al(v, …)` it is `y(…)` that
    distributes (not `x(…)`), and the default is top-pack. Both are asserted in the
    doc and both come straight off the solver's direction switch and the anchor
    default."""

    body = FOUNDATIONS.read_text(encoding="utf-8")
    layout = (CRATES / "layout.rs").read_text(encoding="utf-8")
    scene = (CRATES / "scene.rs").read_text(encoding="utf-8")

    assert "the distributing anchor is `y(…)`" in body
    assert "The default is top-pack." in body
    assert "Nothing stretches on its own." in body

    # Column's main (justifying) axis is align_y; Row's is align_x. Match the
    # direction switch itself, so the `flex_grow` arm earlier in the file — which
    # also opens with `AutoLayoutDirection::Column` — cannot satisfy this.
    switch = re.search(
        r"AutoLayoutDirection::Row => \{\s*"
        r"style\.justify_content = Some\(main_axis_alignment\(&props\.(\w+)\)\);"
        r".*?"
        r"AutoLayoutDirection::Column => \{\s*"
        r"style\.justify_content = Some\(main_axis_alignment\(&props\.(\w+)\)\);",
        layout,
        re.S,
    )
    assert switch, "the direction/justify switch was not found — re-point this pin"
    assert switch.groups() == ("align_x", "align_y")

    # And an undeclared anchor really does start-pack.
    assert "fn default_layout_anchor_start" in scene
    assert "LayoutAnchor::Start" in scene

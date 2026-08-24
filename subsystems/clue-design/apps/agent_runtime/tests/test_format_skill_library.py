"""The format-skill library (fast-loop spec §6) and its pilot, `linkedin-square-ad`.

A format skill sits ABOVE the craft skills: it pre-makes one artifact format's
decisions (surface, skeletons, type floors, brevity budgets, named self-audit
tests) so the author stops rediscovering them. That only pays off if the skill is
**loadable**, **discoverable**, and **true about this repo** — a skill citing a
phantom token or a knowledge file that does not exist sends the author hunting,
which is exactly the cost §6 exists to kill. So this suite guards:

- it loads the way its siblings do (frontmatter `name`/`description`, one dir);
- the description carries the trigger phrases the orchestrator matches on, and
  stays on ONE line (`parse_frontmatter` is a `key: value` line reader — a wrapped
  description silently loses everything after the first line);
- §6.1's composition rule: it names the craft skills it composes with and the
  knowledge files to pin, and **every one of those paths resolves**;
- **every `$token`, DSL form, and archetype name it cites exists in the repo**;
- §5.7's required-decisions contract is machine-readable (`required_decisions:`
  frontmatter) AND matches the human-readable table;
- the §8 self-audit tests are all present;
- the agent's root doc (`AGENT.md`) indexes it;
- ruling R6's sequencing: the follow-on formats are NOT here yet.
"""

from __future__ import annotations

import re
import types
from pathlib import Path

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

# The phrases the orchestrator's progressive-disclosure match runs against. They
# live in the `description` because that (plus `name`) is ALL a subagent sees
# until it opens the skill — see `harness.py`'s SkillsMiddleware wiring note.
TRIGGER_PHRASES = ("linkedin ad", "feed ad", "square social ad", "1:1 paid social")

# Ruling R6: these ship only after the pilot's metrics hold.
DEFERRED_FORMAT_SKILLS = ("story-ad-9x16", "banner-2x1", "a4-poster", "linkedin-banner")


def _skill_text() -> str:
    return SKILL_FILE.read_text(encoding="utf-8")


def _meta_and_body() -> tuple[dict[str, str], str]:
    return parse_frontmatter(_skill_text())


def _corpus() -> str:
    """Every OTHER authored knowledge doc, concatenated — the oracle for "does this
    token / archetype / DSL form actually exist", so the skill can only cite things
    the tree already teaches."""

    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(KNOWLEDGE_DOCS.rglob("*.md"))
        if path != SKILL_FILE
    )


# ============================================================================
# 1. It loads (registration is implicit, by directory)
# ============================================================================


def test_the_pilot_format_skill_is_a_directory_in_the_authored_tree() -> None:
    assert SKILL_FILE.is_file()


def test_the_pilot_skill_parses_with_a_name_matching_its_directory() -> None:
    meta, body = _meta_and_body()

    assert meta.get("name") == SKILL_NAME
    assert meta.get("description")
    assert body.strip()


def test_the_materializer_serves_the_pilot_skill_to_the_agent(tmp_path) -> None:
    """The load smoke over the REAL tree: the skill lands on both surfaces the agent
    reads — `/.deepagent/skills/` (the SkillsMiddleware source) and the
    `/knowledge_docs/` copy that intra-doc references resolve against."""

    ws = tmp_path / "ws"
    materialize_agent_workspace(types.SimpleNamespace(workspace_root=ws))

    served = ws / ".deepagent" / "skills" / SKILL_NAME / "SKILL.md"
    assert served.is_file()
    assert served.read_text(encoding="utf-8") == _skill_text()
    assert (ws / "knowledge_docs" / "skills" / SKILL_NAME / "SKILL.md").is_file()


# ============================================================================
# 2. It is discoverable — trigger phrases, on one line
# ============================================================================


def test_the_description_carries_every_trigger_phrase() -> None:
    description = _meta_and_body()[0]["description"].lower()

    for phrase in TRIGGER_PHRASES:
        assert phrase in description, f"description does not trigger on {phrase!r}"


def test_the_description_survives_the_frontmatter_line_reader() -> None:
    """`parse_frontmatter` splits on the FIRST colon of each line and keeps no
    continuations, so a description wrapped across lines silently loses its tail —
    and with it the trigger phrases. Guard the whole declaration, not just the
    parsed value: assert the raw frontmatter holds `description:` exactly once and
    that no wrapped continuation line follows it."""

    raw = _skill_text().split("---", 2)[1]
    lines = [line for line in raw.splitlines() if line.strip()]
    description_lines = [i for i, line in enumerate(lines) if line.startswith("description:")]

    assert len(description_lines) == 1
    for line in lines:
        assert line == line.lstrip(), f"wrapped frontmatter line is dropped: {line!r}"

    # The parsed value is the whole declaration, tail included.
    assert _meta_and_body()[0]["description"].endswith("creative.")


def test_the_root_agent_doc_indexes_the_pilot_skill_with_its_triggers() -> None:
    text = (KNOWLEDGE_DOCS / "AGENT.md").read_text(encoding="utf-8")
    lowered = text.lower()

    # Both surfaces a reader lands on: the §4 knowledge map and the §5 skills index.
    assert f"skills/{SKILL_NAME}" in text
    assert f"skills/{SKILL_NAME}/SKILL.md" in text
    for phrase in TRIGGER_PHRASES:
        assert phrase in lowered, f"AGENT.md does not route {phrase!r} to the skill"


# ============================================================================
# 3. §6.1 composition — it names what it composes with, and those paths RESOLVE
# ============================================================================


def test_the_skill_names_the_craft_skills_it_composes_with() -> None:
    body = _meta_and_body()[1]

    assert "skills/brand-and-tokens" in body
    assert "skills/brand-imagery" in body
    # It sits ABOVE create-design, so it must not silently duplicate the craft
    # layer's job: the composition pointers are the seam.
    assert "skills/clarify-design-brief" in body


def test_every_skill_and_knowledge_path_the_skill_cites_exists() -> None:
    """The anti-phantom test. A pointer to a file that is not there is the exact
    failure this work kills — the author greps for it and burns calls."""

    body = _meta_and_body()[1]
    missing: list[str] = []

    for ref in sorted(set(re.findall(r"`(skills/[a-z0-9-]+)`", body))):
        if not (KNOWLEDGE_DOCS / f"{ref}/SKILL.md").is_file():
            missing.append(f"{ref}/SKILL.md")

    for ref in sorted(set(re.findall(r"`(knowledge/[a-z0-9/-]+)`", body))):
        if not (KNOWLEDGE_DOCS / f"{ref}.md").is_file():
            missing.append(f"{ref}.md")

    assert not missing, f"the skill points at files that do not exist: {missing}"


def test_the_pinned_knowledge_files_are_the_ones_the_format_actually_needs() -> None:
    body = _meta_and_body()[1]

    for pinned in (
        "knowledge/design/layout-recipes",  # the archetype canon it selects from
        "knowledge/design/blocks/patterns",  # the validated 1080² proportions
        "knowledge/design/foundations",  # squint test + contrast floors
        "knowledge/design/font-library",  # the display voices it names
    ):
        assert pinned in body


# ============================================================================
# 4. Every token / DSL form / archetype it cites is real
# ============================================================================


def test_every_token_the_skill_cites_exists_elsewhere_in_the_corpus() -> None:
    """A `$token` the tree never teaches is a phantom: the author cannot resolve it
    and preflight will not either. Every token here must already appear in another
    authored doc (the taxonomy, the ramp, or a validated block)."""

    body = _meta_and_body()[1]
    corpus = _corpus()
    ramp = (KNOWLEDGE_DOCS / "knowledge" / "lumen-dsl" / "text.md").read_text(
        encoding="utf-8"
    )

    tokens = sorted(set(re.findall(r"\$[a-z]+(?:\.[a-z0-9]+)+", body)))
    assert tokens, "the skill cites no tokens at all — it stopped being concrete"

    def _taught(token: str) -> bool:
        if token in corpus:
            return True
        # The size ramp is published once, in shorthand — `$type.size.xs=12  sm=14
        # … 9xl=128` — so a legitimate step like `$type.size.9xl` never appears
        # fully qualified. Resolve those against the ramp's own declaration.
        step = token.removeprefix("$type.size.")
        return step != token and re.search(rf"\b{re.escape(step)}=\d+", ramp) is not None

    unknown = [token for token in tokens if not _taught(token)]
    assert not unknown, f"phantom tokens (not taught anywhere in knowledge_docs): {unknown}"


def test_the_surface_command_is_the_canonical_one() -> None:
    """`page linkedin_square size(1080,1080,px)` is the exact line every validated
    1080² skeleton opens with; a variant page id would drift the format away from
    the canon it tells the author to recompose."""

    body = _meta_and_body()[1]
    surface = "page linkedin_square size(1080,1080,px)"

    assert surface in body
    assert surface in (
        KNOWLEDGE_DOCS / "knowledge" / "design" / "layout-recipes.md"
    ).read_text(encoding="utf-8")


def test_the_slot_repair_line_matches_the_grammar_as_it_stands() -> None:
    """P0.2 gave image-like slots a born default policy AND the
    `#slot:key image_policy(...)` modify line. The skill's LUMV0820 guidance must
    match that grammar — the modify-line form, the `fit=`/`focal_x=` field spelling,
    and the 'never delete the slot' rule."""

    body = _meta_and_body()[1]
    grammar = (KNOWLEDGE_DOCS / "knowledge" / "lumen-dsl" / "grammar.md").read_text(
        encoding="utf-8"
    )

    assert "#slot:account.logo image_policy(fit=cover," in body
    assert "LUMV0820" in body
    assert "never delete the slot" in body.lower()
    # The grammar this is written against: the modify-line form and the kwarg spelling.
    assert "#slot:account.logo image_policy(fit=cover" in grammar
    assert "born with the default policy" in grammar


def test_the_named_archetypes_are_the_canon_ones() -> None:
    body = _meta_and_body()[1].lower()
    recipes = (
        KNOWLEDGE_DOCS / "knowledge" / "design" / "layout-recipes.md"
    ).read_text(encoding="utf-8")

    for archetype in ("split-panel", "vertical-poster", "numeral-hero"):
        assert archetype in body
        assert archetype in recipes


def test_the_named_display_faces_are_in_the_font_library() -> None:
    body = _meta_and_body()[1]
    library = (KNOWLEDGE_DOCS / "knowledge" / "design" / "font-library.md").read_text(
        encoding="utf-8"
    )

    for face in ("Anton", "Bebas Neue", "Archivo Black", "Bricolage Grotesque"):
        assert face in body
        assert f"| {face} |" in library, f"{face} is not a library family"


# ============================================================================
# 5. §5.7 required decisions — machine-readable, and matching the table
# ============================================================================


def test_the_skill_declares_its_required_decisions_in_frontmatter() -> None:
    """The §5.7 consumer interface: a flat comma-separated `required_decisions:`
    list, deliberately the same shape as `assumes:` so the existing line reader
    parses it with no new machinery."""

    assert required_decision_keys(_skill_text()) == [
        "audience",
        "offer_cta",
        "tone",
        "brand_adherence",
    ]


def test_every_declared_decision_has_a_table_row_with_a_default() -> None:
    """The declaration and the table are two halves of one contract: the ids gate
    the clarification round, the rows supply the question text and the default an
    unanswered question falls back to. A declared id with no row would make the
    orchestrator ask a question it cannot phrase."""

    body = _meta_and_body()[1]
    rows = {
        match.group(1): match.group(0)
        for match in re.finditer(r"^\| `([a-z_]+)` \|.*\|$", body, re.MULTILINE)
    }

    for decision in required_decision_keys(_skill_text()):
        assert decision in rows, f"`{decision}` is declared but has no table row"
        cells = [cell.strip() for cell in rows[decision].strip("|").split("|")]
        # id | question | why_it_matters | options | default
        assert len(cells) == 5, f"`{decision}` row has {len(cells)} cells, expected 5"
        assert cells[1].endswith("?"), f"`{decision}` question is not a question"
        assert cells[2], f"`{decision}` has no why_it_matters"
        assert cells[4], f"`{decision}` has no default — an unanswered question blocks"


def test_the_decision_table_columns_are_the_clarification_question_fields() -> None:
    """So the orchestrator can lift a row straight into `request_clarification`."""

    from lumen_agent.models.schemas import ClarificationQuestion

    body = _meta_and_body()[1]
    header = "| id | question | why_it_matters | options | default |"

    assert header in body
    columns = [cell.strip() for cell in header.strip("|").split("|")]
    assert set(columns) <= set(ClarificationQuestion.model_fields)


def test_a_skill_with_no_declaration_gates_on_nothing() -> None:
    """Every craft skill returns `[]`, so "no declaration" is safely "nothing to
    ask about" rather than a crash or a false gate."""

    for skill_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        if skill_dir.name == SKILL_NAME:
            continue
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        assert required_decision_keys(text) == [], skill_dir.name


# ============================================================================
# 5b. §6.1 `selection_policy` — declared, defaulted, and honest about being inert
# ============================================================================


def test_the_pilot_skill_declares_an_llm_selectable_selection_policy() -> None:
    """The pilot is chosen by the orchestrator matching its trigger phrases, which
    is exactly what `llm_selectable` names. It declares the value explicitly rather
    than leaning on the default, so the field has one worked example in the tree."""

    meta = _meta_and_body()[0]

    assert meta.get("selection_policy") == "llm_selectable"
    assert selection_policy(_skill_text()) == "llm_selectable"


def test_selection_policy_defaults_to_llm_selectable_when_undeclared() -> None:
    """Every craft skill declares nothing, and must keep today's behavior. "No
    declaration" has to mean "the orchestrator picks it", never a crash and never a
    silent switch to deterministic dispatch."""

    for skill_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        if skill_dir.name == SKILL_NAME:
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


def test_every_named_self_audit_test_is_present() -> None:
    """These names are the §5.3 rubric `critique.json` scores against; dropping one
    silently drops a defect class the retired reviewer used to catch."""

    body = _meta_and_body()[1]

    for named_test in (
        "single-focal-point",
        "first-second-ordering",
        "headline-budget",
        "cta-thumbnail-legibility",
        "distinctive-asset-at-real-scale",
        "safe-margins",
        # Added 2026-08-24 after acceptance run #1 shipped a headline sitting on
        # its body copy. No engine diagnostic covers content colliding with
        # content, so this test is the only thing that catches the class.
        "no-collisions",
        "brand-adherence-followed",
    ):
        assert named_test in body, f"self-audit test {named_test!r} is missing"


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


def test_the_self_audit_writes_the_real_critique_shape() -> None:
    """`VisualCritique` has no numeric per-test score field, so the 0–2 scores must
    land in fields that exist — `acceptance_notes` and `issues[]` — or the author
    invents a key that fails validation."""

    from lumen_agent.models.schemas import CritiqueCategory, VisualCritique

    body = _meta_and_body()[1]

    assert "critique.json" in body
    for field in ("acceptance_notes", "issues", "accepted=false"):
        assert field in body
    assert set(VisualCritique.model_fields) >= {"accepted", "acceptance_notes", "issues"}

    # The categories it routes failures to are real enum members.
    cited = set(re.findall(r"\(`([a-z_]+)`\)$", body, re.MULTILINE))
    assert cited, "no critique categories cited"
    assert cited <= {member.value for member in CritiqueCategory}, (
        f"not CritiqueCategory members: {sorted(cited - {m.value for m in CritiqueCategory})}"
    )


def test_the_self_audit_is_render_gated_not_geometry_gated() -> None:
    """§5.2: geometry says nothing about how the ad READS. Both baseline failures
    (cropped baked-in text, unreadable CTA) were visible in one render."""

    # Prose wraps, so compare against whitespace-collapsed text — otherwise the
    # assertion passes or fails on where the paragraph happens to break.
    body = re.sub(r"\s+", " ", _meta_and_body()[1].lower())

    assert "after looking at the render" in body
    assert "never from geometry" in body


def test_the_self_audit_scores_with_measurements_not_adjectives() -> None:
    """A score written as an adjective is not a score. "Looks clean" is how a weak
    design passes its own audit, so the skill has to demand a fact against the named
    test — and show what one looks like."""

    body = re.sub(r"\s+", " ", _meta_and_body()[1].lower())

    assert "never with adjectives" in body
    assert "looks clean" in body
    # It does not just ban the bad form; it shows the good one.
    assert "facts and measurements" in body


def test_the_override_clause_is_last_and_records_the_gap() -> None:
    body = _meta_and_body()[1]

    assert "## Override" in body
    assert body.rstrip().endswith("`record_gap`.")


# ============================================================================
# 7. Ruling R6 — the follow-on formats are sequenced AFTER the pilot
# ============================================================================


def test_the_format_layer_is_the_pilot_alone() -> None:
    """R6 sequences `story-ad-9x16`, `banner-2x1`, `a4-poster`, `linkedin-banner`
    after the pilot's metrics hold. Shipping one early would put an unvalidated
    format skill in front of the author. Update this list deliberately, with the
    metrics, when a follow-on lands."""

    present = {p.name for p in SKILLS_DIR.iterdir() if p.is_dir()}

    assert SKILL_NAME in present
    assert not present.intersection(DEFERRED_FORMAT_SKILLS)


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

"""`skills/generative-imagery` (Brand Ad Assets v1 §5 W3, ruling D7).

A craft skill for the generated image itself: how to prompt for it, how to keep
it on-brand, and how to use what comes back. Its value is entirely in being
**true about this repo** — a skill that names a tool action, a call parameter, or
a result field that does not exist sends the author hunting, and a skill that
describes generation behaviour the code does not have teaches a fiction the
author then reports as fact.

So this suite is the anti-phantom guard from `test_format_skill_library.py`,
pointed at this skill and widened one step: that suite's oracle is the authored
markdown corpus, which can only catch a phantom `$token` or a dead knowledge
path. This skill's load-bearing claims are about **tool vocabulary and runtime
behaviour**, so the oracle here is the Python source that implements them —
`tools/substrate.py`, `tools/view.py`, and `lumen_api/image_provider.py`. Plant
a `generate_backdrop` action or an `actual_ratio` result field and §3 fails.

It also guards the two ways a skill silently stops working:

- the `description` staying on ONE line (`parse_frontmatter` is a `key: value`
  line reader — a wrapped description loses everything after the first line, and
  with it the trigger phrases the orchestrator matches on);
- `AGENT.md` indexing it, so the doc map routes to it the way it routes to every
  other craft skill.

And the generalization rule the colour skill established: illustrative hexes stay
in examples, never in a normative rule (a skill that says "use #FEFF00" teaches
one brand's yellow to every brand).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lumen_agent.knowledge import parse_frontmatter, required_decision_keys

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
DESIGN_ROOT = RUNTIME_ROOT.parents[1]
KNOWLEDGE_DOCS = RUNTIME_ROOT / "knowledge_docs"
SKILLS_DIR = KNOWLEDGE_DOCS / "skills"

SKILL_NAME = "generative-imagery"
SKILL_FILE = SKILLS_DIR / SKILL_NAME / "SKILL.md"

# The Python that actually implements the surface the skill describes. Anything
# the skill names in code voice has to appear in here.
CODE_SOURCES = (
    RUNTIME_ROOT / "lumen_agent" / "tools" / "substrate.py",
    RUNTIME_ROOT / "lumen_agent" / "tools" / "view.py",
    RUNTIME_ROOT / "lumen_agent" / "brand_card.py",
    DESIGN_ROOT / "apps" / "api" / "lumen_api" / "image_provider.py",
)


def _text() -> str:
    return SKILL_FILE.read_text(encoding="utf-8")


def _body() -> str:
    return parse_frontmatter(_text())[1]


def _markdown_corpus() -> str:
    """Every authored knowledge doc EXCEPT this skill, concatenated.

    Same oracle shape as the format-skill suite: a doc cannot validate its own
    invention, so it is excluded from the corpus that judges it.
    """

    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(KNOWLEDGE_DOCS.rglob("*.md"))
        if path != SKILL_FILE
    )


def _code_corpus() -> str:
    missing = [path for path in CODE_SOURCES if not path.is_file()]
    assert not missing, f"the code oracle moved: {missing}"
    return "\n".join(path.read_text(encoding="utf-8") for path in CODE_SOURCES).lower()


# Backticked spans that are NOT code voice: doc pointers (`skills/…`,
# `knowledge/…`) are checked by the path guard, `$tokens` by the token guard.
def _code_spans(body: str) -> list[str]:
    spans = re.findall(r"`([^`\n]+)`", body)
    return [span for span in spans if "/" not in span and not span.startswith("$")]


def _code_identifiers(body: str) -> set[str]:
    """Every identifier the skill uses in code voice, 3+ chars.

    Two-character fragments (`ok`, `id`, `n`) are dropped: they carry no
    anti-phantom signal and would only add noise.
    """

    found: set[str] = set()
    for span in _code_spans(body):
        for word in re.findall(r"[a-z_][a-z0-9_]*", span.lower()):
            if len(word) >= 3:
                found.add(word)
    return found


# --- 1. It loads the way its siblings do -----------------------------------


def test_the_skill_exists_as_one_directory_with_one_skill_file() -> None:
    assert SKILL_FILE.is_file(), f"{SKILL_NAME} is not in the tree"
    assert sorted(p.name for p in SKILL_FILE.parent.iterdir()) == ["SKILL.md"]


def test_the_frontmatter_names_the_directory_and_carries_a_body() -> None:
    meta, body = parse_frontmatter(_text())

    assert meta.get("name") == SKILL_NAME
    assert meta.get("description", "").strip()
    assert body.strip()


def test_the_description_survives_the_frontmatter_line_reader() -> None:
    """`parse_frontmatter` splits each line on its FIRST colon and keeps no
    continuations, so a description wrapped across lines silently loses its tail —
    and with it the trigger sentence. Guard the raw declaration, not just the
    parsed value."""

    raw = _text().split("---", 2)[1]
    lines = [line for line in raw.splitlines() if line.strip()]
    description_lines = [i for i, line in enumerate(lines) if line.startswith("description:")]

    assert len(description_lines) == 1
    for line in lines:
        assert line == line.lstrip(), f"wrapped frontmatter line is dropped: {line!r}"

    # The parsed value is the whole declaration, tail included — the description
    # closes on its trigger sentence, which is exactly what a wrap would eat.
    description = parse_frontmatter(_text())[0]["description"]
    assert description.rstrip().endswith(".")
    assert "Use whenever" in description


def test_it_is_a_craft_skill_not_a_format_skill() -> None:
    """Format skills declare `required_decisions` / `selection_policy` and are a
    closed roster (`test_the_format_layer_is_exactly_the_declared_roster`). This
    one composes with every format instead of competing with them, so it declares
    neither — and gates on nothing."""

    meta = parse_frontmatter(_text())[0]

    assert "required_decisions" not in meta
    assert "selection_policy" not in meta
    assert required_decision_keys(_text()) == []


# --- 2. Anti-phantom: doc pointers and tokens ------------------------------


def test_every_skill_and_knowledge_path_the_skill_cites_exists() -> None:
    body = _body()
    missing: list[str] = []

    for ref in sorted(set(re.findall(r"`(skills/[a-z0-9-]+)`", body))):
        if not (KNOWLEDGE_DOCS / f"{ref}/SKILL.md").is_file():
            missing.append(f"{ref}/SKILL.md")

    for ref in sorted(set(re.findall(r"`(knowledge/[a-z0-9/-]+)`", body))):
        if not (KNOWLEDGE_DOCS / f"{ref}.md").is_file():
            missing.append(f"{ref}.md")

    assert missing == [], f"{SKILL_NAME} points at files that do not exist: {missing}"


def test_every_token_the_skill_cites_exists_elsewhere_in_the_corpus() -> None:
    """A `$token` the tree never teaches is a phantom: the author cannot resolve
    it and preflight will not either."""

    body = _body()
    corpus = _markdown_corpus()

    tokens = sorted(set(re.findall(r"\$[a-z]+(?:\.[a-z0-9]+)+", body)))
    assert tokens, f"{SKILL_NAME} cites no tokens at all — it stopped being concrete"

    unknown = [token for token in tokens if token not in corpus]
    assert unknown == [], f"{SKILL_NAME} cites phantom tokens: {unknown}"


# --- 3. Anti-phantom: tool vocabulary, against the real Python --------------


def test_every_asset_action_the_skill_cites_is_a_real_action() -> None:
    """The tool enumerates its own valid actions in its unknown-action error.
    Read that list rather than restating it here, so a renamed action fails."""

    substrate = (RUNTIME_ROOT / "lumen_agent" / "tools" / "substrate.py").read_text(
        encoding="utf-8"
    )
    block = substrate.split("valid_actions=[", 1)[1].split("]", 1)[0]
    real_actions = set(re.findall(r'"([a-z_]+)"', block))
    assert "generate_image" in real_actions, "the action enumeration moved"

    cited = sorted(set(re.findall(r'action="([a-z_]+)"', _body())))
    assert cited, f"{SKILL_NAME} names no asset action — it stopped being concrete"

    unknown = [action for action in cited if action not in real_actions]
    assert unknown == [], f"{SKILL_NAME} cites phantom asset actions: {unknown}"


def test_every_identifier_the_skill_names_in_code_voice_exists_in_the_code() -> None:
    """The widened anti-phantom guard. Every backticked identifier — tool name,
    call parameter, result field, literal — must appear in the Python that
    implements it. A skill that promises `actual_ratio` or `condition_on_refs`
    costs the author a hunt and then a wrong report."""

    identifiers = _code_identifiers(_body())
    assert identifiers, f"{SKILL_NAME} names nothing in code voice"

    # Load-bearing: the guard is worthless if the skill never names the surface.
    for required in (
        "asset",
        "view",
        "generate_image",
        "target_node_id",
        "brand_notes",
        "aspect_ratio_honored",
        "actual_width",
        "actual_height",
        "transparent_background",
        "preserve_transparency",
        "fallback",
        "placeholder",
    ):
        assert required in identifiers, f"{SKILL_NAME} stopped naming {required!r}"

    corpus = _code_corpus()
    unknown = sorted(word for word in identifiers if word not in corpus)
    assert unknown == [], f"{SKILL_NAME} names identifiers the code does not have: {unknown}"


def test_the_skill_is_honest_about_the_single_no_image_retry() -> None:
    """W1.7a ships exactly ONE automatic retry on a text-only answer. The skill
    tells the author the retry already happened, so a fallback means the model
    failed twice — pin the number to the constant, not to prose."""

    from lumen_api.image_provider import NO_IMAGE_RETRIES

    assert NO_IMAGE_RETRIES == 1
    body = _body()
    assert "retried once" in body
    assert "answers with text and no image" in body


def test_the_skill_is_honest_that_the_ratio_report_only_speaks_on_a_miss() -> None:
    """`aspect_ratio_honored` is emitted ONLY when it is False (substrate.py), so
    "silence means honored" is the fact an author has to know. A skill that says
    the result always reports the ratio teaches a check that never fires."""

    substrate = (RUNTIME_ROOT / "lumen_agent" / "tools" / "substrate.py").read_text(
        encoding="utf-8"
    )
    assert 'if meta.get("aspect_ratio_honored") is False:' in substrate

    body = _body()
    assert "was NOT honored" in body
    assert "silence means the ratio came back right" in body


@pytest.mark.parametrize(
    "guide_path",
    [SKILL_FILE, KNOWLEDGE_DOCS / "knowledge/images/prompts.md"],
    ids=["skill", "linked-prompt-guide"],
)
def test_imagery_guides_match_the_public_reference_selection_parameter(
    guide_path: Path,
) -> None:
    """Both guides describe the public selector, not the helper-only boolean.
    Actual byte delivery is exercised by test_image_reference_selection.py.
    """

    substrate = (RUNTIME_ROOT / "lumen_agent" / "tools" / "substrate.py").read_text(
        encoding="utf-8"
    )
    tool_signature = substrate.split("    def asset(", 1)[1].split(") -> str:", 1)[0]
    assert "condition_on_references" not in tool_signature, (
        "the asset tool grew a reference-conditioning parameter — the skill can now name it"
    )
    assert "reference_asset_ids" in tool_signature

    body = parse_frontmatter(guide_path.read_text(encoding="utf-8"))[1]
    assert "condition_on_references" not in body
    assert "reference_asset_ids" in body
    assert "reference_inputs" in body


# --- 4. Illustrative hexes stay illustrative -------------------------------


def test_no_normative_rule_depends_on_a_specific_hex() -> None:
    """The generalization rule the colour skill established. Example hexes teach
    the METHOD; a hex in a normative rule teaches one brand's palette to every
    brand. So every hex literal has to sit in an explicitly illustrative place: a
    `Worked example` section, or a line that marks itself with `e.g.`."""

    # Paragraph-wise, not line-wise: prose wraps, so a marker like `e.g.` sits on
    # the line before the hex as often as on it. (And a hex literal starts with
    # `#`, so a naive line reader mistakes one for a heading.)
    in_example = False
    offenders: list[str] = []

    for block in re.split(r"\n\s*\n", _body()):
        heading = re.match(r"#{1,6}\s+(.*)", block.strip())
        if heading:
            in_example = "worked example" in heading.group(1).lower()
        if not re.search(r"#[0-9A-Fa-f]{6}\b", block):
            continue
        if in_example or "e.g." in block:
            continue
        offenders.append(" ".join(block.split())[:120])

    assert offenders == [], f"{SKILL_NAME} puts a hex in a normative rule: {offenders}"

    # …and the rule those examples illustrate is stated generally.
    assert "Name exact hexes from the kit." in _body()


# --- 5. Discoverability ----------------------------------------------------


def test_the_root_agent_doc_indexes_the_skill() -> None:
    """Both surfaces a reader lands on: the §4 knowledge map and the §5 skills
    index. Without these the skill is invisible to anyone reading the doc map —
    the failure `brand-imagery` and `clarify-design-brief` already shipped with."""

    text = (KNOWLEDGE_DOCS / "AGENT.md").read_text(encoding="utf-8")

    assert f"skills/{SKILL_NAME}`" in text, "the §4 knowledge map does not route to it"
    assert f"`skills/{SKILL_NAME}/SKILL.md`" in text, "the §5 skills index has no row"


def test_the_skill_points_at_the_decision_skill_it_composes_with() -> None:
    """This skill is the CRAFT of the image; `brand-imagery` decides whether the
    surface earns one at all. Losing the pointer turns a composed pair into two
    skills that each assume the other ran."""

    body = _body()
    assert "`skills/brand-imagery`" in body
    assert "`knowledge/images/decide`" in body


@pytest.mark.parametrize(
    "pointer",
    ["knowledge/images/prompts", "knowledge/images/placement"],
)
def test_the_skill_points_at_the_detail_docs_it_defers_to(pointer: str) -> None:
    assert f"`{pointer}`" in _body()

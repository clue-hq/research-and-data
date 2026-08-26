"""The W3 composition corpus, guarded as DOCS.

Brand Ad Assets v1 §5 W3 added six worked examples to the block catalog: four
snippets (card-on-a-ground, framed plate, pill chip, zone rule) and two
full-artboard skeletons (unequal-weight comparison panel, card on a washed
ground), plus a routing section in `knowledge/design/layout-recipes` that points
at the two compositions.

Their DSL is proven against the real engine in
`apps/api/tests/test_composition_corpus.py` — that suite owns "does it compile
and preflight". This one owns the other half, which the engine cannot see:

- **anti-phantom.** Every `$token` a new section cites must already be taught
  SOMEWHERE ELSE in the authored tree. The oracle deliberately excludes the W3
  sections themselves — a corpus that could vouch for its own inventions is not
  an oracle, and a token invented here is a token the agent will copy into a
  design that then fails preflight in front of a client. Same shape as the
  format-skill suite's guard, narrowed from whole files to the new sections so it
  still has teeth inside a file it shares with vetted blocks.
- **paths resolve.** A `knowledge/...` or `skills/...` pointer to a file that is
  not there sends the author hunting and burns calls.
- **the shape a reader relies on.** Each block carries a "When to use", a "When
  NOT to use", exactly one fenced DSL block, and exactly one published validator
  proof. The when-NOT half is not decoration: these six exist because the agent
  reached for multi-box composition in the wrong places, and a snippet with no
  refusal clause teaches only the reaching.
- **the indexes stay honest.** `blocks/README.md` enumerates every block, and
  `layout-recipes` now routes to the two compositions. An enumeration that has
  gone stale is worse than no enumeration.
- **the archetype count did not silently move.** The two compositions are
  compositions OF archetypes, not new archetypes — `foundations`,
  `skills/create-design`, and `blocks/patterns` all say "ONE of six" in prose, and
  those sentences must stay true.

`test_a_planted_phantom_token_is_rejected` is the red case: it plants a token
that exists nowhere and asserts the same checker that passes the shipped corpus
rejects it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DOCS = RUNTIME_ROOT / "knowledge_docs"
DESIGN = KNOWLEDGE_DOCS / "knowledge" / "design"
BLOCKS = DESIGN / "blocks"


@dataclass(frozen=True)
class CorpusSection:
    doc: Path
    heading: str
    #: the `page <id>` line the DSL opens with — also the id the engine suite uses
    page_id: str
    #: where `blocks/README.md` must list it, and the words it must list it under
    index_row: str

    def text(self) -> str:
        source = self.doc.read_text(encoding="utf-8")
        marker = f"\n## {self.heading}\n"
        start = source.find(marker)
        assert start != -1, f"{self.doc.name} has no section `## {self.heading}`"
        rest = source[start + len(marker) :]
        end = rest.find("\n## ")
        return rest if end == -1 else rest[:end]


W3_SECTIONS = (
    CorpusSection(
        BLOCKS / "data-display.md",
        "Card on a ground (elevated plate)",
        "card_on_ground",
        "Card on a ground (elevated plate)",
    ),
    CorpusSection(
        BLOCKS / "data-display.md",
        "Framed plate (a document inside a card)",
        "framed_plate",
        "Framed plate (a document inside a card)",
    ),
    CorpusSection(
        BLOCKS / "actions.md",
        "Pill chip (hug-sized, fully rounded)",
        "pill_chip",
        "Pill chip (hug-sized)",
    ),
    CorpusSection(
        BLOCKS / "layout.md",
        "Divider — zone rule inside a card (weight and inset)",
        "zone_divider",
        "Divider — zone rule",
    ),
    CorpusSection(
        BLOCKS / "patterns.md",
        "Unequal-weight comparison panel — before/after with a structural winner (1080×1080)",
        "unequal_compare",
        "Unequal-weight comparison panel (1080×1080)",
    ),
    CorpusSection(
        BLOCKS / "patterns.md",
        "Card on a washed ground — the layer stack (1080×1080)",
        "card_on_wash",
        "Card on a washed ground (1080×1080)",
    ),
)

ROUTING_SECTION = CorpusSection(
    DESIGN / "layout-recipes.md",
    "Composing two archetypes — the ad skeletons",
    "",
    "",
)

every_w3_section = pytest.mark.parametrize(
    "section", W3_SECTIONS, ids=[s.page_id for s in W3_SECTIONS]
)

TOKEN_PATTERN = re.compile(r"\$[a-z]+(?:\.[a-z0-9]+)+")


def _oracle() -> str:
    """Every authored knowledge doc, MINUS the W3 sections themselves.

    Whole-file exclusion would be too blunt here: four of the six sections live in
    files that also hold the vetted blocks whose tokens are the very vocabulary
    being checked against. Cutting the sections instead keeps the rest of each
    file as evidence while still refusing to let a W3 section vouch for itself.
    """

    corpus = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(KNOWLEDGE_DOCS.rglob("*.md"))
    )
    for section in (*W3_SECTIONS, ROUTING_SECTION):
        body = section.text()
        assert body in corpus
        corpus = corpus.replace(body, "\n")
    return corpus


def _phantom_tokens(body: str, oracle: str) -> list[str]:
    ramp = (KNOWLEDGE_DOCS / "knowledge" / "lumen-dsl" / "text.md").read_text(encoding="utf-8")

    def taught(token: str) -> bool:
        if token in oracle:
            return True
        # The size ramp is published once in shorthand (`xs=12  sm=14 … 9xl=128`),
        # so a legitimate step never appears fully qualified anywhere.
        step = token.removeprefix("$type.size.")
        return step != token and re.search(rf"\b{re.escape(step)}=\d+", ramp) is not None

    return sorted({token for token in TOKEN_PATTERN.findall(body) if not taught(token)})


# ============================================================================
# 1. Anti-phantom — every token and every path the new sections cite is real
# ============================================================================


@every_w3_section
def test_every_token_the_section_cites_is_taught_elsewhere(section: CorpusSection) -> None:
    body = section.text()
    tokens = TOKEN_PATTERN.findall(body)
    phantoms = _phantom_tokens(body, _oracle())

    assert tokens, f"{section.heading} cites no tokens at all — it stopped being concrete"
    assert not phantoms, f"{section.heading} cites phantom tokens: {phantoms}"


def test_the_routing_section_cites_no_phantom_tokens() -> None:
    """`layout-recipes`' composition section names token roles in prose. Same rule."""

    assert not _phantom_tokens(ROUTING_SECTION.text(), _oracle())


def test_a_planted_phantom_token_is_rejected() -> None:
    """The red case for the guard above. Without it, a checker that silently
    matched everything would look identical to a working one."""

    oracle = _oracle()
    real = _phantom_tokens("fill($surface.card) style($type.headline)", oracle)
    planted = _phantom_tokens("fill($surface.nonexistent) rd($radius.invented)", oracle)

    assert real == []
    assert planted == ["$radius.invented", "$surface.nonexistent"]


@every_w3_section
def test_every_knowledge_and_skill_path_the_section_cites_resolves(
    section: CorpusSection,
) -> None:
    body = section.text()
    missing: list[str] = []

    for ref in sorted(set(re.findall(r"`(knowledge/[a-z0-9/-]+)`", body))):
        if not (KNOWLEDGE_DOCS / f"{ref}.md").is_file():
            missing.append(f"{ref}.md")
    for ref in sorted(set(re.findall(r"`(skills/[a-z0-9-]+)`", body))):
        if not (KNOWLEDGE_DOCS / ref / "SKILL.md").is_file():
            missing.append(f"{ref}/SKILL.md")

    assert not missing, f"{section.heading} points at files that do not exist: {missing}"


def test_the_routing_section_points_at_the_catalog_that_holds_the_skeletons() -> None:
    body = ROUTING_SECTION.text()

    assert "`knowledge/design/blocks/patterns`" in body
    assert (KNOWLEDGE_DOCS / "knowledge" / "design" / "blocks" / "patterns.md").is_file()


# ============================================================================
# 2. The shape a reader relies on
# ============================================================================


@every_w3_section
def test_the_section_says_when_to_use_it_and_when_not_to(section: CorpusSection) -> None:
    """The refusal half is the load-bearing one. These six blocks exist because
    the agent reached for multi-box composition in the wrong places — a snippet
    with only a "when to use" teaches the reaching and nothing else."""

    body = section.text()

    assert "**When to use:**" in body, f"{section.heading} has no when-to-use note"
    assert "**When NOT to use:**" in body, f"{section.heading} has no refusal clause"


@every_w3_section
def test_the_section_carries_exactly_one_dsl_block_and_one_published_proof(
    section: CorpusSection,
) -> None:
    """One block per section is the catalog's contract, and the extraction in the
    engine suite depends on it. The proof is what makes the block *vetted* rather
    than merely *written*."""

    body = section.text()
    dsl = re.findall(r"```text\n(.*?)```", body, re.S)
    proofs = re.findall(r"```json\n(.*?)```", body, re.S)

    assert len(dsl) == 1, f"{section.heading} has {len(dsl)} DSL blocks"
    assert len(proofs) == 1, f"{section.heading} has {len(proofs)} validator proofs"
    assert dsl[0].startswith(f"page {section.page_id} ")
    assert '"ok": true' in proofs[0]
    assert "Validator proof:" in body


@every_w3_section
def test_the_section_authors_in_token_form_not_brand_hexes(section: CorpusSection) -> None:
    """The corpus feeds a kit-driven pipeline, so a brand colour baked into a
    worked example would be copied into every brand's ads. The two neutral
    exemptions are stated in the docs themselves: shadow ink (`#000000`, because
    the kit's `shadows` group is empty and there is no role to reference) and the
    transparent gradient stop (`#00000000`, because there is no `$transparent`
    token)."""

    dsl = re.findall(r"```text\n(.*?)```", section.text(), re.S)[0]

    assert set(re.findall(r"#[0-9a-fA-F]{6,8}", dsl)) <= {"#000000", "#00000000"}
    assert "style($type." in dsl
    assert "fill($surface." in dsl


# ============================================================================
# 3. The indexes stay honest
# ============================================================================


@every_w3_section
def test_the_block_readme_index_lists_the_new_block(section: CorpusSection) -> None:
    """`blocks/README.md` is the map an author reads before opening a file. A block
    that is in the tree but not in the index is a block nobody finds."""

    readme = (BLOCKS / "README.md").read_text(encoding="utf-8")

    assert f"| {section.index_row} |" in readme, f"{section.index_row} is not indexed"


def test_layout_recipes_routes_to_both_compositions() -> None:
    """The archetype canon is where the author chooses. If it does not name these
    two, the agent never learns they are available and goes on inventing the
    geometry — which is the failure the whole wave exists to fix."""

    recipes = (DESIGN / "layout-recipes.md").read_text(encoding="utf-8")
    body = ROUTING_SECTION.text()

    assert "## Composing two archetypes — the ad skeletons" in recipes
    assert "Composing two archetypes" in recipes.split("## Choose the archetype first")[1]
    for name in ("Unequal-weight comparison panel", "Card on a washed ground"):
        assert name in body, f"the routing table does not name {name}"
    # …and each named composition really is a heading in the catalog it points at.
    patterns = (BLOCKS / "patterns.md").read_text(encoding="utf-8")
    assert "## Unequal-weight comparison panel" in patterns
    assert "## Card on a washed ground" in patterns


def test_the_two_compositions_did_not_become_a_seventh_and_eighth_archetype() -> None:
    """They are compositions OF archetypes, and three other docs say "ONE of six"
    in prose. If someone promotes them to archetypes, those three sentences become
    false — so the count is pinned here, where the promotion would happen."""

    recipes = (DESIGN / "layout-recipes.md").read_text(encoding="utf-8")
    headings = re.findall(r"^### \d+ — ([a-z-]+)$", recipes, re.MULTILINE)

    assert headings == [
        "vertical-poster",
        "split-panel",
        "numeral-hero",
        "image-hero",
        "banded",
        "emblem",
    ]
    assert "canonical home for the six design archetypes" in recipes
    assert "ONE of six" in (DESIGN / "foundations.md").read_text(encoding="utf-8")
    assert "ONE of six" in (BLOCKS / "patterns.md").read_text(encoding="utf-8")
    assert "one of six" in (
        (KNOWLEDGE_DOCS / "skills" / "create-design" / "SKILL.md").read_text(encoding="utf-8")
    )


def test_the_routing_section_names_the_archetypes_each_composition_stacks() -> None:
    """The value of the table is the derivation: an author who knows the
    comparison panel IS banded-with-unequal-bands can repair it with what they
    already know about bands."""

    body = ROUTING_SECTION.text()

    assert "banded" in body
    assert "image-hero" in body
    assert "emblem" in body

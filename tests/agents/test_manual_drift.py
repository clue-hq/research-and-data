"""Drift guards for the Head of ABM's operating manual.

The manual is fifteen catalog skills: four rendered from the code by
``clue_agents.manual.build``, eleven hand-written. A hand-written chapter cannot be regenerated,
so nothing but a test keeps it honest when the code it describes moves. These are those tests.

Each one names the exact drift in its assertion: which tool lost a section, which enum value no
longer appears, which refusal code has no note, which rule line carries no authority mark. They
are offline by construction — the toolbelt is composed with every capability absent
(``build_toolbelt(storage=None, gateway=None)``), the chapters are read off disk, and the code
they are checked against is read with :mod:`ast`, never executed.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import re
import sys
from collections.abc import Iterator
from types import ModuleType
from typing import get_args

import pytest

from clue_agents.catalog import ProfileDefinition, SkillHeader, _parse_frontmatter
from clue_agents.contracts import AgentRole, ContextLayer
from clue_agents.manual import build as manual
from clue_api.agent_registry_wiring import (
    C6_ACTIVE_PROFILE_VERSIONS,
    build_agent_profile_registry,
)
from clue_api.agent_turn_fleet_wiring import project_conversation_context_policy
from clue_api.arv2.account_research_store import JobStage, JobStatus, JobSubject
from clue_api.arv2.discovery_store import (
    PENDING_DISPOSITION,
    SHOWN_DISPOSITIONS,
    Disposition,
    Pass,
)
from clue_api.manual_build import build_facts, load_toolbelt, main
from clue_core.enums import VerificationStatus
from clue_toolbelt.registry import ToolRegistry

PROFILE_NAME = "head-of-abm"
CATALOG_ROOT = manual.DEFAULT_CATALOG_ROOT
SKILLS_ROOT = CATALOG_ROOT / "skills"

#: The capability map is prepended to every system prompt, so the skills block is context the
#: model pays for on every turn of every thread.
#:
#: Moved 4096 -> 4608 at `head-of-abm@v55`: the disclosed library grew from sixteen resources to
#: nineteen when the three document skills joined it, and three lines of address, summary and path
#: cost about 330 bytes no summary length can win back (the three are the shortest on the block).
#: This is a cost heuristic and, since layer budgets stopped gating anything (founder ruling
#: 2026-09-14), the only *size* ceiling left in this file — the prompt test below now reports
#: rather than refuses. Adding a resource is what is supposed to move this number; a summary that
#: sprawls is what it is here to catch.
#:
#: Unmoved at `head-of-abm@v56`: the disclosed library is still those nineteen resources, because
#: the four reads that join the grant are TOOLS and a tool is not disclosed on this block. Only
#: the Stage-0 skill's own summary grew — by the words "claims" and "artifacts".
#: Unmoved again at `head-of-abm@v57`, which changes no resource at all: it raises the turn caps
#: and re-mints the manual at `manual-*@v4`, and a chapter's version lives in its path, not in the
#: summary this block measures. 4427 bytes against the 4608 already allowed.
#:
#: Moved 4608 -> 5120 at `head-of-abm@v58` (2026-09-19), on the same terms as the last move: one
#: RESOURCE joins the disclosed library — `code-execution@v1`, the skill that teaches the sandbox
#: — and its address, summary and path cost 256 bytes no shortening wins back. The Stage-0 skill's
#: own summary grew with it (v33 -> v34, the attachments sentence). The block measures 4711 bytes
#: against the 5120 now allowed. Adding a resource is what is supposed to move this number; a
#: summary that sprawls is what it is here to catch.
#:
#: Unmoved at `head-of-abm@v59` and again at `@v60`: neither adds or removes a disclosed resource.
#: v59 moves one TOOL address (`open_design_leg` @4 -> @5) and v60 changes only the prompt, and
#: the manual re-mint both of them carry lives in the path this block prints, not in the summary
#: it measures.
#: Unmoved at head-of-abm@v61: no disclosed resource joins (a tool grant is not a resource).
#:
#: Unmoved at `head-of-abm@v76` (2026-10-20, CRM integration Phase 1), by founder decision: one
#: RESOURCE joins (`crm-sales-analysis@v1`), and the Stage-0 skill's summary was shortened in its
#: new version (v49) to make room, so the block stays inside the same budget.
#:
#: Moved 5120 -> 5632 at `head-of-abm@v77` (2026-10-22, CRM integration Phase 2), on the terms of
#: the v55 and v58 moves: one RESOURCE joins the disclosed library (`crm-writing@v1`), whose
#: address, short summary and path cost about 200 bytes no shortening wins back; the Stage-0
#: summary was already shortened at v49. The block measures 5266 bytes.
SKILLS_BLOCK_MAX_BYTES = 5632

#: The hand-written skill that teaches `run_python@1`. It is not a manual chapter — it carries a
#: tool grant and versions on its own clock — but it is founder-reviewed prose that states rules
#: to the same reader, so the authority-mark audit below covers it too. Bump the version here
#: when the skill re-mints.
CODE_EXECUTION_SKILL = "code-execution"
CODE_EXECUTION_VERSION = "v1"

#: A rule sentence must say which half of the platform holds it: code, or only the prose.
AUTHORITY_MARKS = ("(enforced)", "(asked of you)")

#: The words that make a line a rule rather than a description.
RULE_WORDS = ("never", "must", "only", "cannot", "may not", "do not", "always")

#: The two refusal constructors whose first positional (or ``reason_code=``) argument is the
#: stable code the agent reads. Ruling M3.
REFUSAL_CONSTRUCTORS = ("PreconditionFailure", "Arv2ReadRefused")

_REASON_CODE = re.compile(r"^[a-z_]+$")


# =================================================================================================
# fixtures and shared readers
# =================================================================================================


@pytest.fixture(scope="module")
def toolbelt() -> ToolRegistry:
    return load_toolbelt()


@pytest.fixture(scope="module")
def profile() -> ProfileDefinition:
    return manual.load_profile(CATALOG_ROOT, PROFILE_NAME, manual.PROFILE_VERSION)


@pytest.fixture(scope="module")
def notes() -> dict[str, object]:
    return manual.load_notes(CATALOG_ROOT)


@pytest.fixture(scope="module")
def chapters() -> dict[str, str]:
    """Every chapter's body, keyed by chapter name, front matter stripped."""

    return {name: _chapter(name)[1] for name in manual.MANUAL_CHAPTERS}


def _chapter(name: str) -> tuple[dict[str, object], str]:
    """One chapter's front matter and body, parsed the way the catalog loader parses it."""

    path = SKILLS_ROOT / f"manual-{name}" / manual.MANUAL_VERSION / "SKILL.md"
    assert path.is_file(), f"chapter manual-{name} is missing at {path}"
    return _parse_frontmatter(path.read_bytes(), address=f"skill:manual-{name}")


def _mentions(body: str, value: str) -> bool:
    """Is ``value`` present as a whole token (so ``verified`` never matches ``unverified``)?"""

    return re.search(rf"(?<![0-9A-Za-z_]){re.escape(value)}(?![0-9A-Za-z_])", body) is not None


def _headings(body: str) -> list[str]:
    return [line[3:].strip() for line in body.splitlines() if line.startswith("## ")]


# =================================================================================================
# (a) the generated half is current
# =================================================================================================


def test_the_generated_chapters_are_current(toolbelt: ToolRegistry) -> None:
    """The builder's own drift gate passes, and the four committed files are the fresh render."""

    assert main(["--check", "--catalog-root", str(CATALOG_ROOT)]) == 0, (
        "`python -m clue_api.manual_build --check` reports a stale generated chapter; run "
        "`make manual`"
    )

    rendered = manual.build_chapters(
        toolbelt=toolbelt, facts=build_facts(), catalog_root=CATALOG_ROOT
    )
    assert sorted(rendered) == sorted(manual.GENERATED_CHAPTERS)
    for name, text in rendered.items():
        path = manual.chapter_path(CATALOG_ROOT, name, manual.MANUAL_VERSION)
        assert path.read_bytes() == text.encode(), (
            f"manual-{name} on disk is not the render of the current code; run `make manual`"
        )


# =================================================================================================
# (b) every granted tool is taught, and nothing else is
# =================================================================================================


def test_the_tools_chapter_covers_exactly_the_granted_tools(
    toolbelt: ToolRegistry, profile: ProfileDefinition, chapters: dict[str, str]
) -> None:
    """One ``## name@version`` section per profile grant, in profile order, and no other tool."""

    granted = [f"{pin.name}@{pin.version}" for pin in profile.tools]
    headings = _headings(chapters["tools"])
    addressed = [item for item in headings if re.fullmatch(r"[a-z0-9_]+@\S+", item)]

    missing = [item for item in granted if item not in addressed]
    ungranted = [item for item in addressed if item not in granted]
    assert not missing, (
        f"manual-tools has no section for {missing}, granted by {PROFILE_NAME}@"
        f"{manual.PROFILE_VERSION}"
    )
    assert not ungranted, (
        f"manual-tools has a section for {ungranted}, which {PROFILE_NAME}@"
        f"{manual.PROFILE_VERSION} does not grant"
    )
    assert addressed == granted, (
        f"manual-tools is out of profile order: {addressed} against the profile's {granted}"
    )

    named = [
        item
        for item in headings
        if item not in addressed and item.split("@")[0] in toolbelt.names()
    ]
    assert not named, (
        f"manual-tools sections {named} name a live tool without addressing it as name@version"
    )


# =================================================================================================
# (c) the status vocabularies the chapters own
# =================================================================================================


def test_every_status_value_appears_in_the_chapter_that_owns_it(
    chapters: dict[str, str],
) -> None:
    """A state the lane can be in, with no word about it in its chapter, is a hole in the manual."""

    owned: list[tuple[str, str, tuple[str, ...]]] = [
        ("accounts-research", "JobStatus", get_args(JobStatus)),
        ("accounts-research", "JobStage", get_args(JobStage)),
        ("accounts-research", "JobSubject", get_args(JobSubject)),
        (
            "discovery",
            "Disposition",
            tuple(
                dict.fromkeys((*get_args(Disposition), *SHOWN_DISPOSITIONS, PENDING_DISPOSITION))
            ),
        ),
        ("discovery", "Pass", get_args(Pass)),
        ("claims", "VerificationStatus", tuple(item.value for item in VerificationStatus)),
    ]
    problems: list[str] = []
    for chapter, label, values in owned:
        assert values, f"{label} has no values to check; the import is wrong"
        for value in values:
            if not _mentions(chapters[chapter], value):
                problems.append(f"manual-{chapter} never names {label} value {value!r}")
    assert not problems, "; ".join(problems)


# =================================================================================================
# (d) the field registry
# =================================================================================================


def test_the_fields_chapter_renders_every_snapshot_field(chapters: dict[str, str]) -> None:
    """The chapter is the vocabulary of the claim store; a missing key is a field nothing names."""

    snapshot = json.loads((CATALOG_ROOT / "manual" / "fields.json").read_text())
    declared = {str(row["field_key"]) for row in snapshot}
    rendered = set(
        re.findall(r"^\| `([^`]+)`(?: \(inactive\))? \|", chapters["fields"], re.MULTILINE)
    )
    assert not declared - rendered, (
        f"manual-fields does not render {sorted(declared - rendered)} from fields.json"
    )
    assert not rendered - declared, (
        f"manual-fields renders {sorted(rendered - declared)}, which fields.json does not declare"
    )


# =================================================================================================
# (e) every cross-reference resolves
# =================================================================================================


def test_every_cross_reference_names_a_chapter_that_exists(chapters: dict[str, str]) -> None:
    """Both link forms: the ``manual:<name>`` token, and the materialized path the build writes."""

    token = re.compile(r"manual:([a-z0-9-]+)")
    materialized = re.compile(r"\.deepagent/skills/manual-([a-z0-9-]+)/v[0-9]+/SKILL\.md")
    problems: list[str] = []
    for name, body in chapters.items():
        for target in token.findall(body):
            if target not in manual.MANUAL_CHAPTERS:
                problems.append(f"manual-{name} links to manual:{target}, which is not a chapter")
        for target in materialized.findall(body):
            if target not in manual.MANUAL_CHAPTERS:
                problems.append(
                    f"manual-{name} links to .deepagent/skills/manual-{target}/…, "
                    "which is not a chapter"
                )
    assert not problems, "; ".join(problems)


def test_every_tool_description_points_at_its_own_entry_in_the_current_tools_chapter(
    toolbelt: ToolRegistry,
) -> None:
    """A description's ``Manual:`` pointer names the chapter the agent actually holds.

    Hard-coded versions sat at ``manual-tools/v5`` through six re-mints, so the model was sent to
    a file no current profile mounts. The pointer is built by ``tool_manual_link`` now; this pins
    that every description that has one uses the current version and its own tool's anchor.
    """

    pointer = re.compile(r"\.deepagent/skills/manual-tools/(v[0-9]+)/SKILL\.md#([a-z0-9_]+)")
    problems: list[str] = []
    for descriptor in toolbelt.all_descriptors():
        for version, anchor in pointer.findall(descriptor.model_description):
            if version != manual.MANUAL_VERSION or anchor != descriptor.name:
                problems.append(
                    f"{descriptor.name}@{descriptor.version} points at manual-tools/{version}"
                    f"#{anchor}; expected {manual.MANUAL_VERSION}#{descriptor.name}"
                )
    assert not problems, "; ".join(problems)


# =================================================================================================
# (f) the profile pin and the capability map
# =================================================================================================


@pytest.fixture(scope="module")
def resolved_head_of_abm(toolbelt: ToolRegistry) -> object:
    return build_agent_profile_registry(toolbelt).resolve(AgentRole.HEAD_OF_ABM)


def test_the_profile_pins_every_manual_chapter(resolved_head_of_abm: object) -> None:
    """A chapter the profile does not pin is a chapter the agent can never open."""

    pinned = {
        bundle.resource.address
        for bundle in resolved_head_of_abm.profile.skills  # type: ignore[attr-defined]
    }
    expected = {f"skill:manual-{name}@{manual.MANUAL_VERSION}" for name in manual.MANUAL_CHAPTERS}
    assert not expected - pinned, (
        f"{PROFILE_NAME}@{manual.PROFILE_VERSION} does not pin {sorted(expected - pinned)}"
    )


def test_the_capability_map_discloses_every_manual_chapter(resolved_head_of_abm: object) -> None:
    """Each chapter is disclosed with a summary and an openable path, inside the map's budget."""

    block = _skills_block(resolved_head_of_abm.generated_resource_map)  # type: ignore[attr-defined]
    problems: list[str] = []
    for name in manual.MANUAL_CHAPTERS:
        address = f"skill:manual-{name}@{manual.MANUAL_VERSION}"
        line = next((item for item in block.splitlines() if item.startswith(f"- {address}:")), None)
        if line is None:
            problems.append(f"the capability map does not disclose {address}")
            continue
        summary = line.split(":", 2)[2].split("; open=")[0].strip()
        if not summary.startswith("Manual: "):
            problems.append(f"{address} is disclosed without its manual summary: {summary!r}")
        if f"; open=.deepagent/skills/manual-{name}/{manual.MANUAL_VERSION}/SKILL.md" not in line:
            problems.append(f"{address} is disclosed without its materialized path")
    assert not problems, "; ".join(problems)
    assert len(block.encode()) <= SKILLS_BLOCK_MAX_BYTES, (
        f"the disclosed-skills block is {len(block.encode())} bytes, over the "
        f"{SKILLS_BLOCK_MAX_BYTES} the prompt budget allows for it"
    )


def test_the_resolved_system_prompt_size_is_reported_against_the_identity_budget(
    resolved_head_of_abm: object,
) -> None:
    """Measure the whole disclosed prompt — body plus capability map — and say what it costs.

    This used to be the gate: the prompt had to fit 80% of L1, because a required candidate that
    did not fit failed the turn at assembly. It no longer can (founder ruling 2026-09-14 — layer
    budgets are tracked, never enforced), so holding a share of L1 here would be inventing a limit
    the platform does not have. What remains worth knowing is the number itself and how it compares
    to what the policy expects a profile to cost, printed on every run, plus the two facts that
    would mean something is genuinely wrong: an empty prompt, or one large enough to be a drafting
    accident rather than a manual.

    The L1 budget is read from the production policy, never retyped here.
    """

    prompt_bytes = len(resolved_head_of_abm.system_prompt.encode())  # type: ignore[attr-defined]
    budget = project_conversation_context_policy().budget_for(ContextLayer.L1_IDENTITY)
    print(
        f"{PROFILE_NAME}@{manual.PROFILE_VERSION} resolved system prompt: {prompt_bytes} bytes, "
        f"{prompt_bytes / budget:.0%} of the {budget}-byte production L1 identity budget"
    )
    assert 0 < prompt_bytes < 200_000, (
        f"the resolved {PROFILE_NAME}@{manual.PROFILE_VERSION} system prompt is {prompt_bytes} "
        f"bytes ({prompt_bytes / budget:.0%} of the {budget}-byte production L1 identity budget); "
        f"a prompt this size is a drafting accident, not a manual"
    )


def _skills_block(resource_map: str) -> str:
    """The ``Progressively disclosed skills`` section of the generated capability map."""

    head = "Progressively disclosed skills:\n"
    assert head in resource_map, "the capability map no longer has a disclosed-skills block"
    return resource_map.split(head, 1)[1].split("\n\n", 1)[0]


# =================================================================================================
# (g) refusal codes, both ways (ruling M3)
# =================================================================================================


def test_every_refusal_code_is_noted_and_every_note_is_a_real_code(
    toolbelt: ToolRegistry, profile: ProfileDefinition, notes: dict[str, object]
) -> None:
    """The manual's refusal list and the code's refusal list are the same list.

    Forward: a noted code must exist as a string literal in the tool's own module or in the
    module that defines a refusal exception that module imports (one level of import-follow,
    resolved to where the exception class is *defined*, so a package re-export is followed to
    its home). A code the code builds with an argument — ``f"account_not_found:{account_id}"`` —
    is matched on the stem before the colon, which is how the note spells it too.

    Backward: every literal reason code raised in the module must be noted, unless it is raised
    inside another tool's class body — three of these modules hold tools this profile is not
    granted, and their codes are that tool's manual, not this one's.
    """

    granted = {pin.name for pin in profile.tools}
    by_module: dict[str, list[str]] = {}
    for pin in profile.tools:
        module = type(toolbelt.get(pin.name, pin.version)).__module__
        by_module.setdefault(module, []).append(pin.name)
    # A tool registered UNGRANTED still owns its own refusal codes, and is checked against its own
    # `tool_notes.yaml` entry rather than against a granted neighbour's. The widening was added for
    # `read_claims@1`, which sat in `read_tools.py` beside the three granted reads while its
    # service raised `entity_not_found` / `since_invalid` from a module-level function — where this
    # scan attributes a code to the MODULE rather than to a tool's class body. `head-of-abm@v56`
    # grants it, so it is covered the ordinary way now; the rule stays because the next tool to
    # register ungranted beside a granted sibling would otherwise be fixable only by teaching a
    # granted read a refusal it cannot raise — precisely the drift this guards.
    for module_name, tool_names in by_module.items():
        tool_names.extend(
            sorted(
                name
                for name in toolbelt.names()
                if name not in granted
                and name in notes
                and type(toolbelt.get(name)).__module__ == module_name
            )
        )

    unnoted: list[str] = []
    unfound: list[str] = []
    for module_name, tool_names in sorted(by_module.items()):
        module = importlib.import_module(module_name)
        tree = ast.parse(inspect.getsource(module))
        noted = {
            code.split(":", 1)[0]: name
            for name in tool_names
            for code in notes[name]["refusals"]  # type: ignore[index]
        }

        stems = _literal_stems(tree)
        for extra in _imported_exception_modules(module):
            stems |= _literal_stems(ast.parse(inspect.getsource(extra)))
        for stem, name in sorted(noted.items()):
            if stem not in stems:
                unfound.append(
                    f"{name}: {stem!r} is noted in tool_notes.yaml but is no literal in "
                    f"{module_name} or the modules defining its refusal exceptions"
                )

        for code, lineno, owner in _raised_reason_codes(tree):
            if owner is not None and owner not in granted:
                continue
            if code not in noted:
                unnoted.append(
                    f"{module_name}:{lineno} raises {code!r} for {sorted(tool_names)} and "
                    "tool_notes.yaml has no line for it"
                )
    assert not unfound, "; ".join(unfound)
    assert not unnoted, "; ".join(unnoted)


def _literal_stems(tree: ast.AST) -> set[str]:
    """Every string literal in a module, plus the part before the first colon of each.

    The colon half is what makes ``f"contact_not_found:{contact_id}"`` findable: the f-string's
    literal chunk is ``contact_not_found:``, and the note spells the code ``contact_not_found``.
    Docstrings are excluded, so a code that survives only in prose does not count as present.
    """

    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    stems: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        stems.add(node.value)
        stems.add(node.value.split(":", 1)[0])
    return stems


def _imported_exception_modules(module: ModuleType) -> Iterator[ModuleType]:
    """One level out: the modules that *define* the exception classes this module imports.

    The addendum names ``*Refused``; the rule applied is the general one it stands for — any
    imported name that is an exception class — because ``agent_gate_tools`` imports its codes'
    home as ``AccountResearchDiscoveryNotReady``, which is the same thing under another name.
    """

    seen: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if not isinstance(node, ast.ImportFrom):
            continue
        target = node.module or ""
        if node.level:
            package = module.__name__.rsplit(".", node.level)[0]
            target = f"{package}.{target}" if target else package
        try:
            imported = importlib.import_module(target)
        except ImportError:  # pragma: no cover - a module that cannot be imported has no codes
            continue
        for alias in node.names:
            value = getattr(imported, alias.name, None)
            if not isinstance(value, type) or not issubclass(value, BaseException):
                continue
            home = sys.modules.get(value.__module__)
            if home is None or home.__name__ in seen:
                continue
            try:
                inspect.getsource(home)
            except (OSError, TypeError):  # pragma: no cover - builtins have no source
                continue
            seen.add(home.__name__)
            yield home


def _raised_reason_codes(tree: ast.AST) -> Iterator[tuple[str, int, str | None]]:
    """Every literal reason code a module raises, with the tool whose class body it sits in."""

    owners = _tool_class_ranges(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        if callee not in REFUSAL_CONSTRUCTORS:
            continue
        literal: str | None = None
        if (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            literal = node.args[0].value
        for keyword in node.keywords:
            if (
                keyword.arg == "reason_code"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                literal = keyword.value.value
        if literal is None or not _REASON_CODE.match(literal):
            continue
        owner = next(
            (name for name, start, end in owners if start <= node.lineno <= end),
            None,
        )
        yield literal, node.lineno, owner


def _tool_class_ranges(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Each class that declares a tool ``name``, with the line span of its body."""

    ranges: list[tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for statement in node.body:
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and statement.targets[0].id == "name"
                and isinstance(statement.value, ast.Constant)
                and isinstance(statement.value.value, str)
            ):
                ranges.append((statement.value.value, node.lineno, node.end_lineno or node.lineno))
    return ranges


# =================================================================================================
# (h) the builder renders the profile that is actually active
# =================================================================================================


def test_the_builder_renders_the_active_head_of_abm_profile() -> None:
    """A chapter built from a retired profile teaches a tool set nobody holds."""

    active = C6_ACTIVE_PROFILE_VERSIONS[AgentRole.HEAD_OF_ABM]
    assert active == manual.PROFILE_VERSION, (
        f"the manual builder renders {PROFILE_NAME}@{manual.PROFILE_VERSION} while the active "
        f"profile is {active}; repoint PROFILE_VERSION and run `make manual`"
    )


# =================================================================================================
# (i) every rule says whether code holds it
# =================================================================================================


def test_every_rule_line_says_whether_it_is_enforced(chapters: dict[str, str]) -> None:
    """The manual's central promise: a rule nothing enforces is marked as merely asked of you.

    ``code-execution`` is audited beside the two chapters because it is the same kind of prose
    for the same reader: it tells the agent what the sandbox refuses and what is merely asked of
    it, and the two are indistinguishable to the model unless the line says which it is.
    """

    bodies = {f"manual-{name}": chapters[name] for name in ("gates-authority", "turn")}
    bodies[CODE_EXECUTION_SKILL] = _skill_body(CODE_EXECUTION_SKILL, CODE_EXECUTION_VERSION)

    problems: list[str] = []
    for name, body in bodies.items():
        for lineno, text, default_marked in _rule_lines(body):
            if not any(word in text.lower() for word in RULE_WORDS):
                continue
            if default_marked or any(mark in text for mark in AUTHORITY_MARKS):
                continue
            problems.append(f"{name} line {lineno} carries no authority mark: {text!r}")
    assert not problems, "; ".join(problems)


def _skill_body(name: str, version: str) -> str:
    """One non-manual catalog skill's body, front matter stripped."""

    path = SKILLS_ROOT / name / version / "SKILL.md"
    assert path.is_file(), f"{name} is missing at {path}"
    return _parse_frontmatter(path.read_bytes(), address=f"skill:{name}")[1]


def _rule_lines(body: str) -> Iterator[tuple[int, str, bool]]:
    """Every rule-bearing line of a chapter: list items (wrapped lines joined) and table rows.

    The third element says the line's section declared a blanket mark for everything under it
    ("entirely on you ``(asked of you)`` unless marked otherwise"), which is how the prompt-rules
    section of manual-gates-authority marks its list in one place instead of per item.
    """

    lines = body.splitlines()
    default_marked = False
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if line.startswith("## "):
            default_marked = False
        elif stripped.startswith("- "):
            start = index
            text = stripped
            while index + 1 < len(lines) and _is_continuation(lines[index + 1]):
                index += 1
                text = f"{text} {lines[index].strip()}"
            yield start + 1, text, default_marked
        elif stripped.startswith("|") and not re.fullmatch(r"\|[\s:|-]+\|", stripped):
            if index + 1 >= len(lines) or not re.fullmatch(r"\|[\s:|-]+\|", lines[index + 1]):
                yield index + 1, stripped, default_marked
        elif "unless marked otherwise" in stripped and any(
            mark in stripped for mark in AUTHORITY_MARKS
        ):
            default_marked = True
        index += 1


def _is_continuation(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and line.startswith(("  ", "\t")) and not stripped.startswith("- ")


# =================================================================================================
# (j) every chapter is a loadable skill
# =================================================================================================


def test_every_chapter_is_a_head_of_abm_skill_with_a_manual_summary() -> None:
    """Front matter the catalog will accept, scoped to this role, summarized for the map."""

    on_disk = {path.name.removeprefix("manual-") for path in SKILLS_ROOT.glob("manual-*")}
    assert on_disk == set(manual.MANUAL_CHAPTERS), (
        f"the chapters on disk are {sorted(on_disk)}, and the builder names "
        f"{sorted(manual.MANUAL_CHAPTERS)}"
    )

    problems: list[str] = []
    for name in manual.MANUAL_CHAPTERS:
        values, _ = _chapter(name)
        header = SkillHeader(**values)
        if header.name != f"manual-{name}":
            problems.append(f"manual-{name} declares name {header.name!r}")
        if header.version != manual.MANUAL_VERSION:
            problems.append(f"manual-{name} declares version {header.version!r}")
        if header.roles != [AgentRole.HEAD_OF_ABM]:
            problems.append(f"manual-{name} declares roles {[r.value for r in header.roles]}")
        if header.tools:
            problems.append(
                f"manual-{name} requires tools {[tool.address for tool in header.tools]}; "
                "a chapter is prose and requires none"
            )
        if not header.summary.startswith("Manual: "):
            problems.append(f"manual-{name} summary does not begin 'Manual: ': {header.summary!r}")
        if len(header.summary) > 160:
            problems.append(
                f"manual-{name} summary is {len(header.summary)} characters, over the 160 the "
                "capability map allows"
            )
    assert not problems, "; ".join(problems)

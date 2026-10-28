"""Render the four generated chapters of the Head of ABM's operating manual.

Generated where the code is the source. A tool's address, effect class, inputs, outputs and pins
come off its live descriptor; the field registry comes off a committed snapshot of
``field_definition``; the limits come off the profile and named runtime constants. The only
hand-written half is ``catalog/manual/tool_notes.yaml``: the one-line next move per refusal code,
per error string, and the two cross-reference keys. The builder renders exactly what the notes
list, and a granted tool with no entry fails the build by name, so a new tool cannot ship with an
unexplained refusal.

The rendering has no dependency on the composition root: the toolbelt and the handful of
constants that live in ``clue_api`` are passed in (see :class:`CodeFacts` and
``clue_api.manual_build``), because the agents package may not import it.
"""

from __future__ import annotations

import argparse
import inspect
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, is_dataclass
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import yaml
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from clue_agents.catalog import FolderProfileCatalog, ProfileDefinition
from clue_agents.execution import RECEIPT_REFERENCE_VALUES_MAX_BYTES
from clue_agents.runtime import (
    _FINALIZE_REPAIRS_EXHAUSTED,
    _FINALIZE_TOOL_NAME,
    _FRAMEWORK_TOOL_NAMES,
    _MAX_FINALIZE_REPAIRS,
)
from clue_agents.tool_recovery import MAX_TOOL_REPAIR_ROUNDS
from clue_config import Settings
from clue_toolbelt.envelope import ToolEffectClass
from clue_toolbelt.registry import ToolRegistry

__all__ = [
    "DEFAULT_CATALOG_ROOT",
    "GENERATED_CHAPTERS",
    "HANDWRITTEN_CHAPTERS",
    "MANUAL_CHAPTERS",
    "MANUAL_VERSION",
    "Chapter",
    "CodeFacts",
    "ManualBuildError",
    "build_chapter_objects",
    "build_chapters",
    "build_errors_chapter",
    "build_fields_chapter",
    "build_limits_chapter",
    "build_tools_chapter",
    "chapter_path",
    "link_handwritten_chapters",
    "load_fields",
    "load_notes",
    "load_profile",
    "materialized_links",
    "render_skill",
    "run",
    "tool_manual_link",
]

#: ``platform/agents/catalog`` resolved the way the composition root resolves it: relative to the
#: package, never to the working directory.
DEFAULT_CATALOG_ROOT = Path(__file__).resolve().parents[2] / "catalog"

MANUAL_VERSION = "v33"

#: The profile the generated chapters describe. A chapter is true of one exact grant.
PROFILE_NAME = "head-of-abm"
PROFILE_VERSION = "v87"

#: The chapters the builder writes.
GENERATED_CHAPTERS: tuple[str, ...] = ("tools", "fields", "errors", "limits")

#: Every chapter of the library, generated and hand-written alike. A cross-reference may name any
#: of them: a link to a chapter that is not written yet is still a path, and the file arrives
#: under it. A token naming something outside this list is a typo, and the build says so.
MANUAL_CHAPTERS: tuple[str, ...] = (
    "index",
    "turn",
    "workspace",
    "tools",
    "fields",
    "claims",
    "accounts-research",
    "discovery",
    "documents-decisions",
    "gates-authority",
    "humans-screens",
    "siblings",
    "errors",
    "limits",
    "glossary",
)

#: The chapters a human writes. `--link` rewrites their cross-reference tokens in place; nothing
#: else in this module touches their bytes, because there is no source to regenerate them from.
HANDWRITTEN_CHAPTERS: tuple[str, ...] = tuple(
    name for name in MANUAL_CHAPTERS if name not in GENERATED_CHAPTERS
)

_CHAPTER_SUMMARIES: Mapping[str, str] = {
    "tools": (
        "Manual: every governed tool this role holds, with its address, effect, inputs, outputs, "
        "refusal codes and the next move for each, and what the human sees."
    ),
    "fields": (
        "Manual: the registered claim fields by family, with value type, freshness, reuse scope "
        "and gate; the families a claims read can be narrowed to."
    ),
    "errors": (
        "Manual: every error string a governed tool, a file tool or finalize_turn can hand back, "
        "and the one next move for each."
    ),
    "limits": (
        "Manual: what bounds one turn. Round and time limits, output tokens, the two repair "
        "budgets, receipt and read bounds, quotas, retention."
    ),
}

_SKILL_ROLE = "head_of_abm"
_FRAMEWORK_VERSION = ">=0.6,<0.7"

_LINK_TOKEN = re.compile(r"manual:([a-z][a-z-]*)")
_DOTTED_NAME = re.compile(r"(?<!['\"\w.])(?:[A-Za-z_]\w*\.)+([A-Za-z_]\w*)")
_TOOL_LABELS_BLOCK = re.compile(r"const TOOL_LABELS:[^=]*=\s*\{(.*?)\n\};", re.DOTALL)
_TOOL_LABEL_ROW = re.compile(r"^\s*([a-z_][a-z_0-9]*):\s*\"([^\"]*)\",\s*$")
_DEFAULT_TOOL_LABEL = "Complete a project step"

#: The frontend's own map of tool name to the words the marketer reads on the chat card.
_TOOL_LABELS_SOURCE = (
    Path("apps")
    / "frontend"
    / "src"
    / "features"
    / "projects"
    / "model"
    / "chat-tool-presentation.ts"
)


class ManualBuildError(RuntimeError):
    """A chapter cannot be rendered honestly: a missing note, a bad link, a malformed snapshot."""


@dataclass(frozen=True)
class Chapter:
    """One rendered chapter: the skill name suffix, its one-line summary, and its markdown body."""

    name: str
    summary: str
    body: str

    def __post_init__(self) -> None:
        if self.name not in MANUAL_CHAPTERS:
            raise ManualBuildError(f"{self.name!r} is not a chapter of the manual")
        if not self.summary.startswith("Manual: "):
            raise ManualBuildError(f"chapter {self.name!r} summary must begin 'Manual: '")
        if len(self.summary) > 160:
            raise ManualBuildError(
                f"chapter {self.name!r} summary is {len(self.summary)} characters; the capability "
                "map discloses fifteen of these and the block must stay small"
            )


@dataclass(frozen=True)
class CodeFacts:
    """The facts that live at the composition root, collected once and passed in.

    Every value is read off the real constant or contract, never retyped here. The agents package
    may not import ``clue_api``, so ``clue_api.manual_build`` fills this in.
    """

    settings: Settings
    trusted_turn_field_key: str
    failure_message_limit: int
    governed_tool_repair_help: str
    governed_failure_fields: tuple[tuple[str, str], ...]
    finalize_fields: tuple[tuple[str, str], ...]
    read_references_budget_bytes: int
    budget_limit_millicents: int


# =================================================================================================
# loading
# =================================================================================================


def load_notes(catalog_root: Path) -> dict[str, Any]:
    """The hand-written half: the next move per refusal code and per error string."""

    path = catalog_root / "manual" / "tool_notes.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ManualBuildError(f"{path} must be a mapping")
    return loaded


def load_fields(catalog_root: Path) -> list[dict[str, Any]]:
    """The committed ``field_definition`` snapshot, as written by ``fields_snapshot``."""

    path = catalog_root / "manual" / "fields.json"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise ManualBuildError(f"{path} must be a list of field rows")
    return [dict(row) for row in loaded]


def load_profile(catalog_root: Path, name: str, version: str) -> ProfileDefinition:
    """The exact profile version the generated chapters describe."""

    catalog = FolderProfileCatalog((catalog_root / "profiles").resolve(strict=True))
    return catalog.get(name, version).definition


def load_tool_labels(repo_root: Path | None = None) -> dict[str, str]:
    """``TOOL_LABELS`` from the frontend, parsed as text.

    The chat card is TypeScript and this is Python, so the map is read rather than imported. A
    tool the frontend does not name renders as the frontend's own fallback.
    """

    root = repo_root or DEFAULT_CATALOG_ROOT.parents[2]
    source = (root / _TOOL_LABELS_SOURCE).read_text(encoding="utf-8")
    block = _TOOL_LABELS_BLOCK.search(source)
    if block is None:
        raise ManualBuildError("TOOL_LABELS was not found in the frontend presentation map")
    labels: dict[str, str] = {}
    for line in block.group(1).splitlines():
        row = _TOOL_LABEL_ROW.match(line)
        if row is not None:
            labels[row.group(1)] = row.group(2)
    return labels


# =================================================================================================
# introspection
# =================================================================================================


def _clean(text: str) -> str:
    """Sphinx markup out of a code comment, so a table cell reads as a sentence."""

    text = re.sub(r":[a-z]+:`~?([^`]+)`", r"`\1`", text)
    text = text.replace("``", "`")
    return " ".join(text.split())


def _attribute_comments(model: type[BaseModel]) -> dict[str, str]:
    """The ``#:`` comments above each field, which pydantic does not carry into the schema.

    Every status vocabulary this platform has is written in one of these comments and reaches no
    schema the model ever sees. Reading them here is the whole reason the fields tables are worth
    printing.
    """

    try:
        source = inspect.getsource(model)
    except (OSError, TypeError):  # pragma: no cover - a model with no readable source
        return {}
    comments: dict[str, str] = {}
    pending: list[str] = []
    for raw in source.splitlines():
        line = raw.strip()
        if line.startswith("#:"):
            pending.append(line[2:].strip())
            continue
        named = re.match(r"([a-z_][a-z_0-9]*)\s*:", line)
        if named is not None and pending:
            comments[named.group(1)] = _clean(" ".join(pending))
        pending = []
    return comments


def _render_type(annotation: Any) -> str:
    if annotation is None:
        return "None"
    if isinstance(annotation, type):
        return annotation.__name__
    text = str(annotation).replace("NoneType", "None")
    return _DOTTED_NAME.sub(r"\1", text).replace("|", "or")


def _render_default(field: FieldInfo) -> str:
    if field.is_required():
        return "required"
    if field.default_factory is not None:
        return "(built per call)"
    return f"`{field.default!r}`"


def _render_bounds(field: FieldInfo) -> str:
    """The constraints the field actually declares, with the unset half of each dropped.

    ``StringConstraints`` carries a slot for every constraint it could express, most of them
    ``None``; printing those would make a one-rule field look like an eight-rule one.
    """

    parts: list[str] = []
    for item in field.metadata:
        if is_dataclass(item) and not isinstance(item, type):
            for spec in dataclass_fields(item):
                value = getattr(item, spec.name)
                if value is not None and value is not False:
                    parts.append(f"{spec.name}={value!r}")
        else:  # pragma: no cover - annotated-types ships dataclasses only
            parts.append(str(item))
    return ", ".join(parts).replace("|", "or") if parts else "none"


def _describe(
    field: FieldInfo, comments: Mapping[str, str], name: str, *, trusted_key: str | None = None
) -> str:
    """One field's meaning, and whether the model supplies it at all.

    A trusted field is filled in by the runtime from the turn the human actually sent. The model
    holds the argument in its schema but must never author one, so the manual says so where the
    field is listed rather than leaving it to a refusal.
    """

    text = ""
    if field.description:
        text = _clean(field.description)
    elif name in comments:
        text = comments[name]
    extra = field.json_schema_extra
    if trusted_key and isinstance(extra, dict) and extra.get(trusted_key):
        injected = "Injected by the platform from this turn. Never author one."
        return f"{injected} {text}".strip()
    return text or "—"


def _nested_models(model: type[BaseModel]) -> list[type[BaseModel]]:
    """The row models an output field is built out of, one level down, in field order."""

    found: list[type[BaseModel]] = []
    for field in model.model_fields.values():
        for candidate in _annotation_models(field.annotation):
            if candidate not in found and candidate is not model:
                found.append(candidate)
    return found


def _annotation_models(annotation: Any) -> list[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    found: list[type[BaseModel]] = []
    for argument in get_args(annotation):
        found.extend(_annotation_models(argument))
    return found


def _field_table(
    model: type[BaseModel], *, with_default: bool, trusted_key: str | None = None
) -> list[str]:
    comments = _attribute_comments(model)
    header = (
        "| Field | Type | Default | Bounds | What it is |"
        if with_default
        else "| Field | Type | What it is |"
    )
    rule = "| --- | --- | --- | --- | --- |" if with_default else "| --- | --- | --- |"
    rows = [header, rule]
    for name, field in model.model_fields.items():
        kind = f"`{_render_type(field.annotation)}`"
        text = _describe(field, comments, name, trusted_key=trusted_key).replace("|", "\\|")
        if with_default:
            rows.append(
                f"| `{name}` | {kind} | {_render_default(field)} | {_render_bounds(field)} "
                f"| {text} |"
            )
        else:
            rows.append(f"| `{name}` | {kind} | {text} |")
    return rows


def _gate_kind(model: type[BaseModel]) -> str | None:
    field = model.model_fields.get("gate_kind")
    if field is None:
        return None
    annotation = field.annotation
    if get_origin(annotation) is Literal:
        return str(get_args(annotation)[0])
    # It opens a gate, but declares no one kind: the kind comes off the gate row it opened.
    return ""


# =================================================================================================
# the tools chapter
# =================================================================================================


def build_tools_chapter(
    toolbelt: ToolRegistry,
    profile: ProfileDefinition,
    notes: Mapping[str, Any],
    labels: Mapping[str, str] | None = None,
    trusted_key: str | None = None,
) -> Chapter:
    """One section per granted tool, in profile order, then the framework surface.

    The grant is the profile's ``tools:`` list and nothing else: a tool the platform registers but
    does not grant this role is not in the manual, because a chapter that advertises a tool the
    model cannot call is a lie about the surface.
    """

    label_map = dict(labels) if labels is not None else load_tool_labels()
    missing = [pin.name for pin in profile.tools if pin.name not in notes]
    if missing:
        raise ManualBuildError(
            "tool_notes.yaml has no entry for "
            + ", ".join(sorted(missing))
            + "; every granted tool needs its refusal codes and the next move for each"
        )

    lines: list[str] = [
        f"# Tools: the governed surface of {profile.name}@{profile.version}",
        "",
        "Every tool you hold, read off the live descriptor. The address is what the platform",
        "registered; the model calls it under the bare name. A call is one governed plan: it is",
        "validated, executed and journaled, and you get a bounded receipt or a typed refusal.",
        "Nothing here grants anything. What you may call is stated once, by your resolved",
        "resource and capability map, and that map is authoritative.",
        "",
        "A refusal means nothing was recorded. Correct exactly what the reasons name and call",
        "again, or tell the human what is blocking you. Never report a refused call as done.",
        "Error shapes and the budget that stops a repair loop are in manual:errors and",
        "manual:limits.",
        "",
        "| Tool | Effect | Spends | Opens a gate | The human sees |",
        "| --- | --- | --- | --- | --- |",
    ]
    for pin in profile.tools:
        descriptor = toolbelt.descriptor(pin.name, pin.version)
        spends = "yes" if descriptor.effect_class is ToolEffectClass.SPEND else "no"
        gate = "no" if _gate_kind(descriptor.output_model) is None else "yes"
        lines.append(
            f"| `{descriptor.address}` | {descriptor.effect_class.value} | {spends} "
            f"| {gate} | {label_map.get(pin.name, _DEFAULT_TOOL_LABEL)} |"
        )
    lines.append("")

    for pin in profile.tools:
        lines.extend(
            _tool_section(
                toolbelt.descriptor(pin.name, pin.version),
                notes=notes[pin.name],
                label=label_map.get(pin.name, _DEFAULT_TOOL_LABEL),
                trusted_key=trusted_key,
            )
        )

    lines.extend(_framework_section())
    lines.extend(_finalize_section())
    return Chapter(name="tools", summary=_CHAPTER_SUMMARIES["tools"], body="\n".join(lines) + "\n")


def _tool_section(
    descriptor: Any, *, notes: Mapping[str, Any], label: str, trusted_key: str | None
) -> list[str]:
    refusals = notes.get("refusals")
    if not isinstance(refusals, dict) or not refusals:
        raise ManualBuildError(
            f"tool_notes.yaml gives {descriptor.name!r} no refusal codes; a tool that cannot "
            "refuse has not been read"
        )
    gate = _gate_kind(descriptor.output_model)
    spends = descriptor.effect_class is ToolEffectClass.SPEND
    journal = descriptor.parameter_policy.safe_display_fields

    lines = [
        f"## {descriptor.address}",
        "",
        f"**What it does.** {_clean(descriptor.model_description)}",
        "",
        f"- Effect class: `{descriptor.effect_class.value}`.",
        (
            "- Spends: yes. This call costs money against the project's providers."
            if spends
            else "- Spends: no."
        ),
        _gate_line(gate),
        f"- Replay identity: {_clean(descriptor.replay.durable_identity)}.",
        f"- Pins the call is bound to: {_join_code(descriptor.pin_requirements)}.",
        f"- Journal-safe input fields: {_join_code(journal)}.",
        f'- The human sees: "{label}".',
        "",
        "**Inputs**",
        "",
    ]
    lines.extend(_field_table(descriptor.input_model, with_default=True, trusted_key=trusted_key))
    lines.extend(["", "**Outputs**", ""])
    lines.extend(_field_table(descriptor.output_model, with_default=False))
    for nested in _nested_models(descriptor.output_model):
        summary = _clean(nested.__doc__ or "One row.")
        lines.extend(["", f"*{nested.__name__}*: {summary}", ""])
        lines.extend(_field_table(nested, with_default=False))

    lines.extend(["", "**Refusals**", "", "| Code | Next move |", "| --- | --- |"])
    for code, move in refusals.items():
        lines.append(f"| `{code}` | {str(move).strip()} |")

    afterwards = notes.get("afterwards")
    if afterwards:
        lines.extend(["", f"**Afterwards.** {str(afterwards).strip()}"])
    skill_section = notes.get("skill_section")
    if skill_section:
        lines.extend(["", f"**Taught by.** {str(skill_section).strip()}"])
    see_also = notes.get("see_also") or ()
    if see_also:
        lines.extend(
            ["", "**See also.** " + ", ".join(f"manual:{name}" for name in see_also) + "."]
        )
    lines.append("")
    return lines


def _gate_line(gate: str | None) -> str:
    if gate is None:
        return "- Opens a human gate: no."
    kind = f", of kind `{gate}`" if gate else ", whose kind the output names"
    return (
        f"- Opens a human gate: yes{kind}. Put it into `open_gate_refs` as "
        '`{object_type: "agent_gate", object_id: <the gate id it returns>}` when you finalize, '
        "or the human never sees the card."
    )


def _join_code(values: Sequence[str]) -> str:
    return ", ".join(f"`{value}`" for value in values) if values else "none"


def _framework_section() -> list[str]:
    """The deepagents file tools as they really behave, not as their names suggest."""

    names = ", ".join(f"`{name}`" for name in sorted(_FRAMEWORK_TOOL_NAMES))
    return [
        "## The framework file tools",
        "",
        f"Always installed beside the governed tools: {names}. They act on your virtual",
        "workspace, never on a host. They are not governed: they write no receipt and no journal",
        "row, and their errors are plain prefixed strings (manual:errors).",
        "",
        "| Tool | What it really does |",
        "| --- | --- |",
        "| `ls(path)` | A flat file walk, not a directory tree. `is_dir` is false on every "
        "entry; only the read-only mount roots are marked as directories, and only when you "
        "list the root itself. |",
        "| `read_file(file_path, offset=0, limit=2000)` | `offset` and `limit` count LINES, not "
        "bytes. The default window is the first 2,000 lines; a longer file is silently cut at "
        "the window, so read on with a larger offset. |",
        "| `write_file(file_path, content)` | Whole-file replace inside a writable prefix, with "
        "an allowed extension. The quota is checked before the write. |",
        "| `edit_file(file_path, old_string, new_string)` | Compare-and-replace of exactly one "
        "occurrence. `replace_all=True` is refused outright. A source text that is absent or not "
        "unique is a conflict: copy the span again, never reword it. |",
        "| `glob(pattern, path=None)` | `fnmatch` over a flat list, not a path glob: `*` crosses "
        "`/`, and `**` is only two stars. |",
        "| `grep(pattern, path=None, glob=None)` | A plain substring test, not a regular "
        "expression, over every file the glob matched. Each matched file is read whole. |",
        "| `write_todos(...)` | The framework's own scratch plan. It writes to graph state only: "
        "no file, no durable row, and the human never sees it. |",
        "",
        "What you may read and write is the workspace policy in manual:limits; the folders "
        "themselves are manual:workspace.",
        "",
    ]


def _finalize_section() -> list[str]:
    return [
        f"## {_FINALIZE_TOOL_NAME}",
        "",
        "The mandatory terminal action, and the only thing that reaches the human. It is not a",
        "toolbelt tool: no address, no effect class, no pins. Calling it ends the turn, so call",
        "it once and last. A turn that never calls it commits nothing and shows the human",
        "nothing.",
        "",
        "- `status` is one of `completed`, `awaiting_input`, `blocked`, `failed`. Only `failed`",
        "  may carry a `failure_code`, and `failed` must carry one.",
        "- `user_message` is the message the human reads. `completed` must carry one.",
        "- `awaiting_input` and `blocked` must identify what they wait for: `next_actions`,",
        "  `open_gate_refs`, or a `user_message` that asks for it.",
        "- `open_gate_refs` becomes the gate card; `domain_refs` of a plan-shaped object type",
        "  becomes the plan card. Nothing else you write becomes a card.",
        "- `assumptions` are stored as artifacts and are never shown to the human. If it matters,",
        "  it belongs in `user_message`.",
        "- Finalizing freezes `outputs/`: after it, a write there is a conflict.",
        "",
        "Its refusals have their own budget, separate from the governed one (manual:limits), and",
        "the exact strings are in manual:errors.",
        "",
    ]


# =================================================================================================
# the fields chapter
# =================================================================================================


def build_fields_chapter(snapshot: Sequence[Mapping[str, Any]]) -> Chapter:
    """The registered claim fields, keyed by the family a claims read can be narrowed to.

    A "family" is the first two dotted segments of the key, exactly as the read computes them, so
    ``account.resonance.culture`` and ``account.resonance.frustrations`` share one family while
    ``core.legal_name``, which has no third segment, is its own. Only three families hold more
    than one key today, so the tables are grouped by namespace and carry the family as a column
    rather than splitting into a hundred one-row sections. Families and namespaces alike appear in
    registry order: the order of first appearance in the snapshot.
    """

    if not snapshot:
        raise ManualBuildError("the field snapshot is empty; run the fields_snapshot script")

    namespaces: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    families: set[str] = set()
    for row in snapshot:
        key = str(row["field_key"])
        segments = key.split(".")
        family = ".".join(segments[:2])
        families.add(family)
        namespaces.setdefault(segments[0], []).append((family, row))

    inactive = sum(1 for row in snapshot if not row.get("active"))
    standing = f"{inactive} of them inactive" if inactive else "every one of them active"
    lines = [
        "# Fields: the claim registry",
        "",
        f"{len(snapshot)} registered fields in {len(families)} families across "
        f"{len(namespaces)} namespaces, {standing}. Every claim is about a registered field, so",
        "this is the vocabulary every fact in the store is written in.",
        "",
        "**How to narrow a read.** A claims read takes a `field_prefix`, matched as a plain",
        "string against the start of the field key. Pass a value from the Family column:",
        "`account.resonance` narrows a researched account to that family. Never guess one. The",
        "read carries the families the account actually holds, with a count each, and a prefix",
        "that matches nothing is refused by name and lists them. Registered is not the same as",
        "populated: this chapter says what a field means, and the read says what an account has.",
        "",
        "Columns: the family to narrow by; the value shape the field declares; how long a claim",
        "of it stays fresh; whether its claims are tenant-private or a public footprint; the gate",
        "a claim must clear; the industry pack it belongs to; and the signal it is the cheap or",
        "the deep half of. An absent value is `—`. An inactive field is marked, and a claim is",
        "not written for it.",
        "",
    ]
    for namespace, rows in namespaces.items():
        lines.extend(
            [
                f"## {namespace}",
                "",
                "| Field | Family | Type | Freshness | Reuse scope | Gate | Pack | Signal "
                "| What it is |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for family, row in rows:
            key = str(row["field_key"])
            name = f"`{key}`" if row.get("active") else f"`{key}` (inactive)"
            lines.append(
                f"| {name} | `{family}` | {_cell(row.get('value_type'))} "
                f"| {_freshness(row.get('freshness_ttl'))} | {_cell(row.get('reuse_scope'))} "
                f"| {_cell(row.get('gate'))} | {_cell(row.get('pack'))} "
                f"| {_cell(row.get('signal_class'))} | {_cell(row.get('description'))} |"
            )
        lines.append("")

    lines.extend(
        [
            "What a claim's tier, verification status, use class and display gate mean is",
            "manual:claims. The read that serves them, and everything it can refuse with, is",
            "manual:tools.",
            "",
        ]
    )
    return Chapter(
        name="fields", summary=_CHAPTER_SUMMARIES["fields"], body="\n".join(lines) + "\n"
    )


def _freshness(value: Any) -> str:
    """A stored interval, without the zero remainder Python prints after the days."""

    if value is None:
        return "—"
    return _cell(str(value).removesuffix(", 0:00:00"))


def _cell(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return _clean(str(value)).replace("|", "\\|")


# =================================================================================================
# the errors chapter
# =================================================================================================


def build_errors_chapter(notes: Mapping[str, Any], facts: CodeFacts) -> Chapter:
    """Every string the model can be handed as bad news, and the one next move for each."""

    errors = notes.get("errors")
    if not isinstance(errors, dict) or not errors:
        raise ManualBuildError("tool_notes.yaml carries no `errors` map")

    lines = [
        "# Errors: every string you can be handed, and what to do about it",
        "",
        "Three shapes of bad news reach you, and only three. A governed tool refuses with a typed",
        "JSON object. A file tool returns a prefixed string on its own result. `finalize_turn`",
        "raises a plain message with its own guidance appended. Nothing else is an error you can",
        "read: a turn's own failure code is written after the graph ends, and you never see it.",
        "",
        "## The governed refusal",
        "",
        "A refused governed call comes back as a tool result, not an exception, so you can repair",
        "it. Its fields:",
        "",
        "| Field | What it says |",
        "| --- | --- |",
    ]
    lines.extend(f"| `{name}` | {text} |" for name, text in facts.governed_failure_fields)
    lines.extend(
        [
            "",
            f'`guidance` is always the same sentence: "{facts.governed_tool_repair_help}"',
            "",
            "Read `recorded: false` literally. Nothing was written, no run was queued, no money",
            "was spent. Saying otherwise to the human is the one failure this shape exists to",
            "prevent.",
            "",
            "`error` is `plan_rejected` when the proposal never obtained authority, so nothing",
            "ran at all, and `operation_failed` when it ran and did not complete. Each entry of",
            f"`reasons` is one issue, whitespace-collapsed and cut at "
            f"{facts.failure_message_limit} characters, so a long message may end mid-sentence.",
            "",
        ]
    )

    for group, heading, preamble in (
        (
            "plan_rejected",
            "## Plan-rejection codes",
            "A `plan_rejected` reason reads `<location>: <code>: <message>`. The codes are the "
            "platform's, not a tool's, and none of them is repaired by calling the same tool "
            "again with the same arguments.",
        ),
        (
            "operation_failed",
            "## Precondition refusals",
            "An `operation_failed` reason reads `<error_type>: <message>`. The common one is "
            "`PreconditionFailed`, whose message is `<code>: <what to satisfy>` for each unmet "
            "precondition. The code set is open: every tool owns its own, and the codes you can "
            "actually receive are listed per tool in manual:tools. What matters is the shape, so "
            "read the code, satisfy exactly what it names, and if you cannot, say so to the "
            "human and stay `awaiting_input`.",
        ),
        (
            "file_tools",
            "## File-tool errors",
            "These never go through the governed path. They arrive as a string on the file "
            "tool's own result, under one of three prefixes.",
        ),
        (
            "finalize",
            "## finalize_turn refusals",
            "A refused finalization is not committed and the turn is not over. The message names "
            "exactly what is wrong, and one of two fixed sentences is appended to it.",
        ),
        (
            "middleware",
            "## Two strings the runtime itself produces",
            "Neither is a tool's refusal; both come from the surface that wraps every model call.",
        ),
    ):
        rows = errors.get(group)
        if not isinstance(rows, dict) or not rows:
            raise ManualBuildError(f"tool_notes.yaml `errors` has no {group!r} group")
        lines.extend([heading, "", preamble, "", "| String | Next move |", "| --- | --- |"])
        lines.extend(f"| `{code}` | {str(move).strip()} |" for code, move in rows.items())
        lines.append("")

    lines.extend(
        [
            "## What a refusal costs you",
            "",
            "A refused governed call comes back to you with its reasons. The cost is counted in",
            "rounds, not calls. A round in which one or more calls were refused spends one repair",
            "round. It is charged only after every call in that round has returned.",
            f"{MAX_TOOL_REPAIR_ROUNDS} repair rounds come back to you. The next one ends the turn",
            "with nothing shown to the human.",
            f"`finalize_turn` has its own separate budget of {_MAX_FINALIZE_REPAIRS} repairs.",
            "Those numbers and the rest of the turn's limits are manual:limits.",
            "",
        ]
    )
    return Chapter(
        name="errors", summary=_CHAPTER_SUMMARIES["errors"], body="\n".join(lines) + "\n"
    )


# =================================================================================================
# the limits chapter
# =================================================================================================


def build_limits_chapter(
    profile: ProfileDefinition, settings: Settings, facts: CodeFacts
) -> Chapter:
    """Rounds, clocks, caps, quotas and retention, from the profile and the named constants."""

    workspace = profile.workspace

    lines = [
        f"# Limits: what bounds one turn of {profile.name}@{profile.version}",
        "",
        "Every limit here is enforced. The round limit and the time limit are set by the",
        "deployment, so this page does not state them as numbers. The platform tells you when you",
        "are near either one. Save your work as you go, so that a turn that ends early still",
        "leaves everything you found.",
        "",
        "## The turn",
        "",
        "| Limit | Value | What happens at the edge |",
        "| --- | --- | --- |",
        "| Model rounds | Set by the deployment. A round is one model call. | Three rounds before "
        "the end, a platform notice tells you how many rounds are left. Use them to save what "
        "you have not saved. After that, only `finalize_turn` is offered. If the work is not "
        "finished, finalize with status `awaiting_input`, say in `user_message` what you "
        "completed, list what remains in `next_actions`, and tell the user they can reply "
        '"continue". |',
        "| Wall clock | Set by the deployment. There may be no time limit at all. | When there "
        "is one, the same notice starts about three minutes before it. In the last minute, only "
        "`finalize_turn` is offered. |",
        f"| Output tokens per call | {profile.model.max_output_tokens:,} | A longer answer is cut. "
        "Say less per round rather than more. |",
        f"| Plan nodes | {profile.max_plan_nodes} | A proposal over the ceiling is rejected "
        "before it runs. |",
        f"| Delegations | {profile.max_delegations}, depth {profile.max_delegation_depth} | "
        "Whether delegation is installed at all is decided by the surface, not by this number: "
        "read your capability map. |",
        f"| Estimated spend per plan | {facts.budget_limit_millicents:,} millicents | A ceiling on "
        "the estimate, not a running total. You cannot see what has been spent, and must not "
        "guess at it. |",
        "",
        "## The two repair budgets",
        "",
        "| Budget | Value | What the last one does |",
        "| --- | --- | --- |",
        f"| Rounds with a refused governed call | {MAX_TOOL_REPAIR_ROUNDS} per turn. A round "
        "counts once, however many of its calls were refused, and it is counted only after every "
        "call in that round has returned. | The next such round ends the turn, and the human "
        "sees nothing. |",
        f"| Refused finalizations | {_MAX_FINALIZE_REPAIRS} per turn, counted separately | The "
        "last refusal ends the turn with nothing committed. |",
        "",
        f'Once the finalize budget is spent the runtime appends: "{_FINALIZE_REPAIRS_EXHAUSTED}"',
        "",
        "## What one answer may carry",
        "",
        "| Field | Bound |",
        "| --- | --- |",
    ]
    lines.extend(f"| `{name}` | {bound} |" for name, bound in facts.finalize_fields)
    lines.extend(
        [
            "",
            "## Bytes",
            "",
            "| Bound | Value | Why it bites |",
            "| --- | --- | --- |",
            f"| One governed receipt's `reference_values` | {RECEIPT_REFERENCE_VALUES_MAX_BYTES:,} "
            "bytes | Substantive output stays behind references: a tool that would return a lot "
            "hands back refs, and you read the file or the row. |",
            f"| One read tool's served rows | {facts.read_references_budget_bytes:,} bytes | The "
            "reads page themselves to fit. A page that was cut says so, and carries the offset "
            "to continue from. |",
            f"| Workspace total | {workspace.max_total_bytes:,} bytes across at most "
            f"{workspace.max_file_count:,} files | The envelope is fixed for the turn, so a write "
            "that exceeded it cannot be retried into success. Delete or shorten first. |",
            f"| One workspace file | {workspace.max_file_bytes:,} bytes | Reading a file over the "
            "bound is refused too, not truncated. |",
            "",
            "## The workspace envelope",
            "",
            f"- Readable: {_join_code(workspace.readable_prefixes)}.",
            f"- Writable: {_join_code(workspace.writable_prefixes)}.",
            f"- Allowed file types: {_join_code(workspace.allowed_extensions)}.",
            "- Your folders belong to this chat, not to one turn, and they are not tied to one "
            "machine — any worker can continue this chat and finds them as you left them. Files "
            "are deleted by age, not the folder: see the workspace chapter for what goes when.",
            "",
            "Everything a path means is manual:workspace; the errors these bounds produce are",
            "manual:errors.",
            "",
        ]
    )
    return Chapter(
        name="limits", summary=_CHAPTER_SUMMARIES["limits"], body="\n".join(lines) + "\n"
    )


# =================================================================================================
# rendering and the CLI
# =================================================================================================


def tool_manual_link(tool_name: str) -> str:
    """The closing pointer a governed tool's description gives the model: this tool's entry in the
    CURRENT tools chapter. Built from :data:`MANUAL_VERSION` so a manual re-mint moves every
    pointer with it — hard-coded versions were left naming ``v5`` for six re-mints."""

    return f"Manual: .deepagent/skills/manual-tools/{MANUAL_VERSION}/SKILL.md#{tool_name}"


def materialized_links(version: str) -> dict[str, str]:
    """Every chapter's path in the workspace, the way the resource materializer writes it."""

    return {name: f".deepagent/skills/manual-{name}/{version}/SKILL.md" for name in MANUAL_CHAPTERS}


def render_skill(chapter: Chapter, *, version: str, links: Mapping[str, str]) -> str:
    """Front matter plus the body, with every `manual:<chapter>` token rewritten to its path."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in links:
            raise ManualBuildError(
                f"chapter {chapter.name!r} links to manual:{name}, which is not a chapter"
            )
        return f"`{links[name]}`"

    body = _LINK_TOKEN.sub(replace, chapter.body)
    header = "\n".join(
        [
            "---",
            'schema_version: "1"',
            "kind: skill",
            f"name: manual-{chapter.name}",
            f"version: {version}",
            f"summary: {json.dumps(chapter.summary)}",
            "roles:",
            f"  - {_SKILL_ROLE}",
            "readiness_requirements: []",
            "tools: []",
            "framework: deepagents",
            f'framework_version: "{_FRAMEWORK_VERSION}"',
            "---",
            "",
        ]
    )
    return (header + body).rstrip() + "\n"


def chapter_path(catalog_root: Path, name: str, version: str) -> Path:
    return catalog_root / "skills" / f"manual-{name}" / version / "SKILL.md"


def link_handwritten_chapters(
    *,
    catalog_root: Path = DEFAULT_CATALOG_ROOT,
    version: str = MANUAL_VERSION,
) -> dict[str, int]:
    """Rewrite every `manual:<chapter>` token in the hand-written chapters to its path, in place.

    The generated chapters are never touched: their tokens are resolved by :func:`render_skill`
    while the body is rendered, so a rewrite here would fight the builder. The hand-written ones
    have no source to render from, so the token in the committed file is the thing that has to
    move. A token naming something that is not a chapter fails by name rather than writing a path
    to a file that will never exist. Running this twice changes nothing: after the first pass
    there is no token left to match.
    """

    links = materialized_links(version)

    counts: dict[str, int] = {}
    for name in HANDWRITTEN_CHAPTERS:
        path = chapter_path(catalog_root, name, version)
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        found = 0

        def replace(match: re.Match[str], chapter: str = name) -> str:
            nonlocal found
            target = match.group(1)
            if target not in links:
                raise ManualBuildError(
                    f"chapter {chapter!r} links to manual:{target}, which is not a chapter"
                )
            found += 1
            return f"`{links[target]}`"

        rewritten = _LINK_TOKEN.sub(replace, text)
        if rewritten != text:
            path.write_text(rewritten, encoding="utf-8")
        counts[name] = found
    return counts


def build_chapter_objects(
    *,
    toolbelt: ToolRegistry,
    facts: CodeFacts,
    catalog_root: Path = DEFAULT_CATALOG_ROOT,
) -> dict[str, Chapter]:
    """The four generated chapters, built in a fixed order from the committed inputs."""

    notes = load_notes(catalog_root)
    profile = load_profile(catalog_root, PROFILE_NAME, PROFILE_VERSION)
    chapters = {
        "tools": build_tools_chapter(
            toolbelt, profile, notes, trusted_key=facts.trusted_turn_field_key
        ),
        "fields": build_fields_chapter(load_fields(catalog_root)),
        "errors": build_errors_chapter(notes, facts),
        "limits": build_limits_chapter(profile, facts.settings, facts),
    }
    if tuple(chapters) != GENERATED_CHAPTERS:
        raise ManualBuildError(f"the builder produced {tuple(chapters)}, not {GENERATED_CHAPTERS}")
    return chapters


def build_chapters(
    *,
    toolbelt: ToolRegistry,
    facts: CodeFacts,
    catalog_root: Path = DEFAULT_CATALOG_ROOT,
) -> dict[str, str]:
    """The four chapters as the exact bytes their `SKILL.md` files must hold."""

    links = materialized_links(MANUAL_VERSION)
    return {
        name: render_skill(chapter, version=MANUAL_VERSION, links=links)
        for name, chapter in build_chapter_objects(
            toolbelt=toolbelt, facts=facts, catalog_root=catalog_root
        ).items()
    }


def run(argv: Sequence[str] | None, *, toolbelt: ToolRegistry, facts: CodeFacts) -> int:
    """`--write` regenerates the chapters; `--check` fails on drift; `--link` resolves tokens."""

    parser = argparse.ArgumentParser(
        prog="manual-build",
        description="Regenerate the generated chapters of the Head of ABM's operating manual.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate the chapters in place")
    mode.add_argument("--check", action="store_true", help="fail when a chapter is stale")
    mode.add_argument(
        "--link",
        action="store_true",
        help="rewrite the hand-written chapters' `manual:<chapter>` tokens to their paths",
    )
    parser.add_argument("--catalog-root", type=Path, default=DEFAULT_CATALOG_ROOT)
    parsed = parser.parse_args(argv)

    if parsed.link:
        counts = link_handwritten_chapters(catalog_root=parsed.catalog_root)
        rewritten = {name: found for name, found in counts.items() if found}
        if not rewritten:
            print("no `manual:<chapter>` tokens left in the hand-written chapters")
            return 0
        for name, found in rewritten.items():
            print(f"linked {found} cross-reference(s) in manual-{name}")
        return 0

    rendered = build_chapters(toolbelt=toolbelt, facts=facts, catalog_root=parsed.catalog_root)
    stale: list[str] = []
    for name, text in rendered.items():
        path = chapter_path(parsed.catalog_root, name, MANUAL_VERSION)
        payload = text.encode()
        if path.exists() and path.read_bytes() == payload:
            continue
        if parsed.check:
            stale.append(f"manual-{name}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        print(f"wrote {path}")
    if stale:
        print("stale manual chapters: " + ", ".join(stale) + "\nrun `make manual` and commit them.")
        return 1
    if parsed.check:
        print(f"{len(rendered)} manual chapters are current")
    return 0

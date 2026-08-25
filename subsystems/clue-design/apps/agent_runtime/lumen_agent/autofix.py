"""Deterministic preflight autofix — the code loop below the model (spec §5.4).

WHY THIS EXISTS. The 2026-08-24 forensics (``docs/deepagent-fast-loop-v1-spec.md``
§1) measured a 43m18s / 178-call scene run in which a large share of the calls
went to repairing *mechanical* preflight diagnostics — a text box one line too
short, a slot with no fit fixture. Each of those repairs cost a full model call:
10–25 seconds and 95–124K input tokens, to change a single property whose
correct value was already implied by the engine's own diagnostic. This module
does those repairs in Python, between the engine and the model, so the author
only ever sees the diagnostics that actually need judgment.

THE CONTRACT, in four rules:

1. **Derive, never guess.** Every patch is built from the engine's own
   diagnostic (``code`` + ``subject``) plus the scene state that diagnostic
   points at. Nothing is parsed out of a message string — the engine's
   ``Diagnostic`` (``crates/lumen-core/src/diagnostics.rs``) is
   ``{severity, phase, code, message, subject, hint}`` and carries **no**
   structured payload, so a class that would need a number out of the prose is
   simply not a v1 class. See ``docs`` note at :data:`SHIPPED_CLASSES`.
2. **The engine decides whether it worked.** A patch is applied to a COPY of
   the scene and the copy is re-preflighted. The working scene moves only if
   :func:`_verify` passes.
3. **Rollback is structural, not compensating.** Because the working scene is
   never mutated before verification, a rejected patch needs no undo — the
   original scene and the original diagnostic simply stand, and the attempt is
   reported to the model so it knows the mechanical fix was already tried.
4. **Bounded.** At most ``max_passes`` planning passes, and no diagnostic key is
   ever attempted twice. The loop also exits the moment a pass makes no
   progress, so the cap is a ceiling, not a schedule.

WHAT IT IS NOT. Judgment-shaped repairs — a colour, a layout intent, a word —
stay with the author. Shipping fewer classes safely beats shipping all of them
speculatively; the excluded candidates and the evidence for excluding them are
recorded at :data:`EXCLUDED_CLASSES`.

This module is PURE: no I/O, no tool objects, no engine client. The caller
(``tools/substrate.py::preflight_design``) injects ``apply_operations`` and
``preflight`` callables, which is what makes the whole loop unit-testable
without a helper binary.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

JsonObject = dict[str, Any]

#: A diagnostic's identity for set arithmetic: the engine gives us a code and an
#: adjacently-tagged subject (``{"kind": "node", "id": "headline"}``), and that
#: pair is what "the same problem" means across two preflights.
DiagKey = tuple[str, str, str]

#: The classes this version repairs. Keep in sync with the docstrings below.
SHIPPED_CLASSES = ("text_box_hug", "slot_fixture")

#: Spec §5.4 named three candidate classes. This one did not survive scouting,
#: and the reason is recorded here rather than in a memo nobody reads: preflight
#: computes NO token fallback. ``TokenFallbackPolicy::UseFallbacks``
#: (``crates/lumen-core/src/brand.rs:1594``) is declared and never constructed —
#: the only policy in force is ``DiagnosticsOnly``. An unresolved token
#: (LUMB0201/0301/0401) is reported, never substituted, so there is no
#: engine-computed value for this loop to apply; picking a replacement colour or
#: type role is exactly the judgment call rule 1 forbids.
EXCLUDED_CLASSES = {
    "token_fallback": (
        "preflight computes no fallback value — TokenFallbackPolicy::UseFallbacks "
        "is dead code (brand.rs:1594) and every unresolved token is "
        "diagnostics-only; choosing a substitute token is a design decision"
    ),
}

#: Which SizeSpec dimension each text-fit code is about. The engine's own hints
#: name hug sizing first for both ("Use wrap(true), s(fill,hug), …" / "Use hug
#: height, …"), and hug is the one repair that needs no measurement from us: it
#: hands the sizing decision back to the engine's own text measurer, which is
#: the only component that can measure faithfully (the authoritative
#: ``SkiaTextMeasurer`` lives server-side; Python has no measurement API).
_TEXT_FIT_DIMENSION = {
    "LUMV0902": "width",  # non-wrapping text overflows horizontally
    "LUMV0903": "height",  # text exceeds available height
}

#: The two ways the engine says "this text slot has no fit fixture". LUMV0800 is
#: overloaded — it also means "node exceeds exportable bounds" — so it is only
#: ever a slot-fixture candidate when its subject is a SLOT, and the emptiness
#: precondition is re-derived from the scene rather than trusted from the code.
_SLOT_FIXTURE_CODES = ("LUMV0509", "LUMV0800")


class AutofixUnavailable(Exception):
    """The injected engine callable refused. Never raised out of :func:`run_autofix`."""


@dataclass(frozen=True)
class AutofixPatch:
    """One closed-form repair: the operations, and the diagnostics it claims."""

    klass: str
    targets: tuple[DiagKey, ...]
    operations: tuple[JsonObject, ...]
    detail: str

    @property
    def subject(self) -> str:
        return self.targets[0][2]

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(sorted({key[0] for key in self.targets}))


@dataclass
class AutofixRecord:
    """What the trace and the model are told about one attempt.

    Carries the operations themselves, not just a count: an ACCEPTED record's
    operations have to reach the caller's proposal ledger, because the editor's
    Accept replays that ledger onto the document and never sees the runtime's
    working scene.
    """

    klass: str
    codes: tuple[str, ...]
    subject: str
    detail: str
    operations: tuple[JsonObject, ...]
    accepted: bool
    reason: Optional[str] = None

    @property
    def operations_json(self) -> tuple[JsonObject, ...]:
        return self.operations

    def as_dict(self) -> JsonObject:
        payload: JsonObject = {
            "class": self.klass,
            "codes": list(self.codes),
            "subject": self.subject,
            "detail": self.detail,
            "operations": len(self.operations),
        }
        if not self.accepted:
            payload["rolled_back_because"] = self.reason
        return payload


@dataclass
class AutofixResult:
    """The post-autofix world: what the model sees, and why."""

    scene: JsonObject
    diagnostics: list[JsonObject]
    passes: int = 0
    applied: list[AutofixRecord] = field(default_factory=list)
    rolled_back: list[AutofixRecord] = field(default_factory=list)
    #: The engine's own ``preflight`` summary block for the scene that won, set
    #: by the caller (only it knows which engine response produced it).
    raw_preflight: JsonObject = field(default_factory=dict)

    @property
    def attempted(self) -> bool:
        return bool(self.applied or self.rolled_back)

    @property
    def changed(self) -> bool:
        return bool(self.applied)

    def counts_by_class(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.applied:
            counts[record.klass] = counts.get(record.klass, 0) + 1
        return counts

    def as_payload(self) -> JsonObject:
        """The ``autofix`` block that rides ``preflight.json`` and the tool result.

        The rolled-back list is not bookkeeping: it is the note spec §5.4 owes
        the author — "the mechanical repair for this diagnostic was tried and the
        engine rejected it, so do not spend a call retrying it verbatim".
        """
        return {
            "passes": self.passes,
            "applied_count": len(self.applied),
            "applied": [record.as_dict() for record in self.applied],
            "rolled_back_count": len(self.rolled_back),
            "rolled_back": [record.as_dict() for record in self.rolled_back],
            "by_class": self.counts_by_class(),
        }

    def summary_line(self) -> str:
        parts = []
        if self.applied:
            by_class = ", ".join(
                f"{klass}×{count}" for klass, count in sorted(self.counts_by_class().items())
            )
            parts.append(f"{len(self.applied)} autofix applied ({by_class})")
        if self.rolled_back:
            parts.append(f"{len(self.rolled_back)} rolled back")
        return "; ".join(parts)


# --------------------------------------------------------------------------- #
# diagnostic set arithmetic
# --------------------------------------------------------------------------- #
def diagnostic_key(diagnostic: JsonObject) -> DiagKey:
    subject = diagnostic.get("subject")
    if isinstance(subject, dict):
        kind = str(subject.get("kind") or "")
        ident = str(subject.get("id") or "")
    else:
        kind, ident = "", ""
    return (str(diagnostic.get("code") or ""), kind, ident)


def _keys(diagnostics: list[JsonObject]) -> set[DiagKey]:
    return {diagnostic_key(diagnostic) for diagnostic in diagnostics}


def _error_count(diagnostics: list[JsonObject]) -> int:
    return sum(1 for diagnostic in diagnostics if diagnostic.get("severity") == "error")


def _subject(diagnostic: JsonObject, kind: str) -> Optional[str]:
    subject = diagnostic.get("subject")
    if isinstance(subject, dict) and subject.get("kind") == kind:
        ident = subject.get("id")
        if isinstance(ident, str) and ident:
            return ident
    return None


# --------------------------------------------------------------------------- #
# class: text_box_hug  (LUMV0902 / LUMV0903)
# --------------------------------------------------------------------------- #
def _is_fixed(dimension: Any) -> bool:
    """Only a FIXED dimension is safely swappable for hug.

    ``hug`` is already the answer, ``token`` carries a brand binding this loop
    must not silently drop, and ``fill`` is a stated layout intent (the parent
    is doing the constraining) whose removal changes the design, not the defect.
    """
    return isinstance(dimension, dict) and dimension.get("kind") == "fixed"


def _plan_text_box_hug(scene: JsonObject, diagnostics: list[JsonObject]) -> list[AutofixPatch]:
    """Widen/heighten an overflowing text box by handing sizing back to the engine.

    Guards, each of which maps to a real way this could otherwise go wrong:

    * ``severity == "error"`` — the engine downgrades text-fit codes to *warning*
      for freehand nodes precisely because "a human resizing a pinned text box
      below its content is explicit intent" (``layout.rs:1187-1197``), and
      ``relayout_final`` downgrades them again when the slot policy is
      clip/ellipsis/ask-agent. Both downgrades are the engine telling us the
      overflow is intended. Filtering on ``error`` inherits both rulings for
      free rather than re-deriving them.
    * ``position_mode != "absolute"`` and not ``locked`` — belt for the same
      case, and for a node a human has explicitly pinned.
    * the node is a text node that still exists.
    * the failing dimension is currently ``fixed`` (see :func:`_is_fixed`).

    One patch per node per pass, covering every failing dimension at once: the
    patch carries a whole ``SizeSpec``, so two patches on the same node in the
    same pass would clobber each other.
    """
    from .retokenize import empty_node_patch

    nodes = scene.get("nodes")
    if not isinstance(nodes, dict):
        return []

    by_node: dict[str, list[JsonObject]] = {}
    for diagnostic in diagnostics:
        if diagnostic.get("code") not in _TEXT_FIT_DIMENSION:
            continue
        if diagnostic.get("severity") != "error":
            continue
        node_id = _subject(diagnostic, "node")
        if node_id is None:
            continue
        by_node.setdefault(node_id, []).append(diagnostic)

    patches: list[AutofixPatch] = []
    for node_id, node_diagnostics in sorted(by_node.items()):
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            continue
        kind = node.get("kind")
        if not isinstance(kind, dict) or kind.get("kind") != "text":
            continue
        if node.get("locked") or node.get("position_mode") == "absolute":
            continue
        size = node.get("size")
        if not isinstance(size, dict):
            continue

        new_size = copy.deepcopy(size)
        targets: list[DiagKey] = []
        moved: list[str] = []
        for diagnostic in node_diagnostics:
            dimension = _TEXT_FIT_DIMENSION[str(diagnostic["code"])]
            if not _is_fixed(size.get(dimension)):
                continue
            new_size[dimension] = {"kind": "hug"}
            targets.append(diagnostic_key(diagnostic))
            moved.append(f"{dimension} {size[dimension].get('value')}→hug")
        if not targets:
            continue

        patch = empty_node_patch()
        patch["size"] = {"kind": "set", "value": new_size}
        patches.append(
            AutofixPatch(
                klass="text_box_hug",
                targets=tuple(targets),
                operations=({"kind": "update_node", "node_id": node_id, "patch": patch},),
                detail=f"text node {node_id}: {', '.join(moved)}",
            )
        )
    return patches


# --------------------------------------------------------------------------- #
# class: slot_fixture  (LUMV0509 / LUMV0800-on-a-slot)
# --------------------------------------------------------------------------- #
def _bound_text(scene: JsonObject, slot: JsonObject) -> Optional[tuple[str, str]]:
    """The slot's own bound content, which IS the sample the slot is missing.

    Returns ``(node_id, content)`` for the first bound text node with non-empty
    content, or ``None`` — in which case nothing is derivable and the diagnostic
    belongs to the author, who has to decide what the content should say.
    """
    nodes = scene.get("nodes")
    if not isinstance(nodes, dict):
        return None
    bound = slot.get("bound_nodes")
    if not isinstance(bound, list):
        return None
    for node_id in bound:
        node = nodes.get(node_id) if isinstance(node_id, str) else None
        if not isinstance(node, dict):
            continue
        kind = node.get("kind")
        if not isinstance(kind, dict) or kind.get("kind") != "text":
            continue
        content = kind.get("content")
        if isinstance(content, str) and content.strip():
            return (node_id, content)
    return None


def _needs_fixture(slot: JsonObject, code: str) -> bool:
    """Re-derive the exact engine precondition for THIS code, per code.

    The two codes are not the same test, and conflating them costs a real
    repair. ``validation.rs:545`` (LUMV0509) asks only about *fit-validation*
    fixtures — ``samples`` / ``worst_case`` / ``validation.max_length``, and a
    ``placeholder`` does NOT satisfy it. ``layout.rs::slot_fixtures``
    (LUMV0800) asks whether the fixture LIST is empty, and a placeholder does
    satisfy that.

    Live-proven against the real helper 2026-08-24: the DSL's ``slot(key)``
    constructor sets ``placeholder`` to the node's own text, so every
    DSL-authored text slot arrives with a placeholder AND a LUMV0509. A union
    precondition (the first version of this function) declined to fix any of
    them — i.e. it disabled this whole class on the one path that produces it.
    """
    validation = slot.get("validation")
    validation = validation if isinstance(validation, dict) else {}
    if validation.get("samples") or validation.get("worst_case"):
        return False
    if validation.get("max_length") is not None:
        return False
    if code == "LUMV0509":
        return True
    # LUMV0800: the whole fixture list, placeholder and formatting cap included.
    if slot.get("placeholder"):
        return False
    formatting = slot.get("formatting")
    if isinstance(formatting, dict) and formatting.get("max_length") is not None:
        return False
    return True


def _plan_slot_fixture(scene: JsonObject, diagnostics: list[JsonObject]) -> list[AutofixPatch]:
    """Give a fixture-less text slot the sample its own bound node already renders.

    This is the class with no measurement problem at all: the fixture the slot
    is missing is a *string*, and the string the slot is for is sitting in the
    node it binds. Writing anything else — a longer "worst case", a
    domain-plausible variant — would be content invention, so this class writes
    exactly one sample and leaves ``worst_case`` to the author.
    """
    slots = scene.get("slots")
    if not isinstance(slots, dict):
        return []

    by_slot: dict[str, list[JsonObject]] = {}
    for diagnostic in diagnostics:
        if diagnostic.get("code") not in _SLOT_FIXTURE_CODES:
            continue
        slot_id = _subject(diagnostic, "slot")
        if slot_id is None:
            continue
        by_slot.setdefault(slot_id, []).append(diagnostic)

    patches: list[AutofixPatch] = []
    for slot_id, slot_diagnostics in sorted(by_slot.items()):
        slot = slots.get(slot_id)
        if not isinstance(slot, dict):
            continue
        # Only claim the codes whose OWN precondition this slot actually meets:
        # a slot carrying a placeholder is a LUMV0509 candidate but not a
        # LUMV0800 one, and claiming a target we cannot clear would guarantee a
        # rollback and lose the repair we could have made.
        claimed = [d for d in slot_diagnostics if _needs_fixture(slot, str(d["code"]))]
        if not claimed:
            continue
        derived = _bound_text(scene, slot)
        if derived is None:
            continue
        node_id, content = derived

        new_slot = copy.deepcopy(slot)
        validation = new_slot.get("validation")
        if not isinstance(validation, dict):
            validation = {"samples": [], "worst_case": None, "max_length": None}
        validation = dict(validation)
        validation["samples"] = [content]
        new_slot["validation"] = validation

        preview = content if len(content) <= 40 else content[:37] + "…"
        patches.append(
            AutofixPatch(
                klass="slot_fixture",
                targets=tuple(diagnostic_key(d) for d in claimed),
                operations=({"kind": "upsert_slot", "slot": new_slot},),
                detail=(
                    f"slot {slot.get('key') or slot_id}: sample derived from bound "
                    f"text node {node_id} ({preview!r})"
                ),
            )
        )
    return patches


def plan_autofix(scene: JsonObject, diagnostics: list[JsonObject]) -> list[AutofixPatch]:
    """Every closed-form repair available for this (scene, diagnostics) pair.

    Text-box fixes are planned first on purpose: adding a slot sample makes the
    engine measure that string against the bound box, so a box that is already
    overflowing would turn the sample into a fresh LUMV0810 and get the slot fix
    rolled back. Fixing the box first lets both land in one pass.
    """
    return _plan_text_box_hug(scene, diagnostics) + _plan_slot_fixture(scene, diagnostics)


# --------------------------------------------------------------------------- #
# the bounded loop
# --------------------------------------------------------------------------- #
def _verify(
    before: list[JsonObject], after: list[JsonObject], patch: AutofixPatch
) -> Optional[str]:
    """``None`` when the patch may be kept; otherwise the reason it is rejected.

    Three conditions, all evaluated against the engine's own re-preflight — this
    function never reasons about what the patch "should" have done:

    1. every diagnostic the patch claimed is gone;
    2. no diagnostic key appeared that was not there before (this is what
       catches a hug that pushed the box past its parent, or a sample that
       overflows the node it was derived from);
    3. neither the error count nor the total count grew (belt for a key that
       stayed but changed severity, or one that multiplied).
    """
    after_keys = _keys(after)
    still_present = [key for key in patch.targets if key in after_keys]
    if still_present:
        return "target diagnostic still present: " + ", ".join(
            f"{code}/{ident}" for code, _, ident in still_present
        )
    introduced = sorted(after_keys - _keys(before))
    if introduced:
        return "introduced " + ", ".join(f"{code}/{ident}" for code, _, ident in introduced[:4])
    if _error_count(after) > _error_count(before):
        return "error count rose"
    if len(after) > len(before):
        return "diagnostic count rose"
    return None


def run_autofix(
    scene: JsonObject,
    diagnostics: list[JsonObject],
    *,
    apply_operations: Callable[[JsonObject, list[JsonObject]], JsonObject],
    preflight: Callable[[JsonObject], tuple[JsonObject, list[JsonObject]]],
    max_passes: int = 2,
    on_attempt: Optional[Callable[[AutofixRecord], None]] = None,
) -> AutofixResult:
    """Compile→preflight→patch→re-preflight, in code, below the model.

    ``apply_operations(scene, operations) -> scene`` and
    ``preflight(scene) -> (scene, diagnostics)`` are the two engine calls,
    injected so this loop can be exercised without a helper binary. Either may
    raise; a raise is treated as "this patch is not applicable" and the working
    scene is untouched — an engine hiccup must never cost the turn its scene.

    The working ``scene``/``diagnostics`` are rebound only on a verified patch,
    so rollback needs no undo path: the caller's original objects are still the
    ones in hand.
    """
    result = AutofixResult(scene=scene, diagnostics=list(diagnostics))
    if max_passes <= 0:
        return result

    attempted: set[DiagKey] = set()
    for _ in range(max_passes):
        result.passes += 1
        candidates = [
            patch
            for patch in plan_autofix(result.scene, result.diagnostics)
            if not any(key in attempted for key in patch.targets)
        ]
        if not candidates:
            result.passes -= 1  # a pass that found nothing to do never happened
            break

        progressed = False
        for patch in candidates:
            attempted.update(patch.targets)
            record = _attempt(patch, result, apply_operations, preflight)
            if record.accepted:
                result.applied.append(record)
                progressed = True
            else:
                result.rolled_back.append(record)
            if on_attempt is not None:
                on_attempt(record)
        if not progressed:
            break
    return result


def _attempt(
    patch: AutofixPatch,
    result: AutofixResult,
    apply_operations: Callable[[JsonObject, list[JsonObject]], JsonObject],
    preflight: Callable[[JsonObject], tuple[JsonObject, list[JsonObject]]],
) -> AutofixRecord:
    def rejected(reason: str) -> AutofixRecord:
        return AutofixRecord(
            klass=patch.klass,
            codes=patch.codes,
            subject=patch.subject,
            detail=patch.detail,
            operations=patch.operations,
            accepted=False,
            reason=reason,
        )

    try:
        candidate_scene = apply_operations(result.scene, list(patch.operations))
    except Exception as error:  # noqa: BLE001 - any engine refusal is just "not applicable"
        return rejected(f"engine refused the operation ({type(error).__name__})")
    if not isinstance(candidate_scene, dict):
        return rejected("engine returned no scene")

    try:
        verified_scene, verified_diagnostics = preflight(candidate_scene)
    except Exception as error:  # noqa: BLE001
        return rejected(f"re-preflight failed ({type(error).__name__})")
    if not isinstance(verified_scene, dict):
        return rejected("re-preflight returned no scene")

    reason = _verify(result.diagnostics, verified_diagnostics, patch)
    if reason is not None:
        return rejected(reason)

    result.scene = verified_scene
    result.diagnostics = list(verified_diagnostics)
    return AutofixRecord(
        klass=patch.klass,
        codes=patch.codes,
        subject=patch.subject,
        detail=patch.detail,
        operations=patch.operations,
        accepted=True,
    )

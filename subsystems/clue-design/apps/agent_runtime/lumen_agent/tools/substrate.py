from __future__ import annotations

import base64
import copy
import functools
import hashlib
import inspect
import io
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from py_lumen_obs import bind_run_id, get_logger, log_span
from pydantic import StrictInt

from lumen_api.core import CoreClient, CoreError
from lumen_api.export_policy import draft_verification_note, partition_export_diagnostics
from ..native_copy import (
    NativeCopyReviewProfile,
    native_nominal_em_at_width,
    observe_native_text,
)
from ..paths import to_virtual

try:  # the real Python text-to-image seam, shared with the /assets/generate route
    from lumen_api import image_provider
    from lumen_api.image_provider import image_request_receipt_fields as _image_receipt_fields
except Exception:  # pragma: no cover - keeps the runtime importable without the API package
    image_provider = None  # type: ignore[assignment]

    def _image_receipt_fields(record: dict) -> dict:
        return {}

try:  # generation cache (request -> asset), so the loop doesn't re-pay per iteration
    from lumen_api import image_cache
except Exception:  # pragma: no cover
    image_cache = None  # type: ignore[assignment]

#: Editor Quality Plan 2 (item C): the asset tools refuse on a pageless scene BEFORE they spend.
#: Registering an asset needs a page (engine rule LUMV0100); paying a model or a vendor first
#: and discovering that afterwards cost `run_0452aae9…` ~10 minutes and its repair round.
PAGE_REQUIRED_CODE = "scene.page_required"

from ..autofix import AutofixResult, run_autofix
from ..config import AgentRuntimeConfig
from ..critique_fidelity import stamp_reference_fidelity
from ..models.creative_direction import (
    CREATIVE_DIRECTION_FILENAME,
    CreativeDirection,
    canonical_direction_digest,
    direction_review_requirements,
)
from ..image_crop import (
    ImageCropError, crop_source_pixels, has_generated_image_origin, require_supported_crop_origin,
)
from ..retokenize import (
    build_logo_placement_operations,
    build_retokenize_operations,
    scene_has_kit_logo,
)
from ..brand_card import build_brand_card
from ..knowledge import BRAND_APPLICATION_PATH, DIRECTIVES_PATH, read_task_knowledge
from ..paths import normalize_agent_key
from . import logo_fetch
from .asset_preview import PREVIEWABLE_MIME_TYPES, asset_preview_path, blob_path_for_digest
from ..run_metrics import RunMetrics
from ..text_clearance import collision_advisory
from pydantic import ValidationError

from ..models.schemas import (
    ClarificationRequest,
    CompileSummary,
    DiagnosticSeverity,
    DiagnosticSummary,
    EditSurfaceRecommendation,
    ExportSummary,
    GapArea,
    GapRecord,
    KnowledgeLoadResult,
    KnowledgeSnippet,
    LayoutClusterTarget,
    LumenRunTraceEvent,
    OperationApplicationSummary,
    PreflightSummary,
    PreviewArtifact,
    RepairClass,
    RepairRequest,
    SceneVisualCritique,
    StopReason,
    ToolStatus,
    VisualCritique,
    VisualTarget,
    new_run_id,
)


JsonObject = Dict[str, Any]

# A progress hook: (event_type, event_data) for each recorded trace event.
# Kept dependency-free so agent_runtime never imports the API/DB layer.
EventSink = Callable[[str, JsonObject], None]

# P0.4 checkpoint-commit hook: hand the run's operation ledger, in order, to a
# caller that can persist it mid-run (the API's leg-turn committer). Called with
# the FULL ordered operation list every time — the caller knows which prefix it
# already made durable and commits only the delta, so a dropped or refused
# checkpoint self-heals on the next one. Kept dependency-free for the same
# reason EventSink is: agent_runtime never imports the API/DB layer.
SceneCheckpoint = Callable[[List[JsonObject], JsonObject], None]


# Hard caps for the curated, windowed per-iteration context (P1). They keep the
# director/author/reviewer prompt bounded no matter how many repair iterations
# run. The context is rebuilt fresh each iteration from canonical in-memory
# state and is NEVER written back into the trace, so it cannot self-nest or grow
# unboundedly across iterations (the failure mode that exploded the old
# `full_activity_context` past the token limit).
CONTEXT_MAX_DIAGNOSTICS = 12
CONTEXT_MAX_SUBTREE_NODES = 24
CONTEXT_MAX_VISIBLE_TEXT = 40
CONTEXT_MAX_ATTEMPTS = 6
CONTEXT_MAX_KNOWLEDGE = 6
CONTEXT_MAX_KNOWLEDGE_EXCERPT = 800
CONTEXT_MAX_CRITIQUE_ISSUES = 12
CONTEXT_MAX_SVG_SNIPPET = 4000
CONTEXT_MAX_TEXT_LEN = 120

# Slice 2 (Loop Vision): the Director receives thumbnails of the kit's assets so it
# chooses imagery/logo placements by LOOKING (subject, contrast, baked text), not by
# metadata alone. The reviewer receives the SOURCE thumbnails of the assets a scene
# actually placed so it can verify each placement against its source. Both are capped
# — only paths + small labels ride the context dicts; base64 is produced per call at
# the model boundary (see providers), never accumulated in a persisted dict.
CONTACT_SHEET_MAX = 6
PLACED_PREVIEWS_MAX = 4
# The raster mime types the vision APIs accept as a direct preview — and the
# resolver that reads them — now live in `.asset_preview`, shared with the web
# lane's view("asset:<id>") so the two lanes cannot disagree about which pixels
# represent an asset.


# `blob_path_for_digest` — the one spelling of the digest→path layout — now
# lives in `.asset_preview` beside the shared resolver (both lanes need it);
# imported above and re-exported from this module for its existing callers.

# Diagnostic codes that indicate content does not fit its frame (text overflow)
# or a layout cluster is mis-sized — surfaced as `overflow` in the preview
# summary so the director sees them without the raw scene.
CONTEXT_OVERFLOW_CODES = {
    "LUMV0902",
    "LUMV0903",
    "LUMV0904",
    "LUMV0810",
    "LUMV0800",
    "LUMV0801",
    "LUMV0803",
    "LUMV0805",
}


def _extract_diagnostics(entry: JsonObject) -> list:
    """Pull the diagnostics list out of a feedback entry, whatever its kind."""
    if not isinstance(entry, dict):
        return []
    inner = entry.get("feedback")
    if isinstance(inner, dict):
        diags = inner.get("diagnostics")
        if isinstance(diags, list):
            return diags
        compile_summary = inner.get("compile_summary")
        if isinstance(compile_summary, dict) and isinstance(
            compile_summary.get("diagnostics"), list
        ):
            return compile_summary["diagnostics"]
    repair_request = entry.get("repair_request")
    if isinstance(repair_request, dict) and isinstance(
        repair_request.get("diagnostics"), list
    ):
        return repair_request["diagnostics"]
    return []


def _feedback_one_liner(entry: JsonObject) -> str:
    """One short human line describing what an attempt produced/why it failed."""
    if not isinstance(entry, dict):
        return ""
    if entry.get("kind") == "visual":
        critique = entry.get("feedback") or {}
        return str(critique.get("summary") or "")[:200]
    for diagnostic in _extract_diagnostics(entry):
        if isinstance(diagnostic, dict) and diagnostic.get("message"):
            return str(diagnostic["message"])[:200]
    for key in ("reason", "violation", "message", "summary"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value[:200]
    return str(entry.get("recommended_edit_surface") or "")[:200]


def _is_render_export_issue(diagnostics: list, previous_feedback: list) -> bool:
    """True only when the raw vector/export output is the subject of repair."""
    for diagnostic in diagnostics or []:
        if not isinstance(diagnostic, dict):
            continue
        code = diagnostic.get("code") or ""
        message = (diagnostic.get("message") or "").lower()
        if code.startswith("LUME") or "export" in message or "render" in message:
            return True
    return False


_SUBSTRATE_LOG = get_logger("lumen_agent.substrate")


def _tool_span(method):
    """Wrap an agent-visible tool method body in a ``log_span`` (deliverable 5).

    Every decorated tool emits ``tool_<name>_started`` / ``tool_<name>_completed``
    (or ``tool_<name>_failed`` on an escaping exception), stamped with a duration
    and a compact summary of the arguments the caller actually passed. Argument
    VALUES ride whole — the shared obs chain redacts secrets/blobs and truncates
    for the console while the run file keeps full detail, so nothing is
    hand-truncated here. ``functools.wraps`` (which copies ``__wrapped__``,
    ``__doc__`` and ``__annotations__``) keeps the method transparent to
    LangChain's tool-schema introspection.
    """
    signature = inspect.signature(method)
    span_name = f"tool_{method.__name__}"

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            bound = signature.bind(self, *args, **kwargs)
            fields = {
                name: value
                for name, value in bound.arguments.items()
                if name not in {"self", "logger"}
            }
        except TypeError:
            fields = {}
        with log_span(span_name, logger=self._obs_log, **fields):
            return method(self, *args, **kwargs)

    return wrapper


def _scene_mutation(method):
    """Keep a local scene read, helper response, and ledger/receipt commit indivisible.

    The helper returns a whole scene by value. Locking only the subprocess or
    the response assignment still permits a stale response to erase another
    tool's edits. Provider work must stay outside these bounded transactions.
    Reentrancy lets compile/preflight register assets within the same mutation.
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._scene_mutation_lock:
            return method(self, *args, **kwargs)

    return wrapper


class _CoreHelperProxy:
    """Single-seam ``log_span`` wrapper around the core-helper client (deliverable 5).

    The substrate reaches the core helper from ~25 call sites, but every one goes
    through ``self.core`` — so wrapping the client ONCE here is the single place
    the helper (a subprocess round-trip) is invoked. Each core method call emits a
    ``helper_call`` span tagged with the action; a hung helper subprocess then
    shows as a ``helper_call_started`` with no matching completion — the plan's
    black-box hang forensic. (The API-side ``CoreClient._run`` keeps its own
    ``core_helper_*`` events; this agent-runtime span measures the full round-trip
    from the caller's vantage and is what L4 will unify.)

    Non-callable attributes pass straight through unwrapped, so test fakes that
    expose plain fields (``tools.core.applied_operations``) stay transparent.
    """

    def __init__(self, core: Any, logger: Any) -> None:
        self._core = core
        self._obs_log = logger

    def __getattr__(self, name: str) -> Any:
        # Reached only for names not found on the proxy itself (``_core`` /
        # ``_obs_log`` resolve normally and never recurse here).
        attr = getattr(self._core, name)
        if not callable(attr):
            return attr
        obs_log = self._obs_log

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            with log_span("helper_call", logger=obs_log, action=name):
                return attr(*args, **kwargs)

        return wrapped


class LumenDesignTools:
    def __init__(
        self,
        config: AgentRuntimeConfig,
        prompt: str,
        initial_scene: Optional[JsonObject] = None,
        event_sink: Optional["EventSink"] = None,
        scene_checkpoint: Optional["SceneCheckpoint"] = None,
    ) -> None:
        self.config = config
        # Obs logger for tool spans + the core-helper proxy. Context (run_id) is
        # merged in per-event from contextvars, so one instance logger suffices.
        self._obs_log = _SUBSTRATE_LOG
        # The core-helper client, wrapped once so every helper subprocess call
        # emits a `helper_call` span (deliverable 5). Transparent to callers and
        # to test fakes' plain-field access (see _CoreHelperProxy).
        self.core = _CoreHelperProxy(
            CoreClient(repo_root=config.repo_root), self._obs_log
        )
        # Optional progress hook: every recorded trace event is also handed to
        # this sink so a caller (the API's async turn) can persist it to a
        # durable store and stream it. None keeps the run purely file-traced.
        self.event_sink = event_sink
        # P0.4: optional checkpoint-commit hook (see SceneCheckpoint). None keeps
        # the run save-on-finalize-only, exactly as before.
        self.scene_checkpoint = scene_checkpoint
        # How many ledger entries have already been handed to `scene_checkpoint`.
        # The sink is only called when the ledger has grown past this, so a round
        # that changed nothing never mints a document version.
        self._checkpointed_operations = 0
        # Batched read-only tool calls (deepagent-latency L2) now run on
        # langgraph's ToolNode thread pool, so `record` can be invoked from
        # concurrent threads. This lock serializes the whole record body (jsonl
        # append + event_sink push) so trace lines never interleave and in-process
        # event order stays deterministic.
        self._record_lock = threading.Lock()
        # ToolNode may batch any author tools, not only image registrations.
        # Every scene mutation shares this per-run transaction lock; paid
        # generation/editing and remote logo fetching remain parallel outside it.
        self._scene_mutation_lock = threading.RLock()
        self.run_id = config.run_id or new_run_id()
        self.iteration = 0
        # Fast-loop v1 §7: per-run summary counters, started at the earliest
        # moment of the run so `wall_time_ms` measures the whole turn. The three
        # role tracers fold their calls in (harness._instrument), this class
        # marks compiles and the first validated preview, and the harness runner
        # emits ONE `run_metrics` event + `metrics.json` at any terminal outcome.
        # Pure in-process integer arithmetic — no extra LLM call, tool call, or
        # hot-loop I/O. See lumen_agent/run_metrics.py.
        self.metrics = RunMetrics(self.run_id)
        # Fast loop §5.2: the per-round inner-iteration counter and the round it
        # belongs to. Only read when `config.fast_loop` is on; born here so the
        # attribute always exists (a config swapped mid-run must not AttributeError).
        self._fast_loop_round = 0
        self._fast_loop_round_compiles = 0
        # Solo construction/review share this runtime. Notes may arrive later
        # in a parallel tool batch, so they cannot own its repair allowance.
        self._solo_construction_round = 0
        self._solo_repair_pending = False
        # Design session continuity (2026-09-18). Two branches, side by side:
        #   * no session (editor preview, CLI, fixtures) — the run owns its own
        #     folder and `turn_dir` IS `trace_dir`, byte-identical to before;
        #   * a session (a leg turn on a pinned document) — `trace_dir` is the
        #     PERSISTENT session folder, shared by every turn (the agent-visible
        #     `workspace/` and the component projection live there), and this
        #     turn's harness-owned outputs go under `turns/<run_id>`.
        session_dir = config.session_dir()
        if session_dir is None:
            self.trace_dir = config.trace_dir / self.run_id
            self.turn_dir = self.trace_dir
            self.workspace_scope_id = self.run_id
        else:
            self.trace_dir = session_dir
            self.turn_dir = session_dir / "turns" / self.run_id
            self.workspace_scope_id = f"sessions/{config.session_id}"
        self.iterations_dir = self.turn_dir / "iterations"
        self.turn_dir.mkdir(parents=True, exist_ok=True)
        self.iterations_dir.mkdir(parents=True, exist_ok=True)
        # Rounds are numbered across the whole session: a second turn's first round follows the
        # highest round directory the workspace already holds.
        self.round_base = self._highest_round_dir()
        # Bind run_id ONCE, at the moment the run dir exists (deliverable 4): from
        # here on every obs event in this run's context carries it via
        # merge_contextvars, so the CLI viewer and run.jsonl can group by run
        # without threading the id through call sites.
        bind_run_id(self.run_id)
        # Phase 0a: a caller (the editor's /agent/turn-preview) can seed the
        # working scene from the live canonical scene so targeted edits land on
        # existing NodeIds. Without a seed the run starts from a fresh scene.
        self.seeded_from_initial_scene = initial_scene is not None
        if initial_scene is not None:
            self.scene = copy.deepcopy(initial_scene)
        else:
            self.scene = self.core.new_scene(self.run_id, "Agent-authored design")
        # Slice 3 phase B: the human contract. On a seeded turn the seed scene's
        # node ids are PROTECTED — a reconcile block that omits one keeps it
        # (LUMD0262) rather than deleting human/seed content. Computed once here
        # so every compile call carries the same frozen set; None on fresh runs
        # yields pure declarative reconcile semantics.
        self.protected_node_ids: Optional[list[str]] = (
            sorted((initial_scene.get("nodes") or {}).keys())
            if initial_scene is not None
            else None
        )
        self.prompt = prompt
        self.preview_paths: list[str] = []
        self.loaded_knowledge: list[JsonObject] = []
        self.gaps: list[JsonObject] = []
        self.scene_update_sources: list[str] = (
            ["initial_scene_seed"] if self.seeded_from_initial_scene else []
        )
        # K2 accept-seam: ordered {iteration, source, operation} entries for
        # every applied scene mutation — the proposal's op source of truth
        # (see _log_scene_operations).
        self.operations_ledger: list[JsonObject] = []
        #: Plan 2 Task 5: how much of `operations_ledger` the stream has carried. The client's
        #: cursor applies a frame only when it BEGINS where the cursor stands, so a frame must
        #: carry every ledger entry since the last frame — see `_contiguous_sink_extra`.
        self._streamed_ledger_len = 0
        self.effective_brand_context: Optional[JsonObject] = None
        # K1: compact brand context card, built once from the by-value kit in
        # config (None without a kit). Injected via load_knowledge and
        # curated_context — the full kit JSON never enters model history.
        self.brand_card: Optional[JsonObject] = build_brand_card(
            config.brand_kit,
            source=config.brand_kit_source,
            # W1.3: pixel dimensions for the image/logo rows — they live on the
            # by-value asset records, never on the kit's own asset entries.
            asset_manifest=config.brand_kit_assets,
            scene_dsl=config.scene_skill_bundle == "candidate",
        )
        self.dsl_session: Optional[JsonObject] = None
        self.latest_export_summary: Optional[JsonObject] = None
        self.latest_preview_bundle: Optional[JsonObject] = None
        # P0.4: the last `preflight_design` verdict. None = preflight has not run
        # yet. Recorded on every checkpoint so a reader can tell a clean round's
        # commit from one taken with diagnostics still standing.
        self.latest_preflight_has_errors: Optional[bool] = None
        # Keep the operation counter for diagnostics. Preview freshness binds
        # actual content: failed/no-op core responses can increment the counter.
        self._preview_scene_version: Optional[int] = None
        self._preview_scene_stamp: Optional[str] = None
        # L4b unchanged-scene re-review guard: the iteration at which the last
        # valid preview was rendered, stamped alongside _preview_scene_version.
        # None = nothing rendered yet. Names "round N" in the unchanged fact
        # export_preview_bundle surfaces when re-rendering byte-identical pixels.
        self._preview_rendered_iteration: Optional[int] = None
        # Legacy logo placement is PLACE-ONCE (sweep A3 re-injection fix):
        # once a kit logo has been present (author-placed or our auto-overlay),
        # a later removal is the author's choice and must be respected, not undone.
        self._brand_logo_seen: bool = False
        # Agent-improvement follow-up 1: memoized pre-existing-diagnostics
        # baseline, populated on first access by `baseline_preflight_diagnostics`.
        # None means "not computed yet" (distinct from `[]`, "computed, clean").
        self._baseline_diagnostics: Optional[list[JsonObject]] = None
        # P0.3 finalize guard: the raw diagnostics of the most recent
        # `preflight_design`, kept so `finalize_run` can refuse to record an
        # accepted run that still carries a BLOCKING export error. None means
        # preflight has not run this turn (distinct from `[]`, "ran, clean").
        self._latest_preflight_diagnostics: Optional[list[JsonObject]] = None
        # Runtime-owned receipts bind acceptance to the exact reviewed scene
        # and bytes. Agent-authored JSON alone cannot certify a new render.
        self._preflight_scene_stamp: str | None = None
        self._preflight_iteration: int | None = None
        self._preview_receipt: JsonObject | None = None
        self._review_receipt: JsonObject | None = None
        self._review_iteration: int | None = None
        self._latest_visual_critique: JsonObject | None = None
        # A restarted substrate must validate its own direction. Production
        # checkpoint takeover restarts the turn; graph history is not a receipt.
        self._validated_direction: CreativeDirection | None = None
        self._validated_direction_digest: str | None = None
        self._selected_reference_ids: set[str] = set()
        self._pending_pruned_pages: list[str] = []
        self._write_json(
            self.turn_dir / "input.json",
            {
                "run_id": self.run_id,
                "prompt": prompt,
                "seeded_from_initial_scene": self.seeded_from_initial_scene,
                # Agent-improvement follow-up 3: the initial brief carries the
                # same scene summary (freehand/frozen-doc state included) that
                # repair requests already see, so the author is never blind to
                # frozen geometry on the FIRST pass — only during repairs.
                "scene_summary": self._scene_summary(),
            },
        )
        self.record(
            "coordinator",
            "run_started",
            input_summary=prompt[:500],
            output_summary=(
                f"seeded scene from initial_scene "
                f"({len(self.scene.get('nodes', {}))} nodes, "
                f"{len(self.scene.get('pages', {}))} pages)"
                if self.seeded_from_initial_scene
                else f"created scene {self.run_id}"
            ),
            payload={
                "scene_update_policy": "core_response_only",
                "seeded_from_initial_scene": self.seeded_from_initial_scene,
                "seed_node_count": len(self.scene.get("nodes", {})),
                "seed_page_count": len(self.scene.get("pages", {})),
            },
        )

    def load_knowledge(self, query: str) -> str:
        """Load task-specific Lumen knowledge snippets with provenance."""
        snippets = read_task_knowledge(
            self.config.repo_root,
            query,
            # A seeded turn edits an existing document, so the modify/ref
            # grammar (`#page:` form, directives-are-node-only) must always be
            # loaded — the recipe inlines the essentials, but the full table
            # stays one load away (agent-improvement backlog).
            extra_mandatory_paths=(
                ([DIRECTIVES_PATH] if self.seeded_from_initial_scene else [])
                # K1: a run with an attached kit always gets the brand
                # decide table (intensity per archetype, CTA/accent rule,
                # logo-variant rules) — same pattern as images/decide.
                + ([BRAND_APPLICATION_PATH] if self.brand_card else [])
            ),
        )
        result = KnowledgeLoadResult(query=query, snippets=snippets)
        payload = _dump(result)
        if self.brand_card:
            # The card rides the knowledge payload so the coordinator (and the
            # author via task context) reasons from the kit's ACTUAL roles,
            # accent, and inventory — not from guessed token names.
            # Through the KnowledgeSnippet model, not a hand-rolled dict — the
            # quality loop re-validates every snippet (loop.py), so a shape
            # drift here kills the whole turn (found by the K1 live proof).
            payload["snippets"].append(
                KnowledgeSnippet(
                    path=f"brand-kit:{self.brand_card['kit'].get('id')}",
                    title="Brand context card (this document's attached kit)",
                    score=100,
                    excerpt=json.dumps(self.brand_card, indent=1),
                    category="brand",
                    selected_reason="attached_brand_kit",
                ).model_dump(mode="json")
            )
        # W-isolation (D7): the read path stays repo-rooted (single source of
        # truth), but the `path` metadata handed to the model is rewritten to the
        # virtual namespace so it can re-read any excerpt via its filesystem tools
        # (`apps/agent_runtime/knowledge_docs/…` → `/knowledge_docs/…`). Synthetic
        # snippet ids (e.g. `brand-kit:<id>`) carry no filesystem path and pass
        # through `normalize_agent_key` unchanged.
        for snippet in payload["snippets"]:
            snippet["path"] = normalize_agent_key(
                snippet["path"], self.config.workspace_root
            )
        self.loaded_knowledge = payload["snippets"]
        self._write_json(self.turn_dir / "knowledge.json", payload)
        self.record(
            "coordinator",
            "knowledge_loaded",
            input_summary=query,
            output_summary=f"loaded {len(snippets)} snippets",
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    # --- fast loop §5.2: the per-round inner-iteration cap -------------------
    @property
    def solo_rounds_executed(self) -> int | None:
        """Executed candidate-solo rounds; None retains delegated file custody."""
        if (
            self.config.scene_solo
            and self.config.scene_skill_bundle == "candidate"
            and self.config.fast_loop
        ):
            return self._solo_construction_round
        return None

    def _begin_solo_construction(self) -> None:
        """Called inside the scene transaction, before charging a compile.

        A registered rejection arms one repair; actual construction consumes
        it. Merely writing a note, reviewing or finalizing a draft does not.
        Page-only source preparation before validated direction stays round 0.
        """
        current = self.solo_rounds_executed
        if current is None or self._validated_direction_digest is None:
            return
        if current == 0:
            next_round = 1
        elif current == 1 and self._solo_repair_pending:
            next_round = 2
        else:
            return
        # The directory name continues the SESSION's numbering (`round_base` is
        # the highest round an earlier turn left behind); the counter itself
        # stays per-turn, so this turn's caps are unchanged.
        recorded = self.round_base + next_round
        path = self.trace_dir / "workspace" / "rounds" / f"round_{recorded}"
        path.mkdir(parents=True, exist_ok=True)
        self._solo_construction_round = next_round
        self._solo_repair_pending = False
        self.record(
            "coordinator", "construction_round_started",
            output_summary=f"round {recorded}", payload={"round": recorded},
        )

    def _highest_round_dir(self) -> int:
        """The highest ``round_N`` directory the workspace holds, or 0."""
        rounds = self.trace_dir / "workspace" / "rounds"
        highest = 0
        try:
            for child in rounds.iterdir():
                if child.is_dir() and child.name.startswith("round_"):
                    suffix = child.name[len("round_") :]
                    if suffix.isdigit():
                        highest = max(highest, int(suffix))
        except OSError:
            return 0
        return highest

    def _fast_loop_round_number(self) -> int:
        """Runtime round for solo; newest round directory for delegated runs."""
        if self.solo_rounds_executed is not None:
            return self.round_base + self.solo_rounds_executed
        return self._highest_round_dir()

    def _inner_iteration_refusal(self) -> Optional[str]:
        """Refuse a compile past the round's inner-iteration cap, or None.

        WHY A CAP AT ALL. §5.2's loop is compile → preflight → render → look →
        self-audit → ONE batched fix, and its whole economy assumes the fix is
        batched. The baseline's iterations 21-34 were fourteen compiles carrying
        one property change each — the drip §5.5 forbids in words. This is the
        same rule in Python: when the drip happens anyway, the round ends instead
        of grinding.

        WHY A REFUSAL AND NOT AN EXCEPTION. House style, and it is also the more
        useful behaviour: a refusal string is something the author reads and acts
        on (render, self-audit honestly, report what is unfinished), where an
        exception would take the turn down and lose the perfectly good scene the
        author already compiled. The cap does not roll back anything.

        The count is per ROUND. Solo construction owns its transition; delegated
        rounds retain filesystem custody. A repair gets its own fresh budget.
        """
        cap = int(getattr(self.config, "fast_loop_inner_iterations", 0) or 0)
        if cap <= 0:
            return None
        round_number = self._fast_loop_round_number()
        if round_number != self._fast_loop_round:
            self._fast_loop_round = round_number
            self._fast_loop_round_compiles = 0
        if self._fast_loop_round_compiles < cap:
            self._fast_loop_round_compiles += 1
            return None
        self.metrics.mark_inner_iteration_refused()
        self.record(
            "dsl-author",
            "inner_iteration_cap_reached",
            output_summary=f"round {round_number}: {cap} compiles used",
            payload={"round": round_number, "cap": cap},
        )
        recovery = (
            "write an HONEST critique.json naming every issue still standing "
            "(accepted:false if any blocker remains). The canonical file write "
            "registers the review. After a registered round-1 rejection, the next "
            "construction tool starts the one repair round automatically; note "
            "files do not grant compile allowance. Otherwise call finalize_run "
            "with an honest outcome; acceptance still "
            "requires a current preflight, preview and registered review. The "
            "runtime already journals the DSL and diagnostics. "
            if self.config.scene_solo else
            "write an HONEST critique.json naming every issue still standing "
            "(accepted:false if any blocker remains), save dsl.lumen / "
            "diagnostics.json / author_report.md, and return. The orchestrator "
            "decides whether to open a repair round — that round gets its own "
            "fresh budget of iterations. "
        )
        return self._tool_error(
            "compile.inner_iteration_cap",
            f"REFUSED: this round has used its {cap} inner iterations (fast loop "
            "§5.2). Nothing was rolled back — the scene from your last successful "
            "compile stands. Stop compiling now: render_preview(), view(\"preview\"), "
            f"{recovery}If you were making one property edit per "
            "compile, that is the pattern this cap exists to stop: batch every "
            "planned fix into ONE whole-scene reconcile next time.",
            round=round_number,
            inner_iterations_used=self._fast_loop_round_compiles,
            inner_iteration_cap=cap,
        )

    @_tool_span
    @_scene_mutation
    def compile_dsl_block(self, source: str) -> str:
        """Compile a block of Lumen DSL into the scene: new structure, modify lines (#id ...) for existing
        elements, and directives such as delete(id). Returns the compile result with diagnostics. Each
        compile counts toward the round's compile limit in your instructions. Past the limit it refuses
        and changes nothing, and the scene from your last good compile stands.
        """
        self._begin_solo_construction()
        # Fast loop §5.2. Checked BEFORE the iteration bump so a refused compile
        # costs nothing: no iteration number, no metrics compile, no scene touch.
        # `fast_loop_inner_iterations` is only non-zero under the flag, so this is
        # a single attribute read on the flag-off path.
        if getattr(self.config, "fast_loop", False):
            refusal = self._inner_iteration_refusal()
            if refusal is not None:
                return refusal
        self.iteration += 1
        # §7 metrics: every compile counts, including the ones that fail below —
        # the baseline's micro-edit drip (14 compiles for one property each) is
        # exactly what this counter has to make visible.
        self.metrics.mark_compile_iteration()
        iteration_dir = self._iteration_dir()
        (iteration_dir / "dsl.lumen").write_text(source, encoding="utf-8")

        duplicate_page = first_existing_page_declaration(source, self.scene)
        if duplicate_page:
            summary = CompileSummary(
                status=ToolStatus.error,
                diagnostics=[
                    DiagnosticSummary(
                        severity=DiagnosticSeverity.error,
                        code="LUMA0200",
                        message=(
                            "repair block tries to recreate existing page "
                            f"{duplicate_page['page_id']}"
                        ),
                        line=duplicate_page["line"],
                        target_page_id=duplicate_page["page_id"],
                        suggested_repair=(
                            "Do not emit an existing page line during repair. "
                            "Use checked structured operations for targeted changes, "
                            "or emit only a non-duplicating DSL continuation."
                        ),
                    )
                ],
                halted_at={"code": "LUMA0200", "line": duplicate_page["line"]},
            )
            payload = {"compile": _dump(summary)}
            self._write_json(iteration_dir / "compile.json", payload)
            self.record(
                "dsl-author",
                "dsl_compile_rejected",
                input_summary=source[:500],
                output_summary=summary.diagnostics[0].message,
                diagnostics=[diag.model_dump(mode="json") for diag in summary.diagnostics],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        try:
            brand_source, brand_kit, _ = self._effective_brand_kit()
            response = self.core.compile_dsl_into_scene(
                self.scene,
                source,
                dsl_session=self.dsl_session,
                protected_node_ids=self.protected_node_ids,
                brand_kit=brand_kit,
                mode=self._brand_context(brand_source, brand_kit)["mode"],
            )
        except CoreError as error:
            summary = CompileSummary(
                status=ToolStatus.error,
                diagnostics=diagnostics_from(error.diagnostics),
                operation_error={"code": error.code, "message": error.message},
            )
            payload = {"compile": _dump(summary)}
            self._write_json(iteration_dir / "compile.json", payload)
            self.record(
                "dsl-author",
                "dsl_compile_failed",
                input_summary=source[:500],
                output_summary=error.message,
                diagnostics=[diag.model_dump(mode="json") for diag in summary.diagnostics],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        self._replace_scene_from_core_response(response, "compile_dsl_block")
        # K2: `image asset(<kit asset id>)` written straight in DSL registers
        # nothing — reconcile against the kit manifest so the natural form
        # renders instead of dangling (see _register_referenced_brand_assets).
        self._register_referenced_brand_assets("compile_dsl_block")
        dsl = response.get("dsl", {})
        self.dsl_session = dsl.get("session_snapshot")
        compile_output = dsl.get("compile_output", {})
        diagnostics = diagnostics_from(compile_output.get("diagnostics", []))
        halted_at = normalize_halt_location(compile_output.get("halted_at"))
        has_blocking_diagnostics = any(
            diagnostic.severity in {DiagnosticSeverity.error, DiagnosticSeverity.blocker}
            for diagnostic in diagnostics
        )
        summary = CompileSummary(
            applied_operations=response.get("applied_operations") or 0,
            operation_count=len(compile_output.get("operations", [])),
            diagnostics=diagnostics,
            halted_at=halted_at,
            operation_error=dsl.get("operation_error"),
            status=(
                ToolStatus.error
                if dsl.get("operation_error") or halted_at or has_blocking_diagnostics
                else ToolStatus.ok
            ),
        )
        payload = {
            "compile": _dump(summary),
            "operations": compile_output.get("operations", []),
            "dsl_session": self.dsl_session,
            "checkpoint_label": compile_output.get("checkpoint_label"),
        }
        self._write_json(iteration_dir / "compile.json", payload)
        # Ledger: only a CLEAN compile's ops ride proposals — the same gate
        # the legacy compile.json scrape applied in agent_response_from_trace.
        if summary.status == ToolStatus.ok:
            self._log_scene_operations(
                "compile_dsl_block", compile_output.get("operations", [])
            )
        self.record(
            "dsl-author",
            "dsl_compiled",
            input_summary=source[:500],
            output_summary=(
                f"{summary.operation_count} operations; "
                f"{len(diagnostics)} DSL diagnostics"
            ),
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
            # Live-design-streaming S0: only a CLEAN compile's applied ops ride
            # the sink to the canvas — the same gate that decides whether they
            # ride the proposal ledger above. A blocking-diagnostic (or rejected/
            # failed) compile streams nothing to the canvas: the user never
            # watches a draft that got refused (D1).
            #
            # Rung B: an op-bearing frame also states WHERE its batch sits in the
            # run's operation ledger — `operations_total` is the ledger length
            # AFTER `_log_scene_operations` appended this batch (the append is
            # immediately above, so reading it here is post-append). It is the
            # same quantity `checkpoint_scene` puts on a `design.checkpoint`
            # frame, so a checkpoint at N and an op frame at N describe the same
            # point and the client can drop already-committed batches by
            # subtraction. Refused compiles push neither key — there is no
            # position for operations that never joined the ledger.
            sink_extra=(
                {
                    "operations": compile_output.get("operations", []),
                    "operations_total": len(self.operations_ledger),
                }
                if summary.status == ToolStatus.ok
                else None
            ),
        )
        return json.dumps(payload, indent=2)

    @_scene_mutation
    def apply_operations(self, operations_json: str) -> str:
        """Apply checked core operations. The input must be a JSON operation list."""
        try:
            operations = json.loads(operations_json)
            if not isinstance(operations, list):
                raise ValueError("operations_json must decode to a list")
            response = self.core.apply_operations(self.scene, operations)
        except (CoreError, ValueError, json.JSONDecodeError) as error:
            diagnostics = []
            if isinstance(error, CoreError):
                diagnostics = diagnostics_from(error.diagnostics)
                message = error.message
                code = error.code
            else:
                message = str(error)
                code = "operations.invalid_input"
            summary = OperationApplicationSummary(
                status=ToolStatus.error,
                diagnostics=diagnostics,
                operation_error={"code": code, "message": message},
            )
            payload = {"operations": _dump(summary)}
            self.record(
                "coordinator",
                "operations_failed",
                input_summary=operations_json[:500],
                output_summary=message,
                diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        self._replace_scene_from_core_response(response, "apply_operations", operations, construction=True)
        self.dsl_session = None
        diagnostics = diagnostics_from(response.get("diagnostics", []))
        summary = OperationApplicationSummary(
            applied_operations=response.get("applied_operations") or len(operations),
            diagnostics=diagnostics,
        )
        payload = {"operations": _dump(summary)}
        self.record(
            "coordinator",
            "operations_applied",
            input_summary=operations_json[:500],
            output_summary=f"applied {summary.applied_operations} operation(s)",
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    @_scene_mutation
    def apply_structured_edit(self, edit_json: str) -> str:
        """Apply a typed targeted edit through the Rust edit builder.

        The input must be a JSON object matching the `apply_structured_edit`
        helper contract, for example:

        {
          "kind": "modify",
          "target": {"kind": "node", "id": "headline"},
          "patch": {"kind": "node", "value": {"text": {"content": {"kind": "set", "value": "New copy"}}}}
        }

        Repairs for a concrete critic issue must declare their scope so the
        engine can reject out-of-scope mutations before they happen:

        {
          "kind": "modify",
          "target": {"kind": "node", "id": "headline"},
          "patch": {...},
          "scope": {"mode": "strict", "allowed": [{"kind": "node", "id": "headline"}]}
        }
        """
        scope = None
        try:
            edit = json.loads(edit_json)
            if not isinstance(edit, dict):
                raise ValueError("edit_json must decode to an object")
            scope = edit.pop("scope", None)
            brand_source, brand_kit, _ = self._effective_brand_kit()
            response = self.core.apply_structured_edit(
                self.scene, edit, scope=scope, brand_kit=brand_kit,
                mode=self._brand_context(brand_source, brand_kit)["mode"],
            )
        except (CoreError, ValueError, json.JSONDecodeError) as error:
            diagnostics = []
            if isinstance(error, CoreError):
                diagnostics = diagnostics_from(error.diagnostics)
                message = error.message
                code = error.code
            else:
                message = str(error)
                code = "structured_edit.invalid_input"
            scope_rejected = code == "edit.scope_violation"
            summary = OperationApplicationSummary(
                status=ToolStatus.error,
                diagnostics=diagnostics,
                operation_error={"code": code, "message": message},
            )
            payload = {"structured_edit": _dump(summary)}
            if scope is not None:
                payload["scope"] = scope
                payload["scope_verdict"] = (
                    "rejected" if scope_rejected else "not_evaluated"
                )
            self.record(
                "coordinator",
                "structured_edit_scope_rejected"
                if scope_rejected
                else "structured_edit_failed",
                input_summary=edit_json[:500],
                output_summary=message,
                diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        self._replace_scene_from_core_response(
            response, "apply_structured_edit", response.get("operations") or [], construction=True
        )
        if edit.get("kind") in {
            "delete",
            "move_before",
            "move_after",
            "move_to_parent",
            "replace_node",
        }:
            self.dsl_session = None
        diagnostics = diagnostics_from(response.get("diagnostics", []))
        operations = response.get("operations") or []
        summary = OperationApplicationSummary(
            applied_operations=response.get("applied_operations") or len(operations),
            operation_count=len(operations),
            diagnostics=diagnostics,
        )
        payload = {
            "structured_edit": _dump(summary),
            "edit": response.get("edit") or edit,
            "operations": operations,
        }
        if scope is not None:
            payload["scope"] = scope
            payload["scope_verdict"] = "in_scope"
        self.record(
            "coordinator",
            "structured_edit_applied",
            input_summary=edit_json[:500],
            output_summary=f"applied {summary.applied_operations} operation(s)",
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    @_scene_mutation
    def generate_qr(
        self,
        data: str,
        ec_level: Optional[str] = None,
        print_media: bool = False,
        target_width_mm: Optional[float] = None,
        label: Optional[str] = None,
    ) -> str:
        """Generate a deterministic QR code asset (URL/text -> sanitized SVG)
        and register it in the scene. Use print_media=True for physical
        artifacts (error correction H); declare target_width_mm so print
        scannability diagnostics can fire. Place the returned asset with a
        place_asset_in_node/place_asset_in_slot operation. The scene must already
        contain a page/artboard: on a pageless scene this tool REFUSES before
        generating (error `scene.page_required`) — author the page first."""
        refused = self._refuse_without_page("generate_qr")
        if refused is not None:
            return refused
        asset_id = f"asset_qr_{self.run_id[:8]}_{len(self.scene.get('assets', {}))}"
        try:
            response = self.core.generate_qr(
                store_root=str(self.config.effective_asset_store_root),
                data=data,
                asset_id=asset_id,
                label=label,
                ec_level=ec_level,
                print_media=print_media,
                target_width_mm=target_width_mm,
            )
        except CoreError as error:
            payload = {
                "qr": {
                    "status": "error",
                    "error_code": error.code,
                    "message": error.message,
                },
                "diagnostics": [
                    diag.model_dump(mode="json")
                    for diag in diagnostics_from(error.diagnostics)
                ],
            }
            self.record(
                "coordinator",
                "qr_generation_failed",
                output_summary=error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        asset_payload = response.get("asset") or {}
        record = asset_payload.get("record") or {}
        try:
            apply_response = self.core.apply_operations(
                self.scene, [{"kind": "upsert_asset", "asset": record}]
            )
        except CoreError as error:
            payload = {
                "qr": {
                    "status": "error",
                    "error_code": error.code,
                    "message": error.message,
                    "asset_id": record.get("id"),
                },
                "hint": (
                    "The QR was generated but could not be registered in the scene "
                    "(most often the scene has no page/artboard yet). Author the "
                    "page first, then call generate_qr again — QR generation is "
                    "deterministic, so the retry costs nothing."
                ),
                "diagnostics": [
                    diag.model_dump(mode="json")
                    for diag in diagnostics_from(error.diagnostics)
                ],
            }
            self.record(
                "coordinator",
                "qr_registration_failed",
                input_summary=data[:200],
                output_summary=error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)
        self._replace_scene_from_core_response(
            apply_response, "generate_qr", [{"kind": "upsert_asset", "asset": record}], construction=True
        )

        diagnostics = diagnostics_from(response.get("diagnostics", []))
        payload = {
            "qr": {
                "status": "ok",
                "asset_id": record.get("id"),
                "digest": (record.get("media") or {}).get("digest"),
                "deduplicated": asset_payload.get("deduplicated", False),
                "ec_level": (asset_payload.get("qr") or {}).get("ec_level"),
                "module_count": (asset_payload.get("qr") or {}).get("module_count"),
                "quiet_zone_modules": (asset_payload.get("qr") or {}).get(
                    "quiet_zone_modules"
                ),
                "provenance": record.get("provenance"),
                "source": record.get("source"),
                "license": (record.get("license") or {}).get("name"),
            },
            "diagnostics": [diag.model_dump(mode="json") for diag in diagnostics],
        }
        self.record(
            "coordinator",
            "qr_generated",
            input_summary=data[:200],
            output_summary=(
                f"generated QR asset {record.get('id')} "
                f"(ec={payload['qr']['ec_level']}, modules={payload['qr']['module_count']})"
            ),
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def generate_image(
        self,
        prompt: str,
        target_node_id: Optional[str] = None,
        target_slot_id: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        brand_notes: Optional[List[str]] = None,
        transparent_background: bool = False,
        label: Optional[str] = None,
        condition_on_references: bool = True,
        reference_asset_ids: list[str] | None = None,
        reference_roles: list[str] | None = None,
        reference_framing: str | None = None,
        operation: str | None = None,
    ) -> str:
        """Generate a raster image asset from a text prompt and register it in the
        scene. Pass target_node_id (or target_slot_id) so the aspect ratio is
        derived from that frame's geometry — generated images are cropped to fill,
        never stretched. Uses the configured text-to-image model (image-gen-v1)
        when available, otherwise a deterministic placeholder so the design still
        composes offline. When this turn has attached reference images, generated
        imagery is AUTOMATICALLY conditioned on them (their palette/texture/mood
        anchor the style). `reference_asset_ids` explicitly selects up to four
        inspected inputs from the frozen attachments, kit, library or current
        scene; [] selects none. Omission keeps automatic turn attachments. Exact
        UI/logo pixels belong in separate source layers, not generated artwork.
        The scene must already
        contain a page/artboard: on a pageless scene this tool REFUSES before
        generating (error `scene.page_required`) — author the page first.
        Returns the asset_id; place it with place_asset_in_node /
        place_asset_in_slot (a generated image is not auto-placed).

        Generation NEVER blocks the turn. If the model fails, you still get an
        asset_id, but `image.mode` is "placeholder" and `image.fallback` says why —
        that is a deterministic stand-in, NOT real imagery, so do not ship it as
        though it were: either retry once with a shorter prompt, or drop the image
        ground and use a flat brand-token ground instead. `image.actual_width` /
        `actual_height` report what the model really returned, which can differ from
        the aspect ratio you asked for."""
        refused = self._refuse_without_page("generate_image")
        if refused is not None:
            return refused
        asset_id = f"asset_img_{self.run_id[:8]}_{uuid4().hex}"
        width, height, aspect_ratio = self._image_constraints(
            target_node_id, target_slot_id, width, height, aspect_ratio
        )
        notes = [note for note in (brand_notes or []) if note and note.strip()]
        resolved_label = label or (prompt[:60].strip() or asset_id)

        record, meta, raw_diagnostics, error = self._produce_image_asset(
            asset_id=asset_id,
            prompt=prompt,
            label=resolved_label,
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            brand_notes=notes,
            transparent_background=transparent_background,
            condition_on_references=condition_on_references,
            reference_asset_ids=reference_asset_ids,
            reference_roles=reference_roles,
            reference_framing=reference_framing,
            operation=operation,
        )
        diagnostics = diagnostics_from(raw_diagnostics)
        if record is None:
            payload = {
                "image": {
                    "status": "error",
                    "error_code": error[0] if error else "image.error",
                    "message": error[1] if error else "image generation failed",
                },
                "diagnostics": [diag.model_dump(mode="json") for diag in diagnostics],
            }
            self.record(
                "coordinator",
                "image_generation_failed",
                input_summary=prompt[:200],
                output_summary=payload["image"]["message"],
                diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        try:
            with self._scene_mutation_lock:
                assets = self.scene.get("assets") or {}
                existing = assets.get(record.get("id"))
                if existing is not None and existing != record:
                    # Legacy cache entries can share an ID despite holding
                    # different bytes. Keep cached custody/provenance intact,
                    # changing only the Scene registration ID. Find an earlier
                    # remap first so identical free retries keep a stable ID.
                    reused_id = next(
                        (
                            candidate_id
                            for candidate_id, candidate in assets.items()
                            if candidate == {**record, "id": candidate_id}
                        ),
                        asset_id,
                    )
                    record = {**record, "id": reused_id}
                operations = [{"kind": "upsert_asset", "asset": record}]
                apply_response = self.core.apply_operations(self.scene, operations)
                self._replace_scene_from_core_response(
                    apply_response, "generate_image", operations, construction=True
                )
        except CoreError as error:
            payload = {
                "image": {
                    "status": "error",
                    "error_code": error.code,
                    "message": error.message,
                    "asset_id": record.get("id"),
                },
                "hint": (
                    "The image was generated but could not be registered in the "
                    "scene (most often the scene has no page/artboard yet). Author "
                    "the page first, then call generate_image again with the same "
                    "prompt — the generation cache makes the retry free."
                ),
                "diagnostics": [
                    diag.model_dump(mode="json")
                    for diag in diagnostics_from(error.diagnostics)
                ],
            }
            self.record(
                "coordinator",
                "image_registration_failed",
                input_summary=prompt[:200],
                output_summary=error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)
        image: JsonObject = {
            "status": "ok",
            "asset_id": record.get("id"),
            "mode": meta.get("mode"),
            "model": meta.get("model"),
            "mime_type": (record.get("media") or {}).get("mime_type"),
            "aspect_ratio": aspect_ratio,
            "width": width,
            "height": height,
            "provenance": record.get("provenance"),
            "source": record.get("source"),
            "license": (record.get("license") or {}).get("name"),
            **_image_receipt_fields(record),
        }
        if "reference_inputs" in meta:
            image["reference_inputs"] = meta["reference_inputs"]
        # W1.7(b): `width`/`height`/`aspect_ratio` above are the REQUEST. When the
        # model returned something else, say so rather than let the ask stand in
        # for the answer — cover-fit placement still works, but an agent choosing
        # a ground treatment deserves the real geometry.
        if meta.get("actual_width") and meta.get("actual_height"):
            image["actual_width"] = meta["actual_width"]
            image["actual_height"] = meta["actual_height"]
            if meta.get("aspect_ratio_honored") is False:
                image["aspect_ratio_honored"] = False
                image["note"] = (
                    f"the model returned {meta['actual_width']}x{meta['actual_height']}, "
                    f"which is not the requested {aspect_ratio}; it is placed cover-fit "
                    "and will be cropped to the frame"
                )
        # W1.7(c): a failed generation is a NON-BLOCKING, typed outcome (D5 — no
        # new blocking gates). The placeholder keeps the design composing; this
        # block is how the agent learns the imagery is not real and can choose to
        # proceed with a flat token ground instead.
        if meta.get("fallback"):
            image["fallback"] = meta["fallback"]
            image["hint"] = (
                "Image generation failed and a deterministic PLACEHOLDER was used — "
                "this is not real imagery and must not ship as if it were. The turn is "
                "not blocked: either retry once with a shorter, simpler prompt, or drop "
                "the image ground and proceed with a flat brand-token ground (a clean "
                "token fill beats a placeholder)."
            )
        payload = {
            "image": image,
            "diagnostics": [diag.model_dump(mode="json") for diag in diagnostics],
        }
        self.record(
            "coordinator",
            "image_generated",
            input_summary=prompt[:200],
            output_summary=(
                f"generated image asset {record.get('id')} "
                f"(mode={meta.get('mode')}, model={meta.get('model')}, aspect={aspect_ratio})"
            ),
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def search_assets(self, q: str, kind: Optional[str] = None, limit: int = 8) -> str:
        """Search every image in the brand kit and the workspace library by type, use, source, text or
        exact id. Returns short details for each match. View a match before choosing it, then place it by
        its origin: a "library" result with asset(action='place', asset_id=..., node_id=...), a
        "brand_kit" result with asset(action='use_brand_asset', asset_id=..., node_id=...).
        """
        from .asset_catalog import rank_assets, asset_summary
        if not q.strip() or isinstance(limit, bool) or not 1 <= limit <= 20:
            return json.dumps({"status": "error", "message": "Supply a query and limit 1..20"})
        candidates = {}
        for manifest, origin in ((self.config.brand_kit_assets or {}, "brand_kit"),
                                 (self.config.asset_library or {}, "library")):
            for asset_id, entry in manifest.items():
                candidates.setdefault(asset_id, (entry, origin))
        results = [{"asset_id": aid, "origin": origin, "title": entry.get("title"),
                    "description": entry.get("description"), "usage": entry.get("usage"),
                    "view": f"asset:{aid}", **asset_summary(entry)}
                   for aid, entry, origin, _, _ in rank_assets(candidates, q.strip().lower(), (kind or "").lower())[:limit]]
        return json.dumps({"status": "ok", "results": results, "count": len(results),
                           "inventory_count": len(candidates)})

    def _library_asset_entry(self, asset_id: str) -> Optional[JsonObject]:
        """W1.1: the by-value WORKSPACE ASSET LIBRARY entry for `asset_id`, or None.

        Mirrors website mode's `LumenWebTools._asset_library_entry` exactly (same
        seam, same checks): the entry must carry a record whose own id matches, and
        the record must be `ready`. Anything else is not a usable library asset and
        this returns None so the caller stays honest.

        Deliberately does NOT fall back to the kit manifest — kit membership is
        checked first by every caller, because a kit asset's scene copy is rewritten
        to `brand_guide` provenance (which is what keeps LUMB0809/LUMB0810 logo
        governance matching on kit variant ids), while a library asset's own
        licence and provenance are the truth we must preserve."""
        entry = (self.config.asset_library or {}).get(asset_id)
        if not isinstance(entry, dict):
            return None
        record = entry.get("record")
        if not isinstance(record, dict) or record.get("id") != asset_id:
            return None
        if record.get("status") != "ready":
            return None
        return entry

    def _library_asset_scene_record(self, asset_id: str) -> Optional[JsonObject]:
        """A deep copy of the library record ready to upsert into the scene.

        Unlike a kit asset the `source` block is NOT rewritten: the record's
        recorded licence and provenance are exactly what a grounded library
        placement promises to keep (the ratified website-mode rule in
        `_use_library_asset`)."""
        entry = self._library_asset_entry(asset_id)
        if entry is None:
            return None
        from .asset_catalog import materialize_asset
        materialize_asset(self.config, entry["record"])
        return copy.deepcopy(entry["record"])

    @_scene_mutation
    def _register_referenced_brand_assets(self, origin: str) -> None:
        """K2 root fix: a DSL author naturally writes `image asset(<id>)` with
        an asset_id straight from the brand card — a form the compiler accepts
        but which registers nothing, leaving a dangling reference that renders
        blank (LUME0211; the K2 live verify failed exactly here). Rather than
        prompt-steering against the natural form (a losing fight), any image
        node whose asset_id names a kit-manifest asset that the scene doesn't
        carry yet gets its record auto-registered with brand_guide provenance
        — the same registration use_brand_asset performs. The explicit action
        remains for fit/slot control. Failures never break the calling tool:
        registration is a repair, not a gate.

        W1.1 widens the same repair to the WORKSPACE ASSET LIBRARY. The Apollo POC
        scene cited a pre-generated ground the identical way (`image
        asset(asset_gen_…)`) and preflight answered `LUME0211 op.asset_missing`,
        because a library asset had no channel into a scene turn at all. A library
        record is registered VERBATIM (its own source/licence/provenance survive);
        the kit is still checked first, so an id in both stays a kit asset."""
        kit = self.config.brand_kit_assets or {}
        library = self.config.asset_library or {}
        if not kit and not library:
            return
        scene_assets = self.scene.get("assets") or {}
        referenced: list[str] = []
        for node in (self.scene.get("nodes") or {}).values():
            kind = node.get("kind") or {}
            if kind.get("kind") != "image":
                continue
            asset_id = kind.get("asset_id")
            if not asset_id or asset_id in scene_assets:
                continue
            if asset_id in kit or asset_id in library:
                referenced.append(asset_id)
        for asset_id in dict.fromkeys(referenced):
            from_kit = asset_id in kit
            entry = (kit.get(asset_id) if from_kit else library.get(asset_id)) or {}
            record = (
                copy.deepcopy(entry.get("record") or {})
                if from_kit
                else (self._library_asset_scene_record(asset_id) or {})
            )
            if not record.get("id"):
                continue
            label = entry.get("title") or record.get("label") or asset_id
            if from_kit:
                # A kit asset's scene copy is re-stamped brand_guide so the logo
                # governance that matches on kit variant ids keeps firing. A LIBRARY
                # record keeps its own source/licence/provenance — that is the
                # grounded promise, and rewriting it would launder its origin.
                record["source"] = {
                    "kind": "brand_guide",
                    "source_asset_id": asset_id,
                    "label": label,
                }
            try:
                response = self.core.apply_operations(
                    self.scene, [{"kind": "upsert_asset", "asset": record}]
                )
            except CoreError:
                continue
            self._replace_scene_from_core_response(
                response, origin, [{"kind": "upsert_asset", "asset": record}]
            )
            self.record(
                "coordinator",
                "brand_asset_registered",
                input_summary=asset_id,
                output_summary=(
                    f"auto-registered {'kit' if asset_id in kit else 'library'} "
                    f"asset {asset_id} referenced by the scene ({origin})"
                ),
                payload={
                    "brand_asset": {
                        "asset_id": asset_id,
                        "label": label,
                        "via": origin,
                        "manifest": "brand_kit" if asset_id in kit else "asset_library",
                    }
                },
            )

    @_scene_mutation
    def use_brand_asset(
        self,
        asset_id: str,
        node_id: Optional[str] = None,
        slot_id: Optional[str] = None,
        fit: str = "contain",
        focal_x: float = 0.5,
        focal_y: float = 0.5,
        alt: Optional[str] = None,
    ) -> str:
        """K2: register one of the attached Brand Kit's assets (a logo variant
        or brand image, from the kit-asset manifest the API passed by value)
        into the scene and place it into `node_id` or `slot_id`.

        The library record is upserted VERBATIM under its ORIGINAL id — brand
        governance (LUMB0809 min-size / LUMB0810 allowed-backgrounds)
        identifies logo nodes by matching node.asset_id against the kit's
        variant asset ids, so minting a new id would silently disable it —
        with only the scene copy's provenance rewritten to brand_guide
        (source_asset_id chains back to the library asset). Bytes never move:
        the record's content-addressed location already points into the
        shared store. Default fit is `contain` — logos are never cropped."""
        manifest = self.config.brand_kit_assets or {}
        entry = manifest.get(asset_id)
        if entry is None or not isinstance(entry, dict):
            return self._tool_error(
                "asset.unknown_brand_asset",
                f"'{asset_id}' is not in the attached Brand Kit's asset manifest. "
                "Use an asset_id from the brand context card's logo/image inventory.",
                known_asset_ids=sorted(manifest.keys())[:12],
            )
        record = copy.deepcopy(entry.get("record") or {})
        if not record.get("id"):
            return self._tool_error(
                "asset.bad_manifest_record",
                f"the manifest entry for '{asset_id}' carries no usable record.",
            )
        label = entry.get("title") or record.get("label") or asset_id
        record["source"] = {
            "kind": "brand_guide",
            "source_asset_id": asset_id,
            "label": label,
        }

        try:
            apply_response = self.core.apply_operations(
                self.scene, [{"kind": "upsert_asset", "asset": record}]
            )
        except CoreError as error:
            payload = {
                "brand_asset": {
                    "status": "error",
                    "error_code": error.code,
                    "message": error.message,
                    "asset_id": asset_id,
                },
                "hint": (
                    "The kit asset could not be registered in the scene (most "
                    "often the scene has no page/artboard yet). Author the page "
                    "first, then call use_brand_asset again."
                ),
                "diagnostics": [
                    diag.model_dump(mode="json")
                    for diag in diagnostics_from(error.diagnostics)
                ],
            }
            self.record(
                "coordinator",
                "brand_asset_registration_failed",
                input_summary=asset_id,
                output_summary=error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)
        self._replace_scene_from_core_response(
            apply_response, "use_brand_asset", [{"kind": "upsert_asset", "asset": record}], construction=True
        )
        self.record(
            "coordinator",
            "brand_asset_registered",
            input_summary=asset_id,
            output_summary=(
                f"registered kit asset {record.get('id')} "
                f"({(record.get('media') or {}).get('mime_type')}, provenance brand_guide)"
            ),
            payload={"brand_asset": {"asset_id": record.get("id"), "label": label}},
        )

        if node_id is not None:
            return self.place_asset_in_node(
                node_id, record["id"], fit, focal_x, focal_y, alt, None
            )
        if slot_id is not None:
            return self.place_asset_in_slot(
                slot_id, record["id"], fit, focal_x, focal_y, alt, None
            )
        return self._tool_error(
            "asset.bad_request",
            "action='use_brand_asset' requires `node_id` or `slot_id`.",
        )

    def fetch_logo(
        self,
        domain: str,
        company_name: Optional[str] = None,
        force_refresh: bool = False,
    ) -> str:
        """Fetch a real company's logos and register them. Use it for every company in the design that
        isn't us: the target account, a named customer, a partner.

        It returns up to four logos, one per cell:
        - light_lockup and dark_lockup: the full logo, for light and for dark backgrounds;
        - light_mark and dark_mark: the symbol alone, for light and for dark backgrounds.

        A missing cell means the company publishes nothing for it. That is a real answer, and it is never
        filled by recolouring another cell. Place a cell with asset(action="place", ...).

        Each cell is the best proven logo from two sources, Brandfetch and the company's own site, chosen
        by its measured colour against the background, completeness, format and size. Each says which
        source it came from. `alternatives` lists every other real logo found (a vendor icon, a short
        form, a candidate that lost); each is registered and says why it isn't in a cell. Use a cell
        first. Use an alternative only when the cell doesn't fit the placement, for example when the dark
        lockup turns out to be only a symbol, and say so.

        In an account-personalized or co-branded design, the OTHER company's logo must be its COMPLETE
        lockup — the `light_lockup`/`dark_lockup` cell for the surface you are placing on. The bare
        `*_mark` is a fallback for when the brand publishes no lockup, or the placement is genuinely too
        small to hold one — never the first choice: a naked symbol does not identify an account the way
        its full logo does.

        If the result is needs_review, nothing was registered, because no logo could be tied to that
        company with confidence. Say so and ask the person for the file. Never draw, recolour or
        approximate a logo.

        The site check reads only the page's HTML. A site that builds its header with JavaScript has no
        logo there, and the result says so.

        It needs a page in the scene. Without one it refuses (scene.page_required) before fetching.
        """
        refused = self._refuse_without_page("fetch_logo")
        if refused is not None:
            return refused
        requested = (domain or "").strip()
        if not requested:
            return self._tool_error(
                "logo_fetch.bad_request", "fetch_logo requires a non-empty `domain`."
            )
        try:
            outcome = logo_fetch.fetch_logo_family(
                requested,
                company_name=(company_name or "").strip() or None,
                force_refresh=force_refresh,
                cache=getattr(self.config, "logo_family_cache", None),
            )
        except ValueError as error:
            return self._tool_error("logo_fetch.bad_request", str(error))
        except Exception as error:  # noqa: BLE001 - tool failures are envelopes
            code = getattr(error, "code", "")
            self.record(
                "coordinator",
                "logo_fetch_failed",
                input_summary=requested[:500],
                output_summary=f"{type(error).__name__}: {error}"[:500],
            )
            return self._tool_error(
                "logo_fetch.blocked" if code == "LUMI0501" else "logo_fetch.failed",
                f"{getattr(error, 'message', None) or error}",
                capture_code=code or None,
            )

        if outcome.needs_review:
            self.record(
                "coordinator",
                "logo_fetch_needs_review",
                input_summary=requested[:500],
                output_summary=(outcome.notes[0] if outcome.notes else "no cell filled")[:500],
            )
            return json.dumps(logo_fetch.review_payload(outcome), indent=2)

        store_root = str(self.config.effective_asset_store_root)
        placed: list[JsonObject] = []
        failures: list[JsonObject] = []
        for prepared in outcome.prepared:
            ingest = self.core.ingest_asset(**prepared.ingest_kwargs(store_root))
            if not ingest.get("ok"):
                detail = (ingest.get("error") or {}).get("message", "unknown error")
                failures.append({"cell": prepared.cell, "error": detail})
                continue
            record = (ingest.get("asset") or {}).get("record") or {}
            # SCENE op key is "asset"; the web lane's is "record". Same engine
            # asset table, two operation schemas.
            operations = [{"kind": "upsert_asset", "asset": record}]
            try:
                self._apply_scene_operations("fetch_logo", operations)
            except CoreError as error:
                failures.append({"cell": prepared.cell, "error": error.message})
                continue
            placed.append({
                "cell": prepared.cell,
                "source": prepared.source,
                "asset_id": record.get("id") or prepared.asset_id,
                **prepared.evidence,
            })

        if not placed:
            return self._tool_error(
                "logo_fetch.ingest_failed",
                "the logo was resolved but could not be registered in the scene",
                failures=failures,
            )

        # The other real assets found for this company, registered the same way.
        # A failed alternative is dropped and named; only `placed` decides success.
        alternatives: list[JsonObject] = []
        failed_alternatives: list[JsonObject] = []
        for prepared in outcome.alternatives:
            ingest = self.core.ingest_asset(**prepared.ingest_kwargs(store_root))
            if not ingest.get("ok"):
                detail = (ingest.get("error") or {}).get("message", "unknown error")
                failed_alternatives.append({"cell": prepared.cell, "error": detail})
                continue
            record = (ingest.get("asset") or {}).get("record") or {}
            operations = [{"kind": "upsert_asset", "asset": record}]
            try:
                self._apply_scene_operations("fetch_logo", operations)
            except CoreError as error:
                failed_alternatives.append({"cell": prepared.cell, "error": error.message})
                continue
            alternatives.append({
                "asset_id": record.get("id") or prepared.asset_id,
                "source": prepared.source,
                "competed_for": prepared.evidence.get("competed_for"),
                "reason": prepared.evidence.get("reason"),
                **prepared.evidence,
            })

        payload: JsonObject = {
            "status": outcome.status,
            "site": outcome.site,
            "identity": outcome.identity,
            "lockup_completeness": outcome.lockup_completeness,
            "cache_hit": outcome.cache_hit,
            "logos": placed,
            "alternatives": alternatives,
            "notes": outcome.notes[:4],
            "next": (
                "Place one with asset(action='place', asset_id=..., node_id=... or "
                "slot_id=...). Match the cell to the placement: *_lockup is the full "
                "logo (first choice on any surface that fits it), *_mark is the bare "
                "symbol (small placements only). Use dark_* cells on dark surfaces, "
                "light_* on light ones. `alternatives` are other real assets found "
                "for this company, also registered: use a cell first; pick an "
                "alternative only when the cell does not fit the placement, and say so."
            ),
        }
        if self.config.scene_skill_bundle == "candidate":
            from ..prompts import SCENE_LOGO_SELECTION_GUIDANCE

            payload["next"] = payload["next"].replace(
                "*_lockup is the full logo (first choice on any surface that fits it), "
                "*_mark is the bare symbol (small placements only).",
                SCENE_LOGO_SELECTION_GUIDANCE,
            )
        if failures:
            payload["failed_cells"] = failures
        if failed_alternatives:
            payload["failed_alternatives"] = failed_alternatives
        self.record(
            "coordinator",
            "logo_fetched",
            input_summary=requested[:500],
            output_summary=(
                f"{outcome.site}: " + ", ".join(p["cell"] for p in placed)
            )[:500],
            payload={"site": outcome.site, "cells": [p["cell"] for p in placed]},
        )
        return json.dumps(payload, indent=2)

    def _collect_reference_previews(
        self, condition_on_references: bool, diagnostics: List[JsonObject]
    ) -> tuple[Optional[List[tuple]], Optional[List[str]]]:
        """The turn's reference attachment previews as order-sorted
        (bytes, mime) pairs + their pixel digests, for style-conditioning a
        generation. Returns (None, None) when there are no references or the
        caller opted out (byte-identical to a plain generation). A reference
        whose store blob went missing mid-run is SKIPPED with a recorded warning
        (never a hard fail — the 422 boundary guarded turn start); its digest is
        dropped from the key too, so the cached asset matches what was actually
        conditioned on."""
        manifest = self.config.reference_assets or {}
        if not condition_on_references or not manifest:
            return None, None
        ordered = sorted(
            manifest.items(), key=lambda kv: ((kv[1] or {}).get("order", 0), kv[0])
        )
        store_root = self.config.effective_asset_store_root
        images: List[tuple] = []
        digests: List[str] = []
        for asset_id, entry in ordered:
            entry = entry or {}
            digest = entry.get("preview_digest")
            path = blob_path_for_digest(store_root, digest) if digest else None
            if path is None or not path.is_file():
                self.record(
                    "agent",
                    "reference_preview_missing",
                    input_summary=asset_id,
                    output_summary=(
                        f"reference {asset_id} preview bytes missing "
                        f"({digest or 'no digest'}); skipped conditioning on it"
                    ),
                )
                continue
            images.append((path.read_bytes(), entry.get("mime_type") or "image/png"))
            digests.append(digest)
        return (images or None), (digests or None)

    def _collect_selected_reference_previews(self, asset_ids: list[str]):
        """Resolve only this run's authorized IDs to verified conditioning bytes.

        Library rasters use full source pixels, not contact-sheet thumbnails.
        Vectors need an existing raster preview; generation never vectorizes.
        Explicit selection fails as a unit instead of silently dropping an input.
        The legacy automatic-attachment path retains its existing skip behavior.
        """

        def refuse(reason: str, detail: str):
            return None, None, None, (f"image.reference_{reason}", detail)

        if not isinstance(asset_ids, list) or any(
            not isinstance(item, str) or not item for item in asset_ids
        ):
            return refuse("invalid", "reference_asset_ids must be a list of asset IDs.")
        ids = list(dict.fromkeys(asset_ids))
        if len(ids) > 4:
            return refuse("limit", "Select at most four relevant reference assets per image.")
        images, digests, receipt = [], [], []
        store_root = self.config.effective_asset_store_root
        for asset_id in ids:
            attached = (self.config.reference_assets or {}).get(asset_id)
            if attached is not None:
                digest = attached.get("preview_digest")
                mime = attached.get("mime_type") or "image/png"
            else:
                record = (self.scene.get("assets") or {}).get(asset_id)
                if record is None:
                    entry = (
                        (self.config.brand_kit_assets or {}).get(asset_id)
                        or (self.config.asset_library or {}).get(asset_id)
                        or {}
                    )
                    record = entry.get("record")
                if (
                    not isinstance(record, dict)
                    or record.get("id") != asset_id
                    or record.get("status") != "ready"
                ):
                    return refuse(
                        "unavailable", f"{asset_id} is not a ready asset in this run's context."
                    )
                media = record.get("media") or {}
                mime = media.get("mime_type")
                if mime in PREVIEWABLE_MIME_TYPES:
                    digest = (media.get("digest") or {}).get("value")
                else:
                    preview = asset_preview_path(record, store_root)
                    digest = Path(preview[0]).name if preview else None
                    mime = (media.get("thumbnail") or {}).get("mime_type") or "image/png"
            if (
                not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or mime not in PREVIEWABLE_MIME_TYPES
            ):
                return refuse(
                    "invalid", f"{asset_id} has no valid raster reference digest and MIME type."
                )
            try:
                pixels = blob_path_for_digest(store_root, digest).read_bytes()
            except OSError:
                return refuse(
                    "missing",
                    f"Selected reference {asset_id} has no materialized bytes; "
                    "choose another available source.",
                )
            if hashlib.sha256(pixels).hexdigest() != digest:
                return refuse(
                    "corrupt", f"Selected reference {asset_id} does not match its frozen digest."
                )
            images.append((pixels, mime))
            digests.append(digest)
            receipt.append({"asset_id": asset_id, "digest": digest, "mime_type": mime})
        return images or None, digests or None, receipt, None

    def _produce_image_asset(
        self,
        *,
        asset_id: str,
        prompt: str,
        label: str,
        width: Optional[int],
        height: Optional[int],
        aspect_ratio: Optional[str],
        brand_notes: List[str],
        transparent_background: bool,
        condition_on_references: bool = True,
        reference_asset_ids: list[str] | None = None,
        reference_roles: list[str] | None = None,
        reference_framing: str | None = None,
        operation: str | None = None,
    ) -> tuple[Optional[JsonObject], JsonObject, List[JsonObject], Optional[tuple]]:
        """Produce + ingest one image asset record. Prefers the configured T2I
        model; on a missing config or any model/ingest failure it falls back to the
        deterministic stub provider (with a warning) so the design loop never
        dead-ends on imagery. When this turn carries reference attachments and
        `condition_on_references` is set, the reference previews ride the model
        call as STYLE anchors (and key the cache on their pixel digests). Returns
        (record, meta, raw_diagnostics, error).

        W1.7(c) — FAILED GENERATION NEVER BLOCKS THE TURN (founder ruling D5: no
        new blocking gates). Every degrade path below is non-fatal by
        construction, and each one now also records a TYPED `fallback` descriptor
        on the returned meta — `{reason, error_code, detail, conditioning_lost}` —
        so the agent can react in kind (most often: proceed with a flat token
        ground instead of an image ground) rather than having to parse a warning
        string. `meta["fallback"]` is absent on the success path."""
        diagnostics: List[JsonObject] = []
        fallback: Optional[JsonObject] = None
        selected_receipt = None
        if reference_roles is not None and reference_asset_ids is not None and (
            len(reference_asset_ids) != len(set(reference_asset_ids))
        ):
            return None, {}, diagnostics, (
                "image.reference_invalid", "Role-aware selections require distinct asset IDs."
            )
        if reference_asset_ids is not None:
            reference_images, reference_digests, selected_receipt, error = (
                self._collect_selected_reference_previews(reference_asset_ids)
            )
            if error:
                # A bad selection is a correctable tool error, not permission
                # to spend on unconditioned imagery or mutate the scene.
                return None, {}, diagnostics, error
        else:
            reference_images, reference_digests = self._collect_reference_previews(
                condition_on_references, diagnostics
            )
        if reference_roles is not None or reference_framing is not None:
            try:
                from lumen_api.image_provider import resolve_reference_framing
                resolve_reference_framing(
                    reference_images or [], reference_roles, reference_framing
                )
            except Exception as error:
                return None, {}, diagnostics, ("image.reference_invalid", str(error))
        if selected_receipt:
            self._selected_reference_ids.update(item["asset_id"] for item in selected_receipt)

        # 1) Real text-to-image model, when configured.
        if image_provider is not None and image_provider.is_configured():
            store_root = str(self.config.effective_asset_store_root)
            # Reference-conditioned generation: resolve the turn's attachment
            # preview bytes (order-sorted) so the style rides the model call and
            # the cache keys on their pixel digests. No references / opt-out →
            # (None, None) and the request is byte-identical to a plain generation.
            # Generation cache: re-use the asset an identical earlier request
            # produced (the loop re-requests the same hero each iteration) instead
            # of re-paying the model. Checked BEFORE the provider call.
            cache_key = None
            model_id = getattr(image_provider, "configured_model_id", None)
            if image_cache is not None and callable(model_id):
                cache_key = image_cache.generation_key(
                    prompt=prompt,
                    model=model_id(),
                    width=width,
                    height=height,
                    brand_notes=brand_notes,
                    aspect_ratio=aspect_ratio,
                    transparent_background=transparent_background or None,
                    reference_digests=reference_digests,
                    reference_roles=reference_roles,
                    reference_framing=reference_framing,
                    operation=operation,
                )
                cached = image_cache.lookup(store_root, cache_key)
                if cached:
                    return (
                        cached,
                        {
                            "mode": "cached",
                            "model": (cached.get("source") or {}).get("model"),
                            **_image_receipt_fields(cached),
                            **(
                                {"reference_inputs": selected_receipt}
                                if selected_receipt is not None
                                else {}
                            ),
                        },
                        diagnostics,
                        None,
                    )
            try:
                result = image_provider.generate(
                    prompt=prompt,
                    width=width,
                    height=height,
                    brand_notes=brand_notes,
                    aspect_ratio=aspect_ratio,
                    transparent_background=transparent_background or None,
                    reference_images=reference_images,
                    **{key: value for key, value in {
                        "reference_roles": reference_roles,
                        "reference_framing": reference_framing,
                        "operation": operation,
                    }.items() if value is not None},
                    request_id=asset_id,
                )
                if reference_digests:
                    # Honest provenance: the ingested asset records which reference
                    # pixels conditioned it.
                    notes = result.provenance.setdefault("notes", [])
                    notes.append(
                        f"reference-conditioned on {len(reference_digests)} "
                        f"attachment(s): {', '.join(reference_digests)}"
                    )
                ingest = self.core.ingest_asset(
                    store_root=store_root,
                    bytes_base64=base64.b64encode(result.image_bytes).decode("ascii"),
                    asset_id=asset_id,
                    label=label,
                    declared_mime_type=result.mime_type,
                    kind="raster_image",
                    license=result.license,
                    provenance=result.provenance,
                    source={"kind": "generated", "request_id": asset_id, "model": result.model},
                    raise_on_error=False,
                )
                if ingest.get("ok"):
                    record = (ingest.get("asset") or {}).get("record") or {}
                    diagnostics.extend(_as_diag_list(ingest.get("diagnostics")))
                    if cache_key is not None and image_cache is not None:
                        image_cache.store(store_root, cache_key, record)
                    # W1.7(b): the model's REAL output geometry, measured from the
                    # returned bytes. `width`/`height` above are what we ASKED for,
                    # and the Apollo POC proved the two can differ (16:9 asked,
                    # 1024x1024 delivered) — so both travel, never just the ask.
                    return (
                        record,
                        {
                            "mode": "model",
                            "model": result.model,
                            "actual_width": getattr(result, "width", None),
                            "actual_height": getattr(result, "height", None),
                            "aspect_ratio_honored": getattr(result, "aspect_ratio_honored", None),
                            **_image_receipt_fields(record),
                            **(
                                {"reference_inputs": selected_receipt}
                                if selected_receipt is not None
                                else {}
                            ),
                        },
                        diagnostics,
                        None,
                    )
                detail = (ingest.get("error") or {}).get("message", "unknown error")
                fallback = {
                    "reason": "ingest_failed",
                    "error_code": "image.ingest_failed",
                    "detail": str(detail)[:200],
                    "conditioning_lost": bool(reference_digests),
                }
                diagnostics.append(
                    _image_warning(
                        "LUMA0710",
                        f"generated image could not be ingested ({detail}); used a placeholder",
                    )
                )
            except Exception as error:  # noqa: BLE001 - degrade to a placeholder, never crash the loop
                code = getattr(error, "code", error.__class__.__name__)
                # RC2-1 honesty (refuter note): a placeholder is inherently
                # UNCONDITIONED — when this generation was reference-conditioned,
                # say the conditioning was lost, not just that a placeholder ran.
                conditioning_note = (
                    " (reference conditioning lost)" if reference_digests else ""
                )
                fallback = {
                    "reason": "model_failed",
                    "error_code": str(code),
                    "detail": str(error)[:200],
                    "conditioning_lost": bool(reference_digests),
                }
                diagnostics.append(
                    _image_warning(
                        "LUMA0710",
                        f"text-to-image model unavailable ({code}); used a "
                        f"placeholder image{conditioning_note}",
                    )
                )
        elif image_provider is not None:
            fallback = {
                "reason": "not_configured",
                "error_code": "image_model.not_configured",
                "detail": "text-to-image model is not configured (set IMAGE_MODEL_*)",
                "conditioning_lost": bool(selected_receipt),
            }
            diagnostics.append(
                _image_warning(
                    "LUMA0711",
                    "text-to-image model is not configured (set IMAGE_MODEL_*); used a placeholder image",
                )
            )

        # 2) Deterministic stub fallback through the Rust provider registry.
        request = {
            "request_id": asset_id,
            "prompt": prompt,
            "output_kind": "raster_image",
            "target_node_id": None,
            "target_slot_id": None,
            "constraints": {
                "width": width,
                "height": height,
                "transparent_background": transparent_background or None,
                "brand_notes": brand_notes,
            },
        }
        try:
            response = self.core.generate_asset(
                store_root=str(self.config.effective_asset_store_root),
                provider="stub-image-v0",
                request=request,
                asset_id=asset_id,
                label=label,
            )
        except CoreError as error:
            diagnostics.extend(_as_diag_list(error.diagnostics))
            return None, {}, diagnostics, (error.code, error.message)
        record = (response.get("asset") or {}).get("record") or {}
        diagnostics.extend(_as_diag_list(response.get("diagnostics")))
        meta: JsonObject = {"mode": "placeholder", "model": "stub-image-v0"}
        if fallback is not None:
            meta["fallback"] = fallback
        return record, meta, diagnostics, None

    def _image_constraints(
        self,
        target_node_id: Optional[str],
        target_slot_id: Optional[str],
        width: Optional[int],
        height: Optional[int],
        aspect_ratio: Optional[str],
    ) -> tuple[Optional[int], Optional[int], Optional[str]]:
        """Derive aspect_ratio (and a role-appropriate resolution) from the target
        frame's geometry so generated images match the frame they fill."""
        bounds = self._target_bounds(target_node_id, target_slot_id)
        if bounds:
            box_width, box_height = bounds
            if aspect_ratio is None:
                aspect_ratio = _nearest_aspect_label(box_width, box_height)
            if width is None and height is None:
                width, height = _resolution_for_aspect(box_width, box_height)
        return width, height, aspect_ratio

    def _target_bounds(
        self, target_node_id: Optional[str], target_slot_id: Optional[str]
    ) -> Optional[tuple]:
        """Resolve a target node's (width, height) from computed geometry, falling
        back to its declared fixed size. Slots resolve to their first bound node."""
        node_id = target_node_id
        if node_id is None and target_slot_id:
            slot = self.scene.get("slots", {}).get(target_slot_id) or {}
            bound = slot.get("bound_nodes") or []
            node_id = bound[0] if bound else None
        if not node_id:
            return None
        node = self.scene.get("nodes", {}).get(node_id) or {}
        bounds = (node.get("computed") or {}).get("layout_bounds") or {}
        box_width = bounds.get("width")
        box_height = bounds.get("height")
        if not box_width or not box_height:
            size = node.get("size") or {}
            box_width = _fixed_dim(size.get("width"))
            box_height = _fixed_dim(size.get("height"))
        if box_width and box_height and box_width > 0 and box_height > 0:
            return float(box_width), float(box_height)
        return None

    def place_asset_in_node(
        self,
        node_id: str,
        asset_id: str,
        fit: str = "cover",
        focal_x: float = 0.5,
        focal_y: float = 0.5,
        alt: Optional[str] = None,
        preserve_transparency: Optional[bool] = None,
    ) -> str:
        """Place a real asset into an existing image or reserved empty leaf frame.
        Raster/logo placement converts an empty `fr` to an image in place,
        preserving its ID and geometry. A container with children cannot be
        consumed; missing node/asset IDs remain errors. Path-backed vectors stay
        native vectors. Use fit (default cover), a normalized focal point (0..1,
        default centered) for the cover crop, and alt text. Reversible."""
        return self._place_asset(
            "place_asset_in_node", "node_id", node_id, asset_id, fit, focal_x, focal_y, alt, preserve_transparency
        )

    def place_asset_in_slot(
        self,
        slot_id: str,
        asset_id: str,
        fit: str = "cover",
        focal_x: float = 0.5,
        focal_y: float = 0.5,
        alt: Optional[str] = None,
        preserve_transparency: Optional[bool] = None,
    ) -> str:
        """Place an existing asset into an image slot's bound node — same placement
        semantics as place_asset_in_node, preserving the slot binding. Reversible."""
        return self._place_asset(
            "place_asset_in_slot", "slot_id", slot_id, asset_id, fit, focal_x, focal_y, alt, preserve_transparency
        )

    @_scene_mutation
    def _place_asset(
        self,
        kind: str,
        target_key: str,
        target_id: str,
        asset_id: str,
        fit: str,
        focal_x: float,
        focal_y: float,
        alt: Optional[str],
        preserve_transparency: Optional[bool],
    ) -> str:
        # W1.1: a WORKSPACE ASSET LIBRARY id the scene does not carry yet is
        # registered first, or the engine refuses the placement with
        # `LUME0211 op.asset_missing` — precisely what killed the Apollo POC's
        # pre-generated ground (`.context/ref-ads-pilot-apollo-report.md` §6.1).
        # This tool has always DOCUMENTED "generated or library"; the library half
        # simply had no channel into a scene turn. Same repair-not-gate discipline
        # as `_register_referenced_brand_assets`: an id the library does not hold
        # reaches the engine bare, so an honest miss stays an honest miss.
        self._register_library_asset_for_placement(asset_id, kind)
        placement: JsonObject = {
            "fit": fit,
            "focal_point": {"x": float(focal_x), "y": float(focal_y)},
        }
        if alt is not None:
            placement["alt_text"] = alt
        if preserve_transparency is not None:
            placement["preserve_transparency"] = bool(preserve_transparency)
        operation = {"kind": kind, target_key: target_id, "asset_id": asset_id, "placement": placement}
        try:
            apply_response = self.core.apply_operations(self.scene, [operation])
        except CoreError as error:
            payload = {
                "placement": {
                    "status": "error",
                    "error_code": error.code,
                    "message": error.message,
                },
                "diagnostics": [
                    diag.model_dump(mode="json") for diag in diagnostics_from(error.diagnostics)
                ],
            }
            self.record(
                "coordinator",
                "asset_placement_failed",
                input_summary=f"{kind} {target_id} <- {asset_id}",
                output_summary=error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        self._replace_scene_from_core_response(apply_response, kind, [operation], construction=True)
        diagnostics = diagnostics_from(apply_response.get("diagnostics", []))
        payload = {
            "placement": {
                "status": "ok",
                "operation": kind,
                target_key: target_id,
                "asset_id": asset_id,
                "fit": fit,
                "focal_point": {"x": float(focal_x), "y": float(focal_y)},
                "alt": alt,
            },
            "diagnostics": [diag.model_dump(mode="json") for diag in diagnostics],
        }
        self.record(
            "coordinator",
            "asset_placed",
            input_summary=f"{kind} {target_id} <- {asset_id}",
            output_summary=f"placed {asset_id} into {target_id} (fit={fit})",
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
            # Live-design-streaming S0: the placement's applied op — the same
            # single op logged to the proposal ledger via
            # `_replace_scene_from_core_response(..., [operation])` above — rides
            # the sink so the canvas can render the asset dropping into its node.
            # Rung B: `operations_total` is the ledger length AFTER that append
            # (the append is above), i.e. the position this batch ends at — the
            # same counter a `design.checkpoint` frame reports, so the client can
            # drop batches an already-reloaded checkpoint version covers. A
            # refused placement returns early above and pushes neither key.
            sink_extra={
                "operations": [operation],
                "operations_total": len(self.operations_ledger),
            },
        )
        return json.dumps(payload, indent=2)

    @_scene_mutation
    def _register_library_asset_for_placement(self, asset_id: str, kind: str) -> None:
        """Upsert a workspace-library record into the scene so a placement can bind.

        No-ops for anything already in the scene, anything the kit owns (the kit
        has its own brand_guide registration path), and anything the library does
        not hold as a `ready` record. A failed upsert is swallowed on purpose: the
        placement then reaches the engine exactly as it did before, and the engine's
        own diagnostic — not a second, invented one — is what the agent sees."""
        if not asset_id or asset_id in (self.scene.get("assets") or {}):
            return
        if asset_id in (self.config.brand_kit_assets or {}):
            return
        record = self._library_asset_scene_record(asset_id)
        if record is None:
            return
        operation = {"kind": "upsert_asset", "asset": record}
        try:
            response = self.core.apply_operations(self.scene, [operation])
        except CoreError:
            return
        self._replace_scene_from_core_response(response, kind, [operation], construction=True)
        entry = self._library_asset_entry(asset_id) or {}
        self.record(
            "coordinator",
            "library_asset_registered",
            input_summary=asset_id,
            output_summary=(
                f"registered workspace library asset {asset_id} "
                f"(licence and provenance preserved) before {kind}"
            ),
            payload={
                "library_asset": {
                    "asset_id": asset_id,
                    "label": entry.get("title") or record.get("label") or asset_id,
                    "via": kind,
                }
            },
        )

    def _asset_preview_path(
        self, record: JsonObject
    ) -> Optional[tuple[str, Optional[int], Optional[int]]]:
        """Slice 2: resolve a kit-asset record to an ON-DISK preview the vision APIs
        can read, returning (absolute_path, pixel_width, pixel_height) or None.

        The resolution itself is `asset_preview.asset_preview_path` — shared with
        the web lane's view("asset:<id>") so the two lanes cannot disagree about
        which pixels represent an asset. This binds it to THIS run's asset-store
        root; a None result is a record with no usable raster preview (an SVG with
        no derived thumbnail), which the caller skips and counts in `_omitted`."""
        return asset_preview_path(record, self.config.effective_asset_store_root)

    def _crop_source_record(self, asset_id: str) -> Optional[JsonObject]:
        """Resolve crop custody only within this run's authorized records."""
        record = (self.scene.get("assets") or {}).get(asset_id)
        if record is None:
            for manifest in (
                self.config.brand_kit_assets, self.config.asset_library, self.config.reference_assets
            ):
                entry = (manifest or {}).get(asset_id)
                if isinstance(entry, dict) and isinstance(entry.get("record"), dict):
                    record = entry["record"]
                    break
        return record if isinstance(record, dict) and record.get("id") == asset_id else None

    def _original_raster_source(self, asset_id: str) -> tuple[JsonObject, bytes, str, str]:
        """Read verified original bytes by authorized ID; never substitute a preview.

        Viewing needs no modification license. The caller that derives a new asset
        owns that permission and ancestry check before invoking the crop decoder.
        """
        record = self._crop_source_record(asset_id)
        if (
            not isinstance(record, dict)
            or record.get("id") != asset_id
            or record.get("status") != "ready"
        ):
            raise ImageCropError(
                "asset.crop_unavailable", "Source is not a ready asset in this run's context."
            )
        media = record.get("media") or {}
        digest = (media.get("digest") or {}).get("value")
        mime = media.get("mime_type")
        if (
            record.get("kind") not in {"raster_image", "logo"}
            or mime not in PREVIEWABLE_MIME_TYPES
            or (media.get("digest") or {}).get("algorithm") != "sha256"
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ImageCropError(
                "asset.crop_invalid_source",
                "Requires an original raster with a valid SHA-256 digest.",
            )
        try:
            source_path = blob_path_for_digest(self.config.effective_asset_store_root, digest)
            source_bytes = source_path.read_bytes()
        except OSError as error:
            raise ImageCropError(
                "asset.crop_missing", "Original source bytes are not materialized."
            ) from error
        if hashlib.sha256(source_bytes).hexdigest() != digest:
            raise ImageCropError(
                "asset.crop_corrupt", "Source bytes do not match their frozen digest."
            )
        return record, source_bytes, mime, digest

    def crop_image(
        self, asset_id: str, crop_rect: Any, label: str | None = None,
        frame_index: StrictInt | None = None,
    ) -> str:
        """Register a lossless source rectangle as a separate, unplaced image."""
        refusal = self._refuse_without_page("crop_image")
        if refusal is not None:
            return refusal
        try:
            record = self._crop_source_record(asset_id)
            if record is not None:
                require_supported_crop_origin(record, self._crop_source_record)
            record, source_bytes, mime, _digest = self._original_raster_source(asset_id)
            license = record.get("license")
            # Mirror AssetRecord::allows_modification: absent license permits; a
            # present license with a missing flag defaults to false in the engine.
            if license is not None and license.get("allow_modification") is not True:
                raise ImageCropError(
                    "asset.crop_license", "The source license does not permit modification."
                )
            cropped = crop_source_pixels(
                source_bytes, source_asset_id=asset_id, mime_type=mime, rect=crop_rect,
                source_generated=has_generated_image_origin(record), frame_index=frame_index,
            )
        except ImageCropError as error:
            return self._tool_error(error.code, str(error))
        derived_id = f"asset_crop_{self.run_id[:12]}_{uuid4().hex}"
        provenance = copy.deepcopy(record.get("provenance") or {})
        provenance["notes"] = [
            *(provenance.get("notes") or []),
            "asset_derivation=" + json.dumps(cropped.receipt, sort_keys=True),
        ]
        try:
            ingested = self.core.ingest_asset(
                store_root=str(self.config.effective_asset_store_root),
                bytes_base64=base64.b64encode(cropped.png_bytes).decode("ascii"),
                asset_id=derived_id,
                label=label or f"Crop of {record.get('label') or asset_id}",
                declared_mime_type="image/png",
                kind="raster_image",
                filename=f"{derived_id}.png",
                license=copy.deepcopy(license),
                provenance=provenance,
                # `edited` means MODEL-edited in the existing engine schema.
                # A deterministic crop has no model; its lineage is the receipt.
                source={"kind": "manual", "label": f"deterministic crop of {asset_id}"},
                tags=[*(record.get("tags") or []), "crop"],
            )
            derived = ingested["asset"]["record"]
            with self._scene_mutation_lock:
                operations = [{"kind": "upsert_asset", "asset": derived}]
                response = self.core.apply_operations(self.scene, operations)
                self._replace_scene_from_core_response(response, "crop_image", operations, construction=True)
        except CoreError as error:
            return self._tool_error(error.code, error.message)
        payload = {
            "image_crop": {
                "status": "ok", "asset_id": derived_id, "mode": "deterministic",
                "crop_receipt": cropped.receipt,
            },
            "diagnostics": ingested.get("diagnostics") or [],
            "next": (
                "Inspect the new asset, then place it explicitly in an independent image node "
                "with asset(action='place')."
            ),
        }
        self.record(
            "coordinator", "image_cropped", input_summary=asset_id,
            output_summary=derived_id, payload=payload,
        )
        return json.dumps(payload, indent=2)

    def _resolve_node_image_source(
        self, node_id: str
    ) -> tuple[Optional[JsonObject], Optional[bytes], Optional[str], Optional[str], Optional[tuple]]:
        """Resolve a node's currently placed image asset into (record, bytes, mime,
        source_digest, error). The bytes come from the content-addressed store the
        same way the /assets/generate edit route reads them: media.digest.value →
        `sha256/<first2>/<digest>` under the asset-store root. Returns an error tuple
        (code, message) when the node has no ready image asset to edit — mirroring the
        LUMV0100 graceful guards so an edit on an un-imaged node never crashes the loop."""
        node = (self.scene.get("nodes") or {}).get(node_id)
        if not node:
            return None, None, None, None, (
                "asset.node_not_found",
                f"node {node_id!r} does not exist in the current scene",
            )
        asset_id = (node.get("kind") or {}).get("asset_id")
        if not asset_id:
            return None, None, None, None, (
                "asset.not_an_image_node",
                f"node {node_id!r} is not an image node (no placed asset to edit)",
            )
        record = (self.scene.get("assets") or {}).get(asset_id)
        if not record:
            return None, None, None, None, (
                "asset.source_not_registered",
                f"node {node_id!r} references asset {asset_id!r}, which is not in the scene",
            )
        if record.get("status") != "ready":
            return None, None, None, None, (
                "asset.source_not_ready",
                f"asset {asset_id!r} on node {node_id!r} is not a ready image (status="
                f"{record.get('status')!r}); generate a ready image before editing it",
            )
        media = record.get("media") or {}
        source_digest = (media.get("digest") or {}).get("value")
        mime = media.get("mime_type") or "image/png"
        if not source_digest:
            return None, None, None, None, (
                "asset.source_bytes_missing",
                f"asset {asset_id!r} has no stored digest; its bytes cannot be resolved to edit",
            )
        store_root = Path(self.config.effective_asset_store_root)
        blob_path = store_root / "sha256" / source_digest[:2] / source_digest
        if not blob_path.is_file():
            return None, None, None, None, (
                "asset.source_bytes_missing",
                f"asset {asset_id!r} has no stored bytes to edit ({blob_path})",
            )
        return record, blob_path.read_bytes(), mime, source_digest, None

    def edit_image(
        self,
        node_id: str,
        prompt: str,
        remove_background: bool = False,
        label: Optional[str] = None,
        operation: str | None = None,
    ) -> str:
        """Edit the raster image currently placed in `node_id` with a text
        instruction (Phase 3c) — recolor / adjust warmth / remove or replace the
        background / fix a flawed subject — WITHOUT changing the composition. The
        source pixels ride the model call; the edited result re-enters the SAME node
        preserving its current placement (fit / focal point / alt). Prefer this over a
        full regenerate when the placed image is right-but-flawed. `remove_background`
        requests a transparent background. Returns the new (edited) asset_id, its
        provenance chained to the source asset. Gracefully errors (never crashes) when
        the node has no ready image asset to edit."""
        source_record, source_bytes, source_mime, source_digest, error = (
            self._resolve_node_image_source(node_id)
        )
        if error is not None:
            payload = {
                "image_edit": {
                    "status": "error",
                    "error_code": error[0],
                    "message": error[1],
                    "node_id": node_id,
                },
                "hint": (
                    "edit_image edits the image already placed in this node. Generate "
                    "and place a ready image first, then edit it — or use "
                    "action='generate_image' for a fresh image."
                ),
            }
            self.record(
                "coordinator",
                "image_edit_failed",
                input_summary=f"{node_id}: {prompt[:160]}",
                output_summary=error[1],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        source_asset_id = (source_record or {}).get("id")
        transparent = remove_background or None
        asset_id = f"asset_img_{self.run_id[:8]}_edit_{len(self.scene.get('assets', {}))}"
        resolved_label = label or (prompt[:60].strip() or asset_id)

        record: Optional[JsonObject] = None
        meta: JsonObject = {}
        diagnostics: List[JsonObject] = []
        edit_error: Optional[tuple] = None

        if image_provider is not None and image_provider.is_configured():
            store_root = str(self.config.effective_asset_store_root)
            # Per-run generation cache, keyed on the SOURCE digest + prompt (+ bg flag)
            # so the loop re-editing the same image with the same instruction is free,
            # and the same instruction on a different image never collides.
            cache_key = None
            model_id = getattr(image_provider, "configured_model_id", None)
            if image_cache is not None and callable(model_id):
                cache_key = image_cache.generation_key(
                    prompt=prompt,
                    model=model_id(),
                    transparent_background=transparent,
                    source_digest=source_digest,
                    operation=operation,
                )
                cached = image_cache.lookup(store_root, cache_key)
                if cached:
                    record = cached
                    meta = {
                        "mode": "cached", "model": (cached.get("source") or {}).get("model"),
                        **_image_receipt_fields(cached),
                    }
            if record is None:
                try:
                    result = image_provider.edit(
                        prompt=prompt,
                        source_images=[(source_bytes, source_mime)],
                        transparent_background=transparent,
                        request_id=asset_id,
                        **({"operation": operation} if operation is not None else {}),
                    )
                    ingest = self.core.ingest_asset(
                        store_root=store_root,
                        bytes_base64=base64.b64encode(result.image_bytes).decode("ascii"),
                        asset_id=asset_id,
                        label=resolved_label,
                        declared_mime_type=result.mime_type,
                        kind="raster_image",
                        license=result.license,
                        provenance=result.provenance,
                        source={
                            "kind": "edited",
                            "request_id": asset_id,
                            "model": result.model,
                            "source_asset_id": source_asset_id,
                        },
                        raise_on_error=False,
                    )
                    if ingest.get("ok"):
                        record = (ingest.get("asset") or {}).get("record") or {}
                        diagnostics.extend(_as_diag_list(ingest.get("diagnostics")))
                        if cache_key is not None and image_cache is not None:
                            image_cache.store(store_root, cache_key, record)
                        meta = {
                            "mode": "model", "model": result.model, **_image_receipt_fields(record)
                        }
                    else:
                        detail = (ingest.get("error") or {}).get("message", "unknown error")
                        edit_error = ("image_edit.ingest_failed", f"edited image could not be ingested ({detail})")
                except Exception as exc:  # noqa: BLE001 - report, never crash the loop
                    code = getattr(exc, "code", exc.__class__.__name__)
                    edit_error = ("image_edit.model_failed", f"image edit failed ({code})")
        else:
            edit_error = (
                "image_edit.model_unconfigured",
                "text-to-image model is not configured (set IMAGE_MODEL_*); cannot edit the image",
            )

        diags = diagnostics_from(diagnostics)
        if record is None:
            payload = {
                "image_edit": {
                    "status": "error",
                    "error_code": edit_error[0] if edit_error else "image_edit.error",
                    "message": edit_error[1] if edit_error else "image edit failed",
                    "node_id": node_id,
                    "source_asset_id": source_asset_id,
                },
                "diagnostics": [d.model_dump(mode="json") for d in diags],
            }
            self.record(
                "coordinator",
                "image_edit_failed",
                input_summary=f"{node_id}: {prompt[:160]}",
                output_summary=payload["image_edit"]["message"],
                diagnostics=[d.model_dump(mode="json") for d in diags],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        # Register the edited asset through the canonical upsert path (guarded — a
        # scene without a page/artboard fails here, same as generate_image).
        try:
            self._apply_scene_operations(
                "edit_image", [{"kind": "upsert_asset", "asset": record}]
            )
        except CoreError as reg_error:
            payload = {
                "image_edit": {
                    "status": "error",
                    "error_code": reg_error.code,
                    "message": reg_error.message,
                    "asset_id": record.get("id"),
                    "node_id": node_id,
                },
                "diagnostics": [
                    d.model_dump(mode="json") for d in diagnostics_from(reg_error.diagnostics)
                ],
            }
            self.record(
                "coordinator",
                "image_edit_registration_failed",
                input_summary=f"{node_id}: {prompt[:160]}",
                output_summary=reg_error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        # Re-place the edited asset into the SAME node, preserving the current
        # placement (fit / focal point / alt) so the composition is untouched.
        placement = ((self.scene.get("nodes") or {}).get(node_id) or {}).get("asset_placement") or {}
        focal = placement.get("focal_point") or {}
        place_result = json.loads(
            self.place_asset_in_node(
                node_id,
                record.get("id"),
                fit=placement.get("fit") or "cover",
                focal_x=focal.get("x", 0.5),
                focal_y=focal.get("y", 0.5),
                alt=placement.get("alt_text"),
                preserve_transparency=True if transparent else None,
            )
        )

        payload = {
            "image_edit": {
                "status": "ok",
                "asset_id": record.get("id"),
                "source_asset_id": source_asset_id,
                "node_id": node_id,
                "mode": meta.get("mode"),
                "model": meta.get("model"),
                "remove_background": bool(remove_background),
                "provenance": record.get("provenance"),
                "source": record.get("source"),
                "placement": place_result.get("placement"),
                **_image_receipt_fields(record),
            },
            "diagnostics": [d.model_dump(mode="json") for d in diags],
        }
        self.record(
            "coordinator",
            "image_edited",
            input_summary=f"{node_id}: {prompt[:160]}",
            output_summary=(
                f"edited image {source_asset_id} -> {record.get('id')} "
                f"(mode={meta.get('mode')}, model={meta.get('model')}) re-placed into {node_id}"
            ),
            diagnostics=[d.model_dump(mode="json") for d in diags],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def scene_has_generated_imagery(self) -> bool:
        """Whether the current scene places any generated or edited raster asset —
        the gate for whether the imagery verifier / mid-loop vision check is worth
        running (a design that placed only library images or none needs no check)."""
        assets = self.scene.get("assets") or {}
        nodes = self.scene.get("nodes") or {}
        for node in nodes.values():
            asset_id = (node.get("kind") or {}).get("asset_id")
            if not asset_id:
                continue
            if has_generated_image_origin(assets.get(asset_id) or {}):
                return True
        return False

    def verify_imagery(
        self,
        expected_decision: Optional[str] = None,
        role: Optional[str] = None,
        risks: Optional[List[str]] = None,
        png_path: Optional[str] = None,
    ) -> str:
        """Verify the current scene's use of imagery (Phase 3c gate). Always runs the
        DETERMINISTIC imagery checks (`imagery_checks.score_scene`); runs the
        `judge_imagery` VISION call in addition ONLY when an agent API key is
        configured (the judge reads its credentials from config, providers pattern) and
        a rendered PNG is available. Returns a compact verdict: per-axis finals, the
        hard-gate failures, accept/tier, and one line of guidance — small enough to
        append to a coordinator handoff or feed the imagery-repair path."""
        from ..imagery_checks import score_scene
        from ..imagery_judge import HARD_GATE_AXES, judge_imagery

        brief: JsonObject = {
            "id": self.run_id,
            "expected_decision": expected_decision,
            "role": role,
            "risks": risks or [],
        }
        # Resolve the rendered PNG (for the vision call) from the latest preview when
        # not passed explicitly. The judge only looks at it when it runs.
        resolved_png = png_path
        if resolved_png is None:
            latest = self.latest_preview_bundle or self.latest_export_summary or {}
            for artifact in (latest.get("artifacts") or []):
                if artifact.get("format") == "png" and artifact.get("path"):
                    resolved_png = artifact.get("path")
                    break

        has_key = bool(getattr(self.config, "agent_api_key", None))
        if has_key:
            # Full DET + JUDGE (vision) combine — judge_imagery builds the model from
            # config when no model is injected.
            result = judge_imagery(self.scene, resolved_png, brief, config=self.config)
        else:
            # DET-only: no key → never make a paid vision call.
            det = score_scene(self.scene, expected_decision=expected_decision)
            from ..imagery_judge import combine

            result = combine(det, None, brief)
            result["brief_id"] = brief["id"]
            result["expected_decision"] = expected_decision
            result["det"] = det

        per_axis = result.get("per_axis") or {}
        hard_gate_failures = sorted(
            axis
            for axis, info in per_axis.items()
            if axis in HARD_GATE_AXES and info.get("final") is not None and info["final"] <= 1
        )
        guidance = self._imagery_verdict_guidance(result, hard_gate_failures)
        verdict = {
            "status": "ok",
            "judge_ran": bool(result.get("judge_ran")),
            "accept": bool(result.get("accept")),
            "tier": result.get("tier"),
            "weighted_mean": result.get("weighted_mean"),
            "gate_failed": bool(result.get("gate_failed")),
            "hard_gate_failures": hard_gate_failures,
            "per_axis": {axis: info.get("final") for axis, info in per_axis.items()},
            "image_count": result.get("image_count", 0),
            "guidance": guidance,
        }
        self.record(
            "coordinator",
            "imagery_verified",
            output_summary=(
                f"imagery verdict tier={verdict['tier']} accept={verdict['accept']} "
                f"judge_ran={verdict['judge_ran']} hard_gate={hard_gate_failures}"
            ),
            payload=verdict,
        )
        return json.dumps(verdict, indent=2)

    @staticmethod
    def _imagery_verdict_guidance(result: JsonObject, hard_gate_failures: list) -> str:
        """One-line, actionable guidance from an imagery verdict."""
        if hard_gate_failures:
            return (
                "Hard imagery gate failed on "
                + ", ".join(hard_gate_failures)
                + " — repair the image (recolor/edit, re-scrim, or regenerate) before shipping."
            )
        if result.get("accept"):
            return "Imagery clears the gate; ship."
        if result.get("tier") == "tweak":
            return "Imagery ships with a minor tweak — nudge the weakest axis."
        return "Imagery below the ship bar; edit or regenerate the flawed image."

    def _tool_error(self, code: str, message: str, **extra: Any) -> str:
        """Uniform error envelope for the dispatcher tools (asset/inspect)."""
        payload: JsonObject = {"status": "error", "error_code": code, "message": message}
        payload.update(extra)
        return json.dumps(payload, indent=2)

    def _refuse_without_page(self, tool: str) -> Optional[str]:
        """The pre-spend page guard: a JSON refusal when the scene has no page, else None.

        Checked at the TOP of generate_image / generate_qr / fetch_logo, before any provider,
        core or vendor call. The engine would refuse the registration anyway (LUMV0100); this
        moves that answer in front of the spend, so a misordered author loses one tool call
        and nothing else. The hint names the fix in the author's own vocabulary.
        """
        if self.scene.get("pages"):
            return None
        payload: JsonObject = {
            "status": "error",
            "error_code": PAGE_REQUIRED_CODE,
            "message": (
                f"{tool} refused: the scene has no page/artboard yet, so nothing can be "
                "registered in it."
            ),
            "hint": (
                "Author the page first — compile_dsl_block with a `page <id> size(...)` line, "
                f"the whole design in one block — then call {tool} again."
            ),
        }
        self.record(
            "coordinator",
            f"{tool}_refused_pageless",
            output_summary=payload["message"],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    @_tool_span
    def asset(
        self,
        action: str,
        prompt: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        brand_notes: Optional[List[str]] = None,
        transparent_background: bool = False,
        target_node_id: Optional[str] = None,
        target_slot_id: Optional[str] = None,
        data: Optional[str] = None,
        ec_level: Optional[str] = None,
        print_media: bool = False,
        target_width_mm: Optional[float] = None,
        node_id: Optional[str] = None,
        slot_id: Optional[str] = None,
        asset_id: Optional[str] = None,
        # None = per-action default: cover for place (imagery fills frames),
        # contain for use_brand_asset (a cropped logo is a brand failure).
        # An explicit value always wins.
        fit: Optional[str] = None,
        focal_x: float = 0.5,
        focal_y: float = 0.5,
        alt: Optional[str] = None,
        preserve_transparency: Optional[bool] = None,
        label: Optional[str] = None,
        reference_asset_ids: list[str] | None = None,
        reference_roles: list[str] | None = None,
        reference_framing: str | None = None,
        operation: str | None = None,
        # Preserve raw element types through tool validation; crop_source_pixels
        # refuses bools/floats instead of Pydantic coercing them to integers.
        crop_rect: list[Any] | None = None,
        frame_index: StrictInt | None = None,
    ) -> str:
        """Generate or place a design asset. Pick `action`:

        - `action="generate_image"` — generate a raster image from `prompt` and
          register it (returns its asset_id; NOT auto-placed). Pass `target_node_id`
          (or `target_slot_id`) so the aspect is derived from that frame's geometry —
          images are cropped to fill, never stretched. Optional `aspect_ratio` /
          `width` / `height`, `brand_notes`, `transparent_background`, `label`.
          `brand_notes` and `reference_framing` are appended to the prompt the image
          model receives; they follow the same rules as the prompt
          (`/.deepagent/skills/generative-imagery/SKILL.md`).
          `reference_asset_ids` selects up to four inspected style inputs by ID
          from this run's attachments, brand kit, workspace library or scene.
          Omit it to use turn attachments; [] uses no references. A selection
          replaces automatic attachments. Source pixels and their digest are
          verified before spending; unavailable selections return an error.
          Optional reference_roles align with selected IDs: source, treatment,
          composition. reference_framing states what to preserve/vary; operation
          records intent such as close_companion. These participate in caching.
          Successful model/cache results report exact `reference_inputs` and
          persisted provider `image_request_receipt` when available.
          Viewing an asset alone does not attach it. Keep exact UI and logos as
          separate source layers; this action produces a new raster component.
        - `action="edit_image"` — edit the image already placed in `node_id` with a
          text `prompt` (recolor / warmth / background / fix a flawed subject) WITHOUT
          changing the composition; the edited result re-enters the same node with its
          current placement preserved. Set `transparent_background=True` to remove the
          background. Prefer this over a full regenerate when the image is right-but-flawed.
          This source-only route does not accept reference_asset_ids, reference_roles
          or reference_framing. For selected-reference changes, generate_image with
          those inputs, inspect the result and place it explicitly.
        - `action="crop_image"` — extract an exact rectangle from an inspected
          original raster `asset_id`, without a model or resampling. `crop_rect`
          is four integers [left, top, right, bottom] in ORIGINAL source pixels,
          half-open; right/bottom excluded. Use original dimensions, not preview
          dimensions. Bounds must be nonempty and inside the source. Nonidentity
          EXIF orientation and unsupported images are refused. Animated cropping
          requires an explicit nonnegative integer `frame_index` (GIF only); use
          view(target="asset:<id>", frame_index=...) to inspect that original
          frame first. Coordinates are its decoded composited full-frame pixels,
          not a thumbnail or smaller GIF patch. Omitting the index refuses animation.
          Preserves decoded pixels/alpha and original asset; returns a separate image asset
          and crop_receipt with source digest/rect. Inspect, then explicitly place
          it in an independent image node. Cannot recover occluded or absent UI,
          nor remove backgrounds baked inside the selected rectangle.
        - `action="generate_qr"` — generate a deterministic QR asset from `data`
          (URL/text). For physical artifacts set `print_media=True` and `target_width_mm`
          so print-scannability diagnostics can fire. Optional `ec_level`, `label`.
        - `action="place"` — place an existing asset (`asset_id`: one you generated
          this run, or one from this workspace's asset library — a library asset is
          registered into the scene for you)
          into an existing image or intentionally reserved empty leaf `fr`
          (`node_id`), or a bound image slot (`slot_id`). Raster/logo placement
          converts the leaf to an image in place, preserving its ID and geometry;
          path-backed vectors stay native. Containers with children cannot be
          consumed; missing node/asset IDs remain errors. No assetless image
          declaration is needed. Use `fit` (default cover), normalized focal point
          (`focal_x`/`focal_y`, 0..1, default centered), `alt` text, and optional
          `preserve_transparency`. Reversible.
        - `action="use_brand_asset"` — register one of the attached Brand Kit's assets
          (a logo variant or brand image; `asset_id` from the brand context card's
          inventory) into the scene with brand_guide provenance and place it into
          the same supported `node_id` target or `slot_id` as `place`.
          Logos place with fit `contain` (never cropped);
          pick the variant by background (reversed on dark fields). Requires an
          attached kit — without one this action errors.

        Every action mutates the scene only through the canonical core operation path."""
        if frame_index is not None and action != "crop_image":
            return self._tool_error(
                "asset.frame_unsupported_action",
                "frame_index is only supported by action='crop_image'.",
            )
        if action == "generate_image":
            if not prompt:
                return self._tool_error(
                    "asset.bad_request", "action='generate_image' requires `prompt`."
                )
            return self.generate_image(
                prompt,
                target_node_id,
                target_slot_id,
                aspect_ratio,
                width,
                height,
                brand_notes,
                transparent_background,
                label,
                reference_asset_ids=reference_asset_ids,
                reference_roles=reference_roles,
                reference_framing=reference_framing,
                operation=operation,
            )
        if action == "edit_image":
            if (
                reference_asset_ids is not None
                or reference_roles is not None
                or reference_framing is not None
            ):
                return self._tool_error(
                    "asset.bad_request",
                    "edit_image uses only the placed source; reference_asset_ids/roles/framing "
                    "require generate_image followed by explicit placement.",
                )
            if not node_id:
                return self._tool_error(
                    "asset.bad_request", "action='edit_image' requires `node_id`."
                )
            if not prompt:
                return self._tool_error(
                    "asset.bad_request", "action='edit_image' requires `prompt`."
                )
            return self.edit_image(
                node_id, prompt, transparent_background, label, operation=operation
            )
        if action == "crop_image":
            if not asset_id:
                return self._tool_error("asset.bad_request", "action='crop_image' requires `asset_id`.")
            return self.crop_image(asset_id, crop_rect, label, frame_index=frame_index)
        if action == "generate_qr":
            if not data:
                return self._tool_error(
                    "asset.bad_request", "action='generate_qr' requires `data`."
                )
            return self.generate_qr(data, ec_level, print_media, target_width_mm, label)
        if action == "place":
            if not asset_id:
                return self._tool_error(
                    "asset.bad_request", "action='place' requires `asset_id`."
                )
            # Preserve the two distinct core op kinds: node_id -> place_asset_in_node,
            # slot_id -> place_asset_in_slot. The agent-facing tool merges to one; the
            # core operation `kind` must NOT, or the slot-binding path breaks.
            if node_id is not None:
                return self.place_asset_in_node(
                    node_id,
                    asset_id,
                    fit or "cover",
                    focal_x,
                    focal_y,
                    alt,
                    preserve_transparency,
                )
            if slot_id is not None:
                return self.place_asset_in_slot(
                    slot_id,
                    asset_id,
                    fit or "cover",
                    focal_x,
                    focal_y,
                    alt,
                    preserve_transparency,
                )
            return self._tool_error(
                "asset.bad_request",
                "action='place' requires `node_id` or `slot_id`.",
            )
        if action == "use_brand_asset":
            if not asset_id:
                return self._tool_error(
                    "asset.bad_request",
                    "action='use_brand_asset' requires `asset_id` (from the brand "
                    "context card's logo/image inventory).",
                )
            return self.use_brand_asset(
                asset_id,
                node_id,
                slot_id,
                fit or "contain",
                focal_x,
                focal_y,
                alt,
            )
        return self._tool_error(
            "asset.unknown_action",
            f"unknown action '{action}'.",
            valid_actions=[
                "generate_image",
                "edit_image",
                "crop_image",
                "generate_qr",
                "place",
                "use_brand_asset",
            ],
        )

    def _finalized_snapshot_for(self, binding: JsonObject) -> JsonObject:
        """Instances derive from finalized revisions; for agent previews the
        working scene is treated as a snapshot of the binding's revision."""
        snapshot = copy.deepcopy(self.scene)
        status = (snapshot.get("meta") or {}).get("status") or {}
        if status.get("kind") != "finalized":
            snapshot.setdefault("meta", {})["status"] = {
                "kind": "finalized",
                "template_revision_id": binding.get(
                    "template_revision_id", "tmpl_preview"
                ),
            }
        return snapshot

    @_tool_span
    def validate_binding_set(self, binding_set_json: str) -> str:
        """Validate a Phase G binding set (per-recipient values, links, and
        generated QR entries) against the current scene's slot contracts:
        keys resolve, kinds match content types, required slots covered,
        cardinality and max_length hold, the frozen conditional grammar
        parses, and generated entries chain links.*.url -> qr -> UrlQr
        slot. Returns precise LUMG diagnostics for every violation."""
        binding = parse_json_object(binding_set_json)
        if binding is None:
            payload = {
                "binding_validation": {
                    "status": "error",
                    "message": "binding_set_json is not a JSON object",
                }
            }
            return json.dumps(payload, indent=2)

        snapshot = self._finalized_snapshot_for(binding)
        try:
            response = self.core.validate_binding_set(snapshot, binding)
        except CoreError as error:
            payload = {
                "binding_validation": {
                    "status": "error",
                    "error_code": error.code,
                    "message": error.message,
                }
            }
            self.record(
                "coordinator",
                "binding_validation_failed",
                output_summary=error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        diagnostics = diagnostics_from(response.get("diagnostics", []))
        valid = bool(response.get("ok", False))
        payload = {
            "binding_validation": {
                "status": "valid" if valid else "invalid",
                "binding_set_id": binding.get("binding_set_id"),
                "template_revision_id": binding.get("template_revision_id"),
            },
            "diagnostics": [diag.model_dump(mode="json") for diag in diagnostics],
        }
        self.record(
            "coordinator",
            "binding_set_validated",
            input_summary=binding_set_json[:300],
            output_summary=(
                f"binding set {binding.get('binding_set_id')} is "
                f"{'valid' if valid else 'invalid'}"
            ),
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def derive_instance_preview(
        self, binding_set_json: str, export_format: str = "png"
    ) -> str:
        """Derive a personalized instance from the current scene plus a
        binding set (text/asset application, conditionals, repeater
        expansion, generated QR), render a preview artifact for visual
        critique, and report the instance fit verdicts. The working scene
        is never mutated: instances are derived artifacts."""
        binding = parse_json_object(binding_set_json)
        if binding is None:
            return json.dumps(
                {
                    "instance_preview": {
                        "status": "error",
                        "message": "binding_set_json is not a JSON object",
                    }
                },
                indent=2,
            )

        snapshot = self._finalized_snapshot_for(binding)
        store_root = str(self.config.effective_asset_store_root)
        export_format = export_format if export_format in {"svg", "png", "pdf"} else "png"
        try:
            response = self.core.derive_instance(
                snapshot,
                binding,
                asset_records=[],
                store_root=store_root,
                export_formats=[export_format],
                export_dpi=96,
                brand_fonts=self.config.brand_fonts,
            )
        except CoreError as error:
            payload = {
                "instance_preview": {
                    "status": "error",
                    "error_code": error.code,
                    "message": error.message,
                }
            }
            self.record(
                "coordinator",
                "instance_preview_failed",
                output_summary=error.message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        diagnostics = diagnostics_from(response.get("diagnostics", []))
        instance = response.get("instance") or {}
        fit_report = instance.get("fit_report") or {}
        preview_paths: list[str] = []
        if response.get("ok", False):
            for artifact in instance.get("artifacts", []):
                relative = artifact.get("relative_path")
                if not relative:
                    continue
                source = Path(store_root) / relative
                if not source.exists():
                    continue
                suffix = artifact.get("format", export_format)
                destination = self.turn_dir / (
                    f"instance_{binding.get('binding_set_id', 'preview')}"
                    f"_{len(preview_paths)}.{suffix}"
                )
                destination.write_bytes(source.read_bytes())
                preview_paths.append(str(destination))
            self.preview_paths.extend(preview_paths)

        payload = {
            "instance_preview": {
                "status": "ok" if response.get("ok", False) else "error",
                "binding_set_id": binding.get("binding_set_id"),
                "has_errors": instance.get("has_errors"),
                "fit_status": fit_report.get("status"),
                "fit_slots": fit_report.get("slots", []),
                "repair_requests": instance.get("repair_requests", []),
                "audit_entries": len(instance.get("audit", [])),
                "preview_paths": preview_paths,
            },
            "diagnostics": [diag.model_dump(mode="json") for diag in diagnostics],
        }
        self.record(
            "critic",
            "instance_preview_derived",
            input_summary=binding_set_json[:300],
            output_summary=(
                f"instance for {binding.get('binding_set_id')}: "
                f"fit={fit_report.get('status')}, "
                f"{len(preview_paths)} preview artifact(s)"
            ),
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    @_tool_span
    @_scene_mutation
    def preflight_design(self) -> str:
        """Check the scene against the brand kit in effect (the document's attached kit, or the platform
        default): brand tokens, rules and layout. Returns the diagnostics to fix.
        """
        iteration_dir = self._iteration_dir()
        self._preflight_scene_stamp = None
        self._preflight_iteration = self.iteration
        self._latest_preflight_diagnostics = None
        try:
            # K2 belt: catch kit-asset references that arrived via structured
            # edits / raw operations (compile has its own reconcile pass).
            self._register_referenced_brand_assets("preflight_design")
            source, brand_kit, notice = self._effective_brand_kit()
            brand_context = self._brand_context(source, brand_kit)
            if notice:
                brand_context["notice"] = notice
            # K4 retokenization: on the agent's OWN (unseeded) draft, bind
            # every raw literal that equals a kit token before preflight —
            # deterministic data mapping, applied as real validated ops that
            # ride the ledger through Accept. Seeded scenes are skipped: a
            # human's literals are never rebound (resolution-once). LLM
            # repair measurably cannot do this (run_bff3433f); this pass can.
            if (
                brand_kit is not None
                and source not in (None, "platform_default")
                and not self.seeded_from_initial_scene
            ):
                retokenize_ops = build_retokenize_operations(self.scene, brand_kit)
                if retokenize_ops:
                    try:
                        rt_response = self.core.apply_operations(
                            self.scene, retokenize_ops
                        )
                        self._replace_scene_from_core_response(
                            rt_response, "retokenize_brand", operations=retokenize_ops
                        )
                        self.record(
                            "coordinator",
                            "brand_retokenized",
                            output_summary=(
                                f"{len(retokenize_ops)} node(s) rebound to kit tokens"
                            ),
                            payload={"operation_count": len(retokenize_ops)},
                        )
                    except CoreError:
                        # A rejected rebind never blocks the turn; preflight
                        # proceeds on the unmodified scene.
                        pass
                # Candidate identity is authored composition: a target-only or
                # deliberately unbranded scene must not acquire a hidden overlay.
                # Legacy keeps PLACE-ONCE / respect-removal: after either an
                # authored or automatic kit logo has existed, never re-inject it.
                if self.config.scene_skill_bundle != "candidate":
                    if scene_has_kit_logo(self.scene, brand_kit):
                        self._brand_logo_seen = True
                    elif not self._brand_logo_seen:
                        placement_ops = build_logo_placement_operations(
                            self.scene, brand_kit
                        )
                        if placement_ops:
                            try:
                                placed = self.core.apply_operations(
                                    self.scene, placement_ops
                                )
                                self._replace_scene_from_core_response(
                                    placed, "place_brand_logo", operations=placement_ops
                                )
                                self._brand_logo_seen = True
                                self.record(
                                    "coordinator",
                                    "brand_logo_placed",
                                    output_summary="kit mark auto-placed (page overlay)",
                                    payload={"operation_count": len(placement_ops)},
                                )
                            except CoreError:
                                pass
            # K4: brand governance judges the AUTHORED scene — resolution
            # deliberately CONSUMES token bindings (resolution-once: the
            # resolved scene is fully literal, style_token = None), so any
            # post-preflight governance pass reports LUMB0805/0804/0806 no
            # matter how well the draft was authored (that artifact wasted
            # three live proof rounds). Advisory: steers author + reviewer,
            # never fails the turn. Platform-default runs stay ungoverned.
            governance_diagnostics = []
            if brand_kit is not None and source not in (None, "platform_default"):
                try:
                    governance = self.core.validate_scene_brand_governance(
                        self.scene, brand_kit, strictness="advisory", raise_on_error=False
                    )
                    governance_diagnostics = diagnostics_from(
                        governance.get("diagnostics", [])
                    )
                except CoreError:
                    governance_diagnostics = []
            # The authored (pre-resolution) scene is the ONLY state where
            # bindings are observable — snapshot it for the fidelity eval.
            self._write_json(
                iteration_dir / "authored_scene.json", {"scene": self.scene}
            )
            response = self.core.preflight_scene(
                self.scene, brand_kit, brand_fonts=self.config.brand_fonts
            )
        except CoreError as error:
            summary = PreflightSummary(
                status=ToolStatus.error,
                has_errors=True,
                diagnostics=diagnostics_from(error.diagnostics),
            )
            payload = {"preflight": _dump(summary)}
            self.latest_preflight_has_errors = True
            self._write_json(iteration_dir / "preflight.json", payload)
            self.record(
                "coordinator",
                "preflight_failed",
                output_summary=error.message,
                diagnostics=[diag.model_dump(mode="json") for diag in summary.diagnostics],
                payload=payload,
            )
            return self._preflight_model_result(payload, iteration_dir)

        self._replace_scene_from_core_response(response, "preflight_design")
        raw_diagnostics = list(response.get("diagnostics", []) or [])
        preflight = response.get("preflight", {})

        # §5.4: the deterministic autofix loop runs HERE — after the engine has
        # spoken and before the author is told anything. Everything below this
        # block therefore reports the POST-autofix world, which is the whole
        # point: the author never spends a model call on a repair whose value
        # the engine already implied.
        autofix_result = self._run_autofix(raw_diagnostics, brand_kit, iteration_dir)
        if autofix_result is not None and autofix_result.changed:
            raw_diagnostics = list(autofix_result.diagnostics)
            # `has_errors` must never be inferred from a MISSING summary — an
            # empty block would read as "clean" and could let a blocking export
            # error through the P0.3 finalize guard. Fall back to the same rule
            # the engine uses (preflight.rs:219, `any severity == error`).
            preflight = autofix_result.raw_preflight or {
                "has_errors": any(d.get("severity") == "error" for d in raw_diagnostics)
            }

        diagnostics = diagnostics_from(raw_diagnostics)
        if governance_diagnostics:
            # Deliberately NOT recomputed after autofix: governance judges the
            # AUTHORED (pre-resolution) scene, the only state where bindings are
            # observable, while autofix operates on the resolved one. Re-running
            # it here would report LUMB0805/0804/0806 on a fully-literal scene no
            # matter how well the draft was authored — the exact artifact the K4
            # comment above exists to avoid. It is advisory either way.
            diagnostics = diagnostics + governance_diagnostics
        # P0.3: keep the RAW engine diagnostics (code + severity as the engine
        # spelled them) for the finalize guard — `diagnostics_from` normalizes
        # into the runtime's own wider enum, and the export classification is
        # defined against the engine's vocabulary.
        self._latest_preflight_diagnostics = raw_diagnostics
        brand_context = self._brand_context_from_scene_ref(brand_context)
        self.effective_brand_context = brand_context
        summary = PreflightSummary(
            status=ToolStatus.ok,
            has_errors=bool(preflight.get("has_errors")),
            diagnostics=diagnostics,
            brand_source=brand_context.get("source"),
            brand_kit_id=brand_context.get("brand_kit_id"),
            brand_kit_version=brand_context.get("brand_kit_version"),
            brand_mode=brand_context.get("mode"),
        )
        payload = {
            "preflight": _dump(summary),
            "raw_preflight": preflight,
            "effective_brand": brand_context,
        }
        output_summary = f"has_errors={summary.has_errors}; {len(diagnostics)} diagnostics"
        if autofix_result is not None and autofix_result.attempted:
            # The autofix block rides the SAME payload the author reads, next to
            # the diagnostics it changed — spec §5.4's "recorded in the round's
            # diagnostics so the agent (and the trace) knows what moved". The
            # rolled-back entries matter as much as the applied ones: they tell
            # the author the mechanical repair was already tried and refused.
            payload["autofix"] = autofix_result.as_payload()
            output_summary = f"{output_summary}; {autofix_result.summary_line()}"
        # Text-collision advisory (fast-loop tuning 2026-08-24). Flag-gated, so a
        # flag-off preflight payload stays byte-identical. It rides preflight
        # rather than render because the author reads preflight at work-loop
        # step 3, one step BEFORE its first render — which is the earliest moment
        # the finding can change what it does. Advisory only: it never sets
        # has_errors and never edits the scene. See lumen_agent/text_clearance.py
        # for why the engine itself cannot report this class.
        if self.config.fast_loop:
            try:
                advisory = collision_advisory(self.scene)
            except Exception:  # noqa: BLE001 - an advisory never fails a preflight
                _SUBSTRATE_LOG.warning("text_collision_advisory_failed")
                advisory = None
            if advisory:
                payload["text_collisions"] = advisory
                output_summary = f"{output_summary}; text collisions advised"
        self.latest_preflight_has_errors = bool(summary.has_errors)
        self._preflight_scene_stamp = self._scene_stamp()
        self._write_json(iteration_dir / "preflight.json", payload)
        self.record(
            "coordinator",
            "preflight_completed",
            output_summary=output_summary,
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return self._preflight_model_result(payload, iteration_dir)

    def _preflight_model_result(self, payload: JsonObject, iteration_dir: Path) -> str:
        """Keep the full saved/trace report; shorten only candidate model delivery."""
        if self.config.scene_skill_bundle == "candidate":
            payload = {
                **payload,
                "full_report_path": to_virtual(iteration_dir / "preflight.json", self.config),
            }
            if "raw_preflight" in payload:
                raw = dict(payload["raw_preflight"])
                counts = {}
                for key in ("token_operations", "layout_operations"):
                    if isinstance(raw.get(key), list):
                        counts[key] = len(raw.pop(key))
                if counts:
                    raw["operation_counts"] = counts
                payload["raw_preflight"] = raw
        return json.dumps(payload, indent=2)

    @_scene_mutation
    def _run_autofix(
        self,
        raw_diagnostics: list[JsonObject],
        brand_kit: Optional[JsonObject],
        iteration_dir: Path,
    ) -> Optional[AutofixResult]:
        """Drive the §5.4 code loop against the engine. Never raises.

        Flag-gated to the point of invisibility: with `LUMEN_AGENT_FAST_LOOP`
        down, `config.autofix_passes` is 0 and this returns `None` before making
        a single call or touching a single field, so `preflight_design` is
        byte-identical to the pre-fast-loop version.

        The two engine callables are injected rather than reached for, so
        `autofix.run_autofix` stays a pure, helper-free unit. `apply_operations`
        deliberately does NOT go through `self.apply_operations` (the agent tool)
        — a speculative patch must not mutate the working scene, log to the
        ledger, or emit a trace event before the engine has verified it. Only an
        ACCEPTED patch is committed, below.
        """
        if self.config.autofix_passes <= 0:
            return None

        preflight_blocks: list[tuple[JsonObject, JsonObject]] = []

        def _apply(scene: JsonObject, operations: list[JsonObject]) -> JsonObject:
            applied = self.core.apply_operations(scene, operations)
            return applied.get("scene")

        def _preflight(scene: JsonObject) -> tuple[JsonObject, list[JsonObject]]:
            checked = self.core.preflight_scene(
                scene, brand_kit, brand_fonts=self.config.brand_fonts
            )
            verified_scene = checked.get("scene")
            preflight_blocks.append((verified_scene, checked.get("preflight") or {}))
            return verified_scene, list(checked.get("diagnostics", []) or [])

        try:
            result = run_autofix(
                self.scene,
                raw_diagnostics,
                apply_operations=_apply,
                preflight=_preflight,
                max_passes=self.config.autofix_passes,
                on_attempt=lambda record: self.metrics.record_autofix(
                    record.klass, accepted=record.accepted
                ),
            )
        except Exception as error:  # noqa: BLE001 - autofix must never fail a turn
            self.record(
                "coordinator",
                "autofix_failed",
                output_summary=f"{type(error).__name__}: {error}",
            )
            return None

        if not result.attempted:
            return None

        if result.changed:
            # Commit: the working scene becomes the verified one, and the
            # accepted operations join the ledger. The ledger is not optional —
            # the editor's Accept replays THAT list onto the document and never
            # sees this scene, so an unlogged autofix would silently vanish at
            # accept (the K2 defect `_log_scene_operations` exists to prevent).
            self._begin_solo_construction()
            self.scene = result.scene
            self.scene_update_sources.append("autofix")
            self._log_scene_operations(
                "autofix",
                [
                    dict(operation)
                    for record in result.applied
                    for operation in record.operations_json
                ],
            )
            # Identity match, not "the last one": a rejected attempt after the
            # accepted one would otherwise hand back the losing scene's summary.
            result.raw_preflight = next(
                (block for scene, block in preflight_blocks if scene is result.scene),
                {},
            )

        payload = result.as_payload()
        self._write_json(iteration_dir / "autofix.json", payload)
        self.record(
            "coordinator",
            "autofix_completed",
            output_summary=result.summary_line(),
            payload=payload,
        )
        return result

    def baseline_preflight_diagnostics(self) -> list[JsonObject]:
        """Preflight diagnostics on the scene AS SEEDED, before this turn's own
        edits. (Agent-improvement follow-up 1, the frozen-doc turn wedge.)

        A live turn can seed from a document that already carries legacy
        errors — e.g. LUMV0810 slot-fixture overflow on frozen/pinned text
        that predates this edit entirely. Without a baseline, the Phase A
        repair loop cannot tell "the turn broke this" from "this was already
        broken," and burns its whole iteration budget re-fixing errors that
        were never in scope (run_4a0feb15048e4fbe993029bd2cab436f: two
        pre-existing LUMV0810s ate all 3 iterations while the user's actual
        positional ask never landed).

        Memoized and UNTRACED on purpose: this runs once, before iteration 1,
        against the seeded scene only (a fresh/unseeded scene has nothing to
        baseline against). It must not consume an iteration slot, must not
        bump `self.iteration`, and must not write into `iterations/NNN/` —
        those are reserved for this turn's own authoring attempts. It reuses
        the same core preflight call and `diagnostics_from` normalizer as
        `preflight_design` so the diagnostic shape (and therefore the
        `(code, subject)` keys the loop diffs against) is identical."""
        if self._baseline_diagnostics is not None:
            return self._baseline_diagnostics
        if not self.seeded_from_initial_scene:
            self._baseline_diagnostics = []
            return self._baseline_diagnostics
        try:
            # Same kit precedence as preflight_design — a baseline captured
            # against a different kit than the turn's own preflights would
            # make the (code, subject) diff misattribute brand diagnostics.
            _, brand_kit, _ = self._effective_brand_kit()
            response = self.core.preflight_scene(
                self.scene, brand_kit, brand_fonts=self.config.brand_fonts
            )
        except CoreError:
            # A baseline that cannot be computed is treated as empty — the
            # repair loop falls back to today's un-scoped behavior rather
            # than blocking the turn on a baseline-capture failure.
            self._baseline_diagnostics = []
            return self._baseline_diagnostics
        diagnostics = [
            diag.model_dump(mode="json")
            for diag in diagnostics_from(response.get("diagnostics", []))
        ]
        self._baseline_diagnostics = diagnostics
        self._write_json(
            self.turn_dir / "baseline_preflight.json",
            {"baseline_diagnostics": diagnostics},
        )
        self.record(
            "coordinator",
            "baseline_preflight_captured",
            output_summary=(
                f"{len(diagnostics)} pre-existing diagnostic(s) on the seeded scene"
            ),
            diagnostics=diagnostics,
            payload={"baseline_diagnostics": diagnostics},
        )
        return diagnostics

    def _unresolved_token_paint_refusal(self, requested_format: str) -> Optional[str]:
        """Loud refusal (mirrors the view('preview') staleness contract): if the
        working scene still carries token PAINTS, rendering now would paint the
        engine's magenta LUME0213 sentinel. Token resolution happens canonically
        in `preflight_design` (its ordered side effects — retokenize on the
        authored scene, the `authored_scene.json` snapshot the fidelity eval
        reads, governance — must not be skipped), so we REFUSE here instead of
        auto-resolving. Returns the error-payload JSON string to hand back to the
        model, or None when every paint is already resolved.
        """
        refs = _unresolved_paint_refs(self.scene)
        if not refs:
            return None
        named = "; ".join(f"{owner} -> ${token}" for owner, token in refs[:6])
        more = "" if len(refs) <= 6 else f" (+{len(refs) - 6} more)"
        message = (
            f"Export refused: {len(refs)} unresolved token paint(s) remain — "
            f"rendering now would paint the magenta LUME0213 sentinel. Offending "
            f"(node, token): {named}{more}. Run preflight_design first (resolution "
            f"happens there), then re-render."
        )
        self.latest_export_summary = None
        self.latest_preview_bundle = None
        summary = ExportSummary(
            status=ToolStatus.error,
            requested_format=requested_format,
            validation_errors=[message],
        )
        payload = {"export": _dump(summary)}
        self._write_json(self._iteration_dir() / "export.json", payload)
        self.record(
            "coordinator",
            "export_refused_unresolved_tokens",
            output_summary=message,
            payload={
                "requested_format": requested_format,
                "unresolved_paint_refs": [
                    {"owner": owner, "token": token} for owner, token in refs
                ],
            },
        )
        return json.dumps(payload, indent=2)

    @_scene_mutation
    def export_preview(self, export_format: Optional[str] = None) -> str:
        """Export and validate an SVG or PNG preview for visual critique.

        Requires `preflight_design` after any scene mutation — export refuses
        unresolved token paints (which would otherwise render the LUME0213
        magenta sentinel)."""
        preview_format = (export_format or self.config.preview_format).lower()
        refusal = self._unresolved_token_paint_refusal(preview_format)
        if refusal is not None:
            return refusal
        iteration_dir = self._iteration_dir()
        try:
            response = self.core.export_preview(
                self.scene,
                preview_format,
                asset_store_root=str(self.config.effective_asset_store_root),
                brand_fonts=self.config.brand_fonts,
            )
        except CoreError as error:
            self.latest_export_summary = None
            self.latest_preview_bundle = None
            summary = ExportSummary(
                status=ToolStatus.error,
                requested_format=preview_format,
                diagnostics=diagnostics_from(error.diagnostics),
                validation_errors=[error.message],
            )
            payload = {"export": _dump(summary)}
            self._write_json(iteration_dir / "export.json", payload)
            self.record(
                "coordinator",
                "export_failed",
                output_summary=error.message,
                diagnostics=[diag.model_dump(mode="json") for diag in summary.diagnostics],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        diagnostics = diagnostics_from(response.get("diagnostics", []))
        artifacts = self._write_and_validate_preview_artifacts(
            response.get("export", {}).get("artifacts", []),
            preview_format,
            iteration_dir,
        )
        validation_errors = [
            error for artifact in artifacts for error in artifact.validation_errors
        ]
        status = ToolStatus.error if validation_errors else ToolStatus.ok
        event = "preview_invalid" if validation_errors else "preview_exported"
        summary = ExportSummary(
            status=status,
            requested_format=preview_format,
            diagnostics=diagnostics,
            artifacts=artifacts,
            validation_errors=validation_errors,
        )
        payload = {"export": _dump(summary)}
        if status == ToolStatus.ok:
            self.latest_export_summary = payload["export"]
            self.latest_preview_bundle = None
            self._stamp_preview_rendered()
        else:
            self.latest_export_summary = None
            self.latest_preview_bundle = None
        self._write_json(iteration_dir / "export.json", payload)
        self.record(
            "coordinator",
            event,
            output_summary=(
                f"exported {len(artifacts)} {preview_format} artifact(s); "
                f"{len(validation_errors)} validation error(s)"
            ),
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    @_scene_mutation
    def export_preview_bundle(
        self,
        critic_format: Optional[str] = None,
        *,
        debug_only: bool = False,
        debug_reason: Optional[str] = None,
    ) -> str:
        """Export canonical SVG plus the configured critic preview artifact.

        SVG remains the canonical preview contract. When the critic format is
        PNG, this stores a raster preview beside the SVG so the reviewer or
        provider adapter can inspect rendered pixels as well as vector source.

        When `debug_only` is true, artifacts are still written to disk, but the
        bundle is intentionally not exposed as a valid critic/final preview.
        Use this after preflight errors so humans and agents can inspect the
        broken visual without weakening the acceptance gate.

        Requires `preflight_design` after any scene mutation — the bundle refuses
        unresolved token paints (which would otherwise render the LUME0213
        magenta sentinel) with an honest error before any engine render.
        """
        # L4b: capture the previous valid render's scene-version/iteration BEFORE
        # the inner export_preview calls re-stamp them, so we can tell whether
        # this successful export re-renders byte-identical pixels (no mutation
        # since the last render → re-reviewing yields no new information).
        prev_preview_stamp = self._preview_scene_stamp
        prev_preview_iteration = self._preview_rendered_iteration
        desired_critic_format = (critic_format or self.config.preview_format).lower()
        refusal = self._unresolved_token_paint_refusal(desired_critic_format)
        if refusal is not None:
            export_summary = json.loads(refusal).get("export", {})
            validation_errors = export_summary.get("validation_errors", [])
            bundle = {
                "debug_only": debug_only,
                "debug_reason": debug_reason,
                "canonical": export_summary,
                "critic": export_summary,
                "reviewer": {
                    "status": ToolStatus.error.value,
                    "requested_format": desired_critic_format,
                    "artifacts": [],
                    "validation_errors": validation_errors,
                    "diagnostics": [],
                },
            }
            self.latest_preview_bundle = None
            self.latest_export_summary = None
            self._write_json(self._iteration_dir() / "preview_bundle.json", bundle)
            return json.dumps(bundle, indent=2)
        canonical = json.loads(self.export_preview("svg"))
        critic = canonical
        if desired_critic_format != "svg":
            critic = json.loads(self.export_preview(desired_critic_format))
        canonical_summary = canonical.get("export", canonical)
        critic_summary = critic.get("export", critic)
        bundle_artifacts = combined_preview_artifacts(
            canonical_summary,
            critic_summary,
            desired_critic_format,
        )
        validation_errors = bundle_validation_errors(
            canonical_summary,
            critic_summary,
        )
        if debug_only:
            validation_errors.append(
                debug_reason
                or "debug preview exported from a non-accepted intermediate scene"
            )

        payload = {
            "debug_only": debug_only,
            "debug_reason": debug_reason,
            "canonical": canonical_summary,
            "critic": critic_summary,
            "reviewer": {
                "status": (
                    ToolStatus.error.value
                    if validation_errors
                    else ToolStatus.ok.value
                ),
                "requested_format": desired_critic_format,
                "artifacts": bundle_artifacts,
                "validation_errors": validation_errors,
                "diagnostics": (
                    canonical_summary.get("diagnostics", [])
                    + critic_summary.get("diagnostics", [])
                    if critic_summary is not canonical_summary
                    else canonical_summary.get("diagnostics", [])
                ),
            },
        }
        if not debug_only and payload["reviewer"]["status"] == ToolStatus.ok.value:
            self.latest_preview_bundle = payload["reviewer"]
            self.latest_export_summary = payload["reviewer"]
            self._stamp_preview_rendered()
        elif (
            not debug_only
            and desired_critic_format == "png"
            and checkpoint_acceptance(canonical_summary, critic_summary).accepted
        ):
            # Keep the existing narrow SVG font-embedding exception: the valid
            # PNG is reviewable and exportable. The bundle still reports the
            # canonical SVG refusal above; no other export error is excused.
            self.latest_preview_bundle = critic_summary
            self.latest_export_summary = critic_summary
            self._stamp_preview_rendered()
        else:
            self.latest_preview_bundle = None
            self.latest_export_summary = None
        self._write_json(self._iteration_dir() / "preview_bundle.json", payload)
        self.record(
            "coordinator",
            "debug_preview_exported" if debug_only else "preview_bundle_exported",
            output_summary=(
                (
                    f"exported debug preview after {debug_reason}"
                    if debug_only
                    else (
                        "exported canonical svg"
                        if desired_critic_format == "svg"
                        else f"exported canonical svg and {desired_critic_format} critic preview"
                    )
                )
            ),
            payload={
                "critic_format": desired_critic_format,
                "debug_only": debug_only,
                "debug_reason": debug_reason,
                "canonical_status": payload["canonical"].get("status"),
                "critic_status": payload["critic"].get("status"),
                "reviewer_status": payload["reviewer"].get("status"),
                "reviewer_artifact_formats": [
                    artifact.get("format")
                    for artifact in payload["reviewer"].get("artifacts", [])
                ],
            },
        )
        # L4b unchanged-scene re-review guard (deterministic FACT + teaching, NOT
        # a hard block — a hard refusal would deadlock the RC anti-rubber-stamp
        # guard, which legitimately forces a re-render of the SAME scene). When
        # this valid export re-renders pixels byte-identical to the last one (no
        # scene mutation since), surface the fact so the orchestrator can act on
        # the existing critique instead of burning an author+reviewer round.
        if (
            not debug_only
            and payload["reviewer"]["status"] == ToolStatus.ok.value
            and prev_preview_stamp is not None
            and self._scene_stamp() == prev_preview_stamp
        ):
            render_label = (
                f"the previous render (iteration {prev_preview_iteration})"
                if prev_preview_iteration is not None
                else "the previous render"
            )
            unchanged_note = (
                "unchanged: the scene is identical to the previously rendered "
                f"preview (no mutations since {render_label}); "
                "re-reviewing identical pixels yields no new information."
            )
            payload["unchanged"] = unchanged_note
            self.record(
                "coordinator",
                "unchanged_rerender_recorded",
                output_summary=unchanged_note,
                payload={
                    "previous_render_iteration": prev_preview_iteration,
                    "scene_mutation_count": self._scene_mutation_count(),
                },
            )
        return json.dumps(payload, indent=2)

    def get_latest_preview_for_critique(self, max_svg_chars: int = 40000) -> str:
        """Return the latest validated preview payload WITH the PNG base64 inlined.

        SVG artifacts are returned as text because the model can inspect geometry
        directly. PNG artifacts are returned as base64 so a vision-capable adapter
        can turn them into a real image message. This is the payload the typed
        quality-loop consumes: it strips the base64 from the *text* prompt
        (`compact_preview_payload`) and re-attaches it exactly once as a vision
        block at the model boundary (`preview_image_blocks`), so it never piles up
        in history. Do NOT register this directly as a DeepAgent coordinator tool —
        the coordinator has no vision-block path, so an inlined base64 would sit in
        its message history as dead weight (a single poster PNG's base64 approaches
        the whole model context window). The coordinator uses `get_preview_for_review`.
        """
        return self._latest_preview_payload(include_base64=True, max_svg_chars=max_svg_chars)

    def get_preview_for_review(self, max_svg_chars: int = 20000) -> str:
        """Coordinator-facing preview handoff for the visual-reviewer subagent.

        Returns the rendered SVG geometry (capped) plus, for PNG artifacts, the
        on-disk path and dimensions — NEVER the base64 bytes. In DeepAgent mode the
        reviewer is a text-only subagent (its `task` interface carries a text
        description, and a base64 string inside a tool result is plain text, never
        vision), so it reviews from the SVG geometry and the coordinator's handoff;
        inlining the PNG base64 would only bloat the coordinator's history — a
        987KB poster PNG base64 tokenizes to nearly a whole 1M context window and
        was the cause of the LUMV/context blowup on poster-sized briefs. The
        rendered PNG stays on disk (`png_path`) for the offline imagery judge and
        any filesystem read.

        When the scene places generated/edited imagery, a compact DETERMINISTIC-only
        imagery verdict (`imagery_checks.score_scene`, NO vision call) is appended so
        the coordinator sees any hard-gate failure without a paid judge request.
        """
        payload_json = self._latest_preview_payload(
            include_base64=False, max_svg_chars=max_svg_chars
        )
        if not self.scene_has_generated_imagery():
            return payload_json
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError):
            return payload_json
        if payload.get("status") != ToolStatus.ok.value:
            return payload_json
        from ..imagery_checks import score_scene
        from ..imagery_judge import HARD_GATE_AXES, combine

        det = score_scene(self.scene)
        det_verdict = combine(det, None, {"id": self.run_id})
        per_axis = det_verdict.get("per_axis") or {}
        payload["imagery_verdict"] = {
            "source": "deterministic",
            "gate_failed": bool(det_verdict.get("gate_failed")),
            "tier": det_verdict.get("tier"),
            "hard_gate_failures": sorted(
                axis
                for axis, info in per_axis.items()
                if axis in HARD_GATE_AXES and info.get("final") is not None and info["final"] <= 1
            ),
            "image_count": det.get("image_count", 0),
        }
        return json.dumps(payload, indent=2)

    def _latest_preview_payload(self, *, include_base64: bool, max_svg_chars: int) -> str:
        latest_preview = self.latest_preview_bundle or self.latest_export_summary
        if not latest_preview:
            payload = {
                "status": ToolStatus.error.value,
                "message": "no preview is available; latest preview is invalid or no valid preview has been exported for this run",
            }
            self.record(
                "coordinator",
                "critic_preview_missing",
                output_summary=payload["message"],
                payload=payload,
            )
            return json.dumps(payload, indent=2)
        if latest_preview.get("status") != ToolStatus.ok.value:
            payload = {
                "status": ToolStatus.error.value,
                "message": "latest preview is invalid and cannot be sent to the critic",
                "preview": latest_preview,
            }
            self.record(
                "coordinator",
                "critic_preview_invalid",
                output_summary=payload["message"],
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        artifacts = []
        content_errors: list[str] = []
        for artifact in latest_preview.get("artifacts", []):
            if artifact.get("valid") is False or artifact.get("validation_errors"):
                content_errors.extend(
                    artifact.get("validation_errors")
                    or [f"artifact {artifact.get('format')} is marked invalid"]
                )
                continue
            path_value = artifact.get("path")
            if not path_value:
                content_errors.append(
                    f"artifact {artifact.get('format')} does not include a path"
                )
                continue
            path = Path(path_value)
            if not path.exists():
                content_errors.append(f"artifact path {path} does not exist")
                continue
            item = dict(artifact)
            if artifact.get("format") == "svg":
                text = path.read_text(encoding="utf-8", errors="replace")
                item["svg_text"] = text[:max_svg_chars]
                item["truncated"] = len(text) > max_svg_chars
            elif artifact.get("format") == "png":
                if include_base64:
                    raw = path.read_bytes()
                    item["base64"] = base64.b64encode(raw).decode("ascii")
                    item["encoding"] = "base64"
                else:
                    # Coordinator-facing: keep the on-disk render + dims, drop the
                    # heavy base64 (it is never consumed as vision here and would
                    # dominate the context window). dict(artifact) already carries
                    # path/width/height/byte_len.
                    item["png_path"] = str(path)
                    item["base64_omitted"] = True
                    item["note"] = (
                        "rendered PNG kept on disk; base64 omitted to keep coordinator "
                        "context small — review from svg geometry"
                    )
            else:
                content_errors.append(
                    f"unsupported critic payload format {artifact.get('format')}"
                )
                continue
            artifacts.append(item)

        if content_errors or not artifacts:
            message = (
                "latest preview is invalid and cannot be sent to the critic"
                if content_errors
                else "latest preview has no critic-readable artifacts"
            )
            payload = {
                "status": ToolStatus.error.value,
                "message": message,
                "content_errors": content_errors,
                "preview": latest_preview,
            }
            self.record(
                "coordinator",
                "critic_preview_invalid",
                output_summary=message,
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        payload = {
            "status": ToolStatus.ok.value,
            "run_id": self.run_id,
            "iteration": self.iteration,
            "artifacts": artifacts,
        }
        # Slice 2 D3: attach the SOURCE thumbnails of the kit assets this scene
        # actually placed so the reviewer can verify each placement against its source
        # (right mark/variant, undistorted, legible). Paths only — providers reads the
        # bytes into vision blocks at the boundary. Present only for a kit-attached run
        # whose scene places manifest assets that resolve to real previews.
        placed_previews = self._placed_brand_asset_previews()
        if placed_previews:
            payload["placed_brand_asset_previews"] = placed_previews
        self.record(
            "coordinator",
            "critic_preview_loaded",
            output_summary=f"loaded {len(artifacts)} preview artifact(s) for critique",
            payload={
                "artifact_count": len(artifacts),
                "formats": [artifact.get("format") for artifact in artifacts],
                # D3 observability: how many kit-asset source thumbnails rode
                # along with the reviewer call (0 when the scene placed none).
                # Lets live traces confirm the critic saw source imagery; the
                # payload bytes themselves stay untraced by design.
                "placed_brand_asset_previews": len(placed_previews),
            },
        )
        return json.dumps(payload, indent=2)

    @_scene_mutation
    def submit_visual_critique(self, critique_json: str) -> str:
        """Persist structured reviewer output and fail closed on malformed critique JSON."""
        iteration_dir = self._iteration_dir()
        self._latest_visual_critique = None
        self._review_receipt = None
        self._review_iteration = None
        self._solo_repair_pending = False
        try:
            if self.config.reference_assets or self._selected_reference_ids:
                critique_json = json.dumps(stamp_reference_fidelity(json.loads(critique_json)))
            critique_model = (
                SceneVisualCritique if self.config.scene_skill_bundle == "candidate" else VisualCritique
            )
            critique = critique_model.model_validate_json(critique_json)
            direction_error = self._direction_review_error(critique)
            if direction_error:
                raise ValueError(direction_error)
        except Exception as error:  # pydantic raises provider/version-specific errors.
            raw_payload = parse_json_object(critique_json)
            message = (
                str(raw_payload.get("provider_error"))
                if isinstance(raw_payload, dict) and raw_payload.get("provider_error")
                else str(error)
            )
            payload = {
                "status": ToolStatus.error.value,
                "stop_reason": StopReason.critic_failed.value,
                "message": message,
                "validation_error": str(error),
                "raw": critique_json,
            }
            self._write_json(iteration_dir / "critique.json", payload)
            self.record(
                "visual-reviewer",
                "critique_failed",
                input_summary=critique_json[:500],
                output_summary=str(error),
                payload=payload,
            )
            return json.dumps(payload, indent=2)

        payload = {"status": ToolStatus.ok.value, "critique": critique.model_dump(mode="json")}
        self._latest_visual_critique = payload["critique"]
        self._review_receipt = self._review_receipt_for(self._current_preview_receipt())
        self._review_iteration = self.iteration
        self._solo_repair_pending = self.solo_rounds_executed == 1 and not critique.accepted
        self._write_json(iteration_dir / "critique.json", payload)
        self.record(
            "visual-reviewer",
            "critique_result",
            input_summary=critique_json[:500],
            output_summary=(
                "accepted" if critique.accepted else "rejected: " + critique.summary[:300]
            ),
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    @_scene_mutation
    def observe_written_critique(self, path: Path, content: str) -> str | None:
        """Register the canonical self-review; return rejection to the file tool."""
        workspace = self.trace_dir / "workspace"
        round_number = self._fast_loop_round_number()
        expected = (
            workspace / "rounds" / f"round_{round_number}" / "critique.json"
            if round_number else workspace / "critique.json"
        )
        if path.resolve() != expected.resolve():
            return
        result = json.loads(self.submit_visual_critique(content))
        if result["status"] == ToolStatus.error.value:
            return result["message"]
        return None

    @_scene_mutation
    def validate_creative_direction(self, revision_reason: str = "") -> str:
        """Check this run's creative-direction.json: that it matches its contract, and that the sources it
        names were delivered. It doesn't judge visual quality, or whether your evidence quotes are true,
        and it changes nothing in the scene. Call it after writing the file, and again after changing it.
        """
        from ..materialize import scene_view_manifest
        from ..models.creative_direction import (
            PlaybookEvidenceRequirements,
        )

        path = self.trace_dir / "workspace" / CREATIVE_DIRECTION_FILENAME
        try:
            direction = CreativeDirection.model_validate_json(path.read_text())
            descriptor = self.config.workspace_root / ".deepagent/knowledge-view.json"
            manifest = (
                json.loads(descriptor.read_text()) if descriptor.is_file() else scene_view_manifest()
            )
            if not isinstance(manifest, dict):
                raise ValueError("Delivered scene catalog must be an object.")
            if direction.playbook not in manifest.get("playbooks", []):
                raise ValueError("Playbook is not in the delivered scene catalog.")
            direction.validate_evidence_requirements(
                PlaybookEvidenceRequirements.model_validate(
                    manifest.get("playbook_requirements", {}).get(direction.playbook, {})
                )
            )
            available = {
                **(self.config.reference_assets or {}),
                **(self.config.brand_kit_assets or {}),
                **(self.config.asset_library or {}),
                **(self.scene.get("assets") or {}),
            }
            unknown = sorted({item.asset_id for item in direction.source_roles} - set(available))
            if unknown:
                raise ValueError(f"Sources are unavailable in this run: {', '.join(unknown)}")
            candidate = self.config.scene_skill_bundle == "candidate"
            review_profile = self._native_copy_review_profile() if candidate else None
            digest = canonical_direction_digest(direction)
            previous_digest = self._validated_direction_digest
            changed = previous_digest is not None and previous_digest != digest
            if candidate and changed and not revision_reason.strip():
                raise ValueError("A changed validated direction requires a concise revision_reason.")
        except (OSError, ValueError) as error:
            self.record("coordinator", "creative_direction_invalid", output_summary=str(error))
            return self._tool_error("direction.invalid", str(error))
        payload = {
            "status": "ok",
            "direction": direction.model_dump(mode="json"),
            "source_ids": [item.asset_id for item in direction.source_roles],
            "evidence_verified": False,
        }
        if candidate:
            self._validated_direction = direction
            self._validated_direction_digest = digest
            payload.update(
                direction_digest=digest,
                previous_direction_digest=previous_digest,
                revision_reason=revision_reason.strip(),
                review_requirements=direction_review_requirements(direction),
                visual_accuracy_verified=False,
                native_copy_review_profile=review_profile,
            )
        self.record("coordinator", "creative_direction_validated", payload=payload)
        return json.dumps(payload, indent=2)

    def _direction_review_error(self, critique: VisualCritique) -> str | None:
        """Candidate coverage/freshness only; notes remain model judgments."""
        if self.config.scene_skill_bundle != "candidate":
            return None
        review = getattr(critique, "direction_review", None)
        if review is None:
            return "The candidate review needs direction_review coverage." if critique.accepted else None
        if self._validated_direction is None or self._validated_direction_digest is None:
            return "Validate this run's creative direction before reviewing it."
        try:
            current = CreativeDirection.model_validate_json(
                (self.trace_dir / "workspace" / CREATIVE_DIRECTION_FILENAME).read_text()
            )
        except (OSError, ValueError):
            return "The creative direction is missing or invalid; validate it before review."
        if canonical_direction_digest(current) != self._validated_direction_digest:
            return "The creative direction changed since validation; revise and validate it explicitly."
        if review.direction_digest != self._validated_direction_digest:
            return "The critique reviews an earlier direction; review the current validated direction."
        if review.scope == "scoped_edit" and (
            not self.seeded_from_initial_scene or self._validated_direction.intent != "edit"
        ):
            return "A scoped_edit review requires a seeded scene and a validated edit direction."
        required = {
            (item["section"], item["index"])
            for item in direction_review_requirements(self._validated_direction)
        }
        provided = {(check.section, check.index) for check in review.checks}
        if provided - required:
            return "The critique contains unknown direction review indices."
        if critique.accepted:
            if provided != required:
                return "Accepted review must cover every preserve and review_needs item."
            if any(check.status != "met" for check in review.checks):
                return "Direction deviations or unverified requirements remain; repair or explicitly revise the direction."
        return self._copy_review_error(critique)

    def _native_copy_review_profile(self) -> JsonObject | None:
        """Caller-owned viewing assumptions from this run's delivered catalog."""
        profile_id = self.config.scene_review_profile.strip()
        if self.config.scene_skill_bundle != "candidate" or not profile_id:
            return None
        from ..materialize import scene_view_manifest

        descriptor = self.config.workspace_root / ".deepagent/knowledge-view.json"
        manifest = (
            json.loads(descriptor.read_text()) if descriptor.is_file() else scene_view_manifest()
        )
        if not isinstance(manifest, dict):
            raise ValueError("Delivered scene catalog must be an object.")
        profiles = manifest.get("review_profiles", {})
        if not isinstance(profiles, dict):
            raise ValueError("Delivered scene review profiles must be an object.")
        profile = profiles.get(profile_id)
        if profile is None:
            raise ValueError(f"Unknown caller-selected scene review profile: {profile_id}")
        return {"id": profile_id, **NativeCopyReviewProfile.model_validate(profile).model_dump()}

    def _native_copy_inventory(self) -> JsonObject:
        """Observe exact text in current exported pages without another core call."""
        scene_stamp = self._scene_stamp()
        receipt = self._current_preview_receipt()
        payload = {
            "status": "unavailable", "scene_stamp": scene_stamp,
            "direction_digest": self._validated_direction_digest,
            "preview_receipt": receipt,
            "occurrences": [], "excluded": [], "unresolved": [],
            "evidence_verified": False,
            "limits": (
                "Native text only; instances are not expanded. Clipping, occlusion, "
                "off-canvas placement and text inside images are not measured. "
                "Support and placement readability remain model judgments; source/excerpt "
                "strings are model-authored declarations, not independently verified evidence."
            ),
        }
        if self._preflight_scene_stamp != scene_stamp or self._latest_preflight_diagnostics is None:
            payload["reason"] = "No current resolved preflight."
            return payload
        if receipt is None or receipt != self._preview_receipt:
            payload["reason"] = "No current preview bound to these scene contents and bytes."
            return payload
        try:
            profile = self._native_copy_review_profile()
        except (OSError, ValueError, RuntimeError) as error:
            payload["reason"] = f"Native copy review profile unavailable: {error}"
            return payload
        if profile is not None:
            payload["review_profile"] = profile
            payload["limits"] += (
                " The caller-selected profile checks normalized native nominal em, "
                "not rendered glyph height or a platform font rule. Its width is an "
                "explicit viewing assumption, not inferred from page units. Passing "
                "the minimum does not establish readability; transformed and raster "
                "text still need visual review."
            )
        artifacts = (self.latest_export_summary or {}).get("artifacts") or []
        page_ids = [item.get("page_id") for item in artifacts]
        if not page_ids or any(not isinstance(page_id, str) or not page_id for page_id in page_ids):
            payload["reason"] = "Rendered page association is missing."
            return payload
        for page_id in sorted(set(page_ids)):
            observed = observe_native_text(self.scene, page_id)
            if profile is not None:
                for row in observed["occurrences"]:
                    measured = native_nominal_em_at_width(
                        self.scene, page_id, row, profile["display_width_px"],
                    )
                    measured["passes_minimum"] = (
                        measured["nominal_em_px"] >= profile["minimum_nominal_em_px"]
                        if measured["status"] == "ok" else None
                    )
                    row["nominal_size_review"] = measured
            for key in ("occurrences", "excluded", "unresolved"):
                payload[key].extend(observed[key])
        payload["status"] = "ok"
        return payload

    def _copy_review_error(self, critique: SceneVisualCritique) -> str | None:
        """Verify exact bindings/coverage and cited IDs, never semantic entailment."""
        review = critique.direction_review
        if not critique.accepted and not review.copy_occurrences:
            return None
        inventory = self._native_copy_inventory()
        if inventory["status"] != "ok":
            return f"Native copy review inventory unavailable: {inventory['reason']}"
        if critique.accepted and review.scope == "whole_creative" and inventory["unresolved"]:
            return f"Native copy observation is unresolved: {inventory['unresolved']}"
        actual = {(row["page_id"], row["node_id"]): row for row in inventory["occurrences"]}
        declared = {block.id: block for block in self._validated_direction.copy_blocks}
        covered_nodes, covered_copy = set(), set()

        def words(text: str) -> str:
            return " ".join(text.split())

        for occurrence in review.copy_occurrences:
            block = declared.get(occurrence.copy_id)
            if block is None:
                return f"Unknown declared copy_id: {occurrence.copy_id}"
            parts = []
            for fragment in occurrence.fragments:
                key = (fragment.page_id, fragment.node_id)
                row = actual.get(key)
                if row is None:
                    return (
                        "Native copy binding is absent, hidden, empty or outside "
                        f"the exported pages: {key}"
                    )
                if not words(fragment.text) or words(fragment.text) != words(row["text"]):
                    return f"Native copy binding does not match the current words: {key}"
                if critique.accepted and row["binding_issue"]:
                    return f"Native copy observation is unresolved for {key}: {row['binding_issue']}"
                if (
                    critique.accepted and review.scope == "whole_creative"
                    and inventory.get("review_profile") is not None
                ):
                    measured = row["nominal_size_review"]
                    profile = inventory["review_profile"]
                    if measured["status"] != "ok":
                        return f"Native copy size is unavailable for {key}: {measured['reason']}"
                    if not measured["passes_minimum"]:
                        return (
                            f"Native copy {key} is below caller-selected {profile['id']}: "
                            f"{measured['nominal_em_px']:.6g}px normalized nominal em at "
                            f"{profile['display_width_px']:g}px width; minimum "
                            f"{profile['minimum_nominal_em_px']:g}px. Recompose or simplify "
                            "the copy and inspect a fresh preview; "
                            "a readable label cannot waive this check."
                        )
                parts.append(fragment.join_before + fragment.text)
                covered_nodes.add(key)
            if critique.accepted and words("".join(parts)) != words(block.text):
                return (
                    f"Bound native copy differs from declared copy {block.id}; "
                    "revise and validate the direction."
                )
            support, readability = occurrence.support, occurrence.readability
            if support and not set(support.evidence_refs) <= set(block.evidence_refs):
                return f"Copy {block.id} cites evidence not declared for that copy block."
            if critique.accepted:
                if support is None or support.status not in {"supported", "nonfactual"}:
                    return f"Copy {block.id} needs a passing support judgment for this occurrence."
                if support.status == "supported" and not support.evidence_refs:
                    return f"Supported factual copy {block.id} requires cited declared evidence."
                if support.source_gaps is None:
                    return (
                        f"Copy {block.id} needs an explicit source_gaps assessment "
                        "for this occurrence."
                    )
                if support.source_gaps:
                    gaps = "; ".join(f"{gap.kind}: {gap.reason}" for gap in support.source_gaps)
                    return f"Copy {block.id} has unresolved source gaps: {gaps}"
                if readability is None or readability.status != "readable":
                    return f"Copy {block.id} needs a readable placement judgment for this occurrence."
            covered_copy.add(block.id)
        if critique.accepted and review.scope == "whole_creative":
            if covered_copy != set(declared):
                return (
                    "Accepted review must bind every declared copy ID to its actual native occurrences."
                )
            if covered_nodes != set(actual):
                return "Accepted review leaves extra native copy occurrences unreviewed."
        return None

    def recommend_edit_surface(self, intent: str, context_json: str = "{}") -> str:
        """Recommend a conservative edit surface for an agent repair or creation step.

        Precedence is deliberate: a concrete target (a named node/page/slot) means
        a targeted in-place edit, so it routes to ``structured_ops`` FIRST. Only a
        genuine asset *generation* request — signalled by an explicit verb such as
        "generate image"/"vectorize", never the bare word "asset" — routes to the
        asset tool. This stops an unrelated diagnostic like "font asset brand is
        not marked embeddable" (which merely contains the substring "asset") from
        hijacking a text-fit repair toward the image tool.
        """
        try:
            context = json.loads(context_json)
        except json.JSONDecodeError:
            context = {}
        if not isinstance(context, dict):
            context = {}
        intent_lower = intent.lower()
        target_keys = ("node_id", "page_id", "slot_id", "slot_key", "target")
        has_target = any(context.get(key) for key in target_keys)
        asset_generation = any(
            phrase in intent_lower
            for phrase in (
                "generate image",
                "generate an image",
                "generate a image",
                "image generation",
                "vectorize",
                "vectorise",
                "generate logo",
                "create logo",
                "create a logo",
                "generate qr",
                "qr code",
            )
        )
        if has_target and not asset_generation:
            recommendation = EditSurfaceRecommendation.structured_ops
        elif asset_generation:
            recommendation = EditSurfaceRecommendation.asset_tool
        elif any(
            word in intent_lower
            for word in ("create", "compose", "design", "layout", "draft")
        ):
            recommendation = EditSurfaceRecommendation.dsl
        else:
            recommendation = EditSurfaceRecommendation.external_planner
        payload = {
            "recommendation": recommendation.value,
            "reason": "conservative_phase_a_rule",
        }
        self.record(
            "coordinator",
            "edit_surface_recommended",
            input_summary=intent[:500],
            output_summary=recommendation.value,
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def create_repair_request(
        self,
        exact_feedback: str,
        diagnostics_json: str = "[]",
        target_json: str = "{}",
        allowed_edit_surface: str = "dsl",
        forbidden_changes_json: str = "[]",
        repair_class: Optional[str] = None,
        cluster_json: str = "null",
        permissions_json: str = "[]",
        prohibitions_json: str = "[]",
    ) -> str:
        """Create and persist a repair request without paraphrasing reviewer feedback."""
        diagnostics = diagnostics_from(json.loads(diagnostics_json))
        target_payload = json.loads(target_json)
        forbidden_changes = json.loads(forbidden_changes_json)
        cluster_payload = json.loads(cluster_json)
        permissions = json.loads(permissions_json)
        prohibitions = json.loads(prohibitions_json)
        request = RepairRequest(
            original_user_request=self.prompt,
            exact_feedback=exact_feedback,
            diagnostics=diagnostics,
            target=VisualTarget.model_validate(target_payload) if target_payload else None,
            repair_class=_coerce_repair_class(repair_class),
            cluster=(
                LayoutClusterTarget.model_validate(cluster_payload)
                if cluster_payload
                else None
            ),
            scene_summary=self._scene_summary(),
            allowed_edit_surface=EditSurfaceRecommendation(allowed_edit_surface),
            permissions=permissions,
            prohibitions=prohibitions,
            forbidden_changes=forbidden_changes,
        )
        payload = {"repair_request": request.model_dump(mode="json")}
        self._write_json(self._iteration_dir() / "repair_request.json", payload)
        self.record(
            "coordinator",
            "repair_requested",
            input_summary=exact_feedback[:500],
            output_summary=f"repair via {allowed_edit_surface}",
            diagnostics=[diag.model_dump(mode="json") for diag in diagnostics],
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    @_tool_span
    def record_gap(
        self,
        area: str,
        summary: str,
        evidence: str,
        suggested_phase: Optional[str] = None,
    ) -> str:
        """Record a gap in the product: something the tools, the engine or the guides can't do, or did
        wrong, so the team can fix it. Use it instead of quietly working around a missing capability. It
        is not for missing evidence behind a claim; that goes in your review's source_gaps. It changes
        nothing in the design.
        """
        coerced_area = _coerce_gap_area(area)
        if coerced_area.value != area:
            summary = f"[reported area: {area}] {summary}"
        gap = GapRecord(
            area=coerced_area,
            summary=summary,
            evidence=evidence,
            suggested_phase=suggested_phase,
        )
        payload = gap.model_dump(mode="json")
        self.gaps.append(payload)
        self._write_json(self.turn_dir / "gaps.json", {"gaps": self.gaps})
        self.record(
            "coordinator",
            "gap_recorded",
            input_summary=evidence[:500],
            output_summary=f"{area}: {summary}",
            payload=payload,
        )
        return json.dumps({"gap": payload}, indent=2)

    def summarize_scene(self) -> str:
        """Return a compact document scene summary for planning or repair targeting."""
        return json.dumps(self._scene_summary(), indent=2)

    def summarize_page(self, page_id: str) -> str:
        """Return a page-specific node and geometry summary."""
        pages = self.scene.get("pages", {})
        page = pages.get(page_id)
        if page is None:
            return json.dumps({"status": "missing", "page_id": page_id}, indent=2)
        return json.dumps(
            {
                "status": "ok",
                "page": self._page_summary(page_id, page),
                "node_tree": self._node_tree(page.get("children", [])),
            },
            indent=2,
        )

    def summarize_slots(self) -> str:
        """Return slot-to-node binding summaries."""
        return json.dumps({"slots": self._slot_summaries()}, indent=2)

    def summarize_node_tree(self, page_id: str) -> str:
        """Return the node hierarchy for one page."""
        page = self.scene.get("pages", {}).get(page_id)
        if page is None:
            return json.dumps({"status": "missing", "page_id": page_id}, indent=2)
        return json.dumps(
            {"status": "ok", "page_id": page_id, "node_tree": self._node_tree(page.get("children", []))},
            indent=2,
        )

    @_tool_span
    def inspect(
        self,
        view: str,
        target: str | None = None,
        foreground_color: str | None = None,
        region: list[float] | None = None,
    ) -> str:
        """Read the current scene without changing it. Use it to confirm an id before you edit it.
        """
        if view == "scene":
            return self.summarize_scene()
        if view == "slots":
            return self.summarize_slots()
        if view == "copy_review" and self.config.scene_skill_bundle == "candidate":
            with self._scene_mutation_lock:
                inventory = self._native_copy_inventory()
                # The inventory has a fresh receipt; only the model-facing copy
                # uses virtual paths. Internal custody keeps its host paths.
                for artifact in (inventory.get("preview_receipt") or {}).get("artifacts", []):
                    artifact["path"] = to_virtual(artifact["path"], self.config)
                return json.dumps(inventory, indent=2)
        if view == "image_contrast":
            from ..image_contrast import measure_image_contrast

            if not target or foreground_color is None or region is None:
                return self._tool_error(
                    "inspect.bad_request",
                    "image_contrast requires target=asset_id, foreground_color and region.",
                )
            images, _, receipt, error = self._collect_selected_reference_previews([target])
            if error:
                return self._tool_error(*error)
            try:
                measured = measure_image_contrast(images[0][0], foreground_color, region)
            except (ValueError, OSError) as error:
                return self._tool_error("inspect.image_contrast_unavailable", str(error))
            return json.dumps(
                {
                    "status": "ok",
                    "asset_id": target,
                    "source_digest": receipt[0]["digest"],
                    "foreground_color": foreground_color,
                    "region": region,
                    "contrast": measured,
                }
            )
        if view == "page":
            if not target:
                return self._tool_error(
                    "inspect.bad_request", "view='page' requires target=<page_id>."
                )
            return self.summarize_page(target)
        if view == "node_tree":
            if not target:
                return self._tool_error(
                    "inspect.bad_request", "view='node_tree' requires target=<page_id>."
                )
            return self.summarize_node_tree(target)
        if view == "geometry":
            if not target:
                return self._tool_error(
                    "inspect.bad_request", "view='geometry' requires target=<node_id>."
                )
            return self.query_geometry(target)
        if view == "slot_bindings":
            if not target:
                return self._tool_error(
                    "inspect.bad_request", "view='slot_bindings' requires target=<slot_key>."
                )
            return self.query_slot_bindings(target)
        return self._tool_error(
            "inspect.unknown_view",
            f"unknown view '{view}'.",
            valid_views=[
                "scene",
                "page",
                "node_tree",
                "slots",
                "geometry",
                "slot_bindings",
                "image_contrast",
            ],
        )

    def curated_context(
        self,
        *,
        user_request: str,
        previous_feedback: list[JsonObject],
        director_decisions: list[JsonObject],
    ) -> JsonObject:
        """Build a small, capped situation report from canonical state.

        This is the P1 replacement for the old `full_activity_context`. It is
        rebuilt fresh every iteration and NEVER embeds the whole scene, raw trace
        events, iteration files, base64 PNGs, or full SVG text. Every field is
        hard-capped, so the director/author/reviewer prompt stays bounded no
        matter how many repair iterations run. The latest preview image is sent
        separately as one image block (see providers), not inlined here.
        """
        diagnostics = self._latest_diagnostics_ranked(previous_feedback)
        target_ids = self._diagnostic_target_ids(diagnostics)
        contact_sheet, contact_sheet_omitted = self._brand_asset_contact_sheet()
        context: JsonObject = {
            "run_id": self.run_id,
            "iteration": self.iteration,
            "user_request": user_request,
            "original_prompt": self.prompt,
            # Phase 0b: a seeded run continues the user's live document — the
            # director must choose continuation modes (targeted_patch /
            # layout_cluster_rewrite), never fresh authoring.
            "seeded_from_initial_scene": self.seeded_from_initial_scene,
            "conversation_context": extract_editor_conversation_context(self.prompt),
            "scene_summary": self._scene_summary(),
            "scene_subtree": self._scene_subtree_for_targets(target_ids),
            "diagnostics": diagnostics,
            "latest_feedback": self._latest_feedback_brief(previous_feedback),
            "latest_critique": self._latest_critique(previous_feedback),
            "attempt_history": self._attempt_history(
                director_decisions, previous_feedback
            ),
            "preview_summary": self._preview_summary(
                diagnostics, previous_feedback
            ),
            "loaded_knowledge": self._capped_knowledge(),
            "effective_brand_context": copy.deepcopy(self.effective_brand_context),
            # K1: the compact kit digest (tone, resolved role colors, accent,
            # type roles, logo/image inventory) — the author styles CTAs from
            # its `accent`, the reviewer critiques brand-fit against it.
            "brand_card": copy.deepcopy(self.brand_card),
            "gaps": copy.deepcopy(self.gaps[-CONTEXT_MAX_ATTEMPTS:]),
        }
        # Slice 2: attach the kit-asset contact sheet (thumbnail PATHS + labels) so
        # the Director can choose imagery/logo placements by LOOKING (providers turns
        # each `preview_path` into a vision block at the boundary). Only present when
        # the document has an attached kit whose assets resolve to real previews.
        if contact_sheet:
            context["brand_asset_contact_sheet"] = contact_sheet
            if contact_sheet_omitted:
                context["brand_asset_contact_sheet_omitted"] = contact_sheet_omitted
            self.record(
                "director",
                "contact_sheet_attached",
                output_summary=f"{len(contact_sheet)} asset previews",
                payload={"asset_ids": [entry["asset_id"] for entry in contact_sheet]},
            )
        return context

    # -- Curated-context helpers (all bounded; no file re-reads, no nesting) --

    def _brand_asset_contact_sheet(self) -> tuple[list[JsonObject], int]:
        """Slice 2 D1: the Director's contact sheet — one entry per kit asset that
        resolves to a real on-disk preview, capped at CONTACT_SHEET_MAX.

        Order: logo assets first, then described images (a `title` means the ingest
        pipeline described it → author-selectable), then the rest. Each entry carries
        only PATHS + small strings — never base64 (bytes ride as vision blocks at the
        model boundary). Assets with no usable raster preview (e.g. an SVG with no
        thumbnail) are skipped and counted in the returned omitted total, so a broken
        path never reaches the model."""
        manifest = self.config.brand_kit_assets or {}
        if not manifest:
            return [], 0

        def rank(item: tuple[str, JsonObject]) -> int:
            _asset_id, entry = item
            record = entry.get("record") or {}
            if record.get("kind") == "logo":
                return 0
            return 1 if entry.get("title") else 2

        ordered = sorted(manifest.items(), key=rank)
        sheet: list[JsonObject] = []
        omitted = 0
        for asset_id, entry in ordered:
            if not isinstance(entry, dict):
                omitted += 1
                continue
            record = entry.get("record") or {}
            resolved = self._asset_preview_path(record)
            if resolved is None:
                omitted += 1
                continue
            if len(sheet) >= CONTACT_SHEET_MAX:
                omitted += 1
                continue
            preview_path, pixel_width, pixel_height = resolved
            label = entry.get("title") or record.get("label") or asset_id
            sheet_entry: JsonObject = {
                "asset_id": asset_id,
                "kind": "logo" if record.get("kind") == "logo" else "image",
                "label": label,
                "preview_path": preview_path,
                "pixel_width": pixel_width,
                "pixel_height": pixel_height,
            }
            usage = entry.get("usage")
            if usage:
                sheet_entry["usage_note"] = str(usage)[:120]
            sheet.append(sheet_entry)
        return sheet, omitted

    def _placed_brand_asset_previews(self) -> list[JsonObject]:
        """Slice 2 D3: the reviewer's source-asset comparison list — the intersection
        of (image nodes in the CURRENT scene and their `asset_id`) with the kit
        manifest, each resolved to its source thumbnail path, capped at
        PLACED_PREVIEWS_MAX. Paths only, no base64. Non-kit imagery (generated heroes)
        is excluded — this list exists to verify KIT placements against their source."""
        manifest = self.config.brand_kit_assets or {}
        if not manifest:
            return []
        previews: list[JsonObject] = []
        seen: set[str] = set()
        for node in (self.scene.get("nodes") or {}).values():
            kind = node.get("kind") or {}
            if kind.get("kind") != "image":
                continue
            asset_id = kind.get("asset_id")
            if not asset_id or asset_id in seen or asset_id not in manifest:
                continue
            entry = manifest.get(asset_id) or {}
            record = entry.get("record") or {}
            resolved = self._asset_preview_path(record)
            if resolved is None:
                continue
            seen.add(asset_id)
            preview_path, _pw, _ph = resolved
            label = entry.get("title") or record.get("label") or asset_id
            previews.append(
                {
                    "asset_id": asset_id,
                    "label": label,
                    "preview_path": preview_path,
                }
            )
            if len(previews) >= PLACED_PREVIEWS_MAX:
                break
        return previews

    def _latest_diagnostics_ranked(
        self, previous_feedback: list[JsonObject]
    ) -> list[JsonObject]:
        """Most-recent compile/preflight diagnostics, errors first, capped."""
        raw: list[JsonObject] = []
        for entry in reversed(previous_feedback or []):
            raw = _extract_diagnostics(entry)
            if raw:
                break
        severity_rank = {"blocker": 0, "error": 1, "warning": 2, "info": 3}
        compact: list[JsonObject] = []
        for diagnostic in raw:
            if not isinstance(diagnostic, dict):
                continue
            compact.append(
                {
                    "severity": diagnostic.get("severity"),
                    "code": diagnostic.get("code"),
                    "message": str(diagnostic.get("message") or "")[:300],
                    "target_node_id": diagnostic.get("target_node_id"),
                    "target_page_id": diagnostic.get("target_page_id"),
                    "target_slot_id": diagnostic.get("target_slot_id"),
                    "target_slot_key": diagnostic.get("target_slot_key"),
                }
            )
        compact.sort(key=lambda d: severity_rank.get(d.get("severity") or "info", 4))
        return compact[:CONTEXT_MAX_DIAGNOSTICS]

    def _diagnostic_target_ids(self, diagnostics: list[JsonObject]) -> list[str]:
        slots = self.scene.get("slots", {})
        ids: list[str] = []
        for diagnostic in diagnostics:
            node_id = diagnostic.get("target_node_id")
            if node_id:
                ids.append(node_id)
            slot_ref = diagnostic.get("target_slot_id") or diagnostic.get(
                "target_slot_key"
            )
            if slot_ref:
                for slot_id, slot in slots.items():
                    if slot_id == slot_ref or slot.get("key") == slot_ref:
                        ids.extend(slot.get("bound_nodes", []))
        seen: set[str] = set()
        ordered: list[str] = []
        for node_id in ids:
            if node_id not in seen:
                seen.add(node_id)
                ordered.append(node_id)
        return ordered

    def _scene_subtree_for_targets(self, target_ids: list[str]) -> list[JsonObject]:
        """Briefs for the diagnosed nodes plus their parent and children only."""
        nodes = self.scene.get("nodes", {})
        if not target_ids or not nodes:
            return []
        parent_of: dict[str, str] = {}
        for parent_id, node in nodes.items():
            for child_id in node.get("children", []) or []:
                parent_of[child_id] = parent_id
        selected: list[JsonObject] = []
        seen: set[str] = set()

        def add(node_id: str) -> None:
            if node_id in seen or node_id not in nodes:
                return
            if len(selected) >= CONTEXT_MAX_SUBTREE_NODES:
                return
            seen.add(node_id)
            selected.append(self._node_brief(node_id))

        for node_id in target_ids:
            parent_id = parent_of.get(node_id)
            if parent_id:
                add(parent_id)
            add(node_id)
            for child_id in nodes.get(node_id, {}).get("children", []) or []:
                add(child_id)
        return selected

    def _latest_feedback_brief(
        self, previous_feedback: list[JsonObject]
    ) -> Optional[JsonObject]:
        """The single most-recent feedback entry, trimmed to its decision-relevant
        structure. Keeps `kind`/`repair_class`/`target`/`cluster` (what the
        deterministic director routes on) and visual issue categories, but drops
        the giant `exact_feedback`/`repair_request` strings so it stays bounded
        and never accumulates across iterations.
        """
        if not previous_feedback:
            return None
        latest = previous_feedback[-1]
        if not isinstance(latest, dict):
            return None
        brief: JsonObject = {
            "kind": latest.get("kind"),
            "repair_class": latest.get("repair_class"),
            "recommended_edit_surface": latest.get("recommended_edit_surface"),
            "target": latest.get("target"),
            "cluster": latest.get("cluster"),
            "surgical_repair": latest.get("surgical_repair"),
        }
        inner = latest.get("feedback")
        if isinstance(inner, dict) and latest.get("kind") == "visual":
            issues = inner.get("issues") or []
            brief["feedback"] = {
                "issues": [
                    {
                        "category": issue.get("category"),
                        "severity": issue.get("severity"),
                        "target": issue.get("target"),
                        "detail": str(issue.get("detail") or "")[:300],
                    }
                    for issue in issues[:CONTEXT_MAX_CRITIQUE_ISSUES]
                    if isinstance(issue, dict)
                ]
            }
        return brief

    def _latest_critique(
        self, previous_feedback: list[JsonObject]
    ) -> Optional[JsonObject]:
        for entry in reversed(previous_feedback or []):
            if isinstance(entry, dict) and entry.get("kind") == "visual":
                critique = entry.get("feedback") or {}
                issues = critique.get("issues") or []
                return {
                    "accepted": critique.get("accepted"),
                    "summary": str(critique.get("summary") or "")[:600],
                    "repair_instruction": str(
                        critique.get("repair_instruction") or ""
                    )[:600]
                    or None,
                    "confidence": critique.get("confidence"),
                    "issues": [
                        {
                            "category": issue.get("category"),
                            "severity": issue.get("severity"),
                            "detail": str(issue.get("detail") or "")[:300],
                            "target": issue.get("target"),
                        }
                        for issue in issues[:CONTEXT_MAX_CRITIQUE_ISSUES]
                        if isinstance(issue, dict)
                    ],
                }
        return None

    def _attempt_history(
        self,
        director_decisions: list[JsonObject],
        previous_feedback: list[JsonObject],
    ) -> JsonObject:
        """Short rolling summary of what was tried and how it was rejected."""
        decisions = [
            {
                "iteration": index + 1,
                "action_mode": decision.get("action_mode"),
                "rationale": str(decision.get("rationale") or "")[:200],
            }
            for index, decision in enumerate(director_decisions or [])
            if isinstance(decision, dict)
        ]
        outcomes = [
            {
                "kind": entry.get("kind"),
                "repair_class": entry.get("repair_class"),
                "recommended_edit_surface": entry.get("recommended_edit_surface"),
                "summary": _feedback_one_liner(entry),
            }
            for entry in (previous_feedback or [])
            if isinstance(entry, dict)
        ]
        return {
            "decisions": decisions[-CONTEXT_MAX_ATTEMPTS:],
            "outcomes": outcomes[-CONTEXT_MAX_ATTEMPTS:],
        }

    def _preview_summary(
        self,
        diagnostics: list[JsonObject],
        previous_feedback: list[JsonObject],
    ) -> JsonObject:
        """Image-pointer + structural digest of the latest preview (no raw SVG)."""
        latest = self.latest_preview_bundle or self.latest_export_summary or {}
        artifacts = latest.get("artifacts", []) if isinstance(latest, dict) else []
        svg = next(
            (a for a in artifacts if isinstance(a, dict) and a.get("format") == "svg"),
            {},
        )
        png = next(
            (a for a in artifacts if isinstance(a, dict) and a.get("format") == "png"),
            {},
        )
        pages = self.scene.get("pages", {})
        first_page = next(iter(pages.values()), {}) if pages else {}
        size = first_page.get("size") or {}
        width, height = size.get("width"), size.get("height")
        visible_text: list[str] = []
        for node in self.scene.get("nodes", {}).values():
            kind = node.get("kind", {})
            if isinstance(kind, dict) and kind.get("kind") == "text":
                content = kind.get("content")
                if content:
                    visible_text.append(str(content)[:CONTEXT_MAX_TEXT_LEN])
        overflow = [
            {
                "code": diagnostic.get("code"),
                "message": diagnostic.get("message"),
                "target_node_id": diagnostic.get("target_node_id"),
            }
            for diagnostic in diagnostics
            if (diagnostic.get("code") or "") in CONTEXT_OVERFLOW_CODES
        ]
        summary: JsonObject = {
            "view_box": f"0 0 {width} {height}" if width and height else None,
            "width": width,
            "height": height,
            "element_count": len(self.scene.get("nodes", {})),
            "visible_text": visible_text[:CONTEXT_MAX_VISIBLE_TEXT],
            "overflow": overflow,
            "png_path": png.get("path") or png.get("critic_input_path"),
            "svg_path": svg.get("path") or svg.get("critic_input_path"),
            "svg_byte_len": svg.get("byte_len"),
        }
        # Inline a capped SVG snippet ONLY for renderer/export problems, where the
        # raw vector output is the actual subject of repair. For everything else
        # the image block + structural digest above is higher-value per token.
        if _is_render_export_issue(diagnostics, previous_feedback):
            svg_path = summary["svg_path"]
            if svg_path and Path(svg_path).exists():
                text = Path(svg_path).read_text(encoding="utf-8", errors="replace")
                summary["svg_snippet"] = text[:CONTEXT_MAX_SVG_SNIPPET]
                summary["svg_snippet_truncated"] = len(text) > CONTEXT_MAX_SVG_SNIPPET
        return summary

    def _capped_knowledge(self) -> list[JsonObject]:
        capped: list[JsonObject] = []
        for snippet in (self.loaded_knowledge or [])[:CONTEXT_MAX_KNOWLEDGE]:
            if not isinstance(snippet, dict):
                continue
            item = dict(snippet)
            if isinstance(item.get("excerpt"), str):
                item["excerpt"] = item["excerpt"][:CONTEXT_MAX_KNOWLEDGE_EXCERPT]
            capped.append(item)
        return capped

    @_scene_mutation
    def start_fresh_rewrite_scene(self, reason: str) -> None:
        """Reset the live authoring scene for a director-approved rewrite.

        Phase 0b guarantee: a SEEDED scene is the user's live document and is
        unwipeable — the reset is refused (and recorded) instead of replacing
        the seed with an empty scene. The loop additionally coerces the action
        modes that request this away on seeded runs; this block is the
        belt-and-suspenders enforcement for any other caller.
        """
        if self.seeded_from_initial_scene:
            self.record(
                "director",
                "seeded_scene_wipe_blocked",
                input_summary=reason[:500],
                output_summary=(
                    "refused to reset the live scene: it was seeded from the "
                    "user's document and is unwipeable"
                ),
                payload={"reason": reason},
            )
            return
        self.scene = self.core.new_scene(self.run_id, "Agent-authored design")
        self.dsl_session = None
        self.scene_update_sources.append("director_fresh_rewrite")
        self.record(
            "director",
            "fresh_rewrite_scene_started",
            input_summary=reason[:500],
            output_summary="reset live scene for bounded structural rewrite",
            payload={"reason": reason},
        )

    def query_geometry(self, node_id: str) -> str:
        """Return stored computed geometry and declared transform/size for a node."""
        node = self.scene.get("nodes", {}).get(node_id)
        if node is None:
            return json.dumps({"status": "missing", "node_id": node_id}, indent=2)
        payload: JsonObject = {
            "status": "ok",
            "node_id": node_id,
            "transform": node.get("transform"),
            "size": node.get("size"),
            "computed": node.get("computed"),
        }
        # Phase 1e: a pinned node's geometry is human-owned — the box is
        # authoritative (transform x/y are ignored by the solver while
        # pinned). Surfaced only when set.
        if node.get("position_mode") == "absolute":
            payload["position_mode"] = "absolute"
            payload["absolute_box"] = node.get("absolute_box")
            payload["base_anchor"] = node.get("base_anchor")
        return json.dumps(payload, indent=2)

    def query_slot_bindings(self, slot_key: str) -> str:
        """Return binding details for a semantic slot key."""
        matches = [
            (slot_id, slot)
            for slot_id, slot in self.scene.get("slots", {}).items()
            if slot.get("key") == slot_key or slot_id == slot_key
        ]
        return json.dumps(
            {
                "status": "ok" if matches else "missing",
                "query": slot_key,
                "slots": [
                    {
                        "id": slot_id,
                        "key": slot.get("key"),
                        "content_type": slot.get("content_type"),
                        "bound_nodes": [
                            self._node_brief(node_id)
                            for node_id in slot.get("bound_nodes", [])
                        ],
                    }
                    for slot_id, slot in matches
                ],
            },
            indent=2,
        )

    @_tool_span
    def request_clarification(self, questions: List[Dict[str, Any]]) -> str:
        """Ask the person up to SIX clarifying questions, then STOP — calling this
        ENDS THE TURN. Use it only as an OPENING MOVE, before any authoring,
        rendering or finalize, and never mid-design. Ask only for choices that
        shape the whole design and that you cannot find in the person's message,
        the Head of ABM's brief, the conversation, the ad, the brand kit, the
        seller's files or the research (asking about something you could find is
        a failure). Ask as many questions as you need, from one to six; never pad
        the list. Read the clarify-design-brief skill for what is worth asking.

        After calling this, do NOT author, render, or finalize — the person's next
        message answers the questions and that turn continues the design. Never
        re-ask a question a previous turn already answered.
        """
        try:
            request = ClarificationRequest(questions=questions)  # type: ignore[arg-type]
        except ValidationError as error:
            # House style: a bad payload is a machine-readable error the model can
            # read and retry, never a raised exception that kills the turn.
            return self._tool_error(
                "clarification.invalid_payload",
                "request_clarification payload is invalid. Provide 1-6 questions, "
                "each with a non-empty `default` ('if you don't care, I'll do X').",
                errors=[
                    {
                        "loc": list(item.get("loc", ())),
                        "msg": item.get("msg", ""),
                        "type": item.get("type", ""),
                    }
                    for item in error.errors()
                ],
            )
        questions_payload = [q.model_dump(mode="json") for q in request.questions]
        summary = self._render_clarification_text(questions_payload)
        # Honest turn outcome #3 (sibling of finalize_run's accepted/failed/...):
        # `clarification_requested`. Written to the SAME final.json the runner
        # reads, so run_deepagent_turn returns it verbatim and the API renders a
        # clarification envelope — no authoring, no operations, nothing applied.
        payload = {
            "run_id": self.run_id,
            "status": "clarification_requested",
            "stop_reason": "clarification_requested",
            "outcome": "clarification_requested",
            "summary": summary,
            "clarification": {"questions": questions_payload},
            "final_scene_summary": self._scene_summary(),
            "effective_brand": self.effective_brand_context,
            "preview_paths": self.preview_paths,
            "gaps": self.gaps,
            "seeded_from_initial_scene": self.seeded_from_initial_scene,
        }
        self._write_json(self.turn_dir / "final.json", payload)
        self.record(
            "coordinator",
            "clarification_requested",
            output_summary=f"asked {len(questions_payload)} clarifying question(s)",
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    @staticmethod
    def _render_clarification_text(questions: List[JsonObject]) -> str:
        """A plain-text rendering of the questions for the editor chat surface.

        Until the restyle R2 AI-Elements chat lands (option chips + freeform),
        the envelope's `summary` is shown as text — so it must read as a natural
        chat message, defaults-not-interrogation."""
        lines = [
            "Before I design this, a couple of quick decisions. Answer any of "
            "them, or just say \"go with your defaults\" and I'll proceed:",
            "",
        ]
        for index, question in enumerate(questions, start=1):
            lines.append(f"{index}. {question.get('question', '')}")
            why = question.get("why_it_matters")
            if why:
                lines.append(f"   Why it matters: {why}")
            options = question.get("options") or []
            if options:
                lines.append(f"   Options: {' / '.join(str(o) for o in options)}")
            default = question.get("default")
            if default:
                lines.append(f"   If you don't care, I'll do: {default}")
        return "\n".join(lines)

    @_tool_span
    @_scene_mutation
    def finalize_run(
        self,
        status: str,
        stop_reason: str,
        summary: str,
        critique_json: str = "{}",
        ops_valid_through_iteration: Optional[int] = None,
        baseline_advisory_json: str = "null",
        accommodation_json: str = "null",
    ) -> str:
        """Write the final run summary in a later-API-compatible local format.

        Omit `critique_json` to use the latest registered visual review; do not
        rewrite its JSON. Acceptance still checks that review, current scene,
        preflight and rendered bytes. Omission never creates a passing review.

        `ops_valid_through_iteration` names the last iteration whose applied
        operations are part of the returned draft scene (the keep-best snapshot
        can restore an EARLIER iteration's scene; ops from later iterations must
        then not be replayed by the editor). None means all ok iterations.

        `baseline_advisory_json` (agent-improvement follow-up 1): pre-existing
        diagnostics on the seeded scene that this turn never addressed —
        distinct field from `critique`/`diagnostics` on purpose, so the editor
        can show "N pre-existing issues predate this turn" without implying
        the turn caused or must fix them. `"null"` (default) means either an
        unseeded run or a run with no unaddressed baseline issues.
        """
        if status in {"succeeded", "success", "completed"}:
            status = "accepted"
        try:
            critique = json.loads(critique_json) if critique_json.strip() else {}
        except (ValueError, TypeError):
            return self._finalize_refusal("critique_json must be valid JSON.")
        if not isinstance(critique, dict):
            return self._finalize_refusal("critique_json must be an object.")
        if not critique and self._latest_visual_critique is not None:
            critique = dict(self._latest_visual_critique)
        # RC (D5; adversarial-gate F1 — the deterministic anti-rubber-stamp
        # guard, the tool-level twin of the edit-scoped acceptance refusal):
        # a REFERENCE turn can never finalize as "accepted" without an explicit
        # reviewer fidelity judgment of >= 2. A critique that OMITS
        # reference_fidelity is exactly the moda failure RC exists to kill — a
        # review pass that never asked "does this look like what the user
        # attached?" — so the omission itself refuses the finalize. The
        # orchestrator gets an actionable refusal string and must re-run the
        # reviewer (or finalize honestly as not-accepted).
        #
        # W1.5: before the gate reads the typed field, promote a judgment the
        # author wrote as prose into it. The backend already stamped the durable
        # `critique.json`; this covers the orchestrator handing us a critique it
        # re-serialized on the way here. `stamp_reference_fidelity` only ever
        # promotes a score the author WROTE — an unjudged self-audit stamps
        # `score: 0`, which this gate refuses exactly as an omission did.
        if self.config.reference_assets or self._selected_reference_ids:
            critique = stamp_reference_fidelity(critique)
        if status == "accepted":
            reason = self._reference_fidelity_error(critique)
            if reason:
                self.record(
                    "coordinator",
                    "finalize_refused_reference_fidelity",
                    output_summary=reason,
                )
                return self._finalize_refusal(
                    "this turn has selected image references, and a run "
                    f"cannot finalize as accepted with {reason}.",
                    fallback="Send the "
                    "reviewer back for an explicit reference_fidelity judgment "
                    "(view each reference:<n> against the preview); accept only "
                    "at score >= 2, or finalize honestly with a non-accepted "
                    "status."
                )
        # P0.3 finalize guard — closes the "accepted but unexportable" loophole.
        # The 2026-08-24 baseline run finalized as a success while EVERY export
        # of its scene was refused by preflight; the run result said "done" and
        # the artifact could not leave the building. A run may no longer record
        # acceptance while a BLOCKING export error stands.
        #
        # Scoped to blocking errors on purpose: advisory policy lints (the
        # LUMV0820 class) export fine, so they must not refuse a finalize —
        # that would just re-create the original dead end one layer up. They
        # are reported in the summary instead, never silently dropped.
        if status == "accepted" and self._latest_preflight_diagnostics is not None:
            blocking, advisory = partition_export_diagnostics(
                self._latest_preflight_diagnostics
            )
            if blocking:
                named = ", ".join(
                    sorted({str(item.get("code")) for item in blocking})
                )
                self.record(
                    "coordinator",
                    "finalize_refused_blocking_export_error",
                    output_summary=named,
                )
                return (
                    "REFUSED: this scene cannot be exported — "
                    f"{len(blocking)} blocking preflight error(s) remain ({named}). "
                    "Accepting now would record a success for a design that no "
                    "PNG, SVG or PDF export can produce. Repair the errors and "
                    "re-run preflight_design, or finalize honestly with a "
                    "non-accepted status."
                )
            if advisory:
                lints = ", ".join(
                    sorted({str(item.get("code")) for item in advisory})
                )
                note = (
                    f"Exports carry {len(advisory)} advisory policy lint(s) "
                    f"({lints}); the design exports cleanly regardless."
                )
                summary = f"{summary}\n{note}" if summary else note
        baseline_advisory = (
            json.loads(baseline_advisory_json) if baseline_advisory_json.strip() else None
        )
        # Accommodation edits: turn-introduced crowding this run detected,
        # plus any position-only nudges it applied to the crowded neighbors —
        # the run result must ANNOUNCE accommodation moves, never smuggle them.
        accommodation = (
            json.loads(accommodation_json) if accommodation_json.strip() else None
        )
        # Finalize hygiene (sweep A1): leftover zero-children pages shipped in
        # finals (e.g. an empty second artboard the author abandoned mid-run).
        # Prune them through the core so the mutation rides the operations
        # ledger — the editor's Accept replays that ledger, so a page dropped
        # here is dropped on Accept too, not just cosmetically in final_scene.
        # NEVER silently: the pruned ids are announced in the result summary.
        # Never remove the last remaining page (a design must keep one page).
        pruned_pages = self._prune_empty_pages()
        self._pending_pruned_pages.extend(pruned_pages)
        if self._pending_pruned_pages:
            note = (
                f"Pruned {len(self._pending_pruned_pages)} empty page(s) with no children "
                f"before finalizing: {', '.join(self._pending_pruned_pages)}."
            )
            summary = f"{summary}\n{note}" if summary else note
        if status in {"accepted", "succeeded", "success", "completed"}:
            refusal = self._acceptance_error(critique)
            if refusal:
                self.record("coordinator", "finalize_refused", output_summary=refusal)
                return self._finalize_refusal(refusal)
        verification = self.draft_verification()
        historical_critique = None
        if status != "accepted":
            if critique and (
                verification["review"]["status"] != "current"
                or critique != self._latest_visual_critique
            ):
                registered = critique == self._latest_visual_critique
                historical_critique = {
                    "critique": critique,
                    "status": verification["review"]["status"] if registered else "unbound",
                    "scene_stamp": (self._review_receipt or {}).get("scene") if registered else None,
                    "iteration": self._review_iteration if registered else None,
                }
            critique = (
                dict(self._latest_visual_critique or {})
                if verification["review"]["status"] == "current" else {}
            )
            if status == "completed_with_warnings":
                note = draft_verification_note(verification)
                # Agent prose may repeat an earlier review's failure. Retain
                # that feedback above and in trace, never as the current verdict.
                if verification["review"]["status"] == "current":
                    summary = f"{note} {critique.get('summary', '')}".strip()
                else:
                    summary = note
                if self._pending_pruned_pages:
                    summary += (
                        f"\nPruned {len(self._pending_pruned_pages)} empty page(s) "
                        f"before finalizing: {', '.join(self._pending_pruned_pages)}."
                    )
        payload = {
            "run_id": self.run_id,
            "status": status,
            "stop_reason": stop_reason,
            "summary": summary,
            "final_scene_summary": self._scene_summary(),
            "effective_brand": self.effective_brand_context,
            "preview_paths": self.preview_paths,
            "critique": critique,
            "historical_critique": historical_critique,
            "draft_verification": verification,
            "gaps": self.gaps,
            "scene_update_sources": self.scene_update_sources,
            "seeded_from_initial_scene": self.seeded_from_initial_scene,
            "ops_valid_through_iteration": ops_valid_through_iteration,
            "baseline_advisory": baseline_advisory,
            "accommodation": accommodation,
            "acceptance_receipt": self._review_receipt if status == "accepted" else None,
        }
        self._write_json(self.turn_dir / "final.json", payload)
        # Persist the FULL final scene (not just the summary) so offline tooling — the
        # imagery-quality eval runner in particular — can deterministically score the
        # design's use of imagery (node kinds, asset_placement, asset records, page
        # sizes) without re-running the agent or recompiling the DSL.
        if isinstance(self.scene, dict):
            self._write_json(self.turn_dir / "final_scene.json", self.scene)
        self.record(
            "coordinator",
            "run_finalized",
            output_summary=f"{status}: {stop_reason}",
            payload=payload,
        )
        return json.dumps(payload, indent=2)

    def _reference_fidelity_error(self, critique: JsonObject) -> str | None:
        """Shared reference gate for finalization and payload-recovery advice."""
        if not (self.config.reference_assets or self._selected_reference_ids):
            return None
        fidelity = critique.get("reference_fidelity") or {}
        if not isinstance(fidelity, dict) or not fidelity:
            return "no reference_fidelity judgment in the critique"
        score = fidelity.get("score")
        if not isinstance(score, int) or isinstance(score, bool) or score <= 1:
            return f"reference_fidelity score is {score!r}"
        if fidelity.get("regressed_to_house_style"):
            return "the reference review reports a regression to house style"
        return None

    def _finalize_refusal(self, reason: str, *, fallback: str | None = None) -> str:
        """Distinguish a review-copy error from evidence that needs repair."""
        registered = self._latest_visual_critique
        if (
            registered is not None
            and self._reference_fidelity_error(registered) is None
            and self._acceptance_error(registered) is None
        ):
            recovery = (
                "The current registered review is valid. Retry finalize_run without "
                "critique_json to use it; the same acceptance checks will run. "
                "This payload error does not require a new render or review."
            )
        else:
            recovery = fallback or (
                "Repair and re-run preflight, render, and review, or preserve the "
                "draft with a non-accepted status."
            )
        return f"REFUSED: {reason} {recovery}"

    def _contiguous_sink_extra(self, sink_extra: JsonObject) -> JsonObject:
        """Make an op-bearing sink push begin where the client's cursor stands.

        `operations_ledger` grows at ~20 sites (asset registration, autofix, pruning, …) but only
        the authoring mutations push a frame. The frontend cursor (`scene-stream-cursor.ts`,
        rule 5) applies a frame only when `operations_total - len(operations)` equals the
        position it has been shown up to; a gap makes it dirty and it drops every frame until
        a checkpoint. Live-proven 2026-09-04: two auto-registered kit assets (ledger 1–2, no
        frame) left the fresh Apollo/Ramp document's first batch beginning at 2, and the stage
        showed nothing for nine minutes. So every frame prepends the ledger entries streamed
        since the last frame, and a checkpoint (which re-seats the client) advances the marker.
        """
        operations = sink_extra.get("operations")
        total = sink_extra.get("operations_total")
        if not isinstance(operations, list) or not isinstance(total, int):
            return sink_extra
        begin = total - len(operations)
        if begin > self._streamed_ledger_len:
            missing = [
                entry["operation"]
                for entry in self.operations_ledger[self._streamed_ledger_len : begin]
                if isinstance(entry, dict) and "operation" in entry
            ]
            operations = missing + list(operations)
        self._streamed_ledger_len = max(self._streamed_ledger_len, total)
        return {**sink_extra, "operations": operations}

    def record(
        self,
        actor: str,
        event: str,
        input_summary: Optional[str] = None,
        output_summary: Optional[str] = None,
        diagnostics: Optional[List[JsonObject]] = None,
        payload: Optional[JsonObject] = None,
        sink_extra: Optional[JsonObject] = None,
    ) -> None:
        trace = LumenRunTraceEvent(
            run_id=self.run_id,
            iteration=self.iteration,
            actor=actor,
            event=event,
            input_summary=input_summary,
            output_summary=output_summary,
            diagnostics=diagnostics or [],
            payload=payload or {},
        )
        path = self.turn_dir / "trace.jsonl"
        # Serialize the whole record body under one lock (L2 thread-safety):
        # batched reads call this from concurrent ToolNode threads, so the jsonl
        # append and the event_sink push must never interleave with another
        # thread's. The lock is process-local; the file append is O(one line).
        with self._record_lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(trace.model_dump_json() + "\n")
            if self.event_sink is not None:
                # Progress streaming is best-effort: a sink failure must never
                # abort the design run (the file trace above is the source of
                # truth). Keep the base payload lightweight — the checklist needs
                # the event name + summaries, not the full per-iteration payload.
                # `sink_extra` is an OPT-IN channel merged on top of the five
                # summary fields (live-design-streaming S0): authoring mutations
                # that want the client to render the build as it happens pass
                # their applied `operations` here. It rides the sink push only —
                # never the trace above, which already carries the full payload.
                try:
                    push: JsonObject = {
                        "actor": actor,
                        "iteration": self.iteration,
                        "input_summary": input_summary,
                        "output_summary": output_summary,
                        "diagnostic_count": len(diagnostics or []),
                    }
                    if sink_extra:
                        push.update(self._contiguous_sink_extra(sink_extra))
                    self.event_sink(event, push)
                except Exception:
                    pass

    @_scene_mutation
    def _prune_empty_pages(self) -> list[str]:
        """Remove pages that carry zero children from the working scene, via the
        core `remove_page` op so the deletion rides the operations ledger (and
        thus survives the editor's Accept replay). Returns the pruned page ids
        (announced by finalize_run — never a silent drop). Keeps at least one
        page: a design with a single empty page is left untouched so finals are
        never page-less."""
        if not isinstance(self.scene, dict):
            return []
        pages = self.scene.get("pages") or {}
        empty_ids = [
            page_id
            for page_id, page in pages.items()
            if isinstance(page, dict) and not (page.get("children") or [])
        ]
        if not empty_ids:
            return []
        # Never strip the scene down to zero pages.
        if len(empty_ids) >= len(pages):
            empty_ids = empty_ids[: len(pages) - 1]
        if not empty_ids:
            return []
        operations = [
            {"kind": "remove_page", "page_id": page_id} for page_id in empty_ids
        ]
        try:
            response = self.core.apply_operations(self.scene, operations)
        except CoreError:
            # A rejected prune never blocks finalize; the empty page stays but
            # the run still finalizes cleanly.
            return []
        self._replace_scene_from_core_response(
            response, "prune_empty_pages", operations=operations
        )
        self.record(
            "coordinator",
            "empty_pages_pruned",
            output_summary=f"pruned {len(empty_ids)} empty page(s)",
            payload={"page_ids": empty_ids},
        )
        return empty_ids

    def _scene_mutation_count(self) -> int:
        """Core response/update counter for diagnostics, including no-op responses.

        Freshness decisions use `_scene_stamp`, not this activity counter.
        """
        return len(self.scene_update_sources)

    def _stamp_preview_rendered(self) -> None:
        """Bind a valid preview to current scene content and rendered bytes."""
        self._preview_scene_version = self._scene_mutation_count()
        self._preview_scene_stamp = self._scene_stamp()
        self._preview_rendered_iteration = self.iteration
        self._preview_receipt = self._current_preview_receipt()

    def _scene_stamp(self) -> str:
        # A director repeats preflight after the author's review. The helper
        # returns a scene even when nothing changed; that must preserve review
        # validity. Acceptance binds content and rendered bytes, not call count.
        content = json.dumps(self.scene, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode()).hexdigest()

    def draft_verification(self) -> JsonObject:
        """Report evidence freshness without spending, mutating, or accepting.

        A retained warning draft can be unverified or blocked. Historical
        preflight diagnostics do not describe the current scene; preview and
        review validity also require the original rendered bytes to survive.
        """
        scene_stamp = self._scene_stamp()
        preflight_current = (
            self._preflight_scene_stamp == scene_stamp
            and self._latest_preflight_diagnostics is not None
        )
        current_preview = self._current_preview_receipt()
        preview_current = current_preview is not None and current_preview == self._preview_receipt
        current_review = self._review_receipt_for(current_preview)
        review_current = (
            preview_current
            and self._latest_visual_critique is not None
            and current_review is not None
            and self._review_receipt == current_review
        )
        blocking, advisory = partition_export_diagnostics(self._latest_preflight_diagnostics or [])
        return {
            "scene_stamp": scene_stamp,
            "preflight": {
                "status": "current" if preflight_current else ("stale" if self._preflight_scene_stamp else "missing"),
                "scene_stamp": self._preflight_scene_stamp,
                "iteration": self._preflight_iteration,
                "has_blocking_errors": (
                    bool(blocking or (self.latest_preflight_has_errors and not advisory))
                    if preflight_current else None
                ),
                "diagnostics": (
                    [diag.model_dump(mode="json") for diag in diagnostics_from(self._latest_preflight_diagnostics)]
                    if preflight_current else []
                ),
            },
            "preview": {
                "status": "current" if preview_current else ("stale" if self._preview_receipt else "missing"),
                "scene_stamp": (self._preview_receipt or {}).get("scene"),
                "iteration": self._preview_rendered_iteration,
            },
            "review": {
                "status": "current" if review_current else ("stale" if self._review_receipt else "missing"),
                "scene_stamp": (self._review_receipt or {}).get("scene"),
                "iteration": self._review_iteration,
            },
        }

    def _review_receipt_for(self, preview: JsonObject | None) -> JsonObject | None:
        try:
            profile = self._native_copy_review_profile()
        except (OSError, ValueError, RuntimeError):
            return None
        receipt = {"scene": self._scene_stamp(), "preview": preview}
        if profile is not None:
            receipt["native_copy_review_profile"] = profile
        return receipt

    def _current_preview_receipt(self) -> JsonObject | None:
        summary = self.latest_export_summary or {}
        artifacts = summary.get("artifacts") or []
        if not artifacts or any(not item.get("valid") for item in artifacts):
            return None
        digests = []
        try:
            for item in artifacts:
                path = Path(item["path"]).resolve()
                path.relative_to(self.trace_dir.resolve())
                data = path.read_bytes()
                if not data:
                    return None
                digests.append({"path": str(path), "sha256": hashlib.sha256(data).hexdigest()})
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return {"scene": self._scene_stamp(), "artifacts": digests}

    def _acceptance_error(self, critique: JsonObject) -> str | None:
        """Check evidence at the final write boundary, independent of agent prose."""
        try:
            critique_model = (
                SceneVisualCritique if self.config.scene_skill_bundle == "candidate" else VisualCritique
            )
            typed = critique_model.model_validate(critique)
        except ValidationError:
            return "A complete typed visual critique is required for acceptance."
        if not typed.accepted or any(
            issue.severity in {DiagnosticSeverity.error, DiagnosticSeverity.blocker}
            for issue in typed.issues
        ):
            return "The visual critique rejected this creative or contains blocking issues."
        if typed.model_dump(mode="json") != self._latest_visual_critique:
            return "The final critique differs from the registered visual review."
        direction_error = self._direction_review_error(typed)
        if direction_error:
            return direction_error
        if (
            getattr(typed, "direction_review", None)
            and typed.direction_review.scope != "whole_creative"
        ):
            return (
                "Whole-creative acceptance requires a whole_creative review; "
                "scoped_edit can only support edit_applied."
            )
        if self._preflight_scene_stamp != self._scene_stamp():
            return "The current scene has no fresh preflight."
        diagnostics = self._latest_preflight_diagnostics
        if diagnostics is None:
            return "Preflight did not complete."
        blocking, advisory = partition_export_diagnostics(diagnostics)
        if blocking or (self.latest_preflight_has_errors and not advisory):
            return "Blocking preflight errors remain."
        current = self._current_preview_receipt()
        if current is None or current != self._preview_receipt:
            return "The preview is missing, changed, or does not represent the current scene."
        if self._review_receipt != self._review_receipt_for(current):
            return "The registered critique does not review the current scene and preview bytes."
        return None

    @_scene_mutation
    def _apply_scene_operations(self, source: str, operations: list[JsonObject]) -> JsonObject:
        """Register results after remote work without holding its transaction open."""
        response = self.core.apply_operations(self.scene, operations)
        self._replace_scene_from_core_response(response, source, operations, construction=True)
        return response

    def _replace_scene_from_core_response(
        self,
        response: JsonObject,
        source: str,
        operations: Optional[list[JsonObject]] = None,
        *,
        construction: bool = False,
    ) -> None:
        # The caller must hold _scene_mutation_lock from BEFORE reading the
        # scene passed to the helper through this replacement and ledger write.
        scene = response.get("scene")
        if not isinstance(scene, dict):
            raise CoreError("helper.scene_missing", f"{source} did not return a scene")
        if construction and self.solo_rounds_executed is not None and scene != self.scene:
            # Checked operations, crops and asset placement can repair without
            # a DSL compile. Normalization and final cleanup never own a round,
            # even when their helper response changes scene content.
            self._begin_solo_construction()
        self.scene = scene
        self.scene_update_sources.append(source)
        if operations:
            self._log_scene_operations(source, operations)

    def _log_scene_operations(
        self, source: str, operations: list[JsonObject]
    ) -> None:
        """K2 accept-seam fix: THE proposal operation ledger. The editor's
        Accept replays the proposal's operation list onto the document — it
        never sees the runtime's working scene — so any scene mutation that
        is not in that list silently vanishes at accept (live-proven: the
        auto-registered logo record existed in the run's final scene but the
        accepted document had empty scene.assets → LUME0211). Every
        successful mutation logs here, tagged with its iteration so the
        keep-best ops window still applies; agent_response_from_trace reads
        this ledger instead of scraping compile.json. Preflight's resolution
        ops are deliberately NOT logged — token resolution on accept belongs
        to the K1.6(b) accept bake, and double-carrying it would duplicate."""
        self.operations_ledger.extend(
            {"iteration": self.iteration, "source": source, "operation": operation}
            for operation in operations
        )
        self._write_json(
            self.turn_dir / "operations_ledger.json",
            {"entries": self.operations_ledger},
        )

    @_scene_mutation
    def checkpoint_scene(self, reason: str) -> None:
        """P0.4 — hand this round's work to the checkpoint sink so it becomes
        durable NOW instead of only at finalize.

        Called at the orchestrator's round-verification seam (a `render_preview`
        that produced a validated raster — see `tools/render.py`), which is the
        one place in this runtime where Python can observe "an authoring round
        finished and the scene it produced is real". Before this existed a run
        that died at finalize — the 2026-08-24 quota 403 at 20m42s — discarded a
        fully valid scene and left the document at version 0.

        Three properties this must keep, because it runs mid-run against a live
        document:

        * **Best-effort.** A checkpoint that cannot be committed is a lost
          version, never a lost run. Every failure is recorded and swallowed;
          the finalize commit remains the run's authority.
        * **Monotone.** The FULL ordered ledger goes to the sink every time and
          the sink commits only the delta it has not made durable, so a refused
          checkpoint is simply re-offered inside the next one.
        * **Silent when nothing moved.** No new operations means no call, so an
          unchanged re-render cannot mint an empty document version.
        """
        if self.scene_checkpoint is None:
            return
        pending = len(self.operations_ledger) - self._checkpointed_operations
        if pending <= 0:
            return
        operations = [
            entry["operation"]
            for entry in self.operations_ledger
            if isinstance(entry, dict) and "operation" in entry
        ]
        meta = {
            "reason": reason,
            "run_id": self.run_id,
            "iteration": self.iteration,
            # Recorded, deliberately NOT gated on: a scene that rendered a
            # validated raster is work worth keeping even while preflight still
            # reports diagnostics (LUMV0820 blocks export on runs the fast-loop
            # spec's P0.2/P0.3 own). The reader decides what a dirty checkpoint
            # is worth; this seam only refuses to throw the scene away.
            "preflight_clean": self.latest_preflight_has_errors is False,
            "operations_total": len(operations),
        }
        try:
            self.scene_checkpoint(operations, meta)
        except Exception as error:  # noqa: BLE001 - a checkpoint never fails a run
            self.record(
                "coordinator",
                "scene_checkpoint_failed",
                output_summary=f"{type(error).__name__}: {error}",
                payload=meta,
            )
            return
        self._checkpointed_operations = len(operations)
        # Plan 2 Task 5: the checkpoint re-seats the client at this position (rung A reloads
        # the version it names), so nothing before it needs to ride a later frame.
        self._streamed_ledger_len = max(self._streamed_ledger_len, len(operations))
        self.record(
            "coordinator",
            "scene_checkpointed",
            output_summary=f"{reason}: {pending} new operation(s), {len(operations)} total",
            payload=meta,
        )

    def _write_and_validate_preview_artifacts(
        self,
        raw_artifacts: list[JsonObject],
        requested_format: str,
        iteration_dir: Path,
    ) -> list[PreviewArtifact]:
        if not raw_artifacts:
            return [
                PreviewArtifact(
                    format=requested_format,
                    mime_type="",
                    byte_len=0,
                    valid=False,
                    validation_errors=["export returned no artifacts"],
                )
            ]

        artifacts: list[PreviewArtifact] = []
        for index, artifact in enumerate(raw_artifacts, start=1):
            raw_bytes = bytes(artifact.get("bytes", []))
            artifact_format = str(artifact.get("format") or requested_format).lower()
            page_id = artifact.get("page_id")
            suffix = "svg" if artifact_format == "svg" else artifact_format
            path = iteration_dir / f"preview.{suffix}" if len(raw_artifacts) == 1 else iteration_dir / f"preview_{index}.{suffix}"
            path.write_bytes(raw_bytes)
            self.preview_paths.append(str(path))
            width, height = self._page_dimensions(page_id)
            validation_errors = validate_preview_bytes(
                raw_bytes,
                artifact_format,
                requested_format,
            )
            warnings: list[str] = []
            # L4a: decode PNG pixels once and net a sentinel/uniform frame that
            # slipped the token-paint refusal. Hard sentinel error flips the
            # artifact invalid (→ export status error); near-uniform is a loud
            # non-blocking warning. The guard never raises.
            if artifact_format == "png":
                sentinel_error, uniform_warning = _png_uniformity_guard(raw_bytes)
                if sentinel_error:
                    validation_errors = [*validation_errors, sentinel_error]
                if uniform_warning:
                    warnings.append(uniform_warning)
            if not validation_errors:
                # §7 metrics: time-to-first-preview is the run's single most
                # diagnostic number (baseline: 15.4 min, gate: <= 4 min), and it
                # must mean "the agent could actually SEE something" — so a
                # VALIDATED artifact starts the clock, never a written-but-broken
                # one. Idempotent: only the first call is kept.
                self.metrics.mark_first_preview()
            artifacts.append(
                PreviewArtifact(
                    format=artifact_format,
                    mime_type=artifact.get("mime_type") or "",
                    page_id=page_id,
                    byte_len=len(raw_bytes),
                    path=str(path),
                    width=width,
                    height=height,
                    aspect_ratio=width / height if width and height else None,
                    critic_input_path=str(path),
                    valid=not validation_errors,
                    validation_errors=validation_errors,
                    warnings=warnings,
                )
            )
        return artifacts

    def _iteration_dir(self) -> Path:
        index = max(self.iteration, 1)
        path = self.iterations_dir / f"{index:03d}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _scene_summary(self) -> JsonObject:
        pages = self.scene.get("pages", {})
        nodes = self.scene.get("nodes", {})
        slots = self.scene.get("slots", {})
        summary: JsonObject = {
            "document_id": self.scene.get("meta", {}).get("id"),
            "title": self.scene.get("meta", {}).get("title"),
            "status": self.scene.get("meta", {}).get("status"),
            "brand_kit": self.scene.get("meta", {}).get("brand_kit"),
            "effective_brand": self.effective_brand_context,
            "page_count": len(pages),
            "node_count": len(nodes),
            "slot_count": len(slots),
            "asset_count": len(self.scene.get("assets", {})),
            "pages": [
                self._page_summary(page_id, page) for page_id, page in pages.items()
            ],
            "slots": self._slot_summaries(),
        }
        freehand = self._freehand_summary()
        if freehand is not None:
            summary["freehand"] = freehand
        return summary

    def _freehand_summary(self) -> Optional[JsonObject]:
        """Phase 1e: the director/author's at-a-glance view of human-owned
        geometry. Present only when the scene has freehand state, so
        pre-freehand summaries stay byte-identical."""
        nodes = self.scene.get("nodes", {})
        pinned = [
            node_id
            for node_id, node in nodes.items()
            if node.get("position_mode") == "absolute"
        ]
        free_containers = [
            node_id
            for node_id, node in nodes.items()
            if isinstance(node.get("layout"), dict)
            and node["layout"].get("layout_mode") == "free"
        ]
        if not pinned and not free_containers:
            return None
        return {
            "pinned_nodes": pinned,
            "free_containers": free_containers,
            "note": (
                "human-owned geometry: pinned nodes keep their absolute_box "
                "across relayouts and must not be re-positioned; free "
                "containers hold hand-placed children"
            ),
        }

    def _page_summary(self, page_id: str, page: JsonObject) -> JsonObject:
        width, height = self._page_dimensions(page_id)
        return {
            "id": page_id,
            "name": page.get("name"),
            "size": page.get("size"),
            "width": width,
            "height": height,
            "aspect_ratio": width / height if width and height else None,
            "children": page.get("children", []),
            "child_count": len(page.get("children", [])),
        }

    def _slot_summaries(self) -> list[JsonObject]:
        return [
            {
                "id": slot_id,
                "key": slot.get("key"),
                "content_type": slot.get("content_type"),
                "scope": slot.get("scope"),
                "bound_nodes": [
                    self._node_brief(node_id) for node_id in slot.get("bound_nodes", [])
                ],
            }
            for slot_id, slot in self.scene.get("slots", {}).items()
        ]

    def _node_tree(self, node_ids: list[str]) -> list[JsonObject]:
        return [self._node_with_children(node_id) for node_id in node_ids]

    def _node_with_children(self, node_id: str) -> JsonObject:
        node = self.scene.get("nodes", {}).get(node_id)
        if node is None:
            return {"id": node_id, "missing": True}
        brief = self._node_brief(node_id)
        brief["children"] = self._node_tree(node.get("children", []))
        return brief

    def _node_brief(self, node_id: str) -> JsonObject:
        node = self.scene.get("nodes", {}).get(node_id)
        if node is None:
            return {"id": node_id, "missing": True}
        kind = node.get("kind", {})
        kind_name = kind.get("kind") if isinstance(kind, dict) else kind
        slots = [
            slot.get("key")
            for slot in self.scene.get("slots", {}).values()
            if node_id in slot.get("bound_nodes", [])
        ]
        brief: JsonObject = {
            "id": node_id,
            "name": node.get("name"),
            "kind": kind_name,
            "text": kind.get("content") if isinstance(kind, dict) else None,
            "transform": node.get("transform"),
            "size": node.get("size"),
            "computed": node.get("computed"),
            "slots": slots,
            "source_asset_id": node.get("source_asset_id"),
        }
        # Phase 1e freehand visibility: surfaced only when set (pre-freehand
        # briefs stay byte-identical). `position_mode: "absolute"` means a
        # human pinned this node — its absolute_box is human-owned geometry;
        # base_anchor records where the layout had it at detach (the delta is
        # the human's deliberate nudge). `layout_mode: "free"` marks a
        # container whose children are hand-placed.
        if node.get("position_mode") == "absolute":
            brief["position_mode"] = "absolute"
            if node.get("absolute_box") is not None:
                brief["absolute_box"] = node.get("absolute_box")
            if node.get("base_anchor") is not None:
                brief["base_anchor"] = node.get("base_anchor")
        layout = node.get("layout")
        if isinstance(layout, dict) and layout.get("layout_mode") == "free":
            brief["layout_mode"] = "free"
        return brief

    def _page_dimensions(self, page_id: Optional[str]) -> tuple[Optional[float], Optional[float]]:
        if not page_id:
            return None, None
        page = self.scene.get("pages", {}).get(page_id)
        if not page:
            return None, None
        size = page.get("size") or {}
        width = size.get("width")
        height = size.get("height")
        return _as_float(width), _as_float(height)

    def _effective_brand_kit(self) -> tuple[str, JsonObject, Optional[str]]:
        """The Brand Kit this run designs against: (source, kit, notice).

        Precedence: a kit passed by value in config (the API's agent-turn path
        resolves the document's attached kit; the CLI a --brand-kit-file) →
        the platform default. The runtime never reads the API database.

        A document-attached kit is honored regardless of approval_status —
        attaching it was the human gate, and the editor canvas already resolves
        its values, so designing against a different kit would both split the
        document's visual truth and trip LUMB0101 (scene ref ≠ resolver kit,
        a hard error that short-circuits token resolution). An unapproved kit
        instead carries a notice so the trace and coordinator see the caveat.
        """
        kit = self.config.brand_kit
        if isinstance(kit, dict) and kit.get("id"):
            source = self.config.brand_kit_source or "config"
            status = str(kit.get("approval_status") or "").lower()
            notice = None
            if status != "approved":
                notice = (
                    f"brand kit {kit.get('id')} v{kit.get('version')} has "
                    f"approval_status={status or 'unknown'}; it is honored because "
                    "it is attached to this document, but its tokens and assets "
                    "are not yet human-approved"
                )
            return source, kit, notice
        return "platform_default", self.core.platform_default_brand_kit(), None

    def _brand_context(self, source: str, brand_kit: JsonObject) -> JsonObject:
        mode = brand_mode_from_kit(brand_kit)
        scene_medium = scene_medium_token(self.scene)
        if scene_medium:
            mode["medium"] = scene_medium
        return {
            "source": source,
            "brand_kit_id": brand_kit.get("id"),
            "brand_kit_version": (
                str(brand_kit.get("version"))
                if brand_kit.get("version") is not None
                else None
            ),
            "brand_kit_name": brand_kit.get("name"),
            "mode": mode,
        }

    def _brand_context_from_scene_ref(self, context: JsonObject) -> JsonObject:
        # Honesty rule (K0): the context reports the kit preflight ACTUALLY ran
        # against; a scene ref never overwrites it. A ref for a different kit is
        # surfaced as a mismatch (preflight will also carry LUMB0101) instead of
        # silently masquerading as the effective kit.
        brand_ref = self.scene.get("meta", {}).get("brand_kit") or {}
        ref_id = brand_ref.get("brand_kit_id") or brand_ref.get("id")
        if ref_id:
            honored = ref_id == context.get("brand_kit_id")
            context = {**context, "scene_ref_honored": honored}
            if not honored:
                context["scene_brand_ref"] = {
                    "brand_kit_id": ref_id,
                    "version": (
                        str(brand_ref.get("version"))
                        if brand_ref.get("version") is not None
                        else None
                    ),
                }
        scene_medium = scene_medium_token(self.scene)
        if scene_medium:
            context = {
                **context,
                "mode": {
                    **(context.get("mode") or {}),
                    "medium": scene_medium,
                },
            }
        return context

    def _write_json(self, path: Path, payload: JsonObject) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# L4a raster-guard thresholds (deepagent-latency wasted-round elimination). The
# PNG-black bug class is root-cause-fixed at the engine (white clear + magenta
# UNRESOLVED_PAINT_SENTINEL + LUME0213); this guard is the last-mile net for a
# sentinel frame that slips through as an OK export (the token-paint refusal does
# not cover unparseable hex or a degenerate gradient that fails only at raster).
_MAGENTA_SENTINEL = (255, 0, 255)  # LUME0213 unresolved-paint fill
_SENTINEL_TOLERANCE = 4  # tiny per-channel tolerance around the sentinel rgb
_UNIFORM_FRACTION = 0.99  # >=99% of pixels ⇒ sentinel-hard / uniform-warning
_UNIFORM_DELTA = 6  # per-channel band around the modal color for near-uniform
_GUARD_THUMB_PX = 64  # downsample longest side before counting — decode is cheap


def _png_uniformity_guard(raw_bytes: bytes) -> tuple[Optional[str], Optional[str]]:
    """Inspect PNG pixels for the magenta unresolved-paint sentinel and for a
    near-uniform frame. Returns ``(hard_error, warning)`` — at most one is set:

    - ``hard_error`` (non-None) when >=99% of pixels are the magenta LUME0213
      sentinel within a tiny tolerance. The caller appends it to
      ``validation_errors``, which flips the artifact invalid and the export
      status to error — the frame never reaches review as ok.
    - ``warning`` (non-None) when >=99% of pixels sit within a small delta of the
      modal color (near-uniform anything). Loud but NON-blocking: a legitimate
      minimalist design can be near-uniform, so blocking on a heuristic would
      harm quality. The magenta sentinel alone is engineered and unambiguous —
      hence the asymmetry.

    NEVER raises (turn-safety): any decode failure degrades to ``(None, None)``.
    Counting runs on a <=64px thumbnail, so the decode cost is negligible.
    """
    try:
        from PIL import Image

        with Image.open(io.BytesIO(raw_bytes)) as image:
            image.load()
            rgb = image.convert("RGB")
            # NEAREST keeps real pixel colors (no blended new colors) while
            # shrinking the count set to at most _GUARD_THUMB_PX**2.
            rgb.thumbnail((_GUARD_THUMB_PX, _GUARD_THUMB_PX), Image.NEAREST)
            pixels = list(rgb.getdata())
    except Exception:
        return None, None

    total = len(pixels)
    if total == 0:
        return None, None

    sr, sg, sb = _MAGENTA_SENTINEL
    sentinel_hits = sum(
        1
        for r, g, b in pixels
        if abs(r - sr) <= _SENTINEL_TOLERANCE
        and abs(g - sg) <= _SENTINEL_TOLERANCE
        and abs(b - sb) <= _SENTINEL_TOLERANCE
    )
    if sentinel_hits / total >= _UNIFORM_FRACTION:
        pct = 100.0 * sentinel_hits / total
        return (
            f"raster invalid: {pct:.1f}% of the PNG is the magenta LUME0213 "
            "unresolved-paint sentinel — a paint failed to resolve at raster. "
            "Fix the offending fill (see diagnostics) / run preflight_design, "
            "then re-render. This frame is not reviewable.",
            None,
        )

    from collections import Counter

    (mr, mg, mb), _modal_count = Counter(pixels).most_common(1)[0]
    near_modal = sum(
        1
        for r, g, b in pixels
        if abs(r - mr) <= _UNIFORM_DELTA
        and abs(g - mg) <= _UNIFORM_DELTA
        and abs(b - mb) <= _UNIFORM_DELTA
    )
    if near_modal / total >= _UNIFORM_FRACTION:
        pct = 100.0 * near_modal / total
        return (
            None,
            f"raster suspicious: ~{pct:.1f}% of the PNG is one uniform color "
            f"rgb({mr},{mg},{mb}) — verify this is intentional before reviewing.",
        )
    return None, None


def validate_preview_bytes(
    raw_bytes: bytes,
    artifact_format: str,
    requested_format: str,
) -> list[str]:
    errors: list[str] = []
    if artifact_format != requested_format:
        errors.append(
            f"artifact format {artifact_format} does not match requested {requested_format}"
        )
    if not raw_bytes:
        errors.append("artifact bytes are empty")
        return errors
    if artifact_format == "svg":
        text = raw_bytes.decode("utf-8", errors="ignore").lstrip()
        if "<svg" not in text[:300]:
            errors.append("SVG preview does not contain an <svg root near the start")
    elif artifact_format == "png":
        if not raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            errors.append("PNG preview has an invalid PNG signature")
    else:
        errors.append(f"unsupported visual preview format {artifact_format}")
    return errors


def combined_preview_artifacts(
    canonical_summary: JsonObject,
    critic_summary: JsonObject,
    critic_format: str,
) -> list[JsonObject]:
    canonical_artifacts = list(canonical_summary.get("artifacts", []))
    if critic_format == "svg":
        return canonical_artifacts
    return canonical_artifacts + list(critic_summary.get("artifacts", []))


def _summary_status_error(label: str, summary: JsonObject) -> Optional[str]:
    """The one error a summary's STATUS contributes, or None when it is ok.

    Split out of `bundle_validation_errors` so `checkpoint_acceptance` can tell a
    summary's status restatement apart from the errors that actually name a
    fault; the reviewer's error list is unchanged (status line first, then the
    named errors, canonical before critic)."""
    if summary.get("status") != ToolStatus.ok.value:
        return f"{label} preview status is {summary.get('status')}"
    return None


def _summary_named_errors(label: str, summary: JsonObject) -> list[str]:
    """Every error a summary NAMES — its own, then its artifacts'."""
    errors: list[str] = [
        f"{label}: {error}" for error in summary.get("validation_errors", [])
    ]
    for artifact in summary.get("artifacts", []):
        errors.extend(
            f"{label} {artifact.get('format')}: {error}"
            for error in artifact.get("validation_errors", [])
        )
    return errors


def bundle_validation_errors(
    canonical_summary: JsonObject,
    critic_summary: JsonObject,
) -> list[str]:
    errors: list[str] = []
    for label, summary in (("canonical", canonical_summary), ("critic", critic_summary)):
        status_error = _summary_status_error(label, summary)
        if status_error is not None:
            errors.append(status_error)
        errors.extend(_summary_named_errors(label, summary))
    return errors


# The lumen-export refusal (crates/lumen-export/src/svg.rs) raised when a brand
# face cannot be license-checked for embedding — WOFF2 containers, which are 367
# of the 517 stored brand faces. It arrives as an `ExportError` whose structured
# `code` the Python export summary does not carry (`export_preview` records only
# `CoreError.message`), so this leading marker — the constant half of the
# formatted message, before the page id — is the stable key.
# Since option A (2026-09-02) new ingests never store WOFF2, so this marker only fires for
# faces the backfill (scripts/decode_stored_web_fonts.py) has not reached. Delete the excuse
# once every environment has been backfilled.
SVG_FONT_EMBEDDING_REFUSAL_MARKER = "SVG font embedding failed"


@dataclass(frozen=True)
class CheckpointAcceptance:
    """Was this round ACCEPTED — i.e. is its scene worth making durable?"""

    accepted: bool
    blocking_errors: list[str]


def checkpoint_acceptance(
    canonical_summary: JsonObject,
    critic_summary: JsonObject,
) -> CheckpointAcceptance:
    """The P0.4 checkpoint predicate: round acceptance, not export perfection.

    Deliberately NOT `reviewer.status == "ok"` (controller ruling 2026-09-02).
    The reviewer verdict folds BOTH exports together, and the canonical SVG
    export refuses to embed a font container whose fsType it cannot read — every
    round, for every WOFF2 brand — while the critic PNG renders clean. That is an
    export-FORMAT limitation, not a rejected design, and gating checkpoints on it
    meant no WOFF2-brand run ever persisted a mid-run version.

    So the RASTER is the acceptance proof: the critic summary must be clean, and
    a canonical failure is excused only when every error it names is that font-
    embedding refusal. Any other canonical error — an unparseable SVG root, an
    empty artifact, a failure that names nothing at all — still blocks, and says
    so in `blocking_errors`.

    `reviewer.status` / `reviewer.validation_errors` are untouched by this: the
    agent loop reads them, and a round whose SVG did not embed its fonts should
    still tell the orchestrator so."""
    blocking: list[str] = []

    critic_status_error = _summary_status_error("critic", critic_summary)
    if critic_status_error is not None:
        blocking.append(critic_status_error)
    blocking.extend(_summary_named_errors("critic", critic_summary))

    canonical_errors = _summary_named_errors("canonical", canonical_summary)
    blocking.extend(
        error
        for error in canonical_errors
        if SVG_FONT_EMBEDDING_REFUSAL_MARKER not in error
    )
    canonical_status_error = _summary_status_error("canonical", canonical_summary)
    if canonical_status_error is not None and not canonical_errors:
        # A canonical failure that names nothing cannot be classified as the
        # embedding refusal, so it is not excused.
        blocking.append(canonical_status_error)

    return CheckpointAcceptance(accepted=not blocking, blocking_errors=blocking)


def reviewer_bundle_status(
    canonical_summary: JsonObject,
    critic_summary: JsonObject,
) -> str:
    return (
        ToolStatus.error.value
        if bundle_validation_errors(canonical_summary, critic_summary)
        else ToolStatus.ok.value
    )


def brand_mode_from_kit(brand_kit: JsonObject) -> JsonObject:
    modes = brand_kit.get("modes")
    defaults = modes.get("defaults") if isinstance(modes, dict) else None
    if isinstance(defaults, dict):
        return {str(axis): str(value) for axis, value in defaults.items()}

    default_mode = brand_kit.get("default_mode")
    values = default_mode.get("values") if isinstance(default_mode, dict) else None
    if isinstance(values, dict):
        return {str(axis): str(value) for axis, value in values.items()}
    return {}


def scene_medium_token(scene: JsonObject) -> Optional[str]:
    medium = scene.get("meta", {}).get("medium")
    if medium in {"print", "direct_mail"}:
        return "print"
    if medium in {"digital", "email", "ad"}:
        return "digital"
    return None


def normalize_halt_location(raw_halt: Any) -> Optional[JsonObject]:
    if raw_halt is None:
        return None
    if isinstance(raw_halt, dict):
        normalized: JsonObject = {}
        for key in ("code", "line", "column", "message"):
            if key in raw_halt and raw_halt[key] is not None:
                normalized[key] = raw_halt[key]
        return normalized or {"value": raw_halt}
    if isinstance(raw_halt, int):
        return {"line": raw_halt}
    return {"value": str(raw_halt)}


def parse_json_object(source: str) -> Optional[JsonObject]:
    try:
        parsed = json.loads(source)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_editor_conversation_context(prompt: str) -> JsonObject:
    marker = "Editor context JSON:"
    if marker not in prompt:
        return {"raw_prompt": prompt}
    _, context_text = prompt.split(marker, 1)
    context = parse_json_object(context_text.strip()) or {}
    conversation = context.get("conversation_context")
    if isinstance(conversation, dict):
        return conversation
    if isinstance(conversation, list):
        return {"messages": conversation}
    return {"raw_prompt": prompt}


# Common print/social aspect ratios; a generated image is snapped to the nearest
# one of these so the frame is filled cleanly without an odd model ratio.
_COMMON_ASPECTS: list[tuple[str, float]] = [
    ("1:1", 1.0),
    ("4:5", 4 / 5),
    ("5:4", 5 / 4),
    ("3:4", 3 / 4),
    ("4:3", 4 / 3),
    ("2:3", 2 / 3),
    ("3:2", 3 / 2),
    ("9:16", 9 / 16),
    ("16:9", 16 / 9),
    ("21:9", 21 / 9),
]
# Slice-0 hardcodes a sensible long-edge resolution by frame aspect; the explicit
# image_size tier (1K/2K/4K) lands in Step 7 (G0.2).
_IMAGE_LONG_EDGE = 1536


def _fixed_dim(spec: Any) -> Optional[float]:
    if isinstance(spec, dict) and spec.get("kind") == "fixed":
        value = spec.get("value")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _nearest_aspect_label(box_width: float, box_height: float) -> str:
    target = box_width / box_height
    return min(_COMMON_ASPECTS, key=lambda entry: abs(entry[1] - target))[0]


def _resolution_for_aspect(box_width: float, box_height: float) -> tuple[int, int]:
    if box_width >= box_height:
        width = _IMAGE_LONG_EDGE
        height = max(1, round(_IMAGE_LONG_EDGE * box_height / box_width))
    else:
        height = _IMAGE_LONG_EDGE
        width = max(1, round(_IMAGE_LONG_EDGE * box_width / box_height))
    return int(width), int(height)


def _image_warning(code: str, message: str) -> JsonObject:
    return {"severity": "warning", "phase": "validation", "code": code, "message": message}


def _coerce_gap_area(value: str) -> GapArea:
    """Tolerate a hallucinated gap area from the model (same failure class as
    _coerce_repair_class — a freeform label like 'structured_edit / text
    font_size persistence' crashed a whole run). Unknown values map to the
    closest catch-all rather than raising; the freeform text is preserved in
    the gap's summary/evidence either way."""
    try:
        return GapArea(value)
    except ValueError:
        return GapArea.agent_protocol


def _coerce_repair_class(value: Optional[str]) -> Optional[RepairClass]:
    """Tolerate an unknown/hallucinated repair_class from the model: an invalid
    enum value becomes None (unclassified) rather than raising and crashing the run."""
    if not value:
        return None
    try:
        return RepairClass(value)
    except ValueError:
        return None


def _as_diag_list(raw: Any) -> list[JsonObject]:
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def diagnostics_from(raw_diagnostics: Any) -> list[DiagnosticSummary]:
    diagnostics: list[DiagnosticSummary] = []
    if not isinstance(raw_diagnostics, list):
        return diagnostics
    for raw in raw_diagnostics:
        if not isinstance(raw, dict):
            continue
        # Rust DSL diagnostics wrap the core diagnostic beside its source span;
        # preflight diagnostics are flat. Preserve both contracts at this seam.
        nested = raw.get("diagnostic")
        if isinstance(nested, dict):
            raw = {**raw, **nested}
        span = raw.get("span") or {}
        subject = raw.get("subject") or {}
        target_page_id = None
        target_node_id = None
        target_slot_id = None
        if isinstance(subject, dict):
            kind = subject.get("kind")
            value = subject.get("id") or subject.get("value")
            if kind == "page":
                target_page_id = value
            elif kind == "node":
                target_node_id = value
            elif kind == "slot":
                target_slot_id = value
        target_page_id = target_page_id or raw.get("target_page_id")
        target_node_id = target_node_id or raw.get("target_node_id")
        target_slot_id = target_slot_id or raw.get("target_slot_id")
        severity = str(raw.get("severity") or "info").lower()
        if severity not in {item.value for item in DiagnosticSeverity}:
            severity = "info"
        diagnostics.append(
            DiagnosticSummary(
                severity=DiagnosticSeverity(severity),
                code=raw.get("code"),
                message=str(raw.get("message") or raw.get("detail") or raw),
                line=span.get("line") or raw.get("line"),
                column=span.get("column") or raw.get("column"),
                target_page_id=target_page_id,
                target_node_id=target_node_id,
                target_slot_id=target_slot_id,
                target_slot_key=raw.get("slot_key"),
                suggested_repair=raw.get("hint") or raw.get("suggested_repair"),
            )
        )
    return diagnostics


def first_existing_page_declaration(source: str, scene: JsonObject) -> Optional[JsonObject]:
    existing_pages = set((scene.get("pages") or {}).keys())
    if not existing_pages:
        return None
    for line_number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        page_id = declared_page_id(stripped)
        if page_id and page_id in existing_pages:
            return {"page_id": page_id, "line": line_number}
    return None


def declared_page_id(stripped_line: str) -> Optional[str]:
    if stripped_line.startswith("page("):
        close = stripped_line.find(")")
        if close == -1:
            return None
        return stripped_line[len("page(") : close].strip() or None
    if stripped_line == "page" or not stripped_line.startswith("page "):
        return None
    parts = stripped_line.split()
    return parts[1] if len(parts) > 1 else None


def _paint_token_refs(paint: Any) -> List[str]:
    """Every still-tokenized reference inside ONE serialized paint.

    Paints are internally-tagged serde enums (see `crates/lumen-core/src/scene.rs`,
    `Paint`/`Color`). A token survives resolution in three shapes:

      * ``Paint::Token``           -> ``{"kind": "token", "token": "surface.brand"}``
      * ``Paint::Solid`` over ``Color::Token``
            -> ``{"kind": "solid", "color": {"kind": "token", "token": ...}}``
      * gradient stops over ``Color::Token``
            -> ``{"kind": "linear_gradient"|"radial_gradient",
                   "stops": [{"color": {"kind": "token", ...}, "position": ...}]}``

    Resolved paints (hex/oklch solids, literal-color gradient stops) yield ``[]``.
    Anything malformed (non-dict, missing keys, non-string token) is tolerated
    and simply contributes no refs — this scanner never raises.
    """
    if not isinstance(paint, dict):
        return []
    refs: List[str] = []

    def _token_of(candidate: Any) -> Optional[str]:
        if (
            isinstance(candidate, dict)
            and candidate.get("kind") == "token"
            and isinstance(candidate.get("token"), str)
            and candidate.get("token")
        ):
            return candidate["token"]
        return None

    direct = _token_of(paint)
    if direct is not None:
        refs.append(direct)
    solid = _token_of(paint.get("color"))
    if solid is not None:
        refs.append(solid)
    stops = paint.get("stops")
    if isinstance(stops, list):
        for stop in stops:
            if not isinstance(stop, dict):
                continue
            stop_token = _token_of(stop.get("color"))
            if stop_token is not None:
                refs.append(stop_token)
    return refs


def _fill_list_token_refs(owner: str, entries: Any) -> List[tuple[str, str]]:
    """Token refs from a list of Fill/Stroke dicts (both wrap a `paint`)."""
    out: List[tuple[str, str]] = []
    if not isinstance(entries, list):
        return out
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for token in _paint_token_refs(entry.get("paint")):
            out.append((owner, token))
    return out


def _unresolved_paint_refs(scene: Any) -> List[tuple[str, str]]:
    """Every still-tokenized PAINT in a serialized scene, as
    ``(node_id_or_page, token_ref)`` pairs.

    Covers page background fills, node fills, and node strokes. Text color lives
    on the text node's `fills`, so text fills are covered by the node-fills sweep.
    Non-paint tokens (spacing/size/opacity/typography bindings) are deliberately
    ignored: they do not blacken a raster and are `preflight_design`'s own
    diagnostics' concern — only paints trigger the engine's magenta LUME0213
    sentinel at raster. Tolerant of malformed scenes/pages/nodes (never raises).
    """
    if not isinstance(scene, dict):
        return []
    refs: List[tuple[str, str]] = []
    pages = scene.get("pages")
    if isinstance(pages, dict):
        for page_id, page in pages.items():
            if not isinstance(page, dict):
                continue
            refs.extend(
                _fill_list_token_refs(f"page:{page_id}", page.get("background"))
            )
    nodes = scene.get("nodes")
    if isinstance(nodes, dict):
        for node_id, node in nodes.items():
            if not isinstance(node, dict):
                continue
            owner = str(node_id)
            refs.extend(_fill_list_token_refs(owner, node.get("fills")))
            refs.extend(_fill_list_token_refs(owner, node.get("strokes")))
    return refs


def _dump(model: Any) -> JsonObject:
    return model.model_dump(mode="json")


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    return None

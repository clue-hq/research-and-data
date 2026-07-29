"""Website-mode substrate — the LumenWebTools tool surface.

A website turn's artifact is a WebDoc (tree-canonical HTML document), not a Rust
scene, so it needs its own substrate. This mirrors LumenDesignTools' conventions
in a leaner form: tools are plain methods returning JSON strings (errors via the
shared `_tool_error` envelope), every call is traced to a JSONL file and pushed
to the optional event_sink via `record`, and the core helper is reached through
the SAME `_CoreHelperProxy` so each subprocess round-trip emits a `helper_call`
span.

The web pipeline lives entirely in the core helper (ingest HTML → tree, checked
op apply, editor/delivery render); this class threads those calls, generates
imagery, and captures Playwright screenshots of the rendered page at three
widths for the visual reviewer.
"""

from __future__ import annotations

import base64
import copy
import json
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from py_lumen_obs import bind_run_id, get_logger

from lumen_api.core import CoreClient, CoreError

# The image provider is optional (same guarded import substrate.py uses): absent
# or unconfigured → generation degrades to the deterministic stub provider so a
# web turn never dead-ends on imagery.
try:  # pragma: no cover - exercised only when the T2I model is configured
    from lumen_api import image_provider
except Exception:  # pragma: no cover
    image_provider = None  # type: ignore[assignment]

from ..brand_card import build_brand_card
from ..config import AgentRuntimeConfig
from ..models.schemas import LumenRunTraceEvent, new_run_id
from .substrate import _CoreHelperProxy
from .view import _image_block, _text_block

logger = get_logger("lumen_agent.tools.web_substrate")

JsonObject = Dict[str, Any]

# The page every P0 WebDoc carries (a single "home" page at route "/"). Website
# mode is single-page for now; the id is fixed so the tools never guess.
HOME_PAGE_ID = "home"

# The fixed semantic web token names the theme compiler always emits, in
# emission order (mirrors crates/lumen-web/src/theme.rs SEMANTIC_TOKENS). Every
# kit resolves these eight; the author may reference them for any color class.
_SEMANTIC_WEB_TOKENS = [
    "primary",
    "accent",
    "dark",
    "light",
    "card",
    "muted",
    "border",
    "inverse",
]

# The screenshot widths captured for every render, in emission order.
_PREVIEW_WIDTHS = (1440, 768, 375)

# The two widths interactive STATE captures (dialog-open, accordion-expanded)
# are taken at — desktop + mobile, the ends that break interaction layouts.
_STATE_WIDTHS = (1440, 375)

# At most this many dialog components are captured per render (each dialog costs
# two extra Playwright pages); any beyond the cap are reported, never dropped
# silently.
_MAX_DIALOG_CAPTURES = 3

# At most this many tabs components are captured per render (each costs one extra
# Playwright page); any beyond the cap are reported, never dropped silently.
_MAX_TABS_CAPTURES = 2

# The @font-face data-URL CSS built from the kit fonts is capped at this many
# encoded (base64) bytes so a heavy multi-weight kit cannot bloat every render's
# inlined HTML unbounded. Module-level so tests can force it small.
_FONT_FACE_CSS_MAX_BYTES = 8 * 1024 * 1024

# Sentinel distinguishing "not yet computed" from a resolved None for the cached
# font-face CSS (fonts cannot change mid-run, so the first result is memoized).
_FONT_CSS_UNSET = object()

# Mutating tool calls allowed between renders before the substrate refuses and
# tells the author to end its round. Sized against real healthy rounds (a full
# page install + several patch repairs + a few surgical ops ≈ 11); the
# pathological round this guards against burned 20+ (2026-07-29 blind churn).
_ROUND_MUTATION_BUDGET = 14


def _font_mime_from_magic(data: bytes) -> str:
    """The web font MIME for `data` by its leading magic bytes; unknown → the
    ttf default (a bare sfnt with no recognized signature is a TrueType)."""
    head = data[:4]
    if head == b"wOF2":
        return "font/woff2"
    if head == b"wOFF":
        return "font/woff"
    if head == b"OTTO":
        return "font/otf"
    if head == b"\x00\x01\x00\x00":
        return "font/ttf"
    return "font/ttf"


def _valid_font_weight(value: Any) -> bool:
    """A CSS font-weight the kit may carry: an int 1..=1000 (bools excluded —
    `True`/`False` are ints in Python but never a weight)."""
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 1000


def _valid_font_style(value: Any) -> bool:
    return value in ("normal", "italic")


def _interactive_capture_plan(web_doc: JsonObject) -> JsonObject:
    """Pure scan of a WebDoc for the interactive components that need a STATE
    capture. Factored out of render so it is unit-testable without Playwright.

    Returns ``{"dialogs": [node_id, ...], "has_accordion": bool, "has_nav":
    bool, "tabs": [node_id, ...]}``:
    - ``dialogs`` — every dialog component's node id (opened → screenshot), in
      page-then-node order across all pages.
    - ``has_accordion`` — any accordion component exists (details expanded →
      screenshot).
    - ``has_nav`` — any nav_menu component exists (hamburger opened →
      screenshot).
    - ``tabs`` — every tabs component's node id that has at least two children
      (a single-tab strip has nothing to switch to), same page-then-node order.

    A node's role is its ``component`` value when ``kind == "component"``."""
    dialogs: List[str] = []
    has_accordion = False
    has_nav = False
    tabs: List[str] = []
    for page in web_doc.get("pages") or []:
        if not isinstance(page, dict):
            continue
        nodes = page.get("nodes") or {}
        if not isinstance(nodes, dict):
            continue
        for node_id, node in nodes.items():
            if not isinstance(node, dict) or node.get("kind") != "component":
                continue
            component = node.get("component")
            if component == "dialog":
                dialogs.append(node_id)
            elif component == "accordion":
                has_accordion = True
            elif component == "nav_menu":
                has_nav = True
            elif component == "tabs":
                if len(node.get("children") or []) >= 2:
                    tabs.append(node_id)
    return {
        "dialogs": dialogs,
        "has_accordion": has_accordion,
        "has_nav": has_nav,
        "tabs": tabs,
    }


def sanitize_token_name(name: str) -> str:
    """Mirror crates/lumen-web/src/theme.rs `sanitize_token_name`: keep
    [a-z0-9-], lowercase [A-Z], map ./_/space to '-', drop everything else,
    then trim leading/trailing '-'."""
    out: List[str] = []
    for ch in name:
        if "a" <= ch <= "z" or "0" <= ch <= "9" or ch == "-":
            out.append(ch)
        elif "A" <= ch <= "Z":
            out.append(ch.lower())
        elif ch in "._ ":
            out.append("-")
        # any other character is dropped
    return "".join(out).strip("-")


def web_theme_token_names(brand_kit: Optional[JsonObject]) -> str:
    """The space-joined color-token vocabulary the theme compiler exposes for a
    kit: the eight semantic names plus every additional kit color under its
    sanitized name (dedup-preserving). Mirrors the Rust theme compiler's token
    map so the author prompt names exactly what it may reference. No kit → just
    the semantic eight."""
    names = list(_SEMANTIC_WEB_TOKENS)
    seen = set(names)
    colors = ((brand_kit or {}).get("tokens") or {}).get("colors") or {}
    for key in colors.keys():
        web_name = sanitize_token_name(str(key))
        if not web_name or web_name in seen:
            continue
        seen.add(web_name)
        names.append(web_name)
    return " ".join(names)


def _count_subtree(nodes: JsonObject, node_id: str) -> int:
    """Count `node_id` and all its descendants in a WebDoc page's node map."""
    total = 0
    stack = [node_id]
    while stack:
        current = stack.pop()
        node = nodes.get(current)
        if not isinstance(node, dict):
            continue
        total += 1
        stack.extend(node.get("children") or [])
    return total


class LumenWebTools:
    def __init__(
        self,
        config: AgentRuntimeConfig,
        prompt: str,
        initial_web_doc: JsonObject,
        event_sink=None,
    ) -> None:
        self.config = config
        self._obs_log = logger
        # Same single-seam proxy the scene substrate uses: every core-helper
        # subprocess call emits a `helper_call` span, transparent to callers.
        self.core = _CoreHelperProxy(
            CoreClient(repo_root=config.repo_root), self._obs_log
        )
        self.event_sink = event_sink
        self._record_lock = threading.Lock()
        self.prompt = prompt
        self.run_id = new_run_id()
        self.page_id = HOME_PAGE_ID
        # A deep copy so the caller's stored doc is never mutated in place; every
        # accepted mutation replaces this with the helper's returned doc.
        self.web_doc: JsonObject = copy.deepcopy(initial_web_doc)

        self.trace_dir = config.trace_dir / self.run_id
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        bind_run_id(self.run_id)

        # Monotonic iteration counter naming per-render screenshot dirs
        # (iter_1, iter_2, …). Bumped at the START of each render.
        self.iteration = 0
        # A single Playwright instance + headless chromium kept alive across
        # renders (launching per render dominates web-turn latency). Started
        # lazily by _browser_handle(); torn down by _close_browser() (called
        # from finalize on every outcome).
        self._pw = None
        self._browser = None
        self.preview_paths: List[str] = []
        # The latest screenshot path per width + the iteration that produced it.
        self._preview_by_width: Dict[int, str] = {}
        self._preview_iteration: Optional[int] = None
        # Interactive STATE captures from the latest render (dialog-open,
        # accordion-expanded), reset each render; view("state:<n>") indexes here.
        self._state_captures: List[JsonObject] = []
        # Cached @font-face data-URL CSS (fonts cannot change mid-run). The
        # sentinel distinguishes "not computed" from a resolved None.
        self._font_face_css_cache: Any = _FONT_CSS_UNSET
        # Staleness contract (mirrors the scene view): a monotonic doc-mutation
        # count, and the count stamped at the last successful render. view()
        # refuses a preview older than the current doc.
        self._doc_version = 0
        self._preview_doc_version: Optional[int] = None
        # Between-renders edit budget (live failure 2026-07-29: an author round
        # never returned control — 16 blind subtree rewrites over 14 minutes).
        # Every MUTATING tool call charges it; once exhausted, mutating tools
        # refuse and tell the author to end the round. render_web_preview
        # resets it — control is provably back with the orchestrator there.
        self._mutations_since_render = 0
        self._round_budget_event_recorded = False

        # The last REJECTED authoring submission (author_web_page /
        # author_web_subtree), so patch_web_page can repair the markup with
        # targeted string patches and resubmit it as the same atomic batch
        # instead of the model re-sending the whole document. Set on any ingest
        # rejection (with the SUBMITTED html), cleared on ANY successful
        # authoring write (page, subtree, or a successful patch).
        self._last_rejected_authoring: Optional[JsonObject] = None

        # Compact brand card (None without an attached kit) + its text form for
        # the prompts and view("brand").
        self.brand_card: Optional[JsonObject] = build_brand_card(
            config.brand_kit, source=config.brand_kit_source
        )
        if self.brand_card:
            self.brand_card_text = json.dumps(self.brand_card, indent=2)
        else:
            self.brand_card_text = (
                "No brand kit is attached to this document. Author against the "
                "platform default theme tokens."
            )
        # P5 (D6): the TARGET ACCOUNT card (None on an un-personalized turn) +
        # its text form for the prompts and view("account"). The parallel logo
        # manifest (config.account_assets) feeds `use_account_asset`, exactly as
        # config.brand_kit_assets feeds `use_brand_asset`.
        self.account_card: Optional[JsonObject] = config.account_card
        self.account_card_text = (
            json.dumps(self.account_card, indent=2) if self.account_card else None
        )
        # The base URL the rendered page resolves data-asset images against. The
        # API serves the shared store at /asset-store; a config override wins if
        # present (none today), else the pinned API origin.
        self.asset_base_url = (
            getattr(config, "asset_base_url", None)
            or "http://127.0.0.1:8000/asset-store"
        )

    # --- trace + errors -----------------------------------------------------

    def _tool_error(self, code: str, message: str, **extra: Any) -> str:
        """Uniform error envelope (mirrors LumenDesignTools._tool_error)."""
        payload: JsonObject = {"status": "error", "error_code": code, "message": message}
        payload.update(extra)
        return json.dumps(payload, indent=2)

    def _consume_round_budget(self, tool_name: str) -> Optional[str]:
        """Charge one mutating call against the between-renders budget.

        Returns None while budget remains (and charges it); returns a refusal
        envelope once exhausted. The refusal is a plain tool result — never an
        exception — so the model reads it and ends its round instead of dying."""
        if self._mutations_since_render >= _ROUND_MUTATION_BUDGET:
            if not self._round_budget_event_recorded:
                self._round_budget_event_recorded = True
                self.record(
                    "author",
                    "web_round_budget_exhausted",
                    input_summary=tool_name,
                    output_summary=(
                        f"{_ROUND_MUTATION_BUDGET} mutating calls since the last render"
                    ),
                )
            return self._tool_error(
                "round.budget_exhausted",
                f"Edit budget for this round is exhausted "
                f"({_ROUND_MUTATION_BUDGET} mutating calls since the last render). "
                "STOP editing. END YOUR REPLY now with a short summary of what you "
                "changed and what remains; the orchestrator re-renders fresh "
                "previews and the review continues from there.",
            )
        self._mutations_since_render += 1
        return None

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
        """Append one trace line (JSONL) and best-effort push it to the sink.

        Simplified twin of LumenDesignTools.record: same LumenRunTraceEvent
        shape (so the trace viewer reads a web run) and the same lock so the
        file append + sink push never interleave across threads."""
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
        path = self.trace_dir / "trace.jsonl"
        with self._record_lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(trace.model_dump_json() + "\n")
            if self.event_sink is not None:
                try:
                    push: JsonObject = {
                        "actor": actor,
                        "iteration": self.iteration,
                        "input_summary": input_summary,
                        "output_summary": output_summary,
                        "diagnostic_count": len(diagnostics or []),
                    }
                    if sink_extra:
                        push.update(sink_extra)
                    self.event_sink(event, push)
                except Exception:  # pragma: no cover - streaming is best-effort
                    pass

    # --- WebDoc helpers -----------------------------------------------------

    def _home_page(self) -> JsonObject:
        for page in self.web_doc.get("pages") or []:
            if isinstance(page, dict) and page.get("id") == self.page_id:
                return page
        return {}

    def _page_node_count(self) -> int:
        return len(self._home_page().get("nodes") or {})

    def _doc_summary_text(self) -> str:
        page = self._home_page()
        nodes = page.get("nodes") or {}
        root_id = page.get("root")
        root = nodes.get(root_id) or {}
        sections = []
        for child_id in root.get("children") or []:
            sections.append(f"{child_id} ({_count_subtree(nodes, child_id)} nodes)")
        assets = sorted((self.web_doc.get("assets") or {}).keys())
        return "\n".join(
            [
                f"page {self.page_id!r} — {len(nodes)} nodes, {len(assets)} asset(s)",
                "sections: " + (", ".join(sections) if sections else "(none)"),
                "assets: " + (", ".join(assets) if assets else "(none)"),
            ]
        )

    # --- tools --------------------------------------------------------------

    def author_web_page(self, html: str, custom_css: str = "") -> str:
        """Install a COMPLETE page from constrained HTML. `html` is the full
        section markup (header/section/footer top-level elements); `custom_css`
        is optional page-scoped CSS. The whole page is replaced.

        On any error-severity diagnostic NOTHING is stored — fix every
        diagnostic (each carries a code, node id, and hint) and resend the
        complete page. On success the working document is replaced and the
        installed node count is returned.

        Prefer `patch_web_page` to repair a rejected submission with targeted
        string patches instead of re-sending the whole page."""
        submission: JsonObject = {
            "tool": "author_web_page",
            "html": html,
            "custom_css": custom_css or None,
            "node_id": None,
        }
        return self._submit_authoring(submission, origin="author")

    # --- shared authoring submit path (author + patch resubmit) -------------

    def _submit_authoring(
        self,
        submission: JsonObject,
        origin: str,
        patch_count: Optional[int] = None,
    ) -> str:
        """The single submit-and-record core both an original author call and a
        patched resubmission go through. `origin` is "author" (the tool was
        called directly) or "patch" (patch_web_page repaired a rejected
        submission). Dispatches to the page or subtree ingest path by
        `submission["tool"]`; each path stores `_last_rejected_authoring` (with
        the submitted html) on rejection and clears it on success, so the two
        origins share EXACTLY the same events, doc-version bookkeeping, and
        success/rejection handling."""
        refusal = self._consume_round_budget(submission["tool"])
        if refusal is not None:
            return refusal
        if submission["tool"] == "author_web_page":
            return self._submit_page(submission, origin, patch_count)
        return self._submit_subtree(submission, origin, patch_count)

    def _authored_event(self, origin: str, tool: str) -> str:
        if origin == "patch":
            return "web_page_patched"
        return "web_page_authored" if tool == "author_web_page" else "web_subtree_authored"

    def _rejected_event(self, origin: str, tool: str) -> str:
        if origin == "patch":
            return "web_page_patch_rejected"
        return "web_page_rejected" if tool == "author_web_page" else "web_subtree_rejected"

    def _authoring_input_summary(
        self, origin: str, patch_count: Optional[int], author_default: str
    ) -> str:
        """The record input_summary: "{n} patch(es)" for a patch resubmission,
        else the tool's own default (the submitted html / node summary)."""
        if origin == "patch":
            return f"{patch_count} patch(es)"
        return author_default

    def _store_rejection(self, submission: JsonObject, diagnostics: List[JsonObject]) -> None:
        """Remember the rejected submission (with its SUBMITTED html) so
        patch_web_page can repair and resubmit it."""
        self._last_rejected_authoring = {
            "tool": submission["tool"],
            "html": submission["html"],
            "custom_css": submission["custom_css"],
            "node_id": submission["node_id"],
            "diagnostics": list(diagnostics or []),
        }

    def _clear_pending(self) -> None:
        self._last_rejected_authoring = None

    def _decorate_success(
        self, result: JsonObject, origin: str, patch_count: Optional[int]
    ) -> None:
        if origin == "patch":
            result["repaired_via"] = "patch"
            result["patches_applied"] = patch_count

    def _submit_page(
        self, submission: JsonObject, origin: str, patch_count: Optional[int]
    ) -> str:
        html = submission["html"]
        custom_css = submission["custom_css"]
        input_summary = self._authoring_input_summary(origin, patch_count, html[:200])
        try:
            response = self.core.web_ingest_html(
                self.web_doc,
                self.page_id,
                html,
                custom_css,
                brand_kit=self.config.brand_kit,
            )
        except CoreError as error:
            diagnostics = list(error.diagnostics or [])
            self._store_rejection(submission, diagnostics)
            self.record(
                "author",
                self._rejected_event(origin, submission["tool"]),
                input_summary=input_summary,
                output_summary=error.message,
                diagnostics=diagnostics,
            )
            return self._tool_error(
                "web_author.helper_error",
                error.message,
                diagnostics=diagnostics,
            )

        diagnostics = response.get("diagnostics") or []
        errors = [d for d in diagnostics if isinstance(d, dict) and d.get("severity") == "error"]
        if errors:
            self._store_rejection(submission, diagnostics)
            self.record(
                "author",
                self._rejected_event(origin, submission["tool"]),
                input_summary=input_summary,
                output_summary=f"{len(errors)} error diagnostic(s); page not stored",
                diagnostics=diagnostics,
            )
            return json.dumps(
                {"status": "rejected", "diagnostics": diagnostics}, indent=2
            )

        self.web_doc = response["web_doc"]
        self._doc_version += 1
        self._clear_pending()
        installed = response.get("applied_operations")
        warnings = [
            d for d in diagnostics if isinstance(d, dict) and d.get("severity") != "error"
        ]
        self.record(
            "author",
            self._authored_event(origin, submission["tool"]),
            input_summary=input_summary,
            output_summary=(
                f"installed {installed} node(s); page now {self._page_node_count()} nodes"
            ),
            diagnostics=warnings,
            sink_extra={"installed_nodes": installed},
        )
        result: JsonObject = {
            "status": "ok",
            "installed_nodes": installed,
            "warnings": warnings,
        }
        self._decorate_success(result, origin, patch_count)
        return json.dumps(result, indent=2)

    def author_web_subtree(self, node_id: str, html: str) -> str:
        """Scoped edit: replace ONE top-level section with new markup.

        v0 scoped edits operate at SECTION granularity — a section is a direct
        child of the page root ("root"). `node_id` is resolved to its enclosing
        section: if it already IS a root child that is the target; otherwise
        this walks up the parent chain (parent = the node whose `children`
        contain it) until it reaches a root child. An id that is not in the page
        (or resolves to no enclosing section, e.g. the root itself) is a
        `web_subtree.unknown_node` error listing the section ids.

        `html` is the COMPLETE replacement markup for that one section — a
        `<section id="...">...</section>` (keep the SAME id to preserve the
        section's identity across the edit). Flow:

        1. `web_ingest_fragment` parses the markup WITHOUT mutating the doc. Any
           error-severity diagnostic → {"status": "rejected", diagnostics} (doc
           untouched), mirroring `author_web_page`.
        2. Every fragment root must be a top-level section (the page grammar
           allows only sections at the top level). A non-section root →
           `web_subtree.not_a_section`. Engine reality: the ingester reports a
           non-section top-level element as an error (LUMW0102) and voids the
           fragment, so that specific code is surfaced as `not_a_section` (with
           a wrap hint) rather than a generic rejection.
        3. Compose ONE checked batch — `remove_node` of the old section followed
           by an `insert_node` per fragment root at the old section's index.
           Same-id replacement is legal precisely because the remove precedes
           the insert in a single sequentially-applied batch.
        4. `web_apply_ops` (checked). A rejected batch never replaces the doc;
           on success the working doc is replaced and the section id + new roots
           are returned.

        Prefer `patch_web_page` to repair a rejected submission with targeted
        string patches instead of re-sending the whole section.
        """
        submission: JsonObject = {
            "tool": "author_web_subtree",
            "html": html,
            "custom_css": None,
            "node_id": node_id,
        }
        return self._submit_authoring(submission, origin="author")

    def _submit_subtree(
        self, submission: JsonObject, origin: str, patch_count: Optional[int]
    ) -> str:
        node_id = submission["node_id"]
        html = submission["html"]
        page = self._home_page()
        nodes = page.get("nodes") or {}
        root_id = page.get("root")
        root = nodes.get(root_id) or {}
        root_children = list(root.get("children") or [])

        target_section = self._enclosing_section(node_id, nodes, root_children)
        if target_section is None:
            return self._tool_error(
                "web_subtree.unknown_node",
                f"node id {node_id!r} does not resolve to a section in the page.",
                section_ids=root_children,
            )

        # 1) Ingest the fragment WITHOUT mutating the doc.
        try:
            response = self.core.web_ingest_fragment(
                self.web_doc, html, brand_kit=self.config.brand_kit
            )
        except CoreError as error:
            diagnostics = list(error.diagnostics or [])
            self._store_rejection(submission, diagnostics)
            self.record(
                "author",
                self._rejected_event(origin, submission["tool"]),
                input_summary=self._authoring_input_summary(
                    origin, patch_count, f"{node_id}->{target_section}: {html[:160]}"
                ),
                output_summary=error.message,
                diagnostics=diagnostics,
            )
            return self._tool_error(
                "web_subtree.helper_error",
                error.message,
                diagnostics=diagnostics,
            )

        diagnostics = response.get("diagnostics") or []
        errors = [
            d for d in diagnostics if isinstance(d, dict) and d.get("severity") == "error"
        ]
        fragment = response.get("web_fragment") or {}
        frag_nodes = fragment.get("nodes") or []
        frag_roots = fragment.get("roots") or []
        frag_by_id = {
            n.get("id"): n for n in frag_nodes if isinstance(n, dict) and n.get("id")
        }

        # 2) Every fragment root must be a top-level section. A top-level
        #    non-section is reported by the ingester as LUMW0102 (and voids the
        #    fragment), so that code — or any surviving non-section root — is a
        #    targeted not_a_section error, distinct from a generic lint reject.
        non_section_roots = [
            r for r in frag_roots if (frag_by_id.get(r) or {}).get("kind") != "section"
        ]
        structural = bool(non_section_roots) or any(
            isinstance(d, dict) and d.get("code") == "LUMW0102" for d in errors
        )
        if structural:
            self._store_rejection(submission, diagnostics)
            self.record(
                "author",
                self._rejected_event(origin, submission["tool"]),
                input_summary=self._authoring_input_summary(
                    origin, patch_count, f"{node_id}->{target_section}"
                ),
                output_summary="replacement markup is not a top-level section",
                diagnostics=diagnostics,
            )
            return self._tool_error(
                "web_subtree.not_a_section",
                "a scoped edit's replacement markup must be one or more top-level "
                "sections; wrap it in <section id=\"...\">...</section> (keep the "
                "target section's id).",
                offending_roots=non_section_roots,
                diagnostics=diagnostics,
            )

        # Any other error-severity diagnostic → the fragment is unusable; store
        # nothing (mirrors author_web_page's reject contract).
        if errors:
            self._store_rejection(submission, diagnostics)
            self.record(
                "author",
                self._rejected_event(origin, submission["tool"]),
                input_summary=self._authoring_input_summary(
                    origin, patch_count, f"{node_id}->{target_section}"
                ),
                output_summary=f"{len(errors)} error diagnostic(s); section not changed",
                diagnostics=diagnostics,
            )
            return json.dumps(
                {"status": "rejected", "diagnostics": diagnostics}, indent=2
            )

        if not frag_roots:
            # A clean parse that produced no sections (e.g. empty markup): there
            # is nothing to splice — same remedy as a non-section root.
            self._store_rejection(submission, diagnostics)
            return self._tool_error(
                "web_subtree.not_a_section",
                "the replacement markup produced no top-level section; provide a "
                "<section id=\"...\">...</section>.",
                diagnostics=diagnostics,
            )

        # The fragment is a FRESH ingest, so its auto-minted ids (box_1, txt_2,
        # …) can collide with surviving sections' ids. The remove frees the
        # target section's own subtree ids (so a same-id replacement — the
        # section id and any deliberately re-used descendant ids — stays put),
        # but ids colliding with any SURVIVING node must be renamed or the
        # insert fails with op.id_taken.
        removed_ids = self._subtree_ids(nodes, target_section)
        surviving_ids = set(nodes.keys()) - removed_ids
        frag_nodes, frag_roots = self._dedupe_fragment_ids(
            frag_nodes, frag_roots, surviving_ids
        )
        frag_by_id = {
            n.get("id"): n for n in frag_nodes if isinstance(n, dict) and n.get("id")
        }

        # 3) Compose ONE batch: remove the old section, then insert each
        #    fragment root at the old section's position. Same-id replacement is
        #    legal because the remove precedes the insert in the single batch.
        old_index = root_children.index(target_section)
        batch: List[JsonObject] = [
            {"kind": "remove_node", "page_id": self.page_id, "id": target_section}
        ]
        for offset, frag_root in enumerate(frag_roots):
            subtree = self._fragment_subtree(frag_root, frag_nodes, frag_by_id)
            batch.append(
                {
                    "kind": "insert_node",
                    "page_id": self.page_id,
                    "parent": root_id,
                    "index": old_index + offset,
                    "nodes": subtree,
                    "root": frag_root,
                }
            )

        # 4) Checked apply. A rejected batch (invalid doc) never replaces the doc.
        try:
            applied = self.core.web_apply_ops(self.web_doc, batch)
        except CoreError as error:
            diagnostics = list(error.diagnostics or [])
            self._store_rejection(submission, diagnostics)
            self.record(
                "author",
                self._rejected_event(origin, submission["tool"]),
                input_summary=self._authoring_input_summary(
                    origin, patch_count, f"{node_id}->{target_section}"
                ),
                output_summary=error.message,
                diagnostics=diagnostics,
            )
            return json.dumps(
                {"status": "rejected", "diagnostics": diagnostics},
                indent=2,
            )
        if not applied.get("ok"):
            self._store_rejection(submission, applied.get("diagnostics") or [])
            return json.dumps(
                {"status": "rejected", "diagnostics": applied.get("diagnostics") or []},
                indent=2,
            )

        self.web_doc = applied["web_doc"]
        self._doc_version += 1
        self._clear_pending()
        warnings = [
            d for d in diagnostics if isinstance(d, dict) and d.get("severity") != "error"
        ]
        self.record(
            "author",
            self._authored_event(origin, submission["tool"]),
            input_summary=self._authoring_input_summary(
                origin, patch_count, f"{node_id}->{target_section}"
            ),
            output_summary=f"replaced section {target_section} with {frag_roots}",
            diagnostics=warnings,
            payload={"section": target_section, "replaced_with": frag_roots},
            sink_extra={"section": target_section},
        )
        result: JsonObject = {
            "status": "ok",
            "section": target_section,
            "roots": frag_roots,
            "warnings": warnings,
        }
        self._decorate_success(result, origin, patch_count)
        return json.dumps(result, indent=2)

    def patch_web_page(self, patches_json: str) -> str:
        """The DEFAULT repair path after a rejected author_web_page /
        author_web_subtree: apply targeted patches to your rejected markup and
        resubmit it as the same atomic batch, instead of re-sending the whole
        document. Full resend (author_web_page / author_web_subtree) remains the
        fallback for structural rewrites.

        `patches_json` is a JSON array of `{old_string, new_string,
        replace_all?}` applied IN ORDER, each against the result of the
        previous. `old_string` must match exactly (including whitespace) and,
        unless `replace_all` is true, must occur exactly once. The resubmission
        is atomic exactly like the original tool — a still-rejected patch stores
        nothing and returns the diagnostics for the next patch round; a clean
        resubmission installs the whole batch and clears the pending rejection.
        """
        pending = self._last_rejected_authoring
        if not pending:
            return self._tool_error(
                "patch.no_pending",
                "no rejected authoring submission to patch — the last submission "
                "was accepted (or nothing was authored yet); use web_ops for edits "
                "to the live page.",
            )

        try:
            patches = json.loads(patches_json)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            return self._tool_error(
                "patch.bad_input",
                f"patches must be a JSON array of "
                '{"old_string":"…","new_string":"…","replace_all":false} objects: '
                f"{error}.",
            )
        if not isinstance(patches, list) or not patches:
            return self._tool_error(
                "patch.bad_input",
                "patches must be a non-empty JSON array of "
                '{"old_string","new_string"} objects.',
            )

        # 2) Validate every entry structurally before applying any (a patch is
        #    all-or-nothing; a bad entry never mutates the stored submission).
        for i, entry in enumerate(patches):
            if not isinstance(entry, dict):
                return self._tool_error(
                    "patch.bad_input",
                    f"patch {i}: each patch must be an object with old_string and "
                    "new_string.",
                )
            old = entry.get("old_string")
            new = entry.get("new_string")
            if not isinstance(old, str) or not isinstance(new, str):
                return self._tool_error(
                    "patch.bad_input",
                    f"patch {i}: old_string and new_string must both be strings.",
                )
            if old == "":
                return self._tool_error(
                    "patch.bad_input", f"patch {i}: old_string must not be empty."
                )
            if old == new:
                return self._tool_error(
                    "patch.bad_input",
                    f"patch {i}: old_string and new_string are identical (no-op).",
                )
            if "replace_all" in entry and not isinstance(entry.get("replace_all"), bool):
                return self._tool_error(
                    "patch.bad_input", f"patch {i}: replace_all must be a boolean."
                )

        # 3) Apply in order against a WORKING copy — the stored submission is
        #    untouched until (and unless) the resubmission is attempted.
        working = pending["html"]
        for i, entry in enumerate(patches):
            old = entry["old_string"]
            new = entry["new_string"]
            replace_all = bool(entry.get("replace_all", False))
            count = working.count(old)
            if count == 0:
                return self._tool_error(
                    "patch.not_found",
                    f"patch {i}: old_string not found in the rejected markup (match "
                    "must be exact, including whitespace).",
                )
            if count > 1 and not replace_all:
                return self._tool_error(
                    "patch.ambiguous",
                    f"patch {i}: old_string occurs {count} times; make it unique with "
                    "more context or set replace_all.",
                )
            if replace_all:
                working = working.replace(old, new)
            else:
                working = working.replace(old, new, 1)

        # Belt-and-braces: a patch set that produced no textual change.
        if working == pending["html"]:
            return self._tool_error(
                "patch.bad_input", "patches did not change the markup."
            )

        # 4) Resubmit the patched markup through the SAME path as the original
        #    tool (page or subtree, same custom_css/node_id). Rejection updates
        #    the stored submission's html to the patched version so the next
        #    patch round iterates on it; success clears the pending rejection.
        submission: JsonObject = {
            "tool": pending["tool"],
            "html": working,
            "custom_css": pending["custom_css"],
            "node_id": pending["node_id"],
        }
        return self._submit_authoring(
            submission, origin="patch", patch_count=len(patches)
        )

    def _enclosing_section(
        self, node_id: str, nodes: JsonObject, root_children: List[str]
    ) -> Optional[str]:
        """Resolve `node_id` to the top-level section (root child) that
        contains it, or None if it is not in the page / has no enclosing
        section. A root child resolves to itself; a descendant walks up the
        parent chain until a root child is reached."""
        if node_id not in nodes:
            return None
        root_child_set = set(root_children)
        if node_id in root_child_set:
            return node_id
        parent_of: Dict[str, str] = {}
        for nid, node in nodes.items():
            if not isinstance(node, dict):
                continue
            for child in node.get("children") or []:
                parent_of[child] = nid
        current = node_id
        seen = set()
        while current in parent_of and current not in seen:
            seen.add(current)
            current = parent_of[current]
            if current in root_child_set:
                return current
        return None

    def _subtree_ids(self, nodes: JsonObject, root: str) -> set:
        """The id of `root` plus all its descendants in the page node map."""
        ids = set()
        stack = [root]
        while stack:
            current = stack.pop()
            node = nodes.get(current)
            if not isinstance(node, dict) or current in ids:
                continue
            ids.add(current)
            stack.extend(node.get("children") or [])
        return ids

    def _dedupe_fragment_ids(
        self,
        frag_nodes: List[JsonObject],
        frag_roots: List[str],
        reserved: set,
    ) -> tuple[List[JsonObject], List[str]]:
        """Rename fragment node ids that collide with `reserved` (doc ids that
        SURVIVE the splice) to fresh unique ids, rewriting `children` and the
        roots list. Ids NOT in `reserved` are kept — including the target
        section's own id and any descendant ids the author deliberately reused,
        since the remove frees them."""
        used = set(reserved) | {
            n.get("id") for n in frag_nodes if isinstance(n, dict)
        }
        rename: Dict[str, str] = {}
        for node in frag_nodes:
            if not isinstance(node, dict):
                continue
            nid = node.get("id")
            if nid in reserved:
                counter = 1
                candidate = f"{nid}_r{counter}"
                while candidate in used:
                    counter += 1
                    candidate = f"{nid}_r{counter}"
                used.add(candidate)
                rename[nid] = candidate
        if not rename:
            return frag_nodes, frag_roots
        remapped: List[JsonObject] = []
        for node in frag_nodes:
            if not isinstance(node, dict):
                remapped.append(node)
                continue
            clone = dict(node)
            if clone.get("id") in rename:
                clone["id"] = rename[clone["id"]]
            if clone.get("children"):
                clone["children"] = [rename.get(c, c) for c in clone["children"]]
            remapped.append(clone)
        new_roots = [rename.get(r, r) for r in frag_roots]
        return remapped, new_roots

    def _fragment_subtree(
        self, root: str, frag_nodes: List[JsonObject], frag_by_id: JsonObject
    ) -> List[JsonObject]:
        """The fragment nodes belonging to `root`'s subtree, in the fragment's
        own order (children before parents). The single-root common case
        returns every fragment node; a multi-root fragment is partitioned by
        walking each root's children."""
        ids = set()
        stack = [root]
        while stack:
            current = stack.pop()
            if current in ids or current not in frag_by_id:
                continue
            ids.add(current)
            stack.extend(frag_by_id[current].get("children") or [])
        return [
            n for n in frag_nodes if isinstance(n, dict) and n.get("id") in ids
        ]

    def web_ops(self, operations_json: str) -> str:
        """Apply a small batch of surgical operations to the page — the repair
        ladder's bottom rung, for one-or-a-few-line fixes.

        `operations_json` is a JSON array of op objects. The op grammar
        (page_id is ALWAYS "home" in v0):
          - set_node_classes {page_id:"home", id, classes} — replace a node's
            class string wholesale (it is NOT merged with the old one).
          - set_text {page_id:"home", id, content} — replace a text node's
            content (text nodes only).
          - set_node_props {page_id:"home", id, props:{kind:..., ...}} —
            replace a node's kind object; `props` is the FULL kind object (its
            `kind` tag plus every field), not a partial patch.
          - replace_asset {page_id:"home", id, asset_id} — repoint an image
            node at another already-registered asset.
          - move_node {page_id:"home", id, parent, index} — reparent/reorder.
          - remove_node {page_id:"home", id} — delete a node and its subtree.
          - insert_node {page_id:"home", parent, index, nodes, root} — splice
            a new subtree in.

        Button props are a UNION — a link or a trigger, never both:
          {kind:"button", label, variant, href:"...", new_tab:false}
          {kind:"button", label, variant, command:"show_modal"|"close",
           command_target:"<dialog node id>"}
        Op JSON uses snake_case ("show_modal") — unlike the authored HTML
        attribute (data-command="show-modal"). Rewiring a CTA to a dialog is
        ONE set_node_props with the trigger form.

        Use web_ops for a LOCALIZED fix (a bad class, reworded copy, a swapped
        href). A whole section that needs recomposition is `author_web_subtree`;
        a page that no longer serves the brief is `author_web_page`. Climb that
        ladder reluctantly — a bigger tool destroys human edits you were not
        asked to touch.

        The batch applies checked and atomically: any op that fails, or a batch
        that would leave the document invalid, is rejected WHOLE (nothing is
        stored) → {"status":"rejected", "diagnostics":[...]}. On success the
        working doc is replaced and {"status":"ok", "applied":n, "warnings":[…]}
        is returned."""
        refusal = self._consume_round_budget("web_ops")
        if refusal is not None:
            return refusal
        try:
            operations = json.loads(operations_json)
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            return self._tool_error(
                "web_ops.bad_json",
                f"operations must be a JSON array of op objects: {error}. Each op "
                'is like {"kind":"set_node_classes","page_id":"home","id":"…",'
                '"classes":"…"}.',
            )
        if (
            not isinstance(operations, list)
            or not operations
            or not all(isinstance(op, dict) for op in operations)
        ):
            return self._tool_error(
                "web_ops.bad_json",
                "operations must be a non-empty JSON array of op objects.",
            )

        try:
            response = self.core.web_apply_ops(self.web_doc, operations)
        except CoreError as error:
            diagnostics = list(error.diagnostics or [])
            code = getattr(error, "code", "") or ""
            # web_apply_ops raises for two very different reasons. A genuine
            # helper/infrastructure fault (process crash, unparseable response)
            # carries a `helper.*` code and is surfaced as a helper_error. A
            # rejected batch — an op that could not apply (`op.*`) or one that
            # would leave the document invalid (`op.validation_failed`) — is the
            # checked apply returning ok:false, which the client raises; that is
            # the caller's ops being refused, so it is a `rejected`, guiding the
            # author to fix the ops rather than the plumbing.
            if code.startswith("helper."):
                self.record(
                    "author",
                    "web_ops_rejected",
                    input_summary=operations_json[:200],
                    output_summary=f"helper error: {error.message}",
                    diagnostics=diagnostics,
                )
                return self._tool_error(
                    "web_ops.helper_error", error.message, diagnostics=diagnostics
                )
            if not diagnostics:
                diagnostics = [
                    {
                        "code": code or "op.rejected",
                        "message": error.message,
                        "severity": "error",
                    }
                ]
            self.record(
                "author",
                "web_ops_rejected",
                input_summary=operations_json[:200],
                output_summary=f"batch rejected: {error.message}",
                diagnostics=diagnostics,
            )
            return json.dumps(
                {"status": "rejected", "diagnostics": diagnostics}, indent=2
            )

        # Defensive: a non-raising ok:false path (raise_on_error is on today, so
        # this mirrors author_web_subtree's belt-and-braces reject guard).
        if not response.get("ok"):
            return json.dumps(
                {"status": "rejected", "diagnostics": response.get("diagnostics") or []},
                indent=2,
            )

        self.web_doc = response["web_doc"]
        self._doc_version += 1
        diagnostics = response.get("diagnostics") or []
        warnings = [
            d for d in diagnostics if isinstance(d, dict) and d.get("severity") != "error"
        ]
        kinds = [op.get("kind") for op in operations]
        applied = response.get("applied_operations") or len(operations)
        self.record(
            "author",
            "web_ops_applied",
            input_summary=operations_json[:200],
            output_summary=f"applied {applied} op(s): {kinds}",
            diagnostics=warnings,
            payload={"operation_count": applied, "kinds": kinds},
            sink_extra={"operation_count": applied},
        )
        return json.dumps(
            {"status": "ok", "applied": applied, "warnings": warnings}, indent=2
        )

    def asset(
        self,
        action: str,
        prompt: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        transparent_background: bool = False,
        label: Optional[str] = None,
        asset_id: Optional[str] = None,
        alt: Optional[str] = None,
    ) -> str:
        """Register an image the page can reference by `data-asset=<id>`.

        - action="generate_image" — generate a raster image from `prompt`
          (optional `aspect_ratio`/`width`/`height`, `transparent_background`,
          `label`) and register it. Returns the minted asset id.
        - action="use_brand_asset" — register one of the attached Brand Kit's
          assets by its `asset_id` (from the brand card inventory). Returns the
          asset id.
        - action="use_account_asset" — register the TARGET ACCOUNT's logo (from
          the account card). Takes no asset_id; returns the asset id. Carry it
          on an `<img data-slot="account.logo" data-asset="<id>">` so the page
          derives the right logo per account.

        Registration only — placement is markup: after this, reference the
        returned id with `<img data-asset="<id>" alt="…">` in author_web_page."""
        if action == "generate_image":
            if not prompt:
                return self._tool_error(
                    "asset.bad_request", "action='generate_image' requires `prompt`."
                )
            return self._generate_image(
                prompt, aspect_ratio, width, height, transparent_background, label, alt
            )
        if action == "use_brand_asset":
            if not asset_id:
                return self._tool_error(
                    "asset.bad_request",
                    "action='use_brand_asset' requires `asset_id` (from the brand "
                    "card's logo/image inventory).",
                )
            return self._use_brand_asset(asset_id, label, alt)
        if action == "use_account_asset":
            return self._use_account_asset(label, alt)
        return self._tool_error(
            "asset.unknown_action",
            f"unknown action '{action}'.",
            valid_actions=["generate_image", "use_brand_asset", "use_account_asset"],
        )

    def _generate_image_record(
        self,
        asset_id: str,
        prompt: str,
        label: str,
        width: Optional[int],
        height: Optional[int],
        aspect_ratio: Optional[str],
        transparent_background: bool,
    ) -> tuple[Optional[JsonObject], JsonObject, List[JsonObject]]:
        """Produce one image AssetRecord: prefer the configured T2I model, fall
        back to the deterministic stub provider (same request shape and provider
        handling substrate.generate_image uses). Returns (record, meta,
        diagnostics); record is None only on a hard stub failure."""
        diagnostics: List[JsonObject] = []
        store_root = str(self.config.effective_asset_store_root)

        # 1) Real text-to-image model, when configured.
        if image_provider is not None and image_provider.is_configured():
            try:
                result = image_provider.generate(
                    prompt=prompt,
                    width=width,
                    height=height,
                    brand_notes=None,
                    aspect_ratio=aspect_ratio,
                    transparent_background=transparent_background or None,
                    reference_images=None,
                    request_id=asset_id,
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
                    return record, {"mode": "model", "model": result.model}, diagnostics
            except Exception:  # noqa: BLE001 - degrade to the stub, never crash the turn
                pass

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
                "brand_notes": None,
            },
        }
        try:
            response = self.core.generate_asset(
                store_root=store_root,
                provider="stub-image-v0",
                request=request,
                asset_id=asset_id,
                label=label,
            )
        except CoreError as error:
            diagnostics.extend(list(error.diagnostics or []))
            return None, {"error": error.message}, diagnostics
        record = (response.get("asset") or {}).get("record") or {}
        return record, {"mode": "placeholder", "model": "stub-image-v0"}, diagnostics

    def _generate_image(
        self,
        prompt: str,
        aspect_ratio: Optional[str],
        width: Optional[int],
        height: Optional[int],
        transparent_background: bool,
        label: Optional[str],
        alt: Optional[str],
    ) -> str:
        asset_id = f"asset_img_web_{len(self.web_doc.get('assets') or {})}"
        resolved_label = label or (prompt[:60].strip() or asset_id)
        record, meta, diagnostics = self._generate_image_record(
            asset_id, prompt, resolved_label, width, height, aspect_ratio, transparent_background
        )
        if not record:
            return self._tool_error(
                "asset.image_failed",
                meta.get("error") or "image generation failed",
                diagnostics=diagnostics,
            )
        return self._register_asset_record(
            record,
            origin="generate_image",
            label=resolved_label,
            alt=alt,
            extra={"mode": meta.get("mode"), "model": meta.get("model")},
        )

    def _use_brand_asset(
        self, asset_id: str, label: Optional[str], alt: Optional[str]
    ) -> str:
        manifest = self.config.brand_kit_assets or {}
        entry = manifest.get(asset_id)
        if not isinstance(entry, dict):
            return self._tool_error(
                "asset.unknown_brand_asset",
                f"'{asset_id}' is not in the attached Brand Kit's asset manifest.",
                known_asset_ids=sorted(manifest.keys())[:12],
            )
        record = copy.deepcopy(entry.get("record") or {})
        if not record.get("id"):
            return self._tool_error(
                "asset.bad_manifest_record",
                f"the manifest entry for '{asset_id}' carries no usable record.",
            )
        resolved_label = label or entry.get("title") or record.get("label") or asset_id
        record["source"] = {
            "kind": "brand_guide",
            "source_asset_id": asset_id,
            "label": resolved_label,
        }
        return self._register_asset_record(
            record, origin="use_brand_asset", label=resolved_label, alt=alt, extra={}
        )

    def _use_account_asset(self, label: Optional[str], alt: Optional[str]) -> str:
        """P5 (D6): register the TARGET ACCOUNT's logo into the WebDoc — the
        account twin of `_use_brand_asset`. The account card names the logo by
        `logo_asset_id`; its engine AssetRecord rides in config.account_assets
        (resolved by the API by value, same as brand_kit_assets), so this never
        reads the API database. Errors honestly with no account card and with no
        logo."""
        if not self.account_card:
            return self._tool_error(
                "asset.no_account",
                "no target account is attached to this turn; use_account_asset "
                "is only available on a 1:1 account page.",
            )
        asset_id = self.account_card.get("logo_asset_id")
        manifest = self.config.account_assets or {}
        entry = manifest.get(asset_id) if asset_id else None
        if not asset_id or not isinstance(entry, dict):
            return self._tool_error(
                "asset.no_account_logo",
                "the target account has no resolvable logo asset — author the "
                "page without a logo image (the account name still personalizes "
                "it) or add a logo to the account.",
            )
        record = copy.deepcopy(entry.get("record") or {})
        if not record.get("id"):
            return self._tool_error(
                "asset.bad_account_record",
                f"the account logo entry for '{asset_id}' carries no usable record.",
            )
        resolved_label = (
            label or entry.get("title") or record.get("label") or asset_id
        )
        # `brand_guide` is the engine AssetSource variant for a guide-provided
        # library asset referenced by source_asset_id (same as use_brand_asset);
        # there is no dedicated account variant and minting one is an engine
        # change out of this wave's scope.
        record["source"] = {
            "kind": "brand_guide",
            "source_asset_id": asset_id,
            "label": resolved_label,
        }
        return self._register_asset_record(
            record, origin="use_account_asset", label=resolved_label, alt=alt, extra={}
        )

    def _register_asset_record(
        self,
        record: JsonObject,
        *,
        origin: str,
        label: str,
        alt: Optional[str],
        extra: JsonObject,
    ) -> str:
        """Upsert an AssetRecord into the WebDoc via the checked op path and
        replace the working doc. A rejected batch (invalid doc) never replaces
        the doc; a helper error surfaces verbatim."""
        try:
            response = self.core.web_apply_ops(
                self.web_doc, [{"kind": "upsert_asset", "record": record}]
            )
        except CoreError as error:
            self.record(
                "author",
                "web_asset_rejected",
                input_summary=f"{origin}:{record.get('id')}",
                output_summary=error.message,
                diagnostics=list(error.diagnostics or []),
            )
            return self._tool_error(
                "asset.upsert_rejected",
                error.message,
                asset_id=record.get("id"),
                diagnostics=list(error.diagnostics or []),
            )
        self.web_doc = response["web_doc"]
        self._doc_version += 1
        result: JsonObject = {
            "status": "ok",
            "asset_id": record.get("id"),
            "label": label,
        }
        if alt is not None:
            result["alt"] = alt
        result.update({k: v for k, v in extra.items() if v is not None})
        self.record(
            "author",
            "web_asset_registered",
            input_summary=f"{origin}:{record.get('id')}",
            output_summary=f"registered {record.get('id')} ({origin})",
            sink_extra={"asset_id": record.get("id")},
        )
        return json.dumps(result, indent=2)

    def _font_face_css(self) -> Optional[str]:
        """@font-face CSS embedding the kit's real font faces as data: URLs so
        the preview render shapes in the brand fonts, not the fallback stack.

        The spec is `self.config.brand_fonts` —
        ``{store_root, faces: [{digest, family, weight?, style?}]}``. Each face's
        bytes are read from ``{store_root}/sha256/{digest[:2]}/{digest}`` and
        inlined as ``data:<mime>;base64,…`` (mime by magic bytes) — Playwright
        renders via set_content with no asset server, so a URL src would not
        resolve. weight/style are OPTIONAL: a valid int 1..=1000 / a
        {normal,italic} enum is honored, else 400/normal.

        Unreadable or invalid faces are skipped (one summary warning event, not
        one per face); faces past the 8MB encoded-bytes cap are dropped (one
        warning event). Returns None when nothing resolves. Cached — fonts
        cannot change mid-run."""
        if self._font_face_css_cache is not _FONT_CSS_UNSET:
            return self._font_face_css_cache
        css = self._build_font_face_css()
        self._font_face_css_cache = css
        return css

    def _build_font_face_css(self) -> Optional[str]:
        spec = self.config.brand_fonts
        if not isinstance(spec, dict):
            return None
        store_root = spec.get("store_root")
        faces = spec.get("faces")
        if not isinstance(store_root, str) or not isinstance(faces, list):
            return None

        rules: List[str] = []
        seen: set = set()
        skipped: List[str] = []
        dropped_for_cap = 0
        total_encoded = 0
        for face in faces:
            if not isinstance(face, dict):
                continue
            digest = face.get("digest")
            family = face.get("family")
            if not (isinstance(family, str) and family.strip()):
                continue
            if not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
                skipped.append(str(digest))
                continue
            key = (family, digest)
            if key in seen:
                continue
            path = Path(store_root) / "sha256" / digest[:2] / digest
            try:
                data = path.read_bytes()
            except Exception:  # noqa: BLE001 - unreadable face is skipped-but-recorded
                skipped.append(digest)
                continue
            b64 = base64.b64encode(data).decode("ascii")
            if total_encoded + len(b64) > _FONT_FACE_CSS_MAX_BYTES:
                dropped_for_cap += 1
                continue
            total_encoded += len(b64)
            seen.add(key)
            mime = _font_mime_from_magic(data)
            weight = face.get("weight") if _valid_font_weight(face.get("weight")) else 400
            style = face.get("style") if _valid_font_style(face.get("style")) else "normal"
            rules.append(
                "@font-face{"
                f"font-family:{json.dumps(family)};"
                f"font-style:{style};font-weight:{weight};font-display:swap;"
                f"src:url(data:{mime};base64,{b64});"
                "}"
            )

        if skipped:
            self.record(
                "orchestrator",
                "web_font_faces_skipped",
                output_summary=f"skipped {len(skipped)} unreadable/invalid font face(s)",
                payload={"digests": skipped},
            )
        if dropped_for_cap:
            self.record(
                "orchestrator",
                "web_font_faces_capped",
                output_summary=(
                    f"dropped {dropped_for_cap} font face(s) past the "
                    f"{_FONT_FACE_CSS_MAX_BYTES}-byte encoded cap"
                ),
            )
        if not rules:
            return None
        return "\n".join(rules)

    def _browser_handle(self):
        """The shared headless chromium, started lazily and kept alive across
        renders (a fresh launch per render dominates web-turn latency). Started
        on first use via `sync_playwright().start()`; torn down by
        `_close_browser()` at finalize. Raises if Playwright is unavailable."""
        if self._browser is not None:
            return self._browser
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        return self._browser

    def _close_browser(self) -> None:
        """Tear down the shared browser + Playwright instance. Idempotent and
        exception-safe: each of `browser.close()` / `pw.stop()` is best-effort
        and the handles are reset to None regardless (a partially-torn-down
        browser must not leave a stale handle that a later render reuses)."""
        browser, pw = self._browser, self._pw
        self._browser = None
        self._pw = None
        if browser is not None:
            try:
                browser.close()
            except Exception:  # noqa: BLE001 - teardown is best-effort
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:  # noqa: BLE001 - teardown is best-effort
                pass

    @staticmethod
    def _looks_like_dead_browser(error: Exception) -> bool:
        """True when a Playwright exception looks like the kept-alive browser
        died (closed/crashed connection) — the one case worth relaunching and
        retrying the capture pass once, rather than failing the render."""
        text = f"{type(error).__name__}: {error}".lower()
        return any(
            marker in text
            for marker in (
                "target page, context or browser has been closed",
                "browser has been closed",
                "browser closed",
                "connection closed",
                "targetclosederror",
                "browser has crashed",
                "has crashed",
            )
        )

    def render_web_preview(self) -> str:
        """Render the live document (editor mode) and capture full-page
        screenshots at 1440, 768, and 375 px, plus interactive STATE captures
        (dialogs opened, accordions expanded, nav menu opened, tabs switched) at
        the state widths. Look at them with view("preview:<width>") and
        view("state:<n>"). Returns the screenshot paths, the state-capture list,
        and any render diagnostics.

        Unchanged-render guard (the L4b analogue): if the document has not
        mutated since the last successful render (identical doc ⇒ identical
        pixels, deterministically), the standing previews are reused verbatim —
        no helper call, no Playwright, no iteration bump — and the result
        carries `unchanged: true` so the orchestrator reuses its standing
        critique instead of re-reviewing byte-identical pixels."""
        # A render call means control is back with the orchestrator: open a
        # fresh between-renders edit budget for the next author round.
        self._mutations_since_render = 0
        self._round_budget_event_recorded = False
        # Feature 2 — unchanged-render guard. A doc with no mutation since the
        # last render whose previews are all still on hand is reused verbatim.
        if (
            self._preview_doc_version is not None
            and self._preview_doc_version == self._doc_version
            and all(width in self._preview_by_width for width in _PREVIEW_WIDTHS)
        ):
            paths = [self._preview_by_width[width] for width in _PREVIEW_WIDTHS]
            self.record(
                "orchestrator",
                "web_preview_unchanged",
                output_summary=(
                    f"doc unchanged since iteration {self._preview_iteration}; "
                    f"reusing {len(paths)} standing preview(s)"
                ),
            )
            return json.dumps(
                {
                    "status": "ok",
                    "preview_paths": paths,
                    "state_captures": list(self._state_captures),
                    "diagnostics": [],
                    "unchanged": True,
                },
                indent=2,
            )

        self.iteration += 1
        iter_dir = self.trace_dir / f"iter_{self.iteration}"
        iter_dir.mkdir(parents=True, exist_ok=True)

        try:
            response = self.core.web_render(
                self.web_doc,
                self.page_id,
                mode="editor",
                asset_base_url=self.asset_base_url,
                tailwind_runtime_src=None,
                brand_kit=self.config.brand_kit,
                font_face_css=self._font_face_css(),
            )
        except CoreError as error:
            self.record(
                "orchestrator",
                "web_preview_render_failed",
                output_summary=error.message,
                diagnostics=list(error.diagnostics or []),
            )
            return self._tool_error(
                "web_render.failed", error.message, diagnostics=list(error.diagnostics or [])
            )

        html = response.get("html") or ""
        diagnostics = response.get("diagnostics") or []

        # Inline the vendored Tailwind browser runtime so the editor-mode
        # `<style type="text/tailwindcss">` block is processed at set_content
        # time (the runtime scans on load). Absent → render bare + warn.
        tailwind_missing = False
        runtime_path = (
            Path(self.config.repo_root)
            / "apps"
            / "editor"
            / "public"
            / "vendor"
            / "tailwind-browser.js"
        )
        if runtime_path.exists():
            script = "<script>" + runtime_path.read_text(encoding="utf-8") + "</script>"
            if "</head>" in html:
                html = html.replace("</head>", script + "\n</head>", 1)
            else:
                html = script + html
        else:
            tailwind_missing = True

        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except Exception as error:  # noqa: BLE001
            return self._tool_error(
                "web_preview.playwright_unavailable",
                f"playwright is not available: {error}",
                diagnostics=diagnostics,
            )

        # The capture pass runs on the shared, kept-alive browser. If it dies
        # (closed/crashed connection), close + relaunch ONCE and retry before
        # surfacing the failure.
        try:
            try:
                paths, state_capture_error, state_omitted = self._capture_pass(
                    html, iter_dir, diagnostics
                )
            except Exception as error:  # noqa: BLE001
                if self._looks_like_dead_browser(error):
                    self._close_browser()
                    paths, state_capture_error, state_omitted = self._capture_pass(
                        html, iter_dir, diagnostics
                    )
                else:
                    raise
        except Exception as error:  # noqa: BLE001 - turn-safety boundary
            self.record(
                "orchestrator",
                "web_preview_render_failed",
                output_summary=f"screenshot capture failed: {error}",
                diagnostics=diagnostics,
            )
            return self._tool_error(
                "web_preview.capture_failed",
                f"screenshot capture failed: {error}",
                diagnostics=diagnostics,
            )

        self.preview_paths.extend(paths)
        self._preview_iteration = self.iteration
        self._preview_doc_version = self._doc_version

        result: JsonObject = {
            "status": "ok",
            "preview_paths": paths,
            "state_captures": list(self._state_captures),
            "diagnostics": diagnostics,
        }
        if tailwind_missing:
            result["tailwind_runtime_missing"] = True
        if state_capture_error is not None:
            result["state_capture_error"] = state_capture_error
        omitted_nonempty = {k: v for k, v in (state_omitted or {}).items() if v}
        if omitted_nonempty:
            result["state_captures_omitted"] = omitted_nonempty
        self.record(
            "orchestrator",
            "web_preview_rendered",
            output_summary=(
                f"iteration {self.iteration}: {len(paths)} screenshot(s), "
                f"{len(self._state_captures)} state capture(s)"
            ),
            diagnostics=diagnostics,
        )
        return json.dumps(result, indent=2)

    def _capture_pass(
        self, html: str, iter_dir: Path, diagnostics: List[JsonObject]
    ) -> tuple[List[str], Optional[str], JsonObject]:
        """One full capture pass on the shared browser: the base previews at
        each `_PREVIEW_WIDTH`, then the best-effort interactive STATE captures.

        Returns ``(paths, state_capture_error, omitted)``. A Playwright fault in
        the base-preview loop PROPAGATES (so render's dead-browser retry can
        relaunch and rerun the whole pass); a state-capture failure degrades to
        a recorded warning + a `state_capture_error` string and NEVER voids the
        base previews. `omitted` is ``{"dialogs": [...], "tabs": [...]}``."""
        browser = self._browser_handle()
        paths: List[str] = []
        # Reset per pass so a dead-browser retry does not accumulate stale
        # captures on top of a half-finished first attempt.
        self._state_captures = []
        for width in _PREVIEW_WIDTHS:
            page = browser.new_page(viewport={"width": width, "height": 1200})
            page.set_content(html, wait_until="load")
            page.wait_for_timeout(400)
            dest = iter_dir / f"preview_{width}.png"
            page.screenshot(path=str(dest), full_page=True)
            page.close()
            paths.append(str(dest))
            self._preview_by_width[width] = str(dest)

        state_capture_error: Optional[str] = None
        omitted: JsonObject = {"dialogs": [], "tabs": []}
        try:
            omitted = self._capture_states(browser, html, iter_dir)
        except Exception as error:  # noqa: BLE001 - degrade, keep base previews
            state_capture_error = f"{type(error).__name__}: {error}"
            self.record(
                "orchestrator",
                "web_state_capture_warning",
                output_summary=f"state capture degraded: {state_capture_error}",
                diagnostics=diagnostics,
            )
        return paths, state_capture_error, omitted

    def _capture_states(self, browser, html: str, iter_dir: Path) -> JsonObject:
        """Take the interactive STATE screenshots for this render, appending each
        to `self._state_captures`. Uses the already-open Playwright `browser`.

        Per dialog (first _MAX_DIALOG_CAPTURES only), per state width: a fresh
        page shows the dialog via `showModal()` and a VIEWPORT screenshot is
        taken (the dialog lives in the top layer over the viewport). If any
        accordion exists, per width one FULL-page screenshot is taken with every
        NON-nav `<details>` forced open (a nav hamburger is captured separately).
        If a nav_menu exists, ONE capture at 375px opens just the nav dropdown
        (a VIEWPORT screenshot — the dropdown is viewport-anchored). Per tabs
        component (first _MAX_TABS_CAPTURES only), ONE capture at 1440px clicks
        the SECOND tab and takes a FULL-page screenshot.

        Returns ``{"dialogs": [...], "tabs": [...]}`` — the ids beyond each cap
        (omitted, never dropped silently)."""
        plan = _interactive_capture_plan(self.web_doc)
        dialogs = plan["dialogs"]
        captured_dialogs = dialogs[:_MAX_DIALOG_CAPTURES]
        omitted_dialogs = dialogs[_MAX_DIALOG_CAPTURES:]
        tabs = plan["tabs"]
        captured_tabs = tabs[:_MAX_TABS_CAPTURES]
        omitted_tabs = tabs[_MAX_TABS_CAPTURES:]

        for node_id in captured_dialogs:
            for width in _STATE_WIDTHS:
                page = browser.new_page(viewport={"width": width, "height": 1200})
                page.set_content(html, wait_until="load")
                page.wait_for_timeout(250)
                page.evaluate(
                    "(id) => { const el = document.getElementById(id); "
                    "if (el && el.tagName === 'DIALOG') el.showModal(); }",
                    node_id,
                )
                page.wait_for_timeout(250)
                dest = iter_dir / f"state_{width}_dialog_{node_id}.png"
                page.screenshot(path=str(dest), full_page=False)
                page.close()
                self._state_captures.append(
                    {
                        "kind": "dialog-open",
                        "node_id": node_id,
                        "width": width,
                        "path": str(dest),
                    }
                )

        if plan["has_accordion"]:
            for width in _STATE_WIDTHS:
                page = browser.new_page(viewport={"width": width, "height": 1200})
                page.set_content(html, wait_until="load")
                page.wait_for_timeout(250)
                # Scope to non-nav details so opening accordions never also flips
                # a nav hamburger open (which has its own dedicated capture).
                page.evaluate(
                    "() => document.querySelectorAll('details:not(.lumen-nav-menu)')"
                    ".forEach(d => { d.open = true; })"
                )
                page.wait_for_timeout(250)
                dest = iter_dir / f"state_{width}_accordion.png"
                page.screenshot(path=str(dest), full_page=True)
                page.close()
                self._state_captures.append(
                    {
                        "kind": "accordion-expanded",
                        "node_id": None,
                        "width": width,
                        "path": str(dest),
                    }
                )

        if plan["has_nav"]:
            # The nav hamburger is only visible below 768px; capture the open
            # dropdown at 375px. A VIEWPORT screenshot — the dropdown is
            # viewport-anchored, not part of the full-page flow.
            page = browser.new_page(viewport={"width": 375, "height": 1200})
            page.set_content(html, wait_until="load")
            page.wait_for_timeout(250)
            page.evaluate(
                "() => document.querySelectorAll('details.lumen-nav-menu')"
                ".forEach(d => { d.open = true; })"
            )
            page.wait_for_timeout(250)
            dest = iter_dir / "state_375_nav_open.png"
            page.screenshot(path=str(dest), full_page=False)
            page.close()
            self._state_captures.append(
                {
                    "kind": "nav-open",
                    "node_id": None,
                    "width": 375,
                    "path": str(dest),
                }
            )

        for node_id in captured_tabs:
            # Switch to the SECOND tab (the first is the default panel) at
            # desktop width and capture the full page.
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            page.set_content(html, wait_until="load")
            page.wait_for_timeout(250)
            page.evaluate(
                "(id) => { const root = document.querySelector("
                "'[data-node-id=\"' + id + '\"]'); const tabs = root ? "
                "root.querySelectorAll('[role=\"tab\"]') : []; "
                "if (tabs[1]) tabs[1].click(); }",
                node_id,
            )
            page.wait_for_timeout(250)
            dest = iter_dir / f"state_1440_tabs_{node_id}.png"
            page.screenshot(path=str(dest), full_page=True)
            page.close()
            self._state_captures.append(
                {
                    "kind": "tab-selected",
                    "node_id": node_id,
                    "width": 1440,
                    "path": str(dest),
                }
            )

        if omitted_dialogs:
            self.record(
                "orchestrator",
                "web_state_capture_omitted",
                output_summary=(
                    f"{len(omitted_dialogs)} dialog(s) beyond the "
                    f"{_MAX_DIALOG_CAPTURES}-capture cap were not captured"
                ),
                payload={"omitted_dialog_ids": omitted_dialogs},
            )
        if omitted_tabs:
            self.record(
                "orchestrator",
                "web_state_capture_omitted",
                output_summary=(
                    f"{len(omitted_tabs)} tabs component(s) beyond the "
                    f"{_MAX_TABS_CAPTURES}-capture cap were not captured"
                ),
                payload={"omitted_tabs_ids": omitted_tabs},
            )
        return {"dialogs": omitted_dialogs, "tabs": omitted_tabs}

    def _view_content(self, target: str, can_render: bool = True) -> list:
        """Build the ToolMessage content for view(target). See make_web_view_tool.

        `can_render` says whether the CALLING ROLE also owns render_web_preview
        (orchestrator: yes; author/reviewer subagents: no). The stale/no-preview
        refusals must never instruct a role to call a tool it does not have —
        live failure 2026-07-29: an author churned blind for 14 minutes retrying
        stale views because the refusal said "call render_web_preview() first"."""
        if target == "brand":
            self.record("agent", "web_view_called", input_summary=target, output_summary="brand")
            return [_text_block(self.brand_card_text)]
        if target == "account":
            self.record("agent", "web_view_called", input_summary=target, output_summary="account")
            return [
                _text_block(
                    self.account_card_text
                    if self.account_card_text
                    else "No target account is attached to this turn."
                )
            ]
        if target == "doc":
            self.record("agent", "web_view_called", input_summary=target, output_summary="doc")
            return [_text_block(self._doc_summary_text())]
        if target.startswith("preview:"):
            width_str = target[len("preview:") :]
            if width_str not in {"1440", "768", "375"}:
                self.record(
                    "agent", "web_view_called", input_summary=target, output_summary="unknown_width"
                )
                return [
                    _text_block(
                        f"view: unknown preview width {width_str!r}. Use "
                        "preview:1440, preview:768, or preview:375."
                    )
                ]
            width = int(width_str)
            path = self._preview_by_width.get(width)
            if path is None or not Path(path).exists():
                self.record(
                    "agent", "web_view_called", input_summary=target, output_summary="no_preview"
                )
                return [
                    _text_block(
                        "view: no preview rendered yet — call render_web_preview() first."
                        if can_render
                        else "view: no preview rendered yet. Previews are produced "
                        "between rounds, not by you — use view(\"doc\") for structure, "
                        "finish your work, and end your reply."
                    )
                ]
            if (
                self._preview_doc_version is not None
                and self._doc_version > self._preview_doc_version
            ):
                self.record(
                    "agent", "web_view_called", input_summary=target, output_summary="stale"
                )
                return [
                    _text_block(
                        "view: preview is STALE — the document changed since the last "
                        "render. Call render_web_preview() first, then view again."
                        if can_render
                        else "view: preview is STALE — the document changed since the "
                        "last render, and previews only refresh AFTER your round ends. "
                        "Do NOT keep editing to chase a fresh preview. Finish your "
                        "remaining changes, then END YOUR REPLY with a summary; the "
                        "orchestrator re-renders and the reviewer judges the result."
                    )
                ]
            self.record(
                "agent", "web_view_called", input_summary=target, output_summary="blocks=2"
            )
            return [
                _text_block(
                    f"view: latest preview at {width}px (iteration {self._preview_iteration})"
                ),
                _image_block(Path(path)),
            ]
        if target.startswith("state:"):
            return self._view_state(target)
        self.record(
            "agent", "web_view_called", input_summary=target, output_summary="unknown_target"
        )
        return [
            _text_block(
                f"view: unknown target {target!r}. Use \"preview:1440\", "
                '"preview:768", "preview:375", "state:<n>", "doc", "brand", or '
                '"account".'
            )
        ]

    def _view_state(self, target: str) -> list:
        """Build the view content for a `state:<n>` target — the nth interactive
        STATE capture (0-based) from the latest render, as [text, image] blocks.
        An unparseable or out-of-range index returns an honest text-only error
        naming how many captures exist."""
        index_str = target[len("state:") :]
        try:
            index = int(index_str)
        except ValueError:
            self.record(
                "agent", "web_view_called", input_summary=target, output_summary="bad_state_index"
            )
            return [
                _text_block(
                    f"view: state index {index_str!r} is not an integer. Use "
                    "state:0, state:1, … (0-based)."
                )
            ]
        captures = self._state_captures
        if not captures:
            self.record(
                "agent", "web_view_called", input_summary=target, output_summary="no_state"
            )
            return [
                _text_block(
                    "view: no state captures available — call render_web_preview() "
                    "first (state captures need an interactive component in the page)."
                )
            ]
        if index < 0 or index >= len(captures):
            self.record(
                "agent", "web_view_called", input_summary=target, output_summary="state_out_of_range"
            )
            return [
                _text_block(
                    f"view: state index {index} out of range — there are "
                    f"{len(captures)} state capture(s) (0..{len(captures) - 1})."
                )
            ]
        capture = captures[index]
        path = capture.get("path")
        if not path or not Path(path).exists():
            self.record(
                "agent", "web_view_called", input_summary=target, output_summary="state_missing_file"
            )
            return [_text_block(f"view: state capture {index} has no readable screenshot.")]
        node = capture.get("node_id")
        node_note = f" node {node}" if node else ""
        self.record(
            "agent", "web_view_called", input_summary=target, output_summary="blocks=2"
        )
        return [
            _text_block(
                f"view: state capture {index} — {capture.get('kind')}"
                f"{node_note} at {capture.get('width')}px"
            ),
            _image_block(Path(path)),
        ]

    def finalize_web_run(
        self, outcome: str, summary: str, ladder_gap: Optional[str] = None
    ) -> str:
        """End the turn. `outcome` is accepted | completed_with_warnings |
        failed; `summary` is the user-facing note. Writes the run's final.json
        and final_web_doc.json.

        `ladder_gap` (optional) names a capability the component catalogue could
        NOT express this turn — the escalation ladder's demand signal (e.g. a
        carousel, a tabbed panel, a filterable grid you had to approximate or
        omit). When present, it is recorded to final.json AND emitted as a
        dedicated `ladder_gap` trace event so the demand for new components is
        measurable across runs. Leave it None when the catalogue sufficed."""
        valid = {"accepted", "completed_with_warnings", "failed"}
        if outcome not in valid:
            return self._tool_error(
                "finalize.bad_outcome",
                f"outcome must be one of {sorted(valid)}; got {outcome!r}.",
            )
        # The turn is ending on every valid outcome — release the kept-alive
        # browser so no Playwright process outlives the run.
        self._close_browser()
        payload: JsonObject = {"outcome": outcome, "summary": summary}
        gap = (ladder_gap or "").strip()
        if gap:
            payload["ladder_gap"] = gap
        self._write_json(self.trace_dir / "final.json", payload)
        self._write_json(self.trace_dir / "final_web_doc.json", self.web_doc)
        self.record(
            "coordinator",
            "web_run_finalized",
            output_summary=f"{outcome}: {summary[:200]}",
            payload=payload,
        )
        if gap:
            self.record(
                "coordinator",
                "ladder_gap",
                output_summary=gap,
                payload={"ladder_gap": gap},
            )
        return json.dumps({"status": "ok", **payload}, indent=2)

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def make_web_view_tool(tools: LumenWebTools, can_render: bool = True):
    """The `view` tool for a website turn: real pixels + doc/brand context.

    `can_render=False` builds the variant handed to the author/reviewer
    subagents: identical behavior except the stale/no-preview refusals, which
    must not tell those roles to call render_web_preview (orchestrator-only).

    target="preview:1440"|"preview:768"|"preview:375" returns the latest
    screenshot of that width as [text, image] blocks; "state:<n>" returns the
    nth interactive STATE capture (dialog opened / accordion expanded) from the
    latest render; "doc" returns a compact section/asset summary; "brand"
    returns the brand card; "account" returns the target account card (P5).
    Mirrors tools/view.make_view_tool: any failure inside returns an honest error
    STRING so a bad/unreadable image can never kill the turn unfinalized."""
    from langchain_core.tools import tool
    from py_lumen_obs import log_span

    @tool
    def view(target: str) -> list:
        """Look at the page. target="preview:1440" / "preview:768" /
        "preview:375" returns the latest rendered screenshot at that width;
        "state:<n>" returns the nth interactive STATE capture (0-based: a dialog
        opened or accordions expanded) from the latest render; "doc" returns a
        section + asset summary; "brand" returns the brand card; "account"
        returns the target account card. Returns image content so you judge by
        looking, not guessing."""
        try:
            with log_span("tool_web_view", logger=logger, target=target):
                return tools._view_content(target, can_render=can_render)
        except Exception as exc:  # noqa: BLE001 - turn-safety boundary
            try:
                tools.record(
                    "agent",
                    "web_view_called",
                    input_summary=target,
                    output_summary=f"view_failed: {type(exc).__name__}",
                )
            except Exception:  # pragma: no cover
                pass
            return f"view failed: {exc}"

    return view

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
        self.preview_paths: List[str] = []
        # The latest screenshot path per width + the iteration that produced it.
        self._preview_by_width: Dict[int, str] = {}
        self._preview_iteration: Optional[int] = None
        # Staleness contract (mirrors the scene view): a monotonic doc-mutation
        # count, and the count stamped at the last successful render. view()
        # refuses a preview older than the current doc.
        self._doc_version = 0
        self._preview_doc_version: Optional[int] = None

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
        installed node count is returned."""
        try:
            response = self.core.web_ingest_html(
                self.web_doc,
                self.page_id,
                html,
                custom_css or None,
                brand_kit=self.config.brand_kit,
            )
        except CoreError as error:
            self.record(
                "author",
                "web_page_rejected",
                input_summary=html[:200],
                output_summary=error.message,
                diagnostics=list(error.diagnostics or []),
            )
            return self._tool_error(
                "web_author.helper_error",
                error.message,
                diagnostics=list(error.diagnostics or []),
            )

        diagnostics = response.get("diagnostics") or []
        errors = [d for d in diagnostics if isinstance(d, dict) and d.get("severity") == "error"]
        if errors:
            self.record(
                "author",
                "web_page_rejected",
                input_summary=html[:200],
                output_summary=f"{len(errors)} error diagnostic(s); page not stored",
                diagnostics=diagnostics,
            )
            return json.dumps(
                {"status": "rejected", "diagnostics": diagnostics}, indent=2
            )

        self.web_doc = response["web_doc"]
        self._doc_version += 1
        installed = response.get("applied_operations")
        warnings = [
            d for d in diagnostics if isinstance(d, dict) and d.get("severity") != "error"
        ]
        self.record(
            "author",
            "web_page_authored",
            input_summary=html[:200],
            output_summary=(
                f"installed {installed} node(s); page now {self._page_node_count()} nodes"
            ),
            diagnostics=warnings,
            sink_extra={"installed_nodes": installed},
        )
        return json.dumps(
            {"status": "ok", "installed_nodes": installed, "warnings": warnings},
            indent=2,
        )

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
        """
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
            self.record(
                "author",
                "web_subtree_rejected",
                input_summary=f"{node_id}->{target_section}: {html[:160]}",
                output_summary=error.message,
                diagnostics=list(error.diagnostics or []),
            )
            return self._tool_error(
                "web_subtree.helper_error",
                error.message,
                diagnostics=list(error.diagnostics or []),
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
            self.record(
                "author",
                "web_subtree_rejected",
                input_summary=f"{node_id}->{target_section}",
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
            self.record(
                "author",
                "web_subtree_rejected",
                input_summary=f"{node_id}->{target_section}",
                output_summary=f"{len(errors)} error diagnostic(s); section not changed",
                diagnostics=diagnostics,
            )
            return json.dumps(
                {"status": "rejected", "diagnostics": diagnostics}, indent=2
            )

        if not frag_roots:
            # A clean parse that produced no sections (e.g. empty markup): there
            # is nothing to splice — same remedy as a non-section root.
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
            self.record(
                "author",
                "web_subtree_rejected",
                input_summary=f"{node_id}->{target_section}",
                output_summary=error.message,
                diagnostics=list(error.diagnostics or []),
            )
            return json.dumps(
                {"status": "rejected", "diagnostics": list(error.diagnostics or [])},
                indent=2,
            )
        if not applied.get("ok"):
            return json.dumps(
                {"status": "rejected", "diagnostics": applied.get("diagnostics") or []},
                indent=2,
            )

        self.web_doc = applied["web_doc"]
        self._doc_version += 1
        warnings = [
            d for d in diagnostics if isinstance(d, dict) and d.get("severity") != "error"
        ]
        self.record(
            "author",
            "web_subtree_authored",
            input_summary=f"{node_id}->{target_section}",
            output_summary=f"replaced section {target_section} with {frag_roots}",
            diagnostics=warnings,
            payload={"section": target_section, "replaced_with": frag_roots},
            sink_extra={"section": target_section},
        )
        return json.dumps(
            {
                "status": "ok",
                "section": target_section,
                "roots": frag_roots,
                "warnings": warnings,
            },
            indent=2,
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
        return self._tool_error(
            "asset.unknown_action",
            f"unknown action '{action}'.",
            valid_actions=["generate_image", "use_brand_asset"],
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

    def render_web_preview(self) -> str:
        """Render the live document (editor mode) and capture full-page
        screenshots at 1440, 768, and 375 px. Look at them with
        view("preview:<width>"). Returns the screenshot paths and any render
        diagnostics."""
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
            from playwright.sync_api import sync_playwright
        except Exception as error:  # noqa: BLE001
            return self._tool_error(
                "web_preview.playwright_unavailable",
                f"playwright is not available: {error}",
                diagnostics=diagnostics,
            )

        paths: List[str] = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    for width in _PREVIEW_WIDTHS:
                        page = browser.new_page(viewport={"width": width, "height": 1200})
                        page.set_content(html, wait_until="load")
                        page.wait_for_timeout(400)
                        dest = iter_dir / f"preview_{width}.png"
                        page.screenshot(path=str(dest), full_page=True)
                        page.close()
                        paths.append(str(dest))
                        self._preview_by_width[width] = str(dest)
                finally:
                    browser.close()
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
            "diagnostics": diagnostics,
        }
        if tailwind_missing:
            result["tailwind_runtime_missing"] = True
        self.record(
            "orchestrator",
            "web_preview_rendered",
            output_summary=f"iteration {self.iteration}: {len(paths)} screenshot(s)",
            diagnostics=diagnostics,
        )
        return json.dumps(result, indent=2)

    def _view_content(self, target: str) -> list:
        """Build the ToolMessage content for view(target). See make_web_view_tool."""
        if target == "brand":
            self.record("agent", "web_view_called", input_summary=target, output_summary="brand")
            return [_text_block(self.brand_card_text)]
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
        self.record(
            "agent", "web_view_called", input_summary=target, output_summary="unknown_target"
        )
        return [
            _text_block(
                f"view: unknown target {target!r}. Use \"preview:1440\", "
                '"preview:768", "preview:375", "doc", or "brand".'
            )
        ]

    def finalize_web_run(self, outcome: str, summary: str) -> str:
        """End the turn. `outcome` is accepted | completed_with_warnings |
        failed; `summary` is the user-facing note. Writes the run's final.json
        and final_web_doc.json."""
        valid = {"accepted", "completed_with_warnings", "failed"}
        if outcome not in valid:
            return self._tool_error(
                "finalize.bad_outcome",
                f"outcome must be one of {sorted(valid)}; got {outcome!r}.",
            )
        payload = {"outcome": outcome, "summary": summary}
        self._write_json(self.trace_dir / "final.json", payload)
        self._write_json(self.trace_dir / "final_web_doc.json", self.web_doc)
        self.record(
            "coordinator",
            "web_run_finalized",
            output_summary=f"{outcome}: {summary[:200]}",
            payload=payload,
        )
        return json.dumps({"status": "ok", **payload}, indent=2)

    def _write_json(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def make_web_view_tool(tools: LumenWebTools):
    """The `view` tool for a website turn: real pixels + doc/brand context.

    target="preview:1440"|"preview:768"|"preview:375" returns the latest
    screenshot of that width as [text, image] blocks; "doc" returns a compact
    section/asset summary; "brand" returns the brand card. Mirrors
    tools/view.make_view_tool: any failure inside returns an honest error STRING
    so a bad/unreadable image can never kill the turn unfinalized."""
    from langchain_core.tools import tool
    from py_lumen_obs import log_span

    @tool
    def view(target: str) -> list:
        """Look at the page. target="preview:1440" / "preview:768" /
        "preview:375" returns the latest rendered screenshot at that width;
        "doc" returns a section + asset summary; "brand" returns the brand
        card. Returns image content so you judge by looking, not guessing."""
        try:
            with log_span("tool_web_view", logger=logger, target=target):
                return tools._view_content(target)
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

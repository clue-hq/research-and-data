"""The D6 no-bypass guard (ruling R-D6-6): converted domains have exactly ONE write path.

D6's gate is "every design mutation behind a registered, precondition-checked, idempotency-keyed
tool". A tool that exists is not a tool that is *used*, so the gate needs a mechanical statement
that nothing still writes around it.

**The rule.** For each governed name below, every *call site* anywhere under
``lumen_api/`` + ``lumen_ingestion/`` must live in one of that name's allowed modules. Two kinds
of name are governed:

* a **store mutation** (``HybridRepository.register_web_publish_revision``, …) — an attribute
  call ``<something>.<name>(``. Allowed in ``design_store.py`` (where the method is defined) and
  in ``lumen_api/toolbelt/`` (the tool operation cores).
* an **operation core** (``persist_custom_component_source_revision``, …) — a bare call
  ``<name>(``, excluding its own ``def``. Allowed in its defining module and in
  ``lumen_api/toolbelt/``.

A route handler, the batch loop, the fleet handler, the ingestion pipeline and the deep agent's
component registry are therefore all *excluded by construction* — if any of them regains a direct
mutation, this test names the file and the line.

**Extending it is one edit.** A new domain adds its methods to ``_GOVERNED`` (and, if it
introduces one, the operation-core module that owns them). Nothing else changes.

**Round C closed the list.** Rounds A and B deferred brand kits, ingestion, the asset registry,
personalization and both batch families; all of them are governed here now, and
``UNCONVERTED_MUTATIONS`` has shrunk from "the scheduled backlog" to one closed *exemption* —
the three run-lifecycle writes of the execution plane, which the fleet lease arbitrates rather
than the toolbelt (D8 deleted a fourth, ``set_run_result``, for having no caller at all). ``test_unconverted_domains_are_explicitly_listed`` asserts that set exactly,
so a later round cannot quietly park a new ungoverned write beside them.
"""

from __future__ import annotations

import re
from pathlib import Path

from lumen_api.toolbelt import DESIGN_TOOL_NAMES

API_ROOT = Path(__file__).resolve().parents[1]
LUMEN_API = API_ROOT / "lumen_api"
LUMEN_INGESTION = API_ROOT / "lumen_ingestion"

#: Where a governed name may legally be called from. ``toolbelt`` means any module under
#: ``lumen_api/toolbelt/`` — the tools and their operation cores.
_TOOLBELT = "lumen_api/toolbelt/"

# name -> (kind, extra allowed module paths relative to apps/api)
_GOVERNED: dict[str, tuple[str, tuple[str, ...]]] = {
    # --- Round A domain 1: publishes -----------------------------------------------------
    "register_web_publish_revision": ("method", ("lumen_api/design_store.py",)),
    "upsert_web_publish": ("method", ("lumen_api/design_store.py",)),
    "set_web_publish_status": ("method", ("lumen_api/design_store.py",)),
    "rollback_web_publish": ("method", ("lumen_api/design_store.py",)),
    "build_publish_package": ("function", ("lumen_api/web_export.py",)),
    "persist_publish_assets": ("function", ("lumen_api/web_export.py",)),
    # --- Round A domain 2: personalization accounts --------------------------------------
    "create_web_account": ("method", ("lumen_api/design_store.py",)),
    "update_web_account": ("method", ("lumen_api/design_store.py",)),
    "delete_web_account": ("method", ("lumen_api/design_store.py",)),
    # --- Round A domain 3: custom components ---------------------------------------------
    # These three land inside the two component operation cores, which are themselves governed
    # below — so the chain route/agent -> tool -> core -> store stays closed end to end.
    "create_custom_component_source_revision": (
        "method",
        ("lumen_api/design_store.py", "lumen_api/custom_components.py"),
    ),
    "register_custom_component_artifact": (
        "method",
        ("lumen_api/design_store.py", "lumen_api/custom_components.py"),
    ),
    "record_custom_component_compilation": (
        "method",
        ("lumen_api/design_store.py", "lumen_api/custom_component_compiler.py"),
    ),
    "persist_custom_component_source_revision": (
        "function",
        ("lumen_api/custom_components.py",),
    ),
    "persist_compiled_custom_component_artifact": (
        "function",
        # Called by the compile orchestration core, which is itself governed below.
        ("lumen_api/custom_components.py", "lumen_api/custom_component_compiler.py"),
    ),
    "compile_and_persist_custom_component": (
        "function",
        ("lumen_api/custom_component_compiler.py",),
    ),
    # --- Round B domain 1: scene documents, history + diagnostics -------------------------
    "create_document": ("method", ("lumen_api/design_store.py",)),
    "replace_scene": ("method", ("lumen_api/design_store.py",)),
    "update_document_state": ("method", ("lumen_api/design_store.py",)),
    "set_agent_instructions": ("method", ("lumen_api/design_store.py",)),
    "set_layout_managed_editing": ("method", ("lumen_api/design_store.py",)),
    # Clone-fidelity F4.3, ruling R-F1: the durable `noindex` stamp. Governed like its two
    # per-document siblings above — the CLEAR direction is the only door in the system that can
    # take the robots meta off a published account page, so it may not be reachable off-toolbelt.
    "set_web_noindex": ("method", ("lumen_api/design_store.py",)),
    # Artifacts page (2026-09-15): the library's two curation writes. The rename touches the row
    # title AND the document JSON together and bumps the version; archiving is the gallery/library
    # state. Both are caller-initiated document mutations, so neither may be reachable off-toolbelt.
    "rename_document": ("method", ("lumen_api/design_store.py",)),
    "set_document_archived": ("method", ("lumen_api/design_store.py",)),
    "create_snapshot": ("method", ("lumen_api/design_store.py",)),
    "create_template_revision": ("method", ("lumen_api/design_store.py",)),
    "store_diagnostics": ("method", ("lumen_api/design_store.py",)),
    # The two Round-B operation cores live UNDER lumen_api/toolbelt/, so they are covered by
    # the blanket toolbelt allowance — but they are listed anyway, because a caller that
    # imported one directly would otherwise reach the governed store methods from an allowed
    # module and open exactly the hole this guard exists to close.
    "_advance_scene_state": ("function", ()),
    "apply_web_operations": ("function", ()),
    # --- Round B domain 2: website-mode documents -----------------------------------------
    "update_web_document": ("method", ("lumen_api/design_store.py",)),
    "create_web_template": ("method", ("lumen_api/design_store.py",)),
    # --- Wave 2 Lane A: Puck site documents ------------------------------------------------
    "update_site_document": ("method", ("lumen_api/design_store.py",)),
    "write_site_document": ("function", ()),
    "step_site_history": ("function", ()),
    "build_site_publish_package": ("function", ("lumen_api/site_publish.py",)),
    "publish_site_document": ("function", ()),
    # --- Round B domain 3: turn enqueues ---------------------------------------------------
    # The run row + its fleet task, offered in one transaction. The rest of the run lifecycle
    # (claim, result, completion, events) stays in UNCONVERTED_MUTATIONS below: it is the
    # EXECUTION plane, governed by the fleet lease rather than the toolbelt (the D5 fencing
    # contract). Only the enqueue is a caller-initiated design mutation.
    "create_run_and_offer": ("method", ("lumen_api/design_store.py",)),
    # --- Round C domain 1: brand kits ------------------------------------------------------
    "create_brand_kit": ("method", ("lumen_api/design_store.py",)),
    "publish_next_brand_kit_version": ("method", ("lumen_api/design_store.py",)),
    "update_brand_kit_approval": ("method", ("lumen_api/design_store.py",)),
    "create_brand_compatibility_report": ("method", ("lumen_api/design_store.py",)),
    # --- Round C domain 2: brand-kit ingestion enqueues ------------------------------------
    # The job row + its fleet task, offered in one transaction — the ingestion twin of
    # ``create_run_and_offer``. Staged-blob registration is NOT governed: it is a
    # content-addressed, immutable byte write with no state to lose (see toolbelt/ingestion.py).
    "create_and_offer": ("method", ("lumen_ingestion/jobs.py",)),
    # --- Round C domain 3: the asset registry ----------------------------------------------
    "create_asset_record": ("method", ("lumen_api/design_store.py",)),
    "create_asset_records": ("method", ("lumen_api/design_store.py",)),
    "record_generation_result": ("method", ("lumen_api/design_store.py",)),
    "update_asset_status": ("method", ("lumen_api/design_store.py",)),
    "delete_asset_record": ("method", ("lumen_api/design_store.py",)),
    "merge_human": ("method", ("lumen_ingestion/describe.py",)),
    "delete_asset_and_orphaned_bytes": ("function", ()),
    # --- Round C domain 4: personalization + both batch families ---------------------------
    "upsert_binding_set": ("method", ("lumen_api/design_store.py",)),
    "delete_binding_set": ("method", ("lumen_api/design_store.py",)),
    "upsert_instance": ("method", ("lumen_api/design_store.py",)),
    "upsert_repair_request": ("method", ("lumen_api/design_store.py",)),
    "create_batch": ("method", ("lumen_api/design_store.py",)),
    "update_batch_progress": ("method", ("lumen_api/design_store.py",)),
    "create_web_batch": ("method", ("lumen_api/design_store.py",)),
    "update_web_batch_progress": ("method", ("lumen_api/design_store.py",)),
    "persist_derived_instance": ("function", ()),
    # --- Brand Ad Assets v1 W2 — the ad-assets lane ----------------------------------------
    # Three durable writes over the lane's own tables, on their own workspace-scoped store
    # facade (``AdAssetsStore``) rather than on ``HybridRepository`` — the same shape the
    # ingestion job store and the description store already have. The lane's OTHER two writes
    # are not listed because they are not new: the harvested creatives' asset rows go through
    # ``design_register_captured_assets`` and the pre-generated imagery through
    # ``design_register_generated_asset``, both already governed above.
    "record_creatives": ("method", ("lumen_ingestion/ad_library/store.py",)),
    "create_card_version": ("method", ("lumen_ingestion/ad_library/store.py",)),
    "link_pregenerated_assets": ("method", ("lumen_ingestion/ad_library/store.py",)),
    # --- Wave 2 Lane B: agent-written Puck sections --------------------------------------------
    "record_site_section": ("method", ("lumen_api/design_store.py",)),
    "record_site_section_bytes": ("function", ()),
}

#: Design store mutations that are deliberately NOT behind a tool, each with its justification.
#:
#: **Round C emptied the "scheduled work" half of this list.** Every domain Rounds A and B
#: deferred — brand kits, ingestion, the asset registry, personalization and both batch families
#: — is governed above. What remains is one closed category, and it is an *exemption by
#: construction*, not a backlog:
#:
#: the durable RUN LIFECYCLE (``create_run`` / ``complete_run`` / ``emit_run_event``) is the
#: EXECUTION plane. Those writes are made by a leased fleet worker driving a run it already owns,
#: and they are fenced by the ``work_lease`` generation (the D5 contract) — not by an idempotency
#: key a caller supplies. Putting them behind the toolbelt would add a second, weaker authority
#: over writes the lease already arbitrates, and would mean a worker journaling an invocation for
#: every progress event of a run that is itself a journaled invocation. The one caller-initiated
#: half — the ENQUEUE — is governed (``create_run_and_offer``, ``create_and_offer``).
#:
#: **D7 renamed one member and changed nothing else about the category.** ``append_run_event``
#: (the private ``design_run_event`` log) became ``emit_run_event`` (a ``design.run.event`` on the
#: platform outbox). The exemption argument is unchanged and, if anything, stronger: the emit is
#: now the *projection* of an already-governed durable write, so routing it through the toolbelt
#: would journal an invocation whose only effect is to announce another invocation.
#:
#: **D8 removed a member by DELETING it, not by governing it.** ``set_run_result`` — the raw
#: terminalize-without-emitting facade — had zero callers (every real terminal path goes through
#: ``complete_run`` → ``run_stream.complete_run_and_emit``, which writes the result and its stream
#: event in one fenced transaction). It was the only surface that could leave a run terminal with
#: no terminal event, and the SSE loop carried a defensive branch solely to cover for it; both went
#: together (R-D8-3). The set is now closed at THREE, asserted by equality below.
#:
#: Three facade methods were DELETED rather than governed, because nothing called them:
#: ``set_document_account`` (the derive path sets the account inside ``create_web_document``),
#: ``register_scene_assets`` (every scene-persist path calls the DAL in-transaction) and
#: ``set_run_result`` (above). Minting a tool for a write no caller performs would have been
#: governance theatre.
UNCONVERTED_MUTATIONS: frozenset[str] = frozenset(
    {
        "create_run",
        "complete_run",
        "emit_run_event",
    }
)


def _sources() -> list[Path]:
    return sorted(
        [*LUMEN_API.rglob("*.py"), *LUMEN_INGESTION.rglob("*.py")],
        key=lambda item: str(item),
    )


def _relative(path: Path) -> str:
    return str(path.relative_to(API_ROOT))


def _violations(name: str, kind: str, allowed: tuple[str, ...]) -> list[str]:
    pattern = (
        re.compile(rf"\.\s*{re.escape(name)}\s*\(")
        if kind == "method"
        else re.compile(rf"(?<![\w.]){re.escape(name)}\s*\(")
    )
    found: list[str] = []
    for path in _sources():
        relative = _relative(path)
        if relative.startswith(_TOOLBELT) or relative in allowed:
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith(("def ", "async def ")):
                continue
            if pattern.search(line):
                found.append(f"{relative}:{number}: {stripped}")
    return found


def test_converted_domain_mutations_are_only_called_from_the_toolbelt() -> None:
    """The gate: no design route, batch loop, worker or agent gateway writes around a tool."""
    offences: dict[str, list[str]] = {}
    for name, (kind, allowed) in _GOVERNED.items():
        if hits := _violations(name, kind, allowed):
            offences[name] = hits
    assert not offences, (
        "ungoverned design writes (call them through lumen_api.toolbelt instead):\n"
        + "\n".join(f"  {name}\n    " + "\n    ".join(hits) for name, hits in offences.items())
    )


def test_every_governed_name_actually_exists() -> None:
    """A typo in the guard's list would silently govern nothing."""
    from lumen_api import custom_component_compiler, custom_components, site_publish, web_export
    from lumen_api.design_store import HybridRepository
    from lumen_api.toolbelt import assets as toolbelt_assets
    from lumen_api.toolbelt import documents as toolbelt_documents
    from lumen_api.toolbelt import personalization as toolbelt_personalization
    from lumen_api.toolbelt import publishes as toolbelt_publishes
    from lumen_api.toolbelt import site_documents as toolbelt_site_documents
    from lumen_api.toolbelt import site_sections as toolbelt_site_sections
    from lumen_api.toolbelt import web_documents as toolbelt_web_documents
    from lumen_ingestion.ad_library.store import AdAssetsStore
    from lumen_ingestion.describe import DescriptionStore
    from lumen_ingestion.jobs import IngestionJobStore

    # Round C: two governed mutations live on the design app's OTHER two workspace-scoped store
    # facades rather than on ``HybridRepository`` — the ingestion job store's atomic enqueue and
    # the description store's merge-patch. The guard's textual rule is unchanged (an attribute
    # call ``.<name>(``); only the "does this name exist?" check has to look in three places —
    # four, since the Brand Ad Assets lane added its own facade.
    stores = (HybridRepository, IngestionJobStore, DescriptionStore, AdAssetsStore)
    for name, (kind, _allowed) in _GOVERNED.items():
        if kind == "method":
            assert any(hasattr(store, name) for store in stores), (
                f"{name} is not a method of any design store facade"
            )
        else:
            assert any(
                hasattr(module, name)
                for module in (
                    web_export,
                    custom_components,
                    custom_component_compiler,
                    toolbelt_documents,
                    toolbelt_web_documents,
                    toolbelt_assets,
                    toolbelt_personalization,
                    toolbelt_site_documents,
                    site_publish,
                    toolbelt_publishes,
                    toolbelt_site_sections,
                )
            ), f"{name} is not a known design operation core"


def test_unconverted_domains_are_explicitly_listed() -> None:
    """Every ungoverned mutation is one of the three run-lifecycle writes, and nothing else.

    Round C closed the last scheduled domain, so this list is an exhaustive statement of an
    EXEMPTION rather than a backlog: the execution plane's run-lifecycle writes, fenced by the
    fleet lease. The equality assertion is the point — a future round cannot quietly park a new
    ungoverned write here without changing this test. (D7 renamed ``append_run_event`` to
    ``emit_run_event`` when the private event log became a subject on the platform outbox; D8
    deleted the caller-less ``set_run_result``, taking the set from four to three.)
    """
    from lumen_api.design_store import HybridRepository

    for name in UNCONVERTED_MUTATIONS:
        assert hasattr(HybridRepository, name), f"{name} is no longer a store method"
    assert not (set(_GOVERNED) & UNCONVERTED_MUTATIONS)
    assert UNCONVERTED_MUTATIONS == frozenset({"create_run", "complete_run", "emit_run_event"})


def test_the_deleted_dead_facade_methods_stay_deleted() -> None:
    """``set_document_account`` / ``register_scene_assets`` (Round C) and ``set_run_result`` (D8)
    had zero callers and were removed rather than given tools for writes nobody performs.

    ``set_run_result`` carries an extra condition: it was the ONLY path that could terminalize a
    run without emitting its terminal stream event, and the design SSE loop's defensive
    close-the-stream branch existed solely to cover for it. Both were deleted together (R-D8-3),
    so bringing this one back needs a caller, a tool, AND a decision about that liveness net.
    If any comes back it needs a caller AND a tool — this test is the reminder, not a prohibition.
    """
    from lumen_api.design_store import HybridRepository

    for name in ("set_document_account", "register_scene_assets", "set_run_result"):
        assert not hasattr(HybridRepository, name), (
            f"HybridRepository.{name} is back: give it a governed tool and a _GOVERNED entry"
        )


def test_design_tool_names_are_stable() -> None:
    """The full D6 inventory, pinned. The platform's C6 authority map mirrors this set."""
    assert set(DESIGN_TOOL_NAMES) == {
        # Round A
        "design_publish_web",
        "design_publish_site",
        "design_unpublish_web",
        "design_rollback_web_publish",
        "design_create_web_account",
        "design_update_web_account",
        "design_delete_web_account",
        "design_write_component_source",
        "design_compile_component",
        # Round B — scene documents, history, diagnostics
        "design_create_document",
        "design_set_agent_instructions",
        "design_set_layout_managed_editing",
        # Clone-fidelity F4.3, ruling R-F1: the durable `noindex` stamp on a WEB document. Its
        # two neighbours above are scene-side; this one is here because it is the same kind of
        # thing — one named value assigned to one document — and because the platform's C6
        # authority map mirrors this set, so a new tool has to be a deliberate line.
        "design_set_web_noindex",
        # Artifacts page (2026-09-15): the library's two curation writes. Ungranted, human-only
        # on the platform, like noindex.
        "design_rename_document",
        "design_set_document_archived",
        "design_replace_scene",
        "design_apply_operations",
        "design_apply_edits",
        "design_undo_document",
        "design_redo_document",
        "design_create_snapshot",
        "design_persist_preflight",
        "design_attach_brand_kit",
        "design_finalize_document",
        "design_record_diagnostics",
        # Round B — website-mode documents
        "design_create_web_template",
        "design_derive_web_document",
        "design_apply_web_operations",
        "design_undo_web_document",
        "design_redo_web_document",
        "design_write_site",
        "design_undo_site",
        "design_redo_site",
        # Round B — turn enqueues
        "design_start_agent_turn",
        "design_start_web_turn",
        "design_create_brand_kit",
        "design_publish_brand_kit_version",
        "design_set_brand_kit_approval",
        "design_create_brand_compatibility_report",
        "design_ingest_website",
        "design_ingest_pdf",
        "design_ingest_assets",
        "design_register_asset_record",
        "design_register_qr_asset",
        "design_register_generated_asset",
        "design_register_captured_assets",
        "design_set_asset_status",
        "design_delete_asset",
        "design_set_asset_description",
        "design_upsert_binding_set",
        "design_delete_binding_set",
        "design_derive_instance",
        "design_create_instance_batch",
        "design_advance_instance_batch",
        "design_create_web_batch",
        "design_advance_web_batch",
        # Brand Ad Assets v1 W2 — the ad-assets lane. Registered unconditionally so the
        # platform's C6 authority audit stays a complete statement about every write the
        # platform can name; reachable only through the flag-gated onboarding route.
        "design_ingest_ad_assets",
        "design_enrich_assets",
        "design_record_ad_creatives",
        "design_publish_ad_dna_card",
        "design_link_ad_pregenerated_assets",
        "design_record_site_section",
    }


def test_the_publish_slug_contract_is_one_contract() -> None:
    """``toolbelt.publishes`` restates the slug pattern (it may not import ``main``)."""
    from lumen_api.main import WEB_SLUG_PATTERN as route_pattern
    from lumen_api.toolbelt.publishes import WEB_SLUG_PATTERN as tool_pattern

    assert route_pattern.pattern == tool_pattern.pattern


def test_the_document_gate_predicates_are_one_contract() -> None:
    """``toolbelt.documents`` restates ``main``'s scene-status/finalized predicates.

    Same reason as the slug pattern: the toolbelt may not import ``main``. If the two ever
    disagree, a route would gate a write one way and its tool the other — which is exactly the
    class of divergence the D6 no-bypass guard exists to make impossible.
    """
    from lumen_api import main as route_module
    from lumen_api.toolbelt import documents as tool_module

    cases = [
        {},
        {"status": "draft", "scene": {}},
        {"status": "finalized", "scene": {}},
        {"status": "draft", "scene": {"meta": {"status": {"kind": "finalized"}}}},
        {"status": "draft", "scene": {"meta": {"status": "finalized"}}},
        {"status": "draft", "scene": {"meta": {"status": {"kind": "draft"}}}},
    ]
    for document in cases:
        assert route_module.is_finalized_document(document) == (
            tool_module.is_finalized_document(document)
        ), document
        scene = document.get("scene", {})
        assert route_module.scene_status_kind(scene) == tool_module.scene_status_kind(scene)

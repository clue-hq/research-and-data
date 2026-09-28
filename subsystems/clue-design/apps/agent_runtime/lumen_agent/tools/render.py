"""The `render_preview` tool - render the scene, file the PNG, report as text."""

from __future__ import annotations

import json
from pathlib import Path

from lumen_api.export_policy import partition_export_diagnostics
from py_lumen_obs import get_logger, log_span

from ..paths import to_virtual
from ..workspace import workspace_root
from .substrate import LumenDesignTools, checkpoint_acceptance, combined_preview_artifacts
from .view import _latest_preview_png

logger = get_logger("lumen_agent.tools.render")


def _candidate_freshness(tools: LumenDesignTools) -> dict:
    """Snapshot existing acceptance evidence; never renew or relax a receipt."""
    with tools._scene_mutation_lock:
        scene_stamp = tools._scene_stamp()
        current_preview = tools._current_preview_receipt()
        diagnostics = tools._latest_preflight_diagnostics
        blocking, advisory = partition_export_diagnostics(diagnostics or [])
        critique = tools._latest_visual_critique
        review_error = (
            tools._reference_fidelity_error(critique) or tools._acceptance_error(critique)
            if critique is not None
            else "No visual critique is registered for this run."
        )
        return {
            "preflight_current": (
                tools._preflight_scene_stamp == scene_stamp
                and diagnostics is not None
                and not blocking
                and not (tools.latest_preflight_has_errors and not advisory)
            ),
            "preview_current": (
                current_preview is not None and current_preview == tools._preview_receipt
            ),
            # Current means an accepted registered review satisfies the same
            # direction, preflight and pixel contract as finalization.
            "registered_review_current": review_error is None,
            "review_error": review_error,
        }


def _current_round_dir(tools: LumenDesignTools, current_round: int) -> Path | None:
    if not current_round:
        return None
    candidate = workspace_root(tools) / "rounds" / f"round_{current_round}"
    return candidate if candidate.exists() else None


def _reusable_preview_bundle(tools: LumenDesignTools) -> dict | None:
    """Reuse only the trusted, current, clean SVG/PNG bundle, never a debug export."""
    receipt = getattr(tools, "_preview_receipt", None)
    if not receipt or getattr(tools, "latest_preflight_has_errors", None) is not False:
        return None
    if getattr(tools, "_preflight_scene_stamp", None) != tools._scene_stamp():
        return None
    if tools._current_preview_receipt() != receipt:
        return None
    iteration = getattr(tools, "_preview_rendered_iteration", None)
    if iteration is None:
        return None
    # The substrate's own attribute, not a hand-rebuilt path: iterations belong to
    # the TURN, which is the run folder unless the run is part of a design session.
    bundle_path = tools.iterations_dir / f"{iteration:03d}" / "preview_bundle.json"
    try:
        payload = json.loads(bundle_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("debug_only") is not False:
            return None
        canonical, critic, reviewer = (
            payload.get(key) for key in ("canonical", "critic", "reviewer")
        )
        if any(not isinstance(summary, dict) for summary in (canonical, critic, reviewer)):
            return None
        if any(
            summary.get("status") != "ok" or summary.get("validation_errors")
            for summary in (canonical, critic, reviewer)
        ):
            return None
        if canonical.get("requested_format") != "svg" or critic.get("requested_format") != "png":
            return None
        # The manifest is agent-visible. Its claims must match the in-memory
        # export summary whose exact artifact bytes were checked by the receipt.
        if reviewer != tools.latest_export_summary:
            return None
        artifacts = reviewer.get("artifacts") or []
        if {artifact.get("format") for artifact in artifacts} != {"svg", "png"}:
            return None
        if combined_preview_artifacts(canonical, critic, "png") != artifacts:
            return None
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    payload["unchanged"] = (
        "reused current validated preview; scene content and artifact bytes are unchanged."
    )
    tools.record(
        "coordinator", "preview_reused",
        output_summary=f"reused canonical SVG and PNG from iteration {iteration}",
        payload={"rendered_iteration": iteration, "receipt": receipt},
    )
    return payload


def _render_preview_text(
    tools: LumenDesignTools,
    *,
    checkpoint: bool = True,
    budget=None,
) -> str:
    """Wrap export_preview_bundle(critic_format="png"): render, copy the PNG into
    the round (or previews/) dir, and return a compact TEXT summary. On validation
    failure, return the errors verbatim. Never returns image blocks (§4b).

    `checkpoint` (fast loop §5.2) decides whether a clean render also fires the
    P0.4 checkpoint commit — see the trigger site below for why the AUTHOR's
    renders are built with `checkpoint=False`.

    `budget` (fast loop tuning, 2026-08-24) appends the run's remaining headroom.
    It rides THIS tool because the orchestrator's step-5 verification render is
    the round boundary — the one moment in the loop where "open another round or
    finalize" is actually decided, and the last thing the orchestrator reads
    before deciding it. Handing the number over anywhere else would mean handing
    it over at a moment nobody can act on."""
    payload = _reusable_preview_bundle(tools)
    if payload is None:
        raw = tools.export_preview_bundle(critic_format="png")
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return f"render_preview: unexpected export output:\n{raw}"

    reviewer = payload.get("reviewer") or {}
    status = reviewer.get("status")
    validation_errors = reviewer.get("validation_errors") or []
    artifacts = reviewer.get("artifacts") or []

    lines: list[str] = [f"render_preview: status={status}"]
    png_path = _latest_preview_png(tools)
    copied_to: str | None = None
    if png_path is not None:
        round_dir = _current_round_dir(tools, tools_current_round(tools))
        dest_dir = round_dir if round_dir is not None else (workspace_root(tools) / "previews")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / ("preview.png" if round_dir is not None else "latest.png")
        dest.write_bytes(png_path.read_bytes())
        # D5: the model reads its filesystem at virtual paths — surface the copied
        # preview at the same virtual form it can re-open, not the host path.
        copied_to = to_virtual(dest, tools.config)

    for artifact in artifacts:
        fmt = artifact.get("format")
        path = artifact.get("path") or artifact.get("critic_input_path")
        dims = ""
        if artifact.get("width") and artifact.get("height"):
            dims = f" {artifact['width']}x{artifact['height']}"
        # D5: artifact paths are host paths under the workspace; the model-facing
        # summary shows their virtual form (the API envelope keeps host paths).
        shown = to_virtual(path, tools.config) if path else path
        lines.append(f"- {fmt}{dims}: {shown}")
    if copied_to:
        lines.append(f"- copied preview: {copied_to}")
    if getattr(tools.config, "scene_skill_bundle", "legacy") == "candidate":
        # Already-resolved/exported scene, no model/core/provider call. Never use
        # the truncated visual display table as copy-binding authority.
        lines.append("Native copy review inventory: " + tools.inspect("copy_review"))

    diagnostics = reviewer.get("diagnostics") or []
    if diagnostics:
        lines.append(f"diagnostics ({len(diagnostics)}):")
        for diag in diagnostics[:20]:
            if isinstance(diag, dict):
                lines.append(
                    f"  [{diag.get('severity')}] {diag.get('code')}: {diag.get('message')}"
                )
    if validation_errors:
        lines.append("VALIDATION ERRORS:")
        for err in validation_errors:
            lines.append(f"  - {err}")
    # L4a: loud non-blocking raster advisories (e.g. a near-uniform PNG) ride the
    # artifact; surface them where the orchestrator actually reads.
    raster_warnings = [
        warning
        for artifact in artifacts
        for warning in (artifact.get("warnings") or [])
    ]
    if raster_warnings:
        lines.append("WARNINGS:")
        for warning in raster_warnings:
            lines.append(f"  - {warning}")
    # L4b: the unchanged-scene fact — the orchestrator should act on the existing
    # critique instead of re-delegating a full review of identical pixels.
    unchanged = payload.get("unchanged")
    if unchanged:
        lines.append(unchanged)
    # P0.4 checkpoint commit. THIS is the round-acceptance seam. The
    # ORCHESTRATOR runs render_preview exactly once per round at its step-5
    # verification — so a render that produced a validated raster is the one
    # moment Python can observe "an authoring round finished and its scene is
    # real". The export itself already refuses a scene whose token paints are
    # unresolved, so reaching here also means preflight ran after the last
    # mutation. Best-effort by construction:
    # `checkpoint_scene` swallows and records everything, so the render summary
    # the model reads is unchanged whether or not the document moved.
    #
    # FAST LOOP §5.2 — DELIBERATE DECISION: the author now has render_preview
    # too, and its renders do NOT checkpoint. `checkpoint=False` is passed for
    # the author's instance, and this is the reason:
    #
    #   A checkpoint means "a round was ACCEPTED and its scene is durable". The
    #   author renders MID-round — that is the whole point of §5.2, it renders to
    #   find what is still wrong, and its first render of a round is frequently
    #   of a design its own next self-audit will reject. Committing those would
    #   redefine a checkpoint as "the author rendered something that did not
    #   crash", which is a materially weaker claim, and it would mint a document
    #   version per inner iteration (up to 4 per round) instead of one per
    #   accepted round. The frontend reads checkpoints as progress; a takeover
    #   reads the last one as the best surviving state (P0.4's replay guard).
    #   Both readings depend on "accepted", not "rendered".
    #
    #   So round acceptance stays exactly where P0.4 put it: the orchestrator's
    #   own verification render, which still happens once per round and still
    #   follows the author's report. The author's renders are pure looking —
    #   they write their PNG into the round directory as always (custody
    #   unchanged) and touch nothing durable.
    #
    # TASK 4b (controller ruling 2026-09-02) — the predicate is `accepted`, not
    # `reviewer.status == "ok"`. The reviewer verdict folds the canonical SVG in,
    # and that export refuses to embed WOFF2 brand faces every single round while
    # the critic PNG renders clean; keying on it meant ~71% of stored brand fonts
    # never checkpointed at all. `checkpoint_acceptance` reads the two summaries
    # directly and excuses exactly that one export-format refusal. The reviewer
    # lines above are untouched — the model still reads status=error and both
    # errors verbatim, because the SVG really did fail.
    # OPTION A (2026-09-02, docs/superpowers/plans/2026-09-02-woff2-font-decode-at-ingestion.md)
    # removes the cause: fonts are stored as sfnt. This excuse stays until the backfill has
    # run on every environment; after that it should be deleted, not kept as belt-and-braces.
    acceptance = checkpoint_acceptance(
        payload.get("canonical") or {}, payload.get("critic") or {}
    )
    if checkpoint and acceptance.accepted and png_path is not None:
        tools.checkpoint_scene("render_preview")

    if getattr(tools.config, "scene_skill_bundle", "legacy") == "candidate":
        lines.append("freshness: " + json.dumps(_candidate_freshness(tools)))

    # The round-boundary headroom report. Last line, because it is what the
    # orchestrator acts on after it has read everything else. Best-effort by
    # construction: a budget that cannot describe itself must not take down a
    # render that succeeded.
    if budget is not None:
        try:
            if checkpoint and getattr(tools.config, "scene_skill_bundle", "legacy") == "candidate":
                lines.append(
                    budget.candidate_status_line(
                        current_round=tools_current_round(tools),
                        runtime_owned_rounds=tools.solo_rounds_executed is not None,
                    )
                )
            else:
                lines.append(budget.status_line())
        except Exception:  # noqa: BLE001 - never fail a render over a status line
            logger.warning("render_budget_line_failed")
    return "\n".join(lines)


def tools_current_round(tools: LumenDesignTools) -> int:
    # Use the same authority for compile allowance, review and preview custody.
    return tools._fast_loop_round_number()


def make_render_preview_tool(
    tools: LumenDesignTools,
    *,
    checkpoint: bool = True,
    budget=None,
):
    """Build a `render_preview` tool bound to `tools`.

    Two instances are built under the fast loop over the SAME substrate: the
    orchestrator's (`checkpoint=True`, the P0.4 round-acceptance trigger) and the
    author's (`checkpoint=False`, pure looking). A closure flag rather than a
    caller-identity check because the substrate genuinely cannot tell who is
    calling — the tool object is the only thing that differs between the roles,
    so the tool object is where the difference belongs.

    `budget` follows the same split and for the same reason: only the
    orchestrator's instance carries it, because only the orchestrator decides
    whether to open another round. Telling the author its run is nearly over
    would invite it to cut corners on work it has already been told to finish.
    """
    from langchain_core.tools import tool

    @tool
    def render_preview() -> str:
        """Render the current scene to a validated PNG (and canonical SVG) on disk
        and return a compact text summary: artifact paths, dimensions, validation
        status, and any export diagnostics. Seeing the pixels is view("preview")'s
        job — this tool never returns image blocks.

        Requires preflight_design after any scene mutation — export refuses
        unresolved token paints."""
        with log_span("tool_render_preview", logger=logger):
            return _render_preview_text(tools, checkpoint=checkpoint, budget=budget)

    return render_preview

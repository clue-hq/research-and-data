#!/usr/bin/env python
"""Materialize one design run's derived view into a browsable `.design-runs/<ref>/` directory.

Founder-ratified 2026-08-23 (`docs/superpowers/plans/2026-08-23-design-run-view.md`): the
design subsystem keeps its three real homes — the frozen context bundle in platform blob
storage, the engine materialization cache, and Postgres as the sole source of truth for
scenes/envelopes/events — and this tool is a VIEW over them, never a fourth substrate. What it
writes is DERIVED and DISPOSABLE: delete `.design-runs/` at any time, nothing reads it back.

Usage, from the repo root with the colombo `.env` sourced::

    set -a; source .env; set +a
    .venv/bin/python subsystems/clue-design/scripts/run_view.py <ref> [--out DIR] [--copy]

The venv interpreter is named explicitly on purpose: sourcing `.env` activates nothing, bare
`python` is often not on PATH, and `asyncpg` lives only in the repo-root `.venv`.

`<ref>` is a design run id (`run_…`), a document id (`doc_…`), or a leg UUID. Environment:

* ``CLUE_DATABASE_URL``    — required; the platform Postgres (read-only here).
* ``CLUE_STORAGE_FS_ROOT`` — required, and required ABSOLUTE: neither guessed nor resolved
  against the caller's working directory. That is exactly the bug class the design custody fix
  closed, and a wrong root here would report the frozen bundle and every durable asset blob as
  missing — a confident lie.
* ``LUMEN_ASSET_STORE_ROOT`` — optional; defaults to this repo's git-ignored `.engine-cache`,
  mirroring ``py_lumen_config.Settings.effective_asset_store_root`` (restated rather than
  imported so the script composes no app and needs no settings singleton). A relative value
  warns (naming the absolute path used) rather than refusing: the cache is a per-machine
  materialization, so a wrong one costs a fallback to the durable blob, not a false "missing".

Read-only over every substrate: the only writes are inside the output directory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg

_DESIGN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_DESIGN_ROOT / "apps" / "api"))

from lumen_api.run_view import AssetView, RunView, RunViewNotFound, assemble  # noqa: E402

# The engine materialization cache's documented default home (see the module docstring).
_DEFAULT_ASSET_STORE_ROOT = _DESIGN_ROOT / ".engine-cache"
_DEFAULT_OUT_ROOT = _DESIGN_ROOT / ".design-runs"

# The bridge's RESULT set is capped at this many rows, most-recent-first. It does not bound the
# scan itself — `strpos` over `payload::text` is unindexed, so Postgres still walks the whole
# `design_run` slice of the stream. The window's real job is the ambiguity check: if several
# outer runs mention the same inner id, the view says so instead of picking one silently.
_BRIDGE_SCAN_LIMIT = 500

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")

_WRITTEN_FILES = ("manifest.json", "brief.json", "scene.current.json", "events.jsonl", "README.md")
_WRITTEN_DIRS = ("envelopes", "assets")


# --- the inner-id bridge ------------------------------------------------------------------------


async def _bridge_inner_run_id(conn: asyncpg.Connection, ref: str) -> tuple[str | None, str]:
    """Inner deepagent run id → the OUTER design run that carries it, or ``(None, "")``.

    The trio's inner run id — the one the worker logs print — exists in no durable table; it
    survives only inside the outer run's ``run_event`` payloads (e.g. ``design.run.completed`` →
    ``payload.result.run_id``). A human pasting that id from a log should still get the view, so
    this is the one indirection the CLI performs, and it is reported, never hidden.

    ``strpos`` rather than ``LIKE '%' || $1 || '%'`` on purpose: every design run id contains an
    underscore, which ``LIKE`` reads as a single-character WILDCARD — the literal search is what
    was meant. The ref is bound as a parameter; it is never interpolated into the SQL.
    """
    rows = await conn.fetch(
        "SELECT subject_id FROM run_event"
        " WHERE subject_kind = 'design_run' AND strpos(payload::text, $1) > 0"
        " ORDER BY seq DESC LIMIT $2",
        ref,
        _BRIDGE_SCAN_LIMIT,
    )
    if not rows:
        return None, ""
    outer = str(rows[0]["subject_id"])
    note = (
        f"ref {ref} matched no design_agent_run, run_event subject, document, or leg — it was "
        f"BRIDGED to outer design run {outer}, found by searching run_event payloads that "
        "mention it (an inner deepagent run id is durable nowhere else). Everything below "
        f"belongs to {outer}, not to {ref}."
    )
    distinct = {str(row["subject_id"]) for row in rows}
    if len(distinct) > 1:
        note += (
            f" WARNING: {len(distinct)} distinct outer runs mention this id within the most "
            f"recent {_BRIDGE_SCAN_LIMIT} matching events "
            f"({', '.join(sorted(distinct)[:5])}) — the newest was taken."
        )
    return outer, note


async def load_view(
    ref: str,
    *,
    database_url: str,
    asset_store_root: Path,
    storage_fs_root: Path,
) -> RunView:
    """``assemble``, plus the CLI-only inner-run-id bridge on a ``run_…`` miss.

    The bridge lives here and not in the assembler deliberately: a substring match over JSON
    payload text is a paste-an-id-from-a-log affordance for a human, not a substrate truth, and
    ``assemble`` stays a precise resolver of durable ids for every programmatic caller.
    """
    roots = {"asset_store_root": asset_store_root, "storage_fs_root": storage_fs_root}
    try:
        return await assemble(ref, database_url=database_url, **roots)
    except RunViewNotFound as error:
        if not str(ref).startswith("run_"):
            raise
        missing = error

    conn = await asyncpg.connect(database_url.replace("+asyncpg", ""))
    try:
        outer, note = await _bridge_inner_run_id(conn, str(ref))
    finally:
        await conn.close()
    if outer is None:
        raise RunViewNotFound(
            f"{missing}; nor does any run_event payload mention it (searched the most recent "
            f"{_BRIDGE_SCAN_LIMIT} design_run events containing it)"
        ) from missing

    try:
        view = await assemble(outer, database_url=database_url, **roots)
    except RunViewNotFound as error:
        # Keep the bridge context in the error: without both ids this reads as "your ref is
        # unknown", when in fact the bridge worked and the run it pointed at is the problem.
        raise RunViewNotFound(
            f"bridged from {ref} to design run {outer}, but that outer ref failed to "
            f"assemble: {error}"
        ) from error
    view.manifest["bridged_from"] = ref
    view.manifest.setdefault("gaps", []).append(note)
    return view


# --- the materializer ---------------------------------------------------------------------------


def _safe_name(raw: object, fallback: str) -> str:
    """A filesystem name from substrate DATA (a ref, a scene-supplied asset label).

    Data reaching the filesystem is sanitized rather than trusted — a label of ``../../etc`` must
    become a file name, not a path.
    """
    name = _UNSAFE.sub("_", str(raw)).strip("._")
    return name or fallback


def _dump(value: object) -> str:
    return json.dumps(value, indent=2, default=str, ensure_ascii=False)


def _reset(out: Path) -> None:
    """Clear what a previous materialization wrote — but only inside a directory this tool owns.

    Re-running on the same ref must not leave the previous view's envelopes or asset links
    behind (a stale file in a derived view is a lie, and a leftover symlink would crash the
    second run outright). The removals are name-scoped, but ``envelopes/`` and ``assets/`` are
    ordinary names: in a caller-supplied ``--out`` that happens to hold real directories of
    those names, a name-scoped ``rmtree`` is still a data-loss bug. So the tool first asserts
    OWNERSHIP — the directory must be empty, or hold the ``manifest.json`` every run view has —
    and refuses outright otherwise. A file it did not write and does not know about (anything
    beyond the seven names below) survives untouched either way.
    """
    existing = {path.name for path in out.iterdir()}
    if existing and "manifest.json" not in existing:
        raise SystemExit(
            f"run_view: refusing to write into {out} — it is not empty and holds no "
            "manifest.json, so it is not a run view this tool wrote. Materializing here would "
            "delete any `envelopes/` or `assets/` directory already in it. --out is pointing at "
            "a non-run-view directory; point it at a new, an empty, or a previous run-view "
            "directory instead."
        )
    for name in _WRITTEN_FILES:
        (out / name).unlink(missing_ok=True)
    for name in _WRITTEN_DIRS:
        path = out / name
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)


def materialize(
    view: RunView, out_dir: Path, *, copy: bool = False,
    evaluation_receipt: dict | None = None, comparison_receipt: dict | None = None,
) -> None:
    """Write the run view's browsable layout into ``out_dir``.

    Absent sections are skipped silently — ``manifest['gaps']`` already names them, and an empty
    file would imply an emptiness the assembler did not assert. Raises ``SystemExit`` if
    ``out_dir`` is a non-empty directory this tool did not write (see ``_reset``).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _reset(out)

    # Evaluation is derived from a separate observer receipt, never from runtime counters.
    view.manifest["evaluation"] = evaluate_creative(evaluation_receipt, view.manifest)
    if evaluation_receipt is not None:
        view.manifest["evaluation"]["receipt"] = evaluation_receipt
    if comparison_receipt is not None:
        view.manifest["evaluation"]["comparison"] = compare_evaluations(
            comparison_receipt, evaluation_receipt or {}
        )
    (out / "manifest.json").write_text(_dump(view.manifest), encoding="utf-8")
    if view.brief is not None:
        (out / "brief.json").write_text(_dump(view.brief), encoding="utf-8")
    if view.scene is not None:
        (out / "scene.current.json").write_text(_dump(view.scene), encoding="utf-8")

    if view.envelopes:
        (out / "envelopes").mkdir()
        for index, envelope in enumerate(view.envelopes):
            revision = _safe_name(envelope.get("base_revision"), "unknown")
            path = out / "envelopes" / f"{index:03d}-v{revision}.json"
            path.write_text(_dump(envelope), encoding="utf-8")

    if view.events:
        lines = [json.dumps(event, default=str, ensure_ascii=False) for event in view.events]
        (out / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    skipped = _write_assets(view.assets, out / "assets", copy=copy)
    (out / "README.md").write_text(_readme(view, copy=copy, skipped=skipped), encoding="utf-8")


def _write_assets(assets: list[AssetView], out: Path, *, copy: bool) -> list[str]:
    """Link (or copy) each asset's bytes; return the ids of the assets that had none."""
    linkable = [(a, a.cache_path or a.durable_path) for a in assets]
    if not any(source for _, source in linkable):
        return [a.asset_id for a in assets]

    out.mkdir()
    skipped: list[str] = []
    used: set[str] = set()
    for asset, source in linkable:
        if source is None:
            skipped.append(asset.asset_id)
            continue
        name = _safe_name(
            f"{asset.label or asset.asset_id}--{(asset.digest or 'nodigest')[:12]}", "asset"
        )
        # Two assets can share a label and a digest prefix; the second must not clobber the first.
        candidate, suffix = name, 2
        while candidate in used:
            candidate, suffix = f"{name}-{suffix}", suffix + 1
        used.add(candidate)
        if copy:
            shutil.copyfile(source, out / candidate)
        else:
            (out / candidate).symlink_to(Path(source).resolve())
    return skipped


#: The `docs/deepagent-fast-loop-v1-spec.md` §1 acceptance gates, rendered beside the run's own
#: numbers so the README answers "did this run pass?" rather than only "what did this run do?".
#: Kept as display text — this is a VIEW, so it reports the gate, it never enforces one.
_GATES = {
    "wall_time_ms": "<= 10 min",
    "llm_calls_total": "<= 45",
    "time_to_first_preview_ms": "<= 4 min",
    "input_tokens_total": "<= 3M",
    "rounds_total": "<= 1 repair round",
}


def _ms(value: object) -> str:
    """A duration for humans. Non-numeric (including a genuine `null`) stays honest."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "—"
    ms = int(value)
    if ms >= 60_000:
        return f"{ms // 60_000}m{(ms % 60_000) // 1000:02d}s"
    if ms >= 1000:
        return f"{ms / 1000:.1f}s"
    return f"{ms}ms"


def _num(value: object) -> str:
    return f"{value:,}" if isinstance(value, int) and not isinstance(value, bool) else "—"


def _metrics_section(metrics: dict | None) -> list[str]:
    """The per-run summary block (fast-loop v1 §7).

    This section exists so nobody hand-aggregates 6000 log lines again to learn where 43 minutes
    went. The numbers are the runtime's OWN — read verbatim off the `run_metrics` event, never
    recomputed here from the raw stream, so this README, the run's `metrics.json`, and
    `python -m lumen_agent.trace` can never disagree.
    """
    if not metrics:
        return [
            "",
            "## Run metrics",
            "",
            "None on this run's stream — see the gap below. (Runs from before the per-run "
            "summary counters landed have none, and neither does a run whose terminal emission "
            "was fenced.)",
        ]
    ttfp = metrics.get("time_to_first_preview_ms")
    rows = [
        ("wall time", _ms(metrics.get("wall_time_ms")), _GATES["wall_time_ms"]),
        ("llm calls", _num(metrics.get("llm_calls_total")), _GATES["llm_calls_total"]),
        (
            "time to first preview",
            _ms(ttfp) if ttfp is not None else "never rendered",
            _GATES["time_to_first_preview_ms"],
        ),
        ("input tokens", _num(metrics.get("input_tokens_total")), _GATES["input_tokens_total"]),
        ("output tokens", _num(metrics.get("output_tokens_total")), ""),
        ("rounds", _num(metrics.get("rounds_total")), _GATES["rounds_total"]),
        ("compile iterations", _num(metrics.get("compile_iterations_total")), ""),
        # §5.4: repairs that landed with NO model call. Read next to "llm calls":
        # this is the share of the mechanical work the code loop absorbed.
        ("autofix applied", _num(metrics.get("autofix_count")), ""),
        ("autofix rolled back", _num(metrics.get("autofix_rolled_back")), ""),
        ("failed llm calls", _num(metrics.get("llm_calls_failed")), ""),
        ("llm calls over 30s", _num(metrics.get("llm_calls_over_30s")), ""),
    ]
    lines = [
        "",
        "## Run metrics",
        "",
        f"Outcome: **{metrics.get('outcome') or '?'}** "
        f"({metrics.get('stop_reason') or 'no stop reason recorded'}). "
        "Gates are `docs/deepagent-fast-loop-v1-spec.md` §1.",
        "",
        "| metric | value | v1 gate |",
        "| --- | ---: | ---: |",
    ]
    lines += [f"| {name} | {value} | {gate} |" for name, value, gate in rows]
    lines += [
        "", "The <= 4 min value is the **historical first-preview gate**. "
        "It does not establish the finished-creative target. Runtime wall time is not "
        "submission-to-ready time; see the separate evaluation below.",
    ]

    by_role = metrics.get("by_role")
    if isinstance(by_role, dict) and by_role:
        lines += [
            "",
            "| role | calls | failed | total | slowest | in tokens | out tokens |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for role in sorted(by_role):
            stats = by_role[role] or {}
            lines.append(
                f"| {role} | {_num(stats.get('calls'))} | {_num(stats.get('failed'))} "
                f"| {_ms(stats.get('duration_ms_total'))} "
                f"| {_ms(stats.get('duration_ms_max'))} "
                f"| {_num(stats.get('input_tokens'))} | {_num(stats.get('output_tokens'))} |"
            )
    return lines


# --- optional creative-evaluation receipt (local observation, no runtime authority) -------------


_TIMINGS = {
    "worker_started_at": "queue_ms", "first_preview_at": "first_preview_ms",
    "agent_completed_at": "agent_completion_ms", "saved_at": "save_ms",
    "visible_ready_at": "visible_ready_ms", "export_verified_at": "export_verified_ms",
    "observed_until_at": "observed_elapsed_ms",
}
_FINISH_STAMPS = ("agent_completed_at", "saved_at", "visible_ready_at", "export_verified_at")


def evaluate_creative(receipt: dict | None, manifest: dict | None = None) -> dict:
    """Measure one submission, including internal retries, from explicit UTC/offset stamps.

    Receipt evidence references are observer attestations, not independently verified pixels.
    In particular neither a run_metrics outcome nor current_scene proves browser readiness.
    Missing observations stay null; a timeout stays in the denominator without inventing an
    end timestamp. Assisted repairs need their own receipt linked to the untouched first case.
    """
    gaps: list[str] = []
    result = {
        "status": "unavailable", "finished_creative_ms": None, "within_target": None,
        "within_stretch": None, "target_ms": 240_000, "stretch_ms": 180_000,
        "diagnostic_ceiling_ms": 600_000, "include_in_denominator": True,
        "first_pass_eligible": False, "attempts_total": None,
        "evidence_basis": "observer receipt; evidence references require independent review",
        "gaps": gaps, **dict.fromkeys(_TIMINGS.values()),
    }
    if not receipt:
        gaps.append("finished-creative evidence unavailable: no evaluation receipt")
        return result
    for name in ("context", "timestamps", "delivery", "controls"):
        if name in receipt and not isinstance(receipt[name], dict):
            gaps.append(f"{name} must be an object")
    if gaps:
        result["status"] = "invalid"
        return result
    errors: list[str] = []
    if receipt.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    phase = receipt.get("phase")
    corrections = receipt.get("operator_corrections")
    if phase not in ("first_pass", "assisted_repair"):
        errors.append("phase must distinguish first_pass from assisted_repair")
    if type(corrections) is not int or corrections < 0:
        errors.append("operator_corrections must be a non-negative integer")
    elif phase == "first_pass" and corrections:
        errors.append("first_pass cannot contain operator_corrections")
    if phase == "assisted_repair" and not receipt.get("parent_case_id"):
        errors.append("assisted_repair requires parent_case_id")
    attempts = receipt.get("attempts")
    attempt_errors: list[str] = []
    if not isinstance(attempts, list) or not attempts:
        attempt_errors.append("attempts must be a nonempty list of attempt records")
    else:
        for index, attempt in enumerate(attempts):
            if not isinstance(attempt, dict):
                attempt_errors.append(f"attempts[{index}] must be an object")
                continue
            run_ref = attempt.get("run_ref")
            if not isinstance(run_ref, str) or not run_ref.strip():
                attempt_errors.append(f"attempts[{index}].run_ref must be a nonempty string")
            elif index == 0 and run_ref != receipt.get("run_ref"):
                attempt_errors.append("attempts[0].run_ref must match the receipt run_ref")
            kinds = ("initial",) if index == 0 else ("internal_retry", "internal_repair")
            if attempt.get("kind") not in kinds:
                attempt_errors.append(f"attempts[{index}].kind must be {' or '.join(kinds)}")
        if not attempt_errors:
            result["attempts_total"] = len(attempts)
    errors.extend(attempt_errors)
    stamps = {}
    for name in ("submitted_at", *_TIMINGS):
        raw = (receipt.get("timestamps") or {}).get(name)
        if raw is None:
            gaps.append(f"{name} unavailable")
            continue
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("timezone required")
            stamps[name] = stamp
        except (AttributeError, TypeError, ValueError):
            errors.append(f"{name} invalid: timezone-aware ISO timestamp required")
    start = stamps.get("submitted_at")
    if start is not None:
        for name, key in _TIMINGS.items():
            if name in stamps:
                elapsed = round((stamps[name] - start).total_seconds() * 1000)
                if stamps[name] < start:
                    errors.append(f"{name} precedes submitted_at")
                else:
                    result[key] = elapsed
    for earlier, later in (
        ("worker_started_at", "agent_completed_at"),
        ("saved_at", "visible_ready_at"), ("saved_at", "export_verified_at"),
    ):
        if earlier in stamps and later in stamps and stamps[earlier] > stamps[later]:
            errors.append(f"{later} precedes {earlier}")
    if "observed_until_at" in stamps and any(
        stamp > stamps["observed_until_at"] for stamp in stamps.values()
    ):
        errors.append("observed_until_at precedes an observation")

    delivery = receipt.get("delivery") or {}
    context = receipt.get("context") or {}
    evidence_ok = True
    for name in ("document_id", "scene_sha256", "first_scene_ref", "first_png_ref"):
        if not delivery.get(name):
            gaps.append(f"delivery.{name} unavailable")
            evidence_ok = False
    if type(delivery.get("version")) is not int or delivery["version"] < 0:
        gaps.append("delivery.version unavailable")
        evidence_ok = False
    if delivery.get("document_id") != context.get("document_id"):
        errors.append("delivery.document_id does not match context.document_id")
    for name in ("save_proof", "visible_ready_proof", "export_proof"):
        proof = delivery.get(name) or {}
        if not isinstance(proof, dict) or not proof.get("ref"):
            gaps.append(f"delivery.{name} unavailable")
            evidence_ok = False
        elif any(proof.get(key) != delivery.get(key) for key in ("document_id", "version")):
            errors.append(f"delivery.{name} does not match the delivered document/version")
    if manifest is not None:
        document = manifest.get("document") or {}
        for name, observed, claimed in (
            ("run_ref", manifest.get("ref"), receipt.get("run_ref")),
            ("workspace_id", manifest.get("workspace_id"), context.get("workspace_id")),
            ("document_id", document.get("id"), context.get("document_id")),
        ):
            if not observed or observed != claimed:
                errors.append(f"{name} does not match the materialized run view")
        # The view is CURRENT, so later edits must never pass as the untouched delivery.
        if document.get("current_version") != delivery.get("version"):
            errors.append("current_version differs from delivery.version; preserve the first view")
    complete = start is not None and all(name in stamps for name in _FINISH_STAMPS)
    if errors:
        result["status"] = "invalid"
        gaps.extend(errors)
    elif complete and evidence_ok:
        finish = max(stamps[name] for name in _FINISH_STAMPS)
        elapsed = round((finish - start).total_seconds() * 1000)
        result.update(status="observed", finished_creative_ms=elapsed,
                      within_target=elapsed <= 240_000, within_stretch=elapsed <= 180_000)
    elif (result["observed_elapsed_ms"] or 0) >= 600_000:
        result["status"] = "timed_out"
    result["first_pass_eligible"] = phase == "first_pass" and corrections == 0 and not errors
    return result


def compare_evaluations(baseline: dict, candidate: dict) -> dict:
    """Check paired receipt consistency. This VIEW cannot enforce execution isolation.

    Matching snapshot strings alone do not show that retrieval used the frozen corpus.
    Require named audit receipts and report consistency only; independent execution-seam
    review must establish source eligibility/cache isolation before a causal quality claim.
    """
    gaps: list[str] = []
    evaluations = [evaluate_creative(receipt) for receipt in (baseline, candidate)]
    if any(not isinstance(receipt.get(key, {}), dict)
           for receipt in (baseline, candidate)
           for key in ("context", "timestamps", "delivery", "controls")):
        return {"status": "ineligible", "execution_isolation_verified": False,
                "gaps": ["both arms require valid first_pass receipts"] + [
                    gap for evaluation in evaluations for gap in evaluation["gaps"]]}
    for key in ("pair_id", "request"):
        if not baseline.get(key) or baseline.get(key) != candidate.get(key):
            gaps.append(f"{key} missing or different")
    if baseline.get("arm") != "baseline" or candidate.get("arm") != "candidate":
        gaps.append("arms must be baseline then candidate")
    for key in ("workspace_id", "product_id", "brand_kit_id", "brand_kit_version"):
        left, right = baseline.get("context") or {}, candidate.get("context") or {}
        if left.get(key) is None or left.get(key) != right.get(key):
            gaps.append(f"context.{key} missing or different")
    for key in ("case_id", "run_ref"):
        if not baseline.get(key) or not candidate.get(key) or baseline[key] == candidate[key]:
            gaps.append(f"{key} must be present and distinct")
    left, right = baseline.get("context") or {}, candidate.get("context") or {}
    for key in ("project_id", "thread_id", "document_id"):
        if not left.get(key) or not right.get(key) or left[key] == right[key]:
            gaps.append(f"context.{key} must be present and distinct")
    left, right = baseline.get("controls") or {}, candidate.get("controls") or {}
    for key in ("runtime_sha256", "model_config_sha256", "source_snapshot_sha256",
                "load_profile", "worker_limit", "provider_limit"):
        if not left.get(key) or left.get(key) != right.get(key):
            gaps.append(f"controls.{key} missing or different")
    for arm, receipt, evaluation in zip(("baseline", "candidate"),
                                         (baseline, candidate), evaluations, strict=True):
        if not evaluation["first_pass_eligible"]:
            gaps.append(f"{arm} must be an untouched first_pass receipt")
            gaps.extend(f"{arm}.{gap}" for gap in evaluation["gaps"])
        controls = receipt.get("controls") or {}
        for key in ("knowledge_bundle_sha256", "source_snapshot_ref",
                    "source_enforcement_ref", "cache_isolation_ref"):
            if not controls.get(key):
                gaps.append(f"{arm}.controls.{key} unavailable")
        if controls.get("empty_history") is not True:
            gaps.append(f"{arm}.controls.empty_history is not established")
        hits = controls.get("cache_hits")
        if type(hits) is not int or hits < 0:
            gaps.append(f"{arm}.controls.cache_hits unavailable")
    for key in ("generated_cache_namespace", "knowledge_bundle_sha256"):
        if not left.get(key) or not right.get(key) or left[key] == right[key]:
            gaps.append(f"controls.{key} must be present and distinct")
    return {"status": "ineligible" if gaps else "receipt_consistent",
            "execution_isolation_verified": False, "gaps": gaps}


def _evaluation_section(evaluation: dict) -> list[str]:
    rows = [("queue", "queue_ms"), ("submission to first preview", "first_preview_ms"),
            ("submission to agent completion", "agent_completion_ms"),
            ("submission to save", "save_ms"), ("submission to visible ready", "visible_ready_ms"),
            ("submission to verified export", "export_verified_ms"),
            ("finished creative", "finished_creative_ms")]
    lines = ["", "## Finished-creative evaluation", "",
             f"Status: **{evaluation['status']}**. Target <= 240s; stretch <= 180s. "
             "All durations start at user submission and include queue and internal retries. "
             "Finish requires the same saved, visible, usable artifact and a valid export; "
             "agent completion alone is insufficient.", "",
             "Observer evidence references require independent review. Human acceptance, "
             "native editability and execution isolation are not inferred by this view.", "",
             "| observation | elapsed |", "| --- | ---: |"]
    for name, key in rows:
        value = _ms(evaluation[key]) if evaluation[key] is not None else "unavailable"
        lines.append(f"| {name} | {value} |")
    lines += ["", f"First-pass eligible: {evaluation['first_pass_eligible']}; "
              f"attempts: {evaluation['attempts_total']}; "
              f"retain in denominator: {evaluation['include_in_denominator']}."]
    comparison = evaluation.get("comparison")
    if comparison:
        lines += ["", f"Paired receipts: **{comparison['status']}**. "
                  "Execution isolation is not verified by this view."]
        lines += [f"- {gap}" for gap in comparison["gaps"]]
    lines += [f"- {gap}" for gap in evaluation["gaps"]]
    return lines


def _readme(view: RunView, *, copy: bool, skipped: list[str]) -> str:
    manifest = view.manifest
    # Regenerate with the ref the caller ASKED for — on a bridged view that is the inner id, and
    # it is what reproduces this directory (the outer ref would write a different one).
    asked = manifest.get("bridged_from") or manifest.get("ref")
    lines = [
        f"# Design run view — `{manifest.get('ref')}`",
        "",
        "This directory is **derived and disposable**. It is a materialized VIEW, assembled",
        "on demand by `subsystems/clue-design/scripts/run_view.py`; nothing reads it back and",
        "deleting it loses nothing. Regenerate it any time:",
        "",
        "```",
        "set -a; source .env; set +a",
        f".venv/bin/python subsystems/clue-design/scripts/run_view.py {asked}",
        "```",
        "",
        "## Where this actually lives (the real homes)",
        "",
        "| here | real home |",
        "| --- | --- |",
        "| `brief.json` | the leg's frozen context bundle, in platform blob storage "
        "(`CLUE_STORAGE_FS_ROOT`) |",
        "| `scene.current.json` | `design_document.current_scene_json` (Postgres) |",
        "| `envelopes/` | `design_edit_envelope` (Postgres), seq-ordered |",
        "| `events.jsonl` | `run_event` where `subject_kind='design_run'` (Postgres) |",
        "| `assets/` | "
        + ("copies of " if copy else "symlinks into ")
        + "the engine materialization cache (`LUMEN_ASSET_STORE_ROOT`, preferred) or the "
        "durable design blob (`CLUE_STORAGE_FS_ROOT/{workspace}/design/{digest}`) |",
        "",
        "## Contents",
        "",
    ]
    counts = manifest.get("counts") or {}
    lines += [
        f"- envelopes: {counts.get('envelopes', len(view.envelopes))}",
        f"- events: {counts.get('events', len(view.events))}",
        f"- assets: {counts.get('assets', len(view.assets))}",
        f"- brief: {'present' if view.brief is not None else 'absent (see gaps)'}",
        f"- scene: {'present' if view.scene is not None else 'absent (see gaps)'}",
    ]
    lines += _metrics_section(view.metrics)
    lines += _evaluation_section(manifest.get("evaluation") or evaluate_creative(None))
    if manifest.get("bridged_from"):
        lines += [
            "",
            "## Bridged ref",
            "",
            f"You asked for `{manifest['bridged_from']}`; this view is of "
            f"`{manifest.get('ref')}`. See the gap below.",
        ]
    if skipped:
        lines += [
            "",
            "## Assets with no bytes on this machine",
            "",
            "Named, not dropped — absence is a fact this view exists to show. The cache is a "
            "per-machine materialization and a durable blob may sit on another deployment's "
            "storage backend, so absence here is not proof the bytes were never produced.",
            "",
        ]
        lines += [f"- `{asset_id}`" for asset_id in skipped]
    gaps = manifest.get("gaps") or []
    lines += ["", "## Gaps", ""]
    lines += [f"- {gap}" for gap in gaps] if gaps else ["None — every piece resolved."]
    return "\n".join(lines) + "\n"


# --- the CLI --------------------------------------------------------------------------------


_SOURCE_HINT = (
    "  Run from the repo root with the workspace env sourced:\n    set -a; source .env; set +a"
)


def _require_env(name: str, why: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"run_view: {name} is not set. {why}\n{_SOURCE_HINT}")
    return value


def _require_absolute_root(name: str, raw: str, why: str) -> Path:
    """A RELATIVE root is refused as loudly as a missing one.

    ``Path('.artifacts')`` resolves against wherever the operator happens to stand, so the view
    would report the frozen context bundle and every durable asset as missing — the identical
    confident lie the unset-refusal exists to close, and the same cwd-relative-root class the
    design custody fix killed. Naming the path it WOULD have used is the actionable part.
    """
    path = Path(raw)
    if not path.is_absolute():
        raise SystemExit(
            f"run_view: {name}={raw!r} is a relative path — it would resolve to "
            f"{path.resolve()} from this working directory. {why}\n{_SOURCE_HINT}"
        )
    return path


def _redact(database_url: str) -> str:
    """``host:port/database`` — never the credentials, which a shell error line outlives."""
    parts = urlsplit(database_url.replace("+asyncpg", ""))
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.hostname or '?'}{port}/{parts.path.lstrip('/') or '?'}"


# Connection-class failures only: a refused socket, a bad DSN host, wrong credentials, an absent
# database. Everything else (a query error, a bug here) keeps its traceback — a friendly message
# over an unexpected exception is how a real defect gets mistaken for a config problem.
_UNREACHABLE = (
    OSError,
    asyncpg.PostgresConnectionError,
    asyncpg.InvalidAuthorizationSpecificationError,
    asyncpg.InvalidCatalogNameError,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_view.py",
        description="Materialize one design run's derived, disposable view.",
    )
    parser.add_argument(
        "ref", help="a design run id (run_…), a document id (doc_…), or a leg UUID"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=f"output directory (default: {_DEFAULT_OUT_ROOT}/<ref>)",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="copy asset bytes instead of symlinking them (for handing the directory around)",
    )
    parser.add_argument(
        "--evaluation-receipt", type=Path,
        help="local browser/operator evaluation JSON; kept separate from run metrics",
    )
    parser.add_argument("--comparison-receipt", type=Path,
                        help="baseline receipt to compare with the candidate evaluation receipt")
    args = parser.parse_args(argv)
    if args.comparison_receipt and not args.evaluation_receipt:
        parser.error("--comparison-receipt requires --evaluation-receipt")
    receipts = []
    for path in (args.evaluation_receipt, args.comparison_receipt):
        if path is None:
            receipts.append(None)
            continue
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(receipt, dict):
                raise ValueError("receipt must be a JSON object")
            receipts.append(receipt)
        except (OSError, ValueError) as error:
            parser.error(f"cannot read evaluation receipt {path}: {error}")

    database_url = _require_env("CLUE_DATABASE_URL", "The view reads Postgres (read-only).")
    why_root = (
        "Refusing to guess the durable blob root: a wrong root reports the frozen context "
        "bundle and every durable asset as missing, which is a confident lie."
    )
    storage_fs_root = _require_absolute_root(
        "CLUE_STORAGE_FS_ROOT", _require_env("CLUE_STORAGE_FS_ROOT", why_root), why_root
    )

    # The cache root's DEFAULT is legitimately repo-relative (it is resolved absolute here), and
    # a wrong cache root only costs a fallback to the durable blob — so an operator-supplied
    # relative value warns and continues rather than refusing.
    raw_cache = os.environ.get("LUMEN_ASSET_STORE_ROOT", "").strip()
    asset_store_root = Path(raw_cache) if raw_cache else _DEFAULT_ASSET_STORE_ROOT
    if not asset_store_root.is_absolute():
        asset_store_root = asset_store_root.resolve()
        print(
            f"run_view: warning — LUMEN_ASSET_STORE_ROOT={raw_cache!r} is relative; reading the "
            f"engine cache at {asset_store_root}",
            file=sys.stderr,
        )

    try:
        view = asyncio.run(
            load_view(
                args.ref,
                database_url=database_url,
                asset_store_root=asset_store_root,
                storage_fs_root=storage_fs_root,
            )
        )
    except RunViewNotFound as error:
        raise SystemExit(f"run_view: {error}") from error
    except _UNREACHABLE as error:
        raise SystemExit(
            f"run_view: cannot reach the database at {_redact(database_url)} — check "
            f"CLUE_DATABASE_URL ({type(error).__name__}: {error})"
        ) from error

    out = args.out or _DEFAULT_OUT_ROOT / _safe_name(args.ref, "unnamed-ref")
    materialize(view, out, copy=args.copy,
                evaluation_receipt=receipts[0], comparison_receipt=receipts[1])

    counts = view.manifest.get("counts") or {}
    print(
        f"ref {view.manifest.get('ref')}: {counts.get('envelopes', 0)} envelopes, "
        f"{counts.get('events', 0)} events, {counts.get('assets', 0)} assets",
        file=sys.stderr,
    )
    for gap in view.manifest.get("gaps") or []:
        print(f"gap: {gap}", file=sys.stderr)
    print(out)  # last line on stdout: the path
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())

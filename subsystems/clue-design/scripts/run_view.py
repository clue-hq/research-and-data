#!/usr/bin/env python
"""Materialize one design run's derived view into a browsable `.design-runs/<ref>/` directory.

Founder-ratified 2026-08-23 (`docs/superpowers/plans/2026-08-23-design-run-view.md`): the
design subsystem keeps its three real homes — the frozen context bundle in platform blob
storage, the engine materialization cache, and Postgres as the sole source of truth for
scenes/envelopes/events — and this tool is a VIEW over them, never a fourth substrate. What it
writes is DERIVED and DISPOSABLE: delete `.design-runs/` at any time, nothing reads it back.

Usage, from the repo root with the colombo `.env` sourced::

    set -a; source .env; set +a
    python subsystems/clue-design/scripts/run_view.py <ref> [--out DIR] [--copy]

`<ref>` is a design run id (`run_…`), a document id (`doc_…`), or a leg UUID. Environment:

* ``CLUE_DATABASE_URL``    — required; the platform Postgres (read-only here).
* ``CLUE_STORAGE_FS_ROOT`` — required, and deliberately NOT guessed: a cwd-relative default is
  exactly the bug class the design custody fix closed, and a wrong root here would report the
  frozen bundle and every durable asset blob as missing — a confident lie.
* ``LUMEN_ASSET_STORE_ROOT`` — optional; defaults to this repo's git-ignored `.engine-cache`,
  mirroring ``py_lumen_config.Settings.effective_asset_store_root`` (restated rather than
  imported so the script composes no app and needs no settings singleton).

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
from pathlib import Path

import asyncpg

_DESIGN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_DESIGN_ROOT / "apps" / "api"))

from lumen_api.run_view import AssetView, RunView, RunViewNotFound, assemble  # noqa: E402

# The engine materialization cache's documented default home (see the module docstring).
_DEFAULT_ASSET_STORE_ROOT = _DESIGN_ROOT / ".engine-cache"
_DEFAULT_OUT_ROOT = _DESIGN_ROOT / ".design-runs"

# Bounded, most-recent-first: the payload scan below is unindexed, so it is capped rather than
# allowed to walk the whole stream. The window doubles as an ambiguity check — if several outer
# runs mention the same inner id, the view says so instead of picking one silently.
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

    view = await assemble(outer, database_url=database_url, **roots)
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
    """Clear exactly what a previous materialization wrote, and nothing else.

    Re-running on the same ref must not leave the previous view's envelopes or asset links
    behind (a stale file in a derived view is a lie, and a leftover symlink would crash the
    second run outright). Only the known output names are removed — this never empties a
    directory the caller pointed ``--out`` at for other reasons.
    """
    for name in _WRITTEN_FILES:
        (out / name).unlink(missing_ok=True)
    for name in _WRITTEN_DIRS:
        path = out / name
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)


def materialize(view: RunView, out_dir: Path, *, copy: bool = False) -> None:
    """Write the run view's browsable layout into ``out_dir``.

    Absent sections are skipped silently — ``manifest['gaps']`` already names them, and an empty
    file would imply an emptiness the assembler did not assert.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _reset(out)

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
        f"python subsystems/clue-design/scripts/run_view.py {asked}",
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


def _require_env(name: str, why: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"run_view: {name} is not set. {why}\n"
            "  Run from the repo root with the workspace env sourced:\n"
            "    set -a; source .env; set +a"
        )
    return value


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
    args = parser.parse_args(argv)

    database_url = _require_env("CLUE_DATABASE_URL", "The view reads Postgres (read-only).")
    storage_fs_root = _require_env(
        "CLUE_STORAGE_FS_ROOT",
        "Refusing to guess the durable blob root: a wrong root reports the frozen context "
        "bundle and every durable asset as missing, which is a confident lie.",
    )
    asset_store_root = Path(
        os.environ.get("LUMEN_ASSET_STORE_ROOT", "").strip() or _DEFAULT_ASSET_STORE_ROOT
    )

    try:
        view = asyncio.run(
            load_view(
                args.ref,
                database_url=database_url,
                asset_store_root=asset_store_root,
                storage_fs_root=Path(storage_fs_root),
            )
        )
    except RunViewNotFound as error:
        raise SystemExit(f"run_view: {error}") from error

    out = args.out or _DEFAULT_OUT_ROOT / _safe_name(args.ref, "unnamed-ref")
    materialize(view, out, copy=args.copy)

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

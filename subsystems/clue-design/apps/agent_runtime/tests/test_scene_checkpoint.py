"""P0.4 — checkpoint commits: the runtime half of the seam.

`subsystems/clue-design/docs/deepagent-fast-loop-v1-spec.md` §4 P0.4. The scene deepagent used to
hand its work to the caller ONCE, at finalize, so the 2026-08-24 run that spent 20m42s producing a
valid, reviewer-accepted scene and then hit an OpenRouter 403 on its last model call discarded all
of it ("Nothing was saved", document still at version 0).

`LumenDesignTools.checkpoint_scene` is the seam that fixes it, and `render_preview` is where it
fires: the ORCHESTRATOR runs that tool once per round at its step-5 verification, so a render that
produced a validated raster is the one moment Python can observe "an authoring round finished and
its scene is real".

AMENDED 2026-08-24 (fast loop §5.2): `render_preview` is no longer orchestrator-only — under
`LUMEN_AGENT_FAST_LOOP` the author gets its own instance so it can see its own edits. That instance
is built with `checkpoint=False` and does NOT fire this seam, precisely so a checkpoint keeps
meaning "a round was ACCEPTED" rather than "somebody rendered". The trigger below is unchanged, and
`tests/test_fast_loop.py` pins the two-instance split.

AMENDED 2026-09-02 (task 4b, controller ruling): the trigger's predicate is `checkpoint_acceptance`,
not the folded `reviewer` verdict. The canonical SVG export refuses to embed WOFF2 brand faces — 367
of 517 stored faces, across 47 workspaces — so for those brands `reviewer.status` was error EVERY
round while the critic PNG rendered clean, and no checkpoint ever committed. An export-format
limitation is not a rejected round. `reviewer` itself is unchanged; only the predicate moved.

The commit itself belongs to the caller (`lumen_api.main._LegSceneCommitter`, covered by
`apps/api/tests/test_scene_turn_persist.py` section (i)). What is pinned here is the contract the
runtime owes it: the FULL ledger every time, only when it grew, and never at the cost of the run.
"""

from __future__ import annotations

import json

from lumen_agent.tools import render as render_mod
from lumen_agent.tools.substrate import (
    LumenDesignTools,
    bundle_validation_errors,
    checkpoint_acceptance,
    reviewer_bundle_status,
)

from agent_fixtures import FakeCoreClient, runtime_config


def _tools(tmp_path, monkeypatch, sink=None) -> LumenDesignTools:
    monkeypatch.setattr("lumen_agent.tools.substrate.CoreClient", FakeCoreClient)
    return LumenDesignTools(
        runtime_config(tmp_path), "Make a LinkedIn ad", scene_checkpoint=sink
    )


def _log(tools: LumenDesignTools, *kinds: str) -> None:
    """Put operations on the ledger the way a clean compile does."""
    tools.iteration += 1
    tools._log_scene_operations(
        "compile_dsl_block", [{"kind": kind} for kind in kinds]
    )


class _Sink:
    def __init__(self, raises: int = 0) -> None:
        self.calls: list[tuple[list, dict]] = []
        self._raises = raises

    def __call__(self, operations, meta):
        self.calls.append((list(operations), dict(meta)))
        if self._raises:
            self._raises -= 1
            raise RuntimeError("the document moved under us")


def test_a_checkpoint_hands_over_the_whole_ledger_not_just_the_new_tail(
    tmp_path, monkeypatch
) -> None:
    """The sink is offered every operation the run has applied, in order, every time.

    The caller commits only the prefix it has not made durable, so handing it the whole ledger is
    what makes a dropped checkpoint self-healing: the tail it refused is simply re-offered inside
    the next one.
    """
    sink = _Sink()
    tools = _tools(tmp_path, monkeypatch, sink)

    _log(tools, "add_page")
    tools.checkpoint_scene("render_preview")
    _log(tools, "insert_node", "set_text")
    tools.checkpoint_scene("render_preview")

    assert [[op["kind"] for op in operations] for operations, _ in sink.calls] == [
        ["add_page"],
        ["add_page", "insert_node", "set_text"],
    ]
    assert sink.calls[-1][1]["reason"] == "render_preview"
    assert sink.calls[-1][1]["operations_total"] == 3


def test_a_round_that_changed_nothing_never_mints_a_version(tmp_path, monkeypatch) -> None:
    """No new operations, no call — an unchanged re-render must not cost a document version."""
    sink = _Sink()
    tools = _tools(tmp_path, monkeypatch, sink)

    tools.checkpoint_scene("render_preview")  # nothing applied yet
    _log(tools, "add_page")
    tools.checkpoint_scene("render_preview")
    tools.checkpoint_scene("render_preview")  # the L4b unchanged re-render
    tools.checkpoint_scene("render_preview")

    assert len(sink.calls) == 1


def test_a_failing_checkpoint_never_fails_the_run_and_is_re_offered(
    tmp_path, monkeypatch
) -> None:
    """A checkpoint that cannot be committed costs a version, never the run.

    The refused operations stay un-acknowledged, so the next checkpoint carries them again — which
    is what lets a transient conflict heal instead of silently dropping a round's work.
    """
    sink = _Sink(raises=1)
    tools = _tools(tmp_path, monkeypatch, sink)

    _log(tools, "add_page")
    tools.checkpoint_scene("render_preview")  # raises inside the sink; must not propagate
    _log(tools, "insert_node")
    tools.checkpoint_scene("render_preview")

    assert [[op["kind"] for op in operations] for operations, _ in sink.calls] == [
        ["add_page"],
        ["add_page", "insert_node"],
    ]
    events = [
        json.loads(line)["event"]
        for line in (tools.trace_dir / "trace.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert "scene_checkpoint_failed" in events
    assert "scene_checkpointed" in events


def test_no_sink_means_the_run_is_save_on_finalize_only(tmp_path, monkeypatch) -> None:
    """Every CLI / fixture / direct-editor path passes no sink and must be untouched by P0.4."""
    tools = _tools(tmp_path, monkeypatch, None)

    _log(tools, "add_page")
    tools.checkpoint_scene("render_preview")  # a no-op, and above all not a crash

    events = [
        json.loads(line)["event"]
        for line in (tools.trace_dir / "trace.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert "scene_checkpointed" not in events


def test_the_checkpoint_records_whether_preflight_was_clean(tmp_path, monkeypatch) -> None:
    """Recorded, deliberately NOT gated on.

    A scene that rendered a validated raster is work worth keeping even while preflight still
    reports diagnostics — LUMV0820 blocks export on runs the fast-loop spec's P0.2/P0.3 own, and
    gating here would make P0.4 silent on exactly the runs that most need it. The reader decides
    what a dirty checkpoint is worth; this seam only refuses to throw the scene away.
    """
    sink = _Sink()
    tools = _tools(tmp_path, monkeypatch, sink)

    _log(tools, "add_page")
    tools.latest_preflight_has_errors = True
    tools.checkpoint_scene("render_preview")
    _log(tools, "insert_node")
    tools.latest_preflight_has_errors = False
    tools.checkpoint_scene("render_preview")

    assert [meta["preflight_clean"] for _, meta in sink.calls] == [False, True]


# --- round acceptance (task 4b, controller ruling 2026-09-02) -----------------
#
# The checkpoint predicate used to be `reviewer.status == "ok" and not
# reviewer.validation_errors`. The live walk proved that never holds for a brand
# whose fonts are WOFF2 (367 of 517 stored faces, 47 workspaces): the canonical
# SVG export refuses to embed a font container whose fsType it cannot read, that
# refusal folds into `reviewer`, and no checkpoint ever committed — while the
# critic PNG rendered clean every round. An EXPORT-FORMAT limitation is not a
# rejected round, so acceptance now keys on the raster.

# Verbatim from the live run
# .deepagent-workspace/run_5e3764bec5b5468f96385c49e360fafa/iterations/001/preview_bundle.json
FONT_EMBED_REFUSAL = (
    'SVG font embedding failed for page linkedin_square: font "Season Mix VF" cannot be '
    "license-checked for embedding: unsupported font container (magic 0x774F4632; single "
    "TTF/OTF required) — refusing to embed bytes whose fsType cannot be read"
)


def _canonical_ok() -> dict:
    return {
        "status": "ok",
        "requested_format": "svg",
        "diagnostics": [],
        "artifacts": [
            {"format": "svg", "path": "/tmp/preview.svg", "validation_errors": []}
        ],
        "validation_errors": [],
    }


def _canonical_woff2_refusal() -> dict:
    """The canonical block of a real WOFF2-brand round: error, one refusal, no artifact."""
    return {
        "status": "error",
        "requested_format": "svg",
        "diagnostics": [],
        "artifacts": [],
        "validation_errors": [FONT_EMBED_REFUSAL],
    }


def _critic_ok() -> dict:
    return {
        "status": "ok",
        "requested_format": "png",
        "diagnostics": [],
        "artifacts": [
            {"format": "png", "path": "/tmp/preview.png", "validation_errors": []}
        ],
        "validation_errors": [],
    }


def test_a_canonical_svg_font_embedding_refusal_alone_still_accepts_the_round() -> None:
    """(a) The WOFF2 shape: the raster is the acceptance proof, so the round is accepted."""
    acceptance = checkpoint_acceptance(_canonical_woff2_refusal(), _critic_ok())

    assert acceptance.accepted is True
    assert acceptance.blocking_errors == []


def test_any_other_canonical_error_blocks_and_is_named() -> None:
    """(b) The narrowness of the carve-out: only the embedding refusal is excused."""
    canonical = _canonical_woff2_refusal()
    canonical["validation_errors"].append(
        "SVG preview does not contain an <svg root near the start"
    )

    acceptance = checkpoint_acceptance(canonical, _critic_ok())

    assert acceptance.accepted is False
    assert acceptance.blocking_errors == [
        "canonical: SVG preview does not contain an <svg root near the start"
    ]


def test_a_canonical_failure_that_names_nothing_blocks() -> None:
    """A canonical status error with no error text cannot be classified as the refusal."""
    canonical = {
        "status": "error",
        "requested_format": "svg",
        "artifacts": [],
        "validation_errors": [],
    }

    acceptance = checkpoint_acceptance(canonical, _critic_ok())

    assert acceptance.accepted is False
    assert acceptance.blocking_errors == ["canonical preview status is error"]


def test_a_failing_critic_blocks_even_when_the_canonical_svg_is_clean() -> None:
    """(c) The raster IS the proof — if it did not render, nothing was accepted."""
    critic = {
        "status": "error",
        "requested_format": "png",
        "artifacts": [
            {
                "format": "png",
                "path": "/tmp/preview.png",
                "validation_errors": ["PNG preview has an invalid PNG signature"],
            }
        ],
        "validation_errors": [],
    }

    acceptance = checkpoint_acceptance(_canonical_ok(), critic)

    assert acceptance.accepted is False
    assert acceptance.blocking_errors == [
        "critic preview status is error",
        "critic png: PNG preview has an invalid PNG signature",
    ]


def test_both_summaries_clean_accepts() -> None:
    """(d) The ordinary TTF/OTF-brand round, unchanged by this ruling."""
    acceptance = checkpoint_acceptance(_canonical_ok(), _critic_ok())

    assert acceptance.accepted is True
    assert acceptance.blocking_errors == []


def test_the_reviewer_verdict_the_agent_loop_reads_is_untouched() -> None:
    """(f) Only the CHECKPOINT predicate moved.

    `reviewer.status` / `reviewer.validation_errors` are the agent's own truth — the
    orchestrator reads them to decide whether the round is presentable. A WOFF2 round still
    reports error, with both errors verbatim, exactly as before.
    """
    canonical = _canonical_woff2_refusal()
    critic = _critic_ok()

    assert reviewer_bundle_status(canonical, critic) == "error"
    assert bundle_validation_errors(canonical, critic) == [
        "canonical preview status is error",
        f"canonical: {FONT_EMBED_REFUSAL}",
    ]
    # ...and the round is accepted anyway.
    assert checkpoint_acceptance(canonical, critic).accepted is True


# --- the render_preview trigger ----------------------------------------------


def _render_payload(canonical: dict, critic: dict) -> str:
    """A bundle payload shaped exactly as `export_preview_bundle` builds one."""
    validation_errors = bundle_validation_errors(canonical, critic)
    return json.dumps(
        {
            "debug_only": False,
            "debug_reason": None,
            "canonical": canonical,
            "critic": critic,
            "reviewer": {
                "status": reviewer_bundle_status(canonical, critic),
                "requested_format": "png",
                "artifacts": list(canonical.get("artifacts", []))
                + list(critic.get("artifacts", [])),
                "validation_errors": validation_errors,
                "diagnostics": [],
            },
        }
    )


def _drive_render(tmp_path, monkeypatch, sink, canonical: dict, critic: dict) -> str:
    tools = _tools(tmp_path, monkeypatch, sink)
    _log(tools, "add_page")

    png = tmp_path / "preview.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(
        tools, "export_preview_bundle", lambda **_: _render_payload(canonical, critic)
    )
    monkeypatch.setattr(render_mod, "_latest_preview_png", lambda _tools: png)

    return render_mod._render_preview_text(tools)


def test_render_preview_checkpoints_the_woff2_round_exactly_once(
    tmp_path, monkeypatch
) -> None:
    """(e) The live regression: a WOFF2 brand's round now commits.

    And the summary the model reads is unchanged — still status=error, still both errors.
    """
    sink = _Sink()
    text = _drive_render(
        tmp_path, monkeypatch, sink, _canonical_woff2_refusal(), _critic_ok()
    )

    assert len(sink.calls) == 1
    assert sink.calls[0][1]["reason"] == "render_preview"
    assert text.splitlines()[0] == "render_preview: status=error"
    assert f"  - canonical: {FONT_EMBED_REFUSAL}" in text


def test_render_preview_does_not_checkpoint_when_the_critic_render_failed(
    tmp_path, monkeypatch
) -> None:
    """(e, negative) A round whose raster did not validate is not a finished round."""
    sink = _Sink()
    critic = _critic_ok()
    critic["status"] = "error"
    critic["artifacts"][0]["validation_errors"] = ["artifact bytes are empty"]

    _drive_render(tmp_path, monkeypatch, sink, _canonical_ok(), critic)

    assert sink.calls == []


def test_render_preview_checkpoints_a_wholly_clean_round(tmp_path, monkeypatch) -> None:
    """The unchanged ordinary case."""
    sink = _Sink()
    _drive_render(tmp_path, monkeypatch, sink, _canonical_ok(), _critic_ok())

    assert len(sink.calls) == 1


def test_render_preview_without_a_png_never_checkpoints(tmp_path, monkeypatch) -> None:
    """The gate still requires a PNG on disk — acceptance is not a substitute for pixels."""
    sink = _Sink()
    tools = _tools(tmp_path, monkeypatch, sink)
    _log(tools, "add_page")

    monkeypatch.setattr(
        tools,
        "export_preview_bundle",
        lambda **_: _render_payload(_canonical_ok(), _critic_ok()),
    )
    monkeypatch.setattr(render_mod, "_latest_preview_png", lambda _tools: None)

    render_mod._render_preview_text(tools)

    assert sink.calls == []

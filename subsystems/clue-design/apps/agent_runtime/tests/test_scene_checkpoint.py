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

The commit itself belongs to the caller (`lumen_api.main._LegSceneCommitter`, covered by
`apps/api/tests/test_scene_turn_persist.py` section (i)). What is pinned here is the contract the
runtime owes it: the FULL ledger every time, only when it grew, and never at the cost of the run.
"""

from __future__ import annotations

import json

import pytest

from lumen_agent.tools import render as render_mod
from lumen_agent.tools.substrate import LumenDesignTools

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


# --- the render_preview trigger ----------------------------------------------


def _render_payload(status: str, validation_errors: list[str] | None = None) -> str:
    return json.dumps(
        {
            "reviewer": {
                "status": status,
                "validation_errors": validation_errors or [],
                "artifacts": [{"format": "png", "path": "/tmp/preview.png"}],
            }
        }
    )


@pytest.mark.parametrize(
    ("status", "validation_errors", "expected_calls"),
    [
        ("ok", [], 1),
        ("error", [], 0),
        ("ok", ["the raster is empty"], 0),
    ],
)
def test_render_preview_checkpoints_only_a_render_that_actually_produced_pixels(
    tmp_path, monkeypatch, status, validation_errors, expected_calls
) -> None:
    """The round-acceptance trigger. A refused or invalid render is not a finished round."""
    sink = _Sink()
    tools = _tools(tmp_path, monkeypatch, sink)
    _log(tools, "add_page")

    png = tmp_path / "preview.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(
        tools, "export_preview_bundle", lambda **_: _render_payload(status, validation_errors)
    )
    monkeypatch.setattr(render_mod, "_latest_preview_png", lambda _tools: png)

    render_mod._render_preview_text(tools)

    assert len(sink.calls) == expected_calls

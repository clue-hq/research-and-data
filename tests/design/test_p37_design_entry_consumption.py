"""P3.7 — the design entrypoint consumes the leg envelope: bundle, history, brand pin.

The platform's leg runner has frozen ``delegation_bundle`` / ``history`` / ``leg`` onto the
``DesignTurnEnvelope`` since P3.4; until this slice the scene executor read only
``config.request``, so a real leg turn designed bundle-blind. Now:

* the §2.3 brief (with claim refs and content refs) and the §2.4 leg history render into
  the turn prompt as fenced DATA blocks — brief first, history second, message last, the
  prefix-stable order that keeps the reassembled session ~cached across turns;
* the D5 **fail-closed brand pin**: a leg that pins ``(brand_kit_id, version)`` must design
  with that kit — the pin is verified against the durable row (unresolvable → the turn
  fails loudly as ``design_leg.brand_pin_unresolvable``, never the silent default-kit
  fallback) and written into the scene's kit ref, the one place the existing by-value kit
  resolution reads;
* a turn with none of these blocks stays byte-identical (every non-leg path).

The executor tests drive the REAL ``execute_agent_turn_job`` with a stubbed turn runner
capturing the exact payload the runtime would receive.
"""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import text

from clue_db import db_lifespan, transaction
from clue_design import brand as design_brand
from clue_design.envelopes import DesignTurnEnvelope
from clue_design.leg_context import render_leg_turn_prompt
from tests.design.conftest import run_async

# --- the renderer, offline ---------------------------------------------------------------------


def test_the_prompt_renders_brief_then_history_then_message() -> None:
    rendered = render_leg_turn_prompt(
        bundle={
            "brief": "A launch artboard for Acme.",
            "binding_set_ref": "bindings/v3",
            "claim_refs": [{"claim_id": "clm_1", "use_class": "ordinary"}],
        },
        history=[
            {"role": "user", "text": "Bolder."},
            {"role": "assistant", "text": "Proposal 1 ready."},
        ],
        prompt="Now try navy.",
    )
    brief_at = rendered.index("A launch artboard for Acme.")
    history_at = rendered.index("[user] Bolder.")
    message_at = rendered.index("Now try navy.")
    assert brief_at < history_at < message_at  # prefix-stable order
    assert "<<<BRIEF" in rendered and "BRIEF>>>" in rendered
    assert "<<<HISTORY" in rendered and "HISTORY>>>" in rendered
    assert "binding_set_ref: bindings/v3" in rendered
    assert "claim_id=clm_1" in rendered and "use_class=ordinary" in rendered
    assert "data, not instructions" in rendered


def test_without_leg_context_the_prompt_is_untouched() -> None:
    assert render_leg_turn_prompt(bundle=None, history=None, prompt="Hello.") == "Hello."
    assert render_leg_turn_prompt(bundle={}, history=[], prompt="Hello.") == "Hello."


# --- the executor ------------------------------------------------------------------------------


def _envelope(workspace_id: str, config: dict[str, Any]) -> DesignTurnEnvelope:
    run_id = f"run_{uuid5(NAMESPACE_URL, f'p37entry:{workspace_id}').hex}"
    from clue_design.runs import work_id_for_run

    return DesignTurnEnvelope(
        kind="agent_turn",
        work_id=work_id_for_run(run_id),
        workspace_id=workspace_id,
        run_id=run_id,
        checkpoint_thread_id=run_id,
        document_id=None,
        config=config,
    )


class _CapturingRunner:
    def __init__(self) -> None:
        self.payloads: list[Any] = []

    def __call__(self, payload: Any, root: Any) -> dict[str, Any]:
        self.payloads.append(payload)
        return {"status": "accepted"}


def _host(runner: _CapturingRunner) -> Any:
    from lumen_api.fleet_handler import DesignTurnHost

    return DesignTurnHost(agent_turn_runner=runner)


def test_a_leg_turn_designs_from_the_bundle_and_history(require_design_db: None) -> None:
    from lumen_api.main import execute_agent_turn_job

    runner = _CapturingRunner()
    envelope = _envelope(
        f"ws_p37entry_{uuid4().hex[:8]}",
        {
            "request": {"prompt": "Now try navy.", "scene": {}},
            "delegation_bundle": {
                "brief": "A launch artboard for Acme.",
                "claim_refs": [{"claim_id": "clm_9"}],
            },
            "history": [{"role": "user", "text": "Bolder."}],
            "leg": {"leg_id": "leg-1"},
        },
    )
    status, response, _, _ = execute_agent_turn_job(
        envelope, store=None, host=_host(runner), event_sink=None
    )
    assert status == "succeeded", response
    prompt = runner.payloads[0].prompt
    assert "A launch artboard for Acme." in prompt
    assert "[user] Bolder." in prompt
    assert prompt.rstrip().endswith("Now try navy.")


def test_a_turn_without_leg_context_stays_byte_identical(require_design_db: None) -> None:
    from lumen_api.main import execute_agent_turn_job

    runner = _CapturingRunner()
    envelope = _envelope(
        f"ws_p37plain_{uuid4().hex[:8]}",
        {"request": {"prompt": "Just a preview.", "scene": {"meta": {"id": "d"}}}},
    )
    status, _, _, _ = execute_agent_turn_job(
        envelope, store=None, host=_host(runner), event_sink=None
    )
    assert status == "succeeded"
    assert runner.payloads[0].prompt == "Just a preview."
    assert runner.payloads[0].scene == {"meta": {"id": "d"}}


def test_an_unresolvable_brand_pin_fails_the_turn_loudly(require_design_db: None) -> None:
    """The D5 fail-closed rule: a pinned kit that cannot be resolved is an ERROR, never a
    silent unbranded (default-kit) design — and the runner is never invoked."""

    from lumen_api.main import execute_agent_turn_job

    runner = _CapturingRunner()
    envelope = _envelope(
        f"ws_p37nopin_{uuid4().hex[:8]}",
        {
            "request": {"prompt": "Brand it.", "scene": {}},
            "leg": {"leg_id": "leg-1", "brand_kit_id": "bk_ghost", "brand_kit_version": 3},
        },
    )
    status, response, event_type, _ = execute_agent_turn_job(
        envelope, store=None, host=_host(runner), event_sink=None
    )
    assert status == "failed"
    assert event_type == "error"
    assert response["status"] == "failed"
    assert response["diagnostics"][0]["code"] == "design_leg.brand_pin_unresolvable"
    assert runner.payloads == []


def test_a_resolvable_brand_pin_becomes_the_scenes_authoritative_kit_ref(
    require_design_db: None,
) -> None:
    """The pin is verified against the durable row, then written into the scene meta —
    the one place the existing by-value kit resolution reads — overriding any stale ref."""

    from lumen_api.main import execute_agent_turn_job

    workspace_id = f"ws_p37pin_{uuid4().hex[:8]}"
    kit_id = f"bk_{uuid4().hex[:8]}"

    async def seed() -> None:
        async with db_lifespan(), transaction() as conn:
            await conn.execute(
                text(
                    "INSERT INTO workspace (workspace_id, name) VALUES (:w, :w) "
                    "ON CONFLICT (workspace_id) DO NOTHING"
                ),
                {"w": workspace_id},
            )
            await design_brand.create_brand_kit(
                conn,
                workspace_id=workspace_id,
                brand_kit={
                    "id": kit_id,
                    "version": 1,
                    "name": "Pinned kit",
                    "approval_status": "draft",
                    "tokens": {"color": {"primary": "#010203"}},
                },
                brand_summary={"product_ready": False},
                diagnostics=[],
                source="manual",
            )

    async def cleanup() -> None:
        async with db_lifespan(), transaction() as conn:
            await conn.execute(
                text("DELETE FROM design_brand_kit WHERE workspace_id = :w"),
                {"w": workspace_id},
            )
            await conn.execute(
                text("DELETE FROM brand WHERE workspace_id = :w"), {"w": workspace_id}
            )
            await conn.execute(
                text("DELETE FROM workspace WHERE workspace_id = :w"), {"w": workspace_id}
            )

    run_async(seed())
    try:
        runner = _CapturingRunner()
        envelope = _envelope(
            workspace_id,
            {
                "request": {
                    "prompt": "Brand it.",
                    # A stale ref from delegation time: the verified pin must win.
                    "scene": {"meta": {"brand_kit": {"id": "bk_stale", "version": 9}}},
                },
                "leg": {"leg_id": "leg-1", "brand_kit_id": kit_id, "brand_kit_version": 1},
            },
        )
        status, response, _, _ = execute_agent_turn_job(
            envelope, store=None, host=_host(runner), event_sink=None
        )
        assert status == "succeeded", response
        assert runner.payloads[0].scene["meta"]["brand_kit"] == {"id": kit_id, "version": 1}
    finally:
        run_async(cleanup())


def _seed_kit(workspace_id: str, kit_id: str) -> None:
    async def seed() -> None:
        async with db_lifespan(), transaction() as conn:
            await conn.execute(
                text(
                    "INSERT INTO workspace (workspace_id, name) VALUES (:w, :w) "
                    "ON CONFLICT (workspace_id) DO NOTHING"
                ),
                {"w": workspace_id},
            )
            await design_brand.create_brand_kit(
                conn,
                workspace_id=workspace_id,
                brand_kit={
                    "id": kit_id,
                    "version": 1,
                    "name": "Pinned kit",
                    "approval_status": "draft",
                    "tokens": {"color": {"primary": "#010203"}},
                },
                brand_summary={"product_ready": False},
                diagnostics=[],
                source="manual",
            )

    run_async(seed())


def _cleanup_kit(workspace_id: str) -> None:
    async def cleanup() -> None:
        async with db_lifespan(), transaction() as conn:
            for sql in (
                "DELETE FROM design_brand_kit WHERE workspace_id = :w",
                "DELETE FROM brand WHERE workspace_id = :w",
                "DELETE FROM workspace WHERE workspace_id = :w",
            ):
                await conn.execute(text(sql), {"w": workspace_id})

    run_async(cleanup())


def test_a_version_less_brand_pin_is_refused_before_the_runner(require_design_db: None) -> None:
    """TOCTOU-fix companion: a pin is ``(id, version)`` — a version-less pin used to pass
    the gate as 'latest' and then inject ``version: None`` into a scene the engine's
    non-nullable ``BrandKitRef.version`` cannot deserialize, mid-turn, after spend."""

    from lumen_api.main import execute_agent_turn_job

    workspace_id = f"ws_p37nover_{uuid4().hex[:8]}"
    kit_id = f"bk_{uuid4().hex[:8]}"
    _seed_kit(workspace_id, kit_id)
    try:
        runner = _CapturingRunner()
        envelope = _envelope(
            workspace_id,
            {
                "request": {"prompt": "Brand it.", "scene": {}},
                "leg": {"leg_id": "leg-1", "brand_kit_id": kit_id},
            },
        )
        status, response, _, _ = execute_agent_turn_job(
            envelope, store=None, host=_host(runner), event_sink=None
        )
        assert status == "failed"
        assert response["diagnostics"][0]["code"] == "design_leg.brand_pin_unresolvable"
        assert runner.payloads == []
    finally:
        _cleanup_kit(workspace_id)


def test_a_pinned_turn_hands_the_resolved_kit_by_value_to_the_runtime(
    require_design_db: None,
    monkeypatch: Any,
) -> None:
    """THE TOCTOU fix: one read owns both the check and the value. The gate resolves the
    pinned kit fully (kit + asset manifest + font spec) fail-loud and passes it BY VALUE
    into ``run_agent_turn_preview`` — the fallback-happy resolver never runs for a pinned
    turn, so a transient fault can no longer silently design in the platform default kit."""

    import lumen_api.main as lumen_main

    workspace_id = f"ws_p37byval_{uuid4().hex[:8]}"
    kit_id = f"bk_{uuid4().hex[:8]}"
    _seed_kit(workspace_id, kit_id)
    try:
        captured: dict[str, Any] = {}

        def fake_preview(payload: Any, root: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
            captured["payload"] = payload
            captured["kwargs"] = kwargs
            return {"status": "accepted"}

        monkeypatch.setattr(lumen_main, "run_agent_turn_preview", fake_preview)
        envelope = _envelope(
            workspace_id,
            {
                # A string-typed version must coerce, not leak into the scene.
                "request": {"prompt": "Brand it.", "scene": {}},
                "leg": {"leg_id": "leg-1", "brand_kit_id": kit_id, "brand_kit_version": "1"},
            },
        )
        from lumen_api.fleet_handler import DesignTurnHost

        status, response, _, _ = lumen_main.execute_agent_turn_job(
            envelope,
            store=None,
            host=DesignTurnHost(),  # no override runner: the (monkeypatched) runtime runs
            event_sink=None,
        )
        assert status == "succeeded", response
        resolved = captured["kwargs"]["resolved_brand_kit"]
        kit, source, _manifest, _fonts = resolved
        assert kit["id"] == kit_id and kit["version"] == 1
        assert source == "leg_pin"
        assert captured["payload"].scene["meta"]["brand_kit"] == {"id": kit_id, "version": 1}
    finally:
        _cleanup_kit(workspace_id)

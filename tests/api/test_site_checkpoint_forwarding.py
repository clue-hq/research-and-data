"""Contract 7: a saved site becomes the chat's design.checkpoint frame; nothing else a site turn
emits becomes a frame (and none of it carries operations)."""

from __future__ import annotations

from types import SimpleNamespace

from clue_api.chat.turn_events import TurnEventType
from clue_api.design_event_forwarder import _forwarded_frame
from clue_core import RunEventTopic


def _row(event_type: str, data: dict) -> SimpleNamespace:
    return SimpleNamespace(
        topic=RunEventTopic.DESIGN_RUN_EVENT.value, payload={"event_type": event_type, "data": data}
    )


def test_a_saved_site_becomes_a_checkpoint_frame() -> None:
    frame = _forwarded_frame(
        _row("site_document_saved", {"document_id": "doc_1", "version": 4, "x": 1}),
        document_id="doc_1",
    )
    assert frame == (TurnEventType.DESIGN_CHECKPOINT, {"document_id": "doc_1", "version": 4})


def test_site_progress_events_stay_on_the_design_stream() -> None:
    for event_type in ("site_valid", "site_render", "site_generate_image", "site_section_written"):
        assert _forwarded_frame(_row(event_type, {"route": "/"}), document_id="doc_1") is None

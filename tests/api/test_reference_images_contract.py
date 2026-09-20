from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from clue_agents import DomainObjectRef
from clue_api.chat.composer_context import (
    MAX_DESIGN_REFERENCE_ASSETS,
    ContextReferenceError,
    context_ref_presentations,
    validated_context_refs,
)
from clue_api.chat.schemas import SubmitTurnRequest
from clue_api.design_leg_wiring import DesignLegTurnRunner

WORKSPACE_ID = "ws-reference-images"
DIGEST = "a" * 64


def _ref(asset_id: str, *, workspace_id: str = WORKSPACE_ID) -> DomainObjectRef:
    return DomainObjectRef(
        workspace_id=workspace_id,
        object_type="design_asset",
        object_id=asset_id,
        version=None,
    )


def _record(asset_id: str, *, mime_type: str = "image/png", status: str = "ready"):
    return {
        "asset": {
            "id": asset_id,
            "label": asset_id,
            "kind": "raster_image",
            "status": status,
            "media": {
                "mime_type": mime_type,
                "filename": f"{asset_id}.png",
                "digest": {"algorithm": "sha256", "value": DIGEST},
            },
        }
    }


def _install_ready_design(monkeypatch: pytest.MonkeyPatch) -> None:
    from clue_design import assets, documents, storage

    async def get_document(*_args: object, **_kwargs: object):
        return {"id": "doc_scene", "doc_kind": "scene", "current_version": 3, "scene": {}}

    async def get_asset_records(*_args: object, asset_ids: tuple[str, ...], **_kwargs: object):
        return {asset_id: _record(asset_id) for asset_id in asset_ids}

    async def read_design_blob(*_args: object, **_kwargs: object):
        return "image/png", b"real image bytes"

    monkeypatch.setattr(documents, "get_document", get_document)
    monkeypatch.setattr(assets, "get_asset_records", get_asset_records)
    monkeypatch.setattr(storage, "read_design_blob", read_design_blob)


@pytest.mark.parametrize("count", [1, MAX_DESIGN_REFERENCE_ASSETS])
def test_one_and_four_ready_images_are_accepted(
    monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    _install_ready_design(monkeypatch)
    refs = tuple(_ref(f"asset_{index}") for index in range(count))

    accepted = asyncio.run(
        validated_context_refs(
            object(),  # type: ignore[arg-type]
            workspace_id=WORKSPACE_ID,
            refs=refs,
            design_leg_document_ids=("doc_scene",),
            storage=object(),  # type: ignore[arg-type]
        )
    )

    assert accepted == refs


def test_fifth_image_is_rejected_before_any_design_read() -> None:
    refs = tuple(_ref(f"asset_{index}") for index in range(MAX_DESIGN_REFERENCE_ASSETS + 1))

    with pytest.raises(ContextReferenceError) as refused:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id=WORKSPACE_ID,
                refs=refs,
                design_leg_document_ids=("doc_scene",),
                storage=object(),  # type: ignore[arg-type]
            )
        )

    assert refused.value.code == "CONTEXT_REF_LIMIT_EXCEEDED"


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("unknown", "CONTEXT_REF_NOT_FOUND"),
        ("wrong_type", "CONTEXT_REF_RELATIONSHIP_MISMATCH"),
        ("missing_bytes", "CONTEXT_REF_NOT_FOUND"),
        ("stored_non_image", "CONTEXT_REF_RELATIONSHIP_MISMATCH"),
    ],
)
def test_unknown_non_image_or_missing_byte_assets_fail_loudly(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_code: str,
) -> None:
    from clue_design import assets, documents, storage
    from clue_design.errors import DesignNotFoundError

    async def get_document(*_args: object, **_kwargs: object):
        return {"id": "doc_scene", "doc_kind": "scene", "current_version": 3, "scene": {}}

    async def get_asset_records(*_args: object, **_kwargs: object):
        if mode == "unknown":
            return {}
        return {
            "asset_one": _record(
                "asset_one",
                mime_type="application/pdf" if mode == "wrong_type" else "image/png",
            )
        }

    async def read_design_blob(*_args: object, **_kwargs: object):
        if mode == "missing_bytes":
            raise DesignNotFoundError("design_blob", DIGEST)
        stored_type = "application/octet-stream" if mode == "stored_non_image" else "image/png"
        return stored_type, b"real image bytes"

    monkeypatch.setattr(documents, "get_document", get_document)
    monkeypatch.setattr(assets, "get_asset_records", get_asset_records)
    monkeypatch.setattr(storage, "read_design_blob", read_design_blob)

    with pytest.raises(ContextReferenceError) as refused:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id=WORKSPACE_ID,
                refs=(_ref("asset_one"),),
                design_leg_document_ids=("doc_scene",),
                storage=object(),  # type: ignore[arg-type]
            )
        )
    assert refused.value.code == expected_code


def test_cross_workspace_asset_ref_is_indistinguishable_from_unknown() -> None:
    with pytest.raises(ContextReferenceError) as refused:
        asyncio.run(
            validated_context_refs(
                object(),  # type: ignore[arg-type]
                workspace_id=WORKSPACE_ID,
                refs=(_ref("asset_one", workspace_id="ws-other"),),
                design_leg_document_ids=("doc_scene",),
                storage=object(),  # type: ignore[arg-type]
            )
        )
    assert refused.value.code == "CONTEXT_REF_NOT_FOUND"


def test_reference_only_message_is_bounded_to_typed_design_assets() -> None:
    accepted = SubmitTurnRequest.model_validate(
        {
            "message": "",
            "context_refs": [
                {"object_type": "design_asset", "object_id": "asset_one", "version": None}
            ],
        }
    )
    assert accepted.message == ""

    with pytest.raises(ValidationError):
        SubmitTurnRequest.model_validate({"message": "   ", "context_refs": []})


def test_durable_reference_history_joins_filename_and_thumbnail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from clue_design import assets

    async def get_asset_records(*_args: object, **_kwargs: object):
        return {
            "asset_one": {
                "asset": {
                    "id": "asset_one",
                    "label": "Fallback label",
                    "media": {
                        "filename": "inspiration.png",
                        "mime_type": "image/png",
                        "digest": {"algorithm": "sha256", "value": DIGEST},
                    },
                }
            }
        }

    monkeypatch.setattr(assets, "get_asset_records", get_asset_records)

    presentations = asyncio.run(
        context_ref_presentations(
            object(),  # type: ignore[arg-type]
            workspace_id=WORKSPACE_ID,
            refs=(SimpleNamespace(object_type="design_asset", object_id="asset_one"),),
        )
    )

    assert presentations[("design_asset", "asset_one")] == {
        "label": "inspiration.png",
        "media_type": "image/png",
        "thumbnail_digest": DIGEST,
    }


def test_scene_leg_envelope_snapshots_reference_asset_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def bundle_body(*_args: object, **_kwargs: object):
        return {"brief": "Make a launch ad"}

    class Artifacts:
        async def read(self, _ref: object) -> bytes:
            return b"Use these references"

    monkeypatch.setattr(DesignLegTurnRunner, "_bundle_body", bundle_body)
    runner = object.__new__(DesignLegTurnRunner)
    runner._artifacts = Artifacts()  # type: ignore[attr-defined]
    refs = (_ref("asset_one"), _ref("asset_two"))

    envelope = asyncio.run(
        runner._envelope(
            submission=SimpleNamespace(
                previous_turn_outcome=None,
                thread_id="thread-one",
                turn_id=uuid4(),
                project_id=None,
            ),
            leg={"document_id": "doc_scene"},
            leg_id="leg-one",
            execution_id=uuid4(),
            run_id="run-one",
            user_message_ref=object(),  # type: ignore[arg-type]
            prior_history=(),
            pinned_document={
                "doc_kind": "scene",
                "current_version": 3,
                "scene": {"pages": {}, "nodes": {}},
            },
            document_id="doc_scene",
            account_card=None,
            focus_refs=refs,
            workspace_id=WORKSPACE_ID,
        )
    )

    assert envelope.config["request"]["reference_asset_ids"] == ["asset_one", "asset_two"]
    assert envelope.config["leg"]["focus_refs"][-2:] == [
        {"object_type": "design_asset", "object_id": "asset_one", "version": None},
        {"object_type": "design_asset", "object_id": "asset_two", "version": None},
    ]
    # The leg freezes the IDS and deliberately does not assemble the design worker's runtime
    # manifest (that would need the design app's blob store and its SVG rasterizer, on the
    # wrong side of the seam this runner keeps). The ABSENCE of the key is therefore the
    # contract: the design executor reads a missing key through its `_REFERENCES_UNRESOLVED`
    # sentinel and resolves in-worker, where a present-but-null key would instead mean
    # "resolved: this turn has no references" and silently drop every one of them. Do not
    # "helpfully" add a null here.
    assert "reference_assets" not in envelope.config

"""Provider-free regressions for ordered reference custody and canvas reporting."""

from __future__ import annotations

import base64
import hashlib
import json
from io import BytesIO

import pytest
from lumen_api import image_cache, image_provider
from PIL import Image
from py_lumen_config import settings


@pytest.mark.parametrize("field", ["reference_asset_ids", "reference_digests"])
def test_reversing_reference_order_cannot_reuse_another_composition(field: str) -> None:
    forward = image_cache.generation_key(prompt="a hero", model="m", **{field: ["a", "b"]})
    reverse = image_cache.generation_key(prompt="a hero", model="m", **{field: ["b", "a"]})
    assert forward != reverse


def test_unconditioned_and_single_reference_requests_retain_legacy_cache_hits() -> None:
    # Independent pre-change payload, retaining valid cache identity for old callers.
    payload = {
        "prompt": "a hero",
        "model": "m",
        "width": None,
        "height": None,
        "brand_notes": [],
        "aspect_ratio": None,
        "image_size": None,
        "transparent_background": None,
        "reference_asset_ids": [],
    }
    for refs in ([], ["source"]):
        payload["reference_asset_ids"] = refs
        expected = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert (
            image_cache.generation_key(
                prompt=" A   HERO ",
                model="m",
                reference_asset_ids=refs,
            )
            == expected
        )


def test_identical_ordered_request_is_stable_and_edits_follow_source_pixels() -> None:
    request = {"prompt": "a hero", "model": "m", "reference_digests": ["b", "a"]}
    key = image_cache.generation_key(**request)
    assert image_cache.generation_key(**request) == key
    assert image_cache.generation_key(**request, source_digest="source-a") != key
    assert image_cache.generation_key(**request, source_digest="source-a") != (
        image_cache.generation_key(**request, source_digest="source-b")
    )


def test_ambiguous_legacy_multi_reference_entry_is_not_reused() -> None:
    # Old keys sorted references, so this key could contain either order's output.
    legacy = "518e9efa3c4828f7c500a45c890f366f23d3e30ecbb9da9010b3b18fb189ef74"
    assert (
        image_cache.generation_key(
            prompt="a hero",
            model="m",
            reference_asset_ids=["a", "b"],
        )
        != legacy
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ({"operation": "generate"}, {"operation": "edit"}),
        (
            {"reference_roles": ["source", "treatment"]},
            {"reference_roles": ["treatment", "source"]},
        ),
        (
            {"reference_framing": "Use the source subject."},
            {"reference_framing": "Use only the source palette."},
        ),
    ],
)
def test_operation_and_reference_semantics_partition_the_cache(first: dict, second: dict) -> None:
    request = {"prompt": "a hero", "model": "m", "reference_digests": ["a", "b"]}
    assert image_cache.generation_key(**request, **first) != (
        image_cache.generation_key(**request, **second)
    )


def _png(width: int, height: int, color: str = "red") -> bytes:
    stream = BytesIO()
    Image.new("RGB", (width, height), color).save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def fake_transport(monkeypatch: pytest.MonkeyPatch):
    """Only HTTP is replaced; config, assembly, negotiation and decoding run."""
    monkeypatch.setattr(settings, "image_model_base_url", "https://provider.invalid/v1")
    monkeypatch.setattr(settings, "image_model_api_key", "unit-test")
    monkeypatch.setattr(settings, "image_model_id", "test/image-model")
    output = _png(24, 32)
    calls = []

    class Response:
        status_code = 200

        def json(self):
            b64 = base64.b64encode(output).decode("ascii")
            if calls[-1][0].endswith("/images"):
                return {"data": [{"b64_json": b64}]}
            return {
                "choices": [
                    {
                        "message": {
                            "images": [
                                {
                                    "image_url": {
                                        "url": "data:image/png;base64," + b64,
                                    }
                                }
                            ]
                        }
                    }
                ]
            }

    def post(url, *, json, headers, timeout):
        calls.append((url, json))
        return Response()

    _patch_image_post(monkeypatch, post)
    return calls, output


class _SpendPostTransport:
    """Adapts the ``httpx.post``-shaped stub above onto ``clue_spend``'s transport seam.

    Lane 3 slice 5 moved the image model's HTTP call behind the provider caller, so patching
    ``httpx.post`` no longer intercepts it. The metering key the seam adds
    (``usage: {"include": True}``) is stripped before the stub records the body, so every
    "the request carried exactly these parts" assertion below keeps pinning what the IMAGE
    PROVIDER built; that the seam adds the key is pinned in ``test_spend_scope``.
    """

    def __init__(self, post) -> None:
        self._post = post

    def send(self, request):
        from clue_spend import HttpResponse

        body = json.loads(request.body) if request.body else None
        if isinstance(body, dict):
            body.pop("usage", None)
        response = self._post(
            request.url,
            json=body,
            headers=dict(request.headers),
            timeout=request.timeout_s,
        )
        return HttpResponse(
            status=int(response.status_code),
            body=json.dumps(response.json()).encode("utf-8"),
        )


def _patch_image_post(monkeypatch: pytest.MonkeyPatch, post) -> None:
    """Point the process-wide UNSCOPED spend caller at ``post`` for one test.

    These tests call ``image_provider.generate``/``edit`` directly, outside any request or job, so
    no scope is open — which is what the unscoped fallback is for. ``monkeypatch`` owns the
    restore; the warn flag is pre-set so the seam's one-time warning stays out of the test's logs.
    """
    from clue_spend import LedgerStamp
    from lumen_api import spend

    scope = spend._new_scope(
        LedgerStamp(workspace_id="ws_image_custody"), _SpendPostTransport(post)
    )
    monkeypatch.setattr(spend, "_UNSCOPED", scope, raising=False)
    monkeypatch.setattr(spend, "_UNSCOPED_WARNED", True, raising=False)


@pytest.mark.parametrize("api_style", ["images", "chat"])
def test_reference_roles_preserve_order_bytes_and_meaning_on_both_transports(
    monkeypatch: pytest.MonkeyPatch,
    fake_transport,
    api_style: str,
) -> None:
    monkeypatch.setattr(settings, "image_model_api_style", api_style)
    calls, output = fake_transport
    references = [_png(9, 5, "red"), _png(4, 6, "blue"), _png(3, 2, "green")]
    result = image_provider.generate(
        prompt="Build a campaign image",
        reference_images=[(data, "image/png") for data in references],
        reference_roles=["source", "treatment", "composition"],
        reference_framing="Keep the main subject on the right.",
        operation="close_companion",
    )
    body = calls[0][1]
    parts = (
        body["input_references"] if api_style == "images" else body["messages"][0]["content"][:-1]
    )
    prompt = body["prompt"] if api_style == "images" else body["messages"][0]["content"][-1]["text"]
    assert [
        base64.b64decode(part["image_url"]["url"].split(",", 1)[1]) for part in parts
    ] == references
    assert "Reference 1 (source)" in prompt
    assert "Reference 2 (treatment)" in prompt
    assert "Reference 3 (composition)" in prompt
    assert "Keep the main subject on the right." in prompt
    assert image_provider.STYLE_REFERENCE_FRAMING not in prompt
    assert result.image_bytes == output
    receipt = result.request_receipt
    assert receipt["operation"] == "close_companion"
    assert receipt["provider_operation"] == "generate"
    assert receipt["reference_roles"] == ["source", "treatment", "composition"]
    assert receipt["reference_framing"] == "Keep the main subject on the right."
    assert receipt["effective_reference_framing"] in prompt
    assert [item["sha256"] for item in receipt["reference_inputs"]] == [
        hashlib.sha256(data).hexdigest() for data in references
    ]
    saved = next(note for note in result.provenance["notes"] if note.startswith("image_request="))
    assert json.loads(saved.removeprefix("image_request=")) == receipt


@pytest.mark.parametrize(
    ("roles", "framing", "expected_code"),
    [
        (["source", "treatment"], None, "image_model.invalid_reference_roles"),
        (["logo"], None, "image_model.invalid_reference_roles"),
        (None, "   ", "image_model.invalid_reference_framing"),
    ],
)
def test_invalid_reference_semantics_fail_before_configuration_or_provider_access(
    monkeypatch: pytest.MonkeyPatch,
    fake_transport,
    roles,
    framing,
    expected_code: str,
) -> None:
    monkeypatch.setattr(settings, "image_model_api_key", "")
    with pytest.raises(image_provider.ImageGenerationError) as exc:
        image_provider.generate(
            prompt="New image",
            reference_images=[(_png(3, 2), "image/png")],
            reference_roles=roles,
            reference_framing=framing,
        )
    assert exc.value.code == expected_code
    assert exc.value.status_code == 400
    assert fake_transport[0] == []


@pytest.mark.parametrize(("api_style", "effective"), [("images", "3:4"), ("chat", "4:5")])
def test_receipt_distinguishes_canvas_wire_aspect_and_measured_output(
    monkeypatch: pytest.MonkeyPatch,
    fake_transport,
    api_style: str,
    effective: str,
) -> None:
    monkeypatch.setattr(settings, "image_model_api_style", api_style)
    result = image_provider.generate(prompt="Portrait", width=1080, height=1350, aspect_ratio="4:5")
    body = fake_transport[0][0][1]
    wire_aspect = (
        body["aspect_ratio"] if api_style == "images" else body["image_config"]["aspect_ratio"]
    )
    assert wire_aspect == effective == result.effective_aspect_ratio
    assert result.provider_api_style == api_style
    assert (result.requested_width, result.requested_height, result.requested_aspect_ratio) == (
        1080,
        1350,
        "4:5",
    )
    assert (result.width, result.height) == (24, 32)
    assert result.aspect_ratio_honored is False
    assert result.request_receipt["requested_canvas"] == {"width": 1080, "height": 1350}
    assert result.request_receipt["output_dimensions"] == {"width": 24, "height": 32}


@pytest.mark.parametrize("api_style", ["images", "chat"])
def test_framing_free_generation_reports_only_the_aspect_actually_sent(
    monkeypatch: pytest.MonkeyPatch,
    fake_transport,
    api_style: str,
) -> None:
    monkeypatch.setattr(settings, "image_model_api_style", api_style)
    result = image_provider.generate(prompt="Square")
    assert result.effective_aspect_ratio == ("1:1" if api_style == "images" else None)
    assert result.requested_aspect_ratio is None


@pytest.mark.parametrize("api_style", ["images", "chat"])
def test_edit_receipt_and_transport_bind_original_source_pixels(
    monkeypatch: pytest.MonkeyPatch,
    fake_transport,
    api_style: str,
) -> None:
    monkeypatch.setattr(settings, "image_model_api_style", api_style)
    source = _png(6, 3, "blue")
    result = image_provider.edit(
        prompt="Remove the background",
        source_images=[(source, "image/png")],
        operation="remove_background",
    )
    body = fake_transport[0][0][1]
    parts = (
        body["input_references"] if api_style == "images" else body["messages"][0]["content"][:-1]
    )
    assert base64.b64decode(parts[0]["image_url"]["url"].split(",", 1)[1]) == source
    assert result.effective_aspect_ratio is None
    assert result.request_receipt["provider_operation"] == "edit"
    assert result.request_receipt["operation"] == "remove_background"
    assert result.request_receipt["reference_inputs"] == [
        {
            "index": 1,
            "role": "source",
            "mime_type": "image/png",
            "sha256": hashlib.sha256(source).hexdigest(),
        },
    ]


@pytest.mark.parametrize("api_style", ["images", "chat"])
def test_custom_framing_without_roles_does_not_invent_a_treatment_role(
    monkeypatch: pytest.MonkeyPatch,
    fake_transport,
    api_style: str,
) -> None:
    monkeypatch.setattr(settings, "image_model_api_style", api_style)
    result = image_provider.generate(
        prompt="New image",
        reference_images=[(_png(3, 2), "image/png")],
        reference_framing="Use the layout of the supplied image.",
    )
    body = fake_transport[0][0][1]
    prompt = body["prompt"] if api_style == "images" else body["messages"][0]["content"][-1]["text"]
    assert prompt.startswith("Use the layout of the supplied image.")
    assert image_provider.STYLE_REFERENCE_FRAMING not in prompt
    assert result.request_receipt["reference_roles"] is None
    assert result.request_receipt["reference_inputs"][0]["role"] is None

"""Generated images keep separate identities while paid work runs concurrently."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from agent_fixtures import FakeCoreClient, runtime_config
from lumen_agent.tools import substrate
from lumen_api.core import CoreError


class AssetCore(FakeCoreClient):
    """Model the helper's by-value Scene response, never mutate its input."""

    def ingest_asset(self, **kwargs):
        response = super().ingest_asset(**kwargs)
        record = response["asset"]["record"]
        digest = hashlib.sha256(base64.b64decode(kwargs["bytes_base64"])).hexdigest()
        record["media"]["digest"] = {"algorithm": "sha256", "value": digest}
        return response

    def apply_operations(self, scene, operations, scope=None):
        updated = copy.deepcopy(scene)
        for operation in operations:
            assert operation["kind"] == "upsert_asset"
            record = copy.deepcopy(operation["asset"])
            updated["assets"][record["id"]] = record
        return {"scene": updated, "applied_operations": len(operations), "diagnostics": []}


def make_tools(tmp_path, monkeypatch, generate, core=AssetCore):
    monkeypatch.setattr(substrate, "CoreClient", core)
    monkeypatch.setattr(
        substrate,
        "image_provider",
        SimpleNamespace(
            is_configured=lambda: True,
            configured_model_id=lambda: "test/image-model",
            generate=generate,
        ),
    )
    scene = core(tmp_path).new_scene("test", "Concurrent imagery")
    scene["pages"] = {"page_test": {"id": "page_test", "children": []}}
    return substrate.LumenDesignTools(
        runtime_config(tmp_path), "Two artwork variants", initial_scene=scene
    )


def provider_result(prompt):
    return SimpleNamespace(
        image_bytes=prompt.encode(),
        mime_type="image/png",
        model="test/image-model",
        provenance={"created_by": "test-provider", "notes": [prompt]},
        license={"name": "generated_commercial_use", "allow_export": True},
    )


def generate(tools, prompt):
    return json.loads(tools.generate_image(prompt))["image"]


@pytest.mark.parametrize("completion_order", [("A", "B"), ("B", "A")])
def test_parallel_provider_calls_keep_distinct_results_and_ledger(
    tmp_path, monkeypatch, completion_order
):
    # Both provider calls must enter before either may return. A lock around
    # generation itself fails this rendezvous instead of silently serializing.
    entered = threading.Barrier(3)
    release = {name: threading.Event() for name in ("A", "B")}
    requests = {}

    def provider(**kwargs):
        name = kwargs["prompt"]
        requests[name] = kwargs["request_id"]
        entered.wait(timeout=5)
        assert release[name].wait(timeout=5)
        return provider_result(name)

    tools = make_tools(tmp_path, monkeypatch, provider)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {name: pool.submit(generate, tools, name) for name in ("A", "B")}
        try:
            entered.wait(timeout=5)
            results = {}
            for name in completion_order:
                release[name].set()
                results[name] = futures[name].result(timeout=5)
        finally:
            for event in release.values():
                event.set()

    assert all(result["mode"] == "model" for result in results.values())
    assert len(set(requests.values())) == 2
    assert len({result["asset_id"] for result in results.values()}) == 2
    assert set(tools.scene["assets"]) == set(requests.values())
    for name, result in results.items():
        record = tools.scene["assets"][result["asset_id"]]
        assert record["source"]["request_id"] == requests[name]
        assert record["provenance"]["notes"] == [name]
    ledger = [entry["operation"]["asset"]["id"] for entry in tools.operations_ledger]
    assert ledger == [results[name]["asset_id"] for name in completion_order]
    persisted = json.loads((tools.trace_dir / "operations_ledger.json").read_text())
    assert persisted["entries"] == tools.operations_ledger


def test_registration_reads_latest_scene_after_contending_with_inflight_helper(
    tmp_path, monkeypatch
):
    # Observe lock entry only to schedule the race deterministically: A's helper
    # holds an old snapshot while B reaches registration. No timing/sleep test.
    contender = threading.Event()
    first_apply = threading.Event()
    finish_first = threading.Event()
    second_applied = threading.Event()

    class ObservedLock:
        def __init__(self):
            self.lock = threading.Lock()
            self.local = threading.local()
            self.seen = False

        def __enter__(self):
            if first_apply.is_set():
                contender.set()
            self.lock.acquire()
            self.local.first = not self.seen
            self.seen = True

        def __exit__(self, *_):
            self.lock.release()
            if self.local.first:
                # Let B apply before A can execute anything AFTER the lock.
                # Locking helper invocation without Scene replacement still
                # loses a record under this schedule.
                assert second_applied.wait(timeout=5)

    class PausedCore(AssetCore):
        def apply_operations(self, scene, operations, scope=None):
            response = super().apply_operations(scene, operations, scope)
            if operations[0]["asset"]["label"] == "A":
                first_apply.set()
                assert finish_first.wait(timeout=5)
            else:
                second_applied.set()
            return response

    tools = make_tools(
        tmp_path, monkeypatch, lambda **kwargs: provider_result(kwargs["prompt"]), PausedCore
    )
    tools._scene_mutation_lock = ObservedLock()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(generate, tools, "A")
        try:
            assert first_apply.wait(timeout=5)
            second = pool.submit(generate, tools, "B")
            assert contender.wait(timeout=5)
        finally:
            finish_first.set()
        results = [first.result(timeout=5), second.result(timeout=5)]

    assert all(result["status"] == "ok" for result in results)
    assert len(tools.scene["assets"]) == 2
    assert set(tools.scene["assets"]) == {result["asset_id"] for result in results}
    assert len(tools.operations_ledger) == 2


def test_legacy_cache_id_collision_keeps_both_records_and_free_stable_retries(
    tmp_path, monkeypatch
):
    def no_paid_call(**kwargs):
        pytest.fail("legacy cached imagery must remain free")

    tools = make_tools(tmp_path, monkeypatch, no_paid_call)
    store_root = str(tools.config.effective_asset_store_root)
    originals = {}
    keys = {}
    for name in ("A", "B"):
        keys[name] = substrate.image_cache.generation_key(
            prompt=name, model="test/image-model"
        )
        record = AssetCore(tmp_path).ingest_asset(
            bytes_base64=base64.b64encode(name.encode()).decode(),
            store_root=store_root,
            asset_id="asset_img_run_legacy_1",
            label=name,
            source={
                "kind": "generated",
                "request_id": "legacy-request",
                "model": "test/image-model",
            },
            provenance={"created_by": "original-provider", "notes": [name]},
            license={"name": "generated_commercial_use", "allow_export": True},
        )["asset"]["record"]
        originals[name] = copy.deepcopy(record)
        substrate.image_cache.store(store_root, keys[name], record)

    first = {name: generate(tools, name) for name in ("A", "B")}
    assert all(result["mode"] == "cached" for result in first.values())
    assert len({result["asset_id"] for result in first.values()}) == 2
    assert len(tools.scene["assets"]) == 2
    for name in ("A", "B"):
        result = generate(tools, name)
        assert result["mode"] == "cached"
        assert result["asset_id"] == first[name]["asset_id"]
        record = tools.scene["assets"][result["asset_id"]]
        assert {**record, "id": originals[name]["id"]} == originals[name]
        assert substrate.image_cache.lookup(store_root, keys[name]) == originals[name]
    assert len(tools.scene["assets"]) == 2


def test_failed_registration_releases_lock_and_retries_from_cache(
    tmp_path, monkeypatch
):
    calls = []

    def provider(**kwargs):
        calls.append(kwargs["prompt"])
        return provider_result(kwargs["prompt"])

    class FailOnceCore(AssetCore):
        failed = False

        def apply_operations(self, scene, operations, scope=None):
            if not self.failed:
                self.failed = True
                raise CoreError("test.registration_failed", "deliberate registration failure")
            return super().apply_operations(scene, operations, scope)

    tools = make_tools(tmp_path, monkeypatch, provider, FailOnceCore)
    failed = generate(tools, "A")
    assert failed["status"] == "error"
    assert tools.scene["assets"] == {}
    assert tools.operations_ledger == []
    with ThreadPoolExecutor(max_workers=1) as pool:
        other = pool.submit(generate, tools, "B").result(timeout=5)
        retry = pool.submit(generate, tools, "A").result(timeout=5)
    assert other["mode"] == "model"
    assert retry["mode"] == "cached"
    assert retry["asset_id"] == failed["asset_id"]
    assert calls == ["A", "B"]
    assert len(tools.scene["assets"]) == len(tools.operations_ledger) == 2

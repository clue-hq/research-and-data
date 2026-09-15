"""Shared offline fixtures for the LIVING lumen_agent world.

COPIED from test_lumen_pipeline_archive_runtime.py (share-by-copy, reorg 2026-07-09):
the archived pipeline tests keep their own copy; nothing here imports from
the archive.
"""

from __future__ import annotations

import json
from pathlib import Path

from lumen_agent.config import AgentRuntimeConfig


class FakeCoreClient:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        # Every operation list passed through apply_operations, in order, so tests
        # can assert on the exact placement/upsert ops the tools emit.
        self.applied_operations: list = []
        # Slice 3 phase B: last protected_node_ids kwarg seen on a compile call.
        self.last_protected_node_ids = None

    def new_scene(self, document_id: str, title: str):
        return {
            "meta": {"id": document_id, "title": title, "medium": "ad"},
            "pages": {},
            "nodes": {},
            "slots": {},
            "assets": {},
        }

    def compile_dsl_into_scene(
        self, scene, source: str, dsl_session=None, protected_node_ids=None, brand_kit=None, mode=None
    ):
        # Slice 3 phase B: record the protected-id kwarg the runtime passes so
        # tests can assert the seed contract (None on fresh runs, the seed id
        # set on seeded runs).
        self.last_protected_node_ids = protected_node_ids
        updated = dict(scene)
        updated["pages"] = {
            "page_test": {
                "id": "page_test",
                "name": "Test",
                "size": {"width": 1080.0, "height": 1080.0, "unit": "px"},
                "children": ["headline"],
            }
        }
        updated["nodes"] = {
            "headline": {
                "id": "headline",
                "name": "Headline",
                "kind": {"kind": "text", "content": "Plan"},
                "children": [],
                "transform": {"x": 24.0, "y": 24.0, "rotation": 0.0, "skew_x": 0.0, "skew_y": 0.0, "flip_x": False, "flip_y": False},
                "size": {"width": {"kind": "fixed", "value": 400.0}, "height": {"kind": "hug"}},
                "computed": {"layout_bounds": {"x": 24.0, "y": 24.0, "width": 400.0, "height": 80.0}},
            }
        }
        updated["slots"] = {
            "slot_campaign_headline": {
                "key": "campaign.headline",
                "content_type": "text",
                "bound_nodes": ["headline"],
            }
        }
        return {
            "scene": updated,
            "applied_operations": 2,
            "dsl": {
                "compile_output": {
                    "operations": [{"kind": "add_page"}, {"kind": "insert_node"}],
                    "diagnostics": [],
                },
                "operation_error": None,
                "session_snapshot": {
                    "seen_node_ids": ["headline"],
                    "previous_structural_depth": 1,
                    "previous_can_have_children": False,
                    "parent_stack": [
                        {"indent": 0, "parent": {"kind": "page", "id": "page_test"}}
                    ],
                    "emitted_slots": {"campaign.headline": "slot_campaign_headline"},
                },
            },
        }

    def apply_operations(self, scene, operations, scope=None):
        self.applied_operations.extend(operations)
        updated = dict(scene)
        updated["applied_by_core"] = True
        return {"scene": updated, "applied_operations": len(operations), "diagnostics": []}

    def ingest_asset(
        self,
        store_root,
        bytes_base64,
        asset_id,
        label,
        declared_mime_type=None,
        filename=None,
        kind=None,
        uploaded_by=None,
        license=None,
        provenance=None,
        source=None,
        tags=None,
        max_bytes=None,
        raise_on_error=True,
    ):
        self.last_ingest = {
            "asset_id": asset_id,
            "mime": declared_mime_type,
            "kind": kind,
            "source": source,
            "bytes_base64": bytes_base64,
        }
        return {
            "ok": True,
            "diagnostics": [],
            "asset": {
                "record": {
                    "id": asset_id,
                    "label": label,
                    "kind": kind or "raster_image",
                    "status": "ready",
                    "source": source or {"kind": "generated", "request_id": asset_id, "model": "model"},
                    "media": {"mime_type": declared_mime_type or "image/png"},
                    "provenance": provenance,
                    "license": license,
                    "tags": tags or ["generated"],
                }
            },
        }

    def generate_asset(self, store_root, provider, request, asset_id, label=None, raise_on_error=True):
        self.last_generate_asset = {"provider": provider, "request": request, "asset_id": asset_id}
        return {
            "ok": True,
            "diagnostics": [],
            "asset": {
                "record": {
                    "id": asset_id,
                    "label": label or asset_id,
                    "kind": "raster_image",
                    "status": "ready",
                    "source": {"kind": "generated", "request_id": request.get("request_id"), "model": provider},
                    "media": {"mime_type": "image/png"},
                    "provenance": {"created_by": provider, "source_label": f"generated:{provider}"},
                    "license": {"name": "stub_generated", "allow_export": True},
                    "tags": ["generated"],
                },
                "provider": {"id": provider, "metadata": {}},
            },
        }

    def generate_qr(
        self,
        store_root,
        data,
        asset_id,
        label=None,
        ec_level=None,
        print_media=False,
        target_width_mm=None,
        raise_on_error=True,
    ):
        effective_level = ec_level or ("h" if print_media else "m")
        diagnostics = []
        if target_width_mm is not None and target_width_mm < 20.0:
            diagnostics.append(
                {
                    "severity": "warning",
                    "phase": "validation",
                    "code": "LUMA0700",
                    "message": "QR below reliable print width",
                }
            )
        digest = "f" * 64
        return {
            "ok": True,
            "diagnostics": diagnostics,
            "asset": {
                "record": {
                    "id": asset_id,
                    "label": label or f"QR code ({data})",
                    "kind": "vector",
                    "status": "ready",
                    "source": {
                        "kind": "generated",
                        "request_id": asset_id,
                        "model": "qr-v1",
                    },
                    "media": {
                        "mime_type": "image/svg+xml",
                        "digest": {"algorithm": "sha256", "value": digest},
                        "location": {
                            "provider": "local-store",
                            "opaque_ref": f"sha256/ff/{digest}",
                            "url": None,
                        },
                    },
                    "provenance": {
                        "created_by": "qr-v1",
                        "source_label": "generated:qr",
                    },
                    "license": {"name": "generated_qr", "allow_export": True},
                    "tags": ["qr", "generated"],
                },
                "deduplicated": False,
                "qr": {
                    "ec_level": effective_level,
                    "module_count": 29,
                    "quiet_zone_modules": 4,
                },
            },
        }

    def apply_structured_edit(self, scene, edit, scope=None, brand_kit=None, mode=None):
        if scope and scope.get("mode") == "strict":
            allowed_ids = {target.get("id") for target in scope.get("allowed", [])}
            target_id = (edit.get("target") or {}).get("id")
            if target_id not in allowed_ids:
                raise CoreError(
                    "edit.scope_violation",
                    "1 operation(s) touch targets outside the declared scope",
                    diagnostics=[
                        {
                            "severity": "error",
                            "phase": "operation",
                            "code": "edit.scope_violation",
                            "message": "out of declared scope",
                        }
                    ],
                )
        updated = json.loads(json.dumps(scene))
        updated["structured_edit_applied_by_core"] = True
        return {
            "scene": updated,
            "applied_operations": 1,
            "diagnostics": [],
            "operations": [{"kind": "update_node", "node_id": "headline"}],
            "edit": {
                "kind": edit.get("kind"),
                "touched_targets": [edit.get("target")],
                "intent": "modify_node",
                "checkpoint_label": None,
            },
        }

    def platform_default_brand_kit(self):
        return {
            "id": "brand_kit_platform_default",
            "version": 1,
            "name": "Platform Default",
            "modes": {
                "defaults": {
                    "theme": "light",
                    "density": "comfortable",
                    "accessibility": "standard",
                    "medium": "print",
                }
            },
        }

    def validate_scene_brand_governance(
        self, scene, brand_kit, strictness="strict", raise_on_error=True
    ):
        # K4: the runtime merges governance diagnostics into every
        # kit-attached preflight; the base fake reports a clean scene.
        return {"ok": True, "diagnostics": []}

    def preflight_scene(self, scene, brand_kit, brand_fonts=None):
        # Faithful to the real engine (preflight.rs): the kit ref is attached
        # only when the scene has none; an existing ref is never overwritten.
        updated = json.loads(json.dumps(scene))
        meta = updated.setdefault("meta", {})
        if not meta.get("brand_kit"):
            meta["brand_kit"] = {
                "id": brand_kit["id"],
                "version": brand_kit["version"],
            }
        return {
            "scene": updated,
            "diagnostics": [],
            "preflight": {
                "has_errors": False,
                "brand_ref_operations": [],
                "token_operations": [],
                "layout_operations": [],
            },
        }

    def export_preview(
        self, scene, export_format="svg", page_ids=None, asset_store_root=None,
        brand_fonts=None,
    ):
        # The critic now always requests a PNG (judge on pixels); return valid PNG
        # magic bytes for png and SVG otherwise so the bundle validates.
        if export_format == "png":
            mime_type, raw = "image/png", b"\x89PNG\r\n\x1a\nfake"
        else:
            mime_type, raw = "image/svg+xml", b"<svg></svg>"
        return {
            "diagnostics": [],
            "export": {
                "artifacts": [
                    {
                        "format": export_format,
                        "mime_type": mime_type,
                        "page_id": "page_test",
                        "bytes": list(raw),
                    }
                ]
            },
        }



def runtime_config(tmp_path: Path, max_iterations: int = 3) -> AgentRuntimeConfig:
    # OpenRouter is the sole gateway; the fixture carries the gateway creds so
    # harness construction (always via init_model) can build a model instance.
    return AgentRuntimeConfig(
        repo_root=tmp_path,
        model="openai:anthropic/claude-opus-4.8",
        max_iterations=max_iterations,
        preview_format="svg",
        # W-isolation (D3): trace_dir IS the deepagent's isolated workspace root;
        # substrate lands runs at `<workspace>/run_<id>` and the materializer syncs
        # skills/knowledge here.
        trace_dir=tmp_path / ".deepagent-workspace",
        agent_base_url="https://openrouter.ai/api/v1",
        agent_api_key="sk-test",
    )


def prepare_acceptance_evidence(tools, critique=None, *, preflight=True):
    """Exercise the real evidence seams around the fake deterministic core.

    Success fixtures need a current preflight, valid preview artifact and registered
    typed review. Never manufacture the runtime's private receipt/stamp fields.
    Existing scenes are preserved so hygiene and scoped-edit cases keep their subject.
    """
    if not tools.scene.get("pages"):
        result = json.loads(tools.compile_dsl_block("page page_test size(1080,1080,px)"))
        assert result["compile"]["status"] == "ok"
    if preflight:
        result = json.loads(tools.preflight_design())
        assert result["preflight"]["status"] == "ok"
    result = json.loads(tools.export_preview("svg"))
    assert result["export"]["status"] == "ok"
    review = critique if critique is not None else {
        "accepted": True,
        "summary": "Reviewed the current rendered fixture scene.",
        "issues": [],
    }
    result = json.loads(tools.submit_visual_critique(json.dumps(review)))
    assert result["status"] == "ok"
    return review

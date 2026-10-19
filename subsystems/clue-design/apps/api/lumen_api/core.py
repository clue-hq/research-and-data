from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from py_lumen_config import settings
from py_lumen_obs import get_logger

from .font_containers import normalize_ingest_font
from .image_containers import normalize_ingest_image
from .observability import (
    current_request_id,
    diagnostic_summary,
    duration_ms,
    helper_request_summary,
    log_event,
)


JsonObject = Dict[str, Any]
core_logger = get_logger("lumen_api.core")
helper_logger = get_logger("lumen_api.core.helper")


class CoreError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        diagnostics: Optional[List[JsonObject]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.diagnostics = diagnostics or []


class CoreClient:
    def __init__(self, repo_root: Optional[Path] = None) -> None:
        self.repo_root = repo_root or Path(__file__).resolve().parents[3]

    def new_scene(
        self,
        document_id: str,
        title: str,
        artifact_type: Optional[str] = None,
        medium: Optional[Any] = None,
    ) -> JsonObject:
        response = self._run(
            {
                "action": "new_scene",
                "document_id": document_id,
                "title": title,
                "artifact_type": artifact_type,
                "medium": medium,
            }
        )
        return response["scene"]

    def validate_scene(self, scene: JsonObject) -> JsonObject:
        return self._run({"action": "validate_scene", "scene": scene})

    def apply_operations(
        self,
        scene: JsonObject,
        operations: List[JsonObject],
        scope: Optional[JsonObject] = None,
    ) -> JsonObject:
        request = {"action": "apply_operations", "scene": scene, "operations": operations}
        if scope is not None:
            request["scope"] = scope
        return self._run(request)

    def apply_structured_edit(
        self,
        scene: JsonObject,
        edit: JsonObject,
        scope: Optional[JsonObject] = None,
        *,
        brand_kit: Optional[JsonObject] = None,
        mode: Optional[JsonObject] = None,
    ) -> JsonObject:
        request = {"action": "apply_structured_edit", "scene": scene, "edit": edit}
        if scope is not None:
            request["scope"] = scope
        if brand_kit is not None:
            request["brand_kit"] = brand_kit
        if mode is not None:
            request["mode"] = mode
        return self._run(request)

    def compile_dsl_into_scene(
        self,
        scene: JsonObject,
        source: str,
        dsl_session: Optional[JsonObject] = None,
        protected_node_ids: Optional[list[str]] = None,
        *,
        brand_kit: Optional[JsonObject] = None,
        mode: Optional[JsonObject] = None,
    ) -> JsonObject:
        request: JsonObject = {
            "action": "compile_dsl_into_scene",
            "scene": scene,
            "source": source,
            "dsl_session": dsl_session,
        }
        # Slice 3: seed-born / human node ids a reconcile block must KEEP when
        # omitted. Omitted from the request when None so the helper defaults it
        # empty (pure declarative). Phase B wires the runtime call site.
        if protected_node_ids is not None:
            request["protected_node_ids"] = protected_node_ids
        if brand_kit is not None:
            request["brand_kit"] = brand_kit
        if mode is not None:
            request["mode"] = mode
        return self._run(request)

    def preflight_scene(
        self,
        scene: JsonObject,
        brand_kit: Optional[JsonObject],
        mode: Optional[JsonObject] = None,
        brand_fonts: Optional[JsonObject] = None,
    ) -> JsonObject:
        return self._run(
            {
                "action": "preflight_scene",
                "scene": scene,
                "brand_kit": brand_kit,
                "mode": mode,
                "brand_fonts": brand_fonts,
            }
        )

    def export_preview(
        self,
        scene: JsonObject,
        export_format: str = "svg",
        page_ids: Optional[List[str]] = None,
        profile: Optional[JsonObject] = None,
        raise_on_error: bool = True,
        asset_store_root: Optional[str] = None,
        brand_fonts: Optional[JsonObject] = None,
    ) -> JsonObject:
        return self._run(
            {
                "action": "export_preview",
                "scene": scene,
                "format": export_format,
                "page_ids": page_ids or [],
                "profile": profile,
                "asset_store_root": asset_store_root,
                "brand_fonts": brand_fonts,
            },
            raise_on_error=raise_on_error,
        )

    def ingest_asset(
        self,
        store_root: str,
        bytes_base64: str,
        asset_id: str,
        label: str,
        declared_mime_type: Optional[str] = None,
        filename: Optional[str] = None,
        kind: Optional[str] = None,
        uploaded_by: Optional[str] = None,
        license: Optional[JsonObject] = None,
        provenance: Optional[JsonObject] = None,
        source: Optional[JsonObject] = None,
        tags: Optional[List[str]] = None,
        max_bytes: Optional[int] = None,
        raise_on_error: bool = True,
    ) -> JsonObject:
        # Option A (2026-09-02): the ONE chokepoint every font byte passes through — harvest,
        # uploads, PDF capture, `POST /assets`, font-library provisioning. A WOFF/WOFF2 payload
        # is unwrapped to sfnt HERE, before the Rust helper sniffs it, so the stored primary
        # bytes are always TTF/OTF (see `font_containers.py` for why that invariant matters).
        # `max_bytes` is checked by the helper against the DECODED size, which can be 2-3x the
        # wrapper; that is the honest number for what the store keeps.
        normalized = normalize_ingest_font(
            bytes_base64=bytes_base64,
            declared_mime_type=declared_mime_type,
            filename=filename,
            provenance=provenance,
        )
        if normalized.refusal is not None:
            if raise_on_error:
                raise CoreError(normalized.refusal["code"], normalized.refusal["message"])
            return {"ok": False, "error": dict(normalized.refusal), "diagnostics": []}
        # 2026-10-18: AVIF and ICO become PNG at the same chokepoint (`image_containers.py`),
        # because the helper's sniffer stores them as unreadable `application/octet-stream`.
        normalized = normalize_ingest_image(
            bytes_base64=normalized.bytes_base64,
            declared_mime_type=normalized.declared_mime_type,
            filename=normalized.filename,
            provenance=normalized.provenance,
        )
        if normalized.refusal is not None:
            if raise_on_error:
                raise CoreError(normalized.refusal["code"], normalized.refusal["message"])
            return {"ok": False, "error": dict(normalized.refusal), "diagnostics": []}
        return self._run(
            {
                "action": "ingest_asset",
                "store_root": store_root,
                "bytes_base64": normalized.bytes_base64,
                "asset_id": asset_id,
                "label": label,
                "declared_mime_type": normalized.declared_mime_type,
                "filename": normalized.filename,
                "kind": kind,
                "uploaded_by": uploaded_by,
                "license": license,
                "provenance": normalized.provenance,
                "source": source,
                "tags": tags,
                "max_bytes": max_bytes,
            },
            raise_on_error=raise_on_error,
        )

    def generate_qr(
        self,
        store_root: str,
        data: str,
        asset_id: str,
        label: Optional[str] = None,
        ec_level: Optional[str] = None,
        print_media: bool = False,
        target_width_mm: Optional[float] = None,
        raise_on_error: bool = True,
    ) -> JsonObject:
        return self._run(
            {
                "action": "generate_qr",
                "store_root": store_root,
                "data": data,
                "asset_id": asset_id,
                "label": label,
                "ec_level": ec_level,
                "print": print_media,
                "target_width_mm": target_width_mm,
            },
            raise_on_error=raise_on_error,
        )

    def generate_asset(
        self,
        store_root: str,
        provider: str,
        request: JsonObject,
        asset_id: str,
        label: Optional[str] = None,
        raise_on_error: bool = True,
    ) -> JsonObject:
        return self._run(
            {
                "action": "generate_asset",
                "store_root": store_root,
                "provider": provider,
                "request": request,
                "asset_id": asset_id,
                "label": label,
            },
            raise_on_error=raise_on_error,
        )

    def validate_binding_set(
        self,
        scene: JsonObject,
        binding_set: JsonObject,
        raise_on_error: bool = False,
    ) -> JsonObject:
        return self._run(
            {
                "action": "validate_binding_set",
                "scene": scene,
                "binding_set": binding_set,
            },
            raise_on_error=raise_on_error,
        )

    def derive_instance(
        self,
        scene: JsonObject,
        binding_set: JsonObject,
        asset_records: Optional[List[JsonObject]] = None,
        store_root: Optional[str] = None,
        export_formats: Optional[List[str]] = None,
        export_dpi: Optional[int] = None,
        export_profile: Optional[JsonObject] = None,
        brand_fonts: Optional[JsonObject] = None,
        raise_on_error: bool = False,
    ) -> JsonObject:
        return self._run(
            {
                "action": "derive_instance",
                "scene": scene,
                "binding_set": binding_set,
                "asset_records": asset_records or [],
                "store_root": store_root,
                "export_formats": export_formats or [],
                "export_dpi": export_dpi,
                "export_profile": export_profile,
                "brand_fonts": brand_fonts,
            },
            raise_on_error=raise_on_error,
        )

    def finalize_template(
        self, scene: JsonObject, template_revision_id: str
    ) -> JsonObject:
        return self._run(
            {
                "action": "finalize_template",
                "scene": scene,
                "template_revision_id": template_revision_id,
            }
        )

    def platform_default_brand_kit(self) -> JsonObject:
        response = self._run({"action": "platform_default_brand_kit"})
        return response["brand_kit"]

    def validate_brand_kit(
        self,
        brand_kit: JsonObject,
        product_ready: bool = True,
        raise_on_error: bool = True,
    ) -> JsonObject:
        return self._run(
            {
                "action": "validate_brand_kit",
                "brand_kit": brand_kit,
                "product_ready": product_ready,
            },
            raise_on_error=raise_on_error,
        )

    def compile_styles_brand_kit(
        self,
        source: str,
        brand_kit_id: str,
        version: int,
        name: str,
    ) -> JsonObject:
        return self._run(
            {
                "action": "compile_styles_brand_kit",
                "source": source,
                "brand_kit_id": brand_kit_id,
                "version": version,
                "name": name,
            }
        )

    def generate_brand_kit(self, seed: JsonObject) -> JsonObject:
        return self._run({"action": "generate_brand_kit", "seed": seed})

    def summarize_brand_kit(
        self, brand_kit: JsonObject, raise_on_error: bool = True
    ) -> JsonObject:
        return self._run(
            {"action": "summarize_brand_kit", "brand_kit": brand_kit},
            raise_on_error=raise_on_error,
        )

    def validate_scene_brand_governance(
        self,
        scene: JsonObject,
        brand_kit: JsonObject,
        strictness: str = "strict",
        raise_on_error: bool = True,
    ) -> JsonObject:
        return self._run(
            {
                "action": "validate_scene_brand_governance",
                "scene": scene,
                "brand_kit": brand_kit,
                "strictness": strictness,
            },
            raise_on_error=raise_on_error,
        )

    def compare_brand_kit_compatibility(
        self,
        from_brand_kit: JsonObject,
        to_brand_kit: JsonObject,
        raise_on_error: bool = True,
    ) -> JsonObject:
        return self._run(
            {
                "action": "compare_brand_kit_compatibility",
                "from": from_brand_kit,
                "to": to_brand_kit,
            },
            raise_on_error=raise_on_error,
        )

    def layout_geometry(
        self, scene: JsonObject, brand_fonts: Optional[JsonObject] = None
    ) -> JsonObject:
        return self._run(
            {"action": "layout_geometry", "scene": scene, "brand_fonts": brand_fonts}
        )

    def build_info(self) -> JsonObject:
        """Engine build info for the Track E version handshake."""
        response = self._run({"action": "build_info"})
        return response["build_info"]

    # Website mode (WebDoc): the helper owns the whole web pipeline — mint,
    # validate, HTML ingest, operation apply, and render. Each method is a
    # thin passthrough of the raw helper response (web_doc / html /
    # inverse_operations / diagnostics live under their own keys); callers
    # read what they need.
    def web_new_doc(
        self,
        document_id: str,
        title: str,
        brand_kit_ref: Optional[JsonObject] = None,
    ) -> JsonObject:
        return self._run(
            {
                "action": "web_new_doc",
                "document_id": document_id,
                "title": title,
                "brand_kit_ref": brand_kit_ref,
            }
        )

    def web_validate(
        self,
        doc: JsonObject,
        brand_kit: Optional[JsonObject] = None,
    ) -> JsonObject:
        return self._run(
            {"action": "web_validate", "doc": doc, "brand_kit": brand_kit}
        )

    def web_ingest_html(
        self,
        doc: JsonObject,
        page_id: str,
        html: str,
        custom_css: Optional[str] = None,
        brand_kit: Optional[JsonObject] = None,
    ) -> JsonObject:
        return self._run(
            {
                "action": "web_ingest_html",
                "doc": doc,
                "page_id": page_id,
                "html": html,
                "custom_css": custom_css,
                "brand_kit": brand_kit,
            }
        )

    def web_apply_ops(
        self,
        doc: JsonObject,
        operations: List[JsonObject],
        raise_on_error: bool = True,
    ) -> JsonObject:
        # The manual-edit path passes raise_on_error=False so a checked-apply
        # rejection (ok:false + diagnostics) comes back as a plain response the
        # endpoint maps to a 422, rather than a raised CoreError.
        return self._run(
            {"action": "web_apply_ops", "doc": doc, "operations": operations},
            raise_on_error=raise_on_error,
        )

    def web_render(
        self,
        doc: JsonObject,
        page_id: str,
        mode: str = "editor",
        asset_base_url: Optional[str] = None,
        tailwind_runtime_src: Optional[str] = None,
        bridge_script: Optional[str] = None,
        custom_component_runtimes: Optional[Dict[str, JsonObject]] = None,
        brand_kit: Optional[JsonObject] = None,
        font_face_css: Optional[str] = None,
        fragments: Optional[Dict[str, JsonObject]] = None,
        fragment_css: Optional[str] = None,
    ) -> JsonObject:
        # `fragments` / `fragment_css` (clone-fidelity F1.3): API-resolved cloned-section
        # artifacts keyed by `frag_<16 hex>` id, and their concatenated already-scoped CSS.
        # The engine resolves neither — an id absent from the map renders the placeholder.
        response = self._run(
            {
                # Older helpers must refuse rather than silently ignore a new dependency.
                "action": "web_render_native_fragments" if any(
                    "native_dependencies" in content for content in (fragments or {}).values()
                ) else "web_render",
                "doc": doc,
                "page_id": page_id,
                "mode": mode,
                "asset_base_url": asset_base_url,
                "tailwind_runtime_src": tailwind_runtime_src,
                "bridge_script": bridge_script,
                "custom_component_runtimes": custom_component_runtimes or {},
                "brand_kit": brand_kit,
                "font_face_css": font_face_css,
                "fragments": fragments or {},
                "fragment_css": fragment_css,
            }
        )

        if mode == "editor" and isinstance(response.get("html"), str):
            from .fragments.editor_candidates import isolate_fragment_candidates

            html, diagnostics = isolate_fragment_candidates(response["html"])
            # Inline preview callers qualify only after reading the actual runtime bytes.
            if tailwind_runtime_src is not None:
                from .fragments.editor_preflight import qualify_fragment_preflight

                html, preflight_diagnostics = qualify_fragment_preflight(
                    html, runtime_src=tailwind_runtime_src
                )
                diagnostics.extend(preflight_diagnostics)
            response = {**response, "html": html}
            if diagnostics:
                response["diagnostics"] = list(response.get("diagnostics") or []) + diagnostics
        return response

    def web_derive(
        self,
        doc: JsonObject,
        values: JsonObject,
        assets: Optional[List[JsonObject]] = None,
        new_doc_id: Optional[str] = None,
        new_title: Optional[str] = None,
        raise_on_error: bool = True,
    ) -> JsonObject:
        """P5 derive (D4): apply an account's value map to a template WebDoc,
        producing a marker-preserving derived doc. Pure (no render/I/O). The
        derive path passes raise_on_error=False so an engine rejection
        (ok:false + web_derive.rejected + coverage) comes back as a plain
        response the endpoint maps to a 422, mirroring web_apply_ops."""
        return self._run(
            {
                "action": "web_derive",
                "doc": doc,
                "values": values,
                "assets": assets or [],
                "new_doc_id": new_doc_id,
                "new_title": new_title,
            },
            raise_on_error=raise_on_error,
        )

    def web_ingest_fragment(
        self,
        doc: JsonObject,
        html: str,
        brand_kit: Optional[JsonObject] = None,
    ) -> JsonObject:
        """Parse a constrained-HTML fragment against `doc` WITHOUT mutating it.
        Returns `web_fragment: {nodes, roots}` + diagnostics so callers can
        compose surgical RemoveNode/InsertNode batches (scoped edit turns).

        Nothing to do with CLONED SECTIONS: "fragment" here means a snippet of
        authored markup being ingested into the tree, while a cloned section's
        `frag_…` artifact (F1/F2) is a stored verbatim band that never passes
        through this parser at all."""
        return self._run(
            {
                "action": "web_ingest_fragment",
                "doc": doc,
                "html": html,
                "brand_kit": brand_kit,
            }
        )

    # Every shaping action the helper accepts library fonts for. The spec is
    # injected HERE, at the single helper gateway, rather than threaded
    # through each call site: a forgotten site would silently shape library
    # families with the Inter fallback (the LUMS0100 class of bug). Callers
    # may still pass an explicit `library_fonts` (including None) to override.
    _LIBRARY_FONT_ACTIONS = frozenset(
        {"preflight_scene", "export_preview", "layout_geometry", "derive_instance"}
    )

    def _run(self, request: JsonObject, raise_on_error: bool = True) -> JsonObject:
        if (
            request.get("action") in self._LIBRARY_FONT_ACTIONS
            and "library_fonts" not in request
        ):
            from .font_library import library_font_spec

            request = {**request, "library_fonts": library_font_spec()}
        command = self._command()
        action = str(request.get("action") or "unknown")
        helper_call_id = f"core_{uuid4().hex}"
        start = time.perf_counter()
        env = os.environ.copy()
        env.setdefault("LUMEN_CORE_HELPER_LOG", "1")
        env["LUMEN_CORE_CALL_ID"] = helper_call_id
        if current_request_id():
            env["LUMEN_REQUEST_ID"] = current_request_id() or ""
        log_event(
            core_logger,
            logging.INFO,
            "core_helper_started",
            helper_call_id=helper_call_id,
            **helper_request_summary(request),
        )
        process = subprocess.run(
            command,
            input=json.dumps(request),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.repo_root),
            env=env,
            check=False,
        )
        forward_helper_logs(process.stderr, helper_call_id, action)
        if process.returncode != 0:
            log_event(
                core_logger,
                logging.ERROR,
                "core_helper_process_failed",
                helper_call_id=helper_call_id,
                action=action,
                returncode=process.returncode,
                duration_ms=duration_ms(start),
                stderr_line_count=len([line for line in process.stderr.splitlines() if line]),
            )
            raise CoreError("helper.process", process.stderr.strip() or process.stdout)

        try:
            response = json.loads(process.stdout)
        except json.JSONDecodeError as error:
            log_event(
                core_logger,
                logging.ERROR,
                "core_helper_response_invalid",
                helper_call_id=helper_call_id,
                action=action,
                duration_ms=duration_ms(start),
                stdout_length=len(process.stdout),
            )
            raise CoreError("helper.response", str(error)) from error

        diagnostics = response.get("diagnostics") or []
        error = response.get("error") or {}
        log_event(
            core_logger,
            logging.INFO,
            "core_helper_completed",
            helper_call_id=helper_call_id,
            action=action,
            ok=bool(response.get("ok")),
            duration_ms=duration_ms(start),
            applied_operations=response.get("applied_operations"),
            error_code=error.get("code") if isinstance(error, dict) else None,
            **diagnostic_summary(diagnostics if isinstance(diagnostics, list) else []),
        )
        if not response.get("ok") and raise_on_error:
            raise CoreError(
                error.get("code", "helper.error"),
                error.get("message", "core helper returned an error"),
                response.get("diagnostics") or [],
            )
        return response

    def _command(self) -> List[str]:
        helper = settings.lumen_core_helper
        if helper:
            return [helper]
        return [
            "cargo",
            "run",
            "--quiet",
            "--manifest-path",
            str(self.repo_root / "Cargo.toml"),
            "-p",
            "lumen-api-helper",
        ]


def forward_helper_logs(stderr: str, helper_call_id: str, action: str) -> None:
    for line in stderr.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            log_event(
                helper_logger,
                logging.WARNING,
                "core_helper_stderr",
                helper_call_id=helper_call_id,
                action=action,
                stderr_length=len(line),
            )
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("source") != "lumen-api-helper":
            log_event(
                helper_logger,
                logging.DEBUG,
                "core_helper_stderr_json",
                helper_call_id=helper_call_id,
                action=action,
                helper_payload_keys=sorted(str(key) for key in payload.keys()),
                helper_payload_source=payload.get("source"),
            )
            continue
        event = str(payload.get("event") or "core_helper_boundary")
        level_name = str(payload.get("level") or "info").upper()
        level = getattr(logging, level_name, logging.INFO)
        fields = {
            key: value
            for key, value in payload.items()
            if key not in {"source", "event", "level"}
        }
        fields.setdefault("helper_call_id", helper_call_id)
        fields.setdefault("action", action)
        log_event(helper_logger, level, event, **fields)


def has_error_diagnostics(diagnostics: List[JsonObject]) -> bool:
    return any(diagnostic.get("severity") == "error" for diagnostic in diagnostics)

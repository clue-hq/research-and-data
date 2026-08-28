"""The design API's pure contract + helper module — no storage, no SQLite.

Part II slice D2.5B **deleted the SQLite substrate**. Every ``Repository`` domain moved to
Postgres through ``clue_design`` behind :class:`lumen_api.design_store.HybridRepository`, so the
``Repository`` class, ``connect``/``run_migrations``/``backfill_edit_envelopes``, the
``ensure_column`` machinery, ``apps/api/migrations/*.sql``, and every ``sqlite3.Row`` decoder are
gone with it. **Storage is ``clue_design`` via ``design_store``.**

What survives here is what was never storage in the first place:

* the API's **error vocabulary** — :class:`NotFoundError`, :class:`WebDocumentVersionConflict`,
  :class:`CustomComponentArtifactConflict`, :class:`CustomComponentSourceVersionConflict`,
  :class:`CustomComponentReferenceError`. ``main.py`` registers HTTP handlers for these and the
  ``clue_design`` errors are translated *into* them at the bridge, so the DTOs are unchanged.
* the **custom-component contract** — blob canonicalization, the artifact/source registration
  candidates, the pinned-node index, and the generated-props schema check. These are P6 product
  rules, not table rules; the Postgres path runs these exact functions.
* ``utc_now`` — the one ISO-8601 stamp helper the API still mints for itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from .custom_component_contract import custom_component_slug_is_valid

JsonObject = Dict[str, Any]


class NotFoundError(KeyError):
    def __init__(self, resource_type: str, resource_id: str) -> None:
        super().__init__(resource_type, resource_id)
        self.resource_type = resource_type
        self.resource_id = resource_id

    def __str__(self) -> str:
        return f"{self.resource_type} {self.resource_id} was not found"


class WebDocumentVersionConflict(RuntimeError):
    """A website write lost its optimistic-concurrency race.

    Raised from the repository rather than only checked at the HTTP boundary so
    background agent workers and foreground editor writes share the same atomic
    compare-and-swap protection.
    """

    def __init__(self, document_id: str, expected: int, current: int) -> None:
        super().__init__(
            f"document {document_id} expected version {expected}, current version is {current}"
        )
        self.document_id = document_id
        self.expected = expected
        self.current = current


class DesignResourceVersionConflict(RuntimeError):
    """A NON-document compare-and-set write lost its race (Part II slice D6 Round C).

    The DAL's ``DesignVersionConflictError`` has always carried the resource ``kind``; the API
    only had :class:`WebDocumentVersionConflict` to translate it into, whose ``document_id``
    attribute would be a lie for the two CAS sites D6 Round C adds — the brand-kit version
    allocator (``kind='brand_kit'``) and the batch cursor single-flight
    (``kind='instance_batch'`` / ``'web_batch'``). Documents keep their own type so every
    existing handler and every ``except WebDocumentVersionConflict`` is untouched.
    """

    def __init__(self, kind: str, key: str, expected: int, current: int) -> None:
        super().__init__(f"{kind} {key} expected {expected}, current is {current}")
        self.kind = kind
        self.key = key
        self.expected = expected
        self.current = current


class WebPublishRevisionConflict(RuntimeError):
    """A ``webpub_<digest>`` id was re-registered with different stored content.

    The publish twin of :class:`CustomComponentArtifactConflict` (Part II slice D6 Round C).
    ``clue_design.publishes.register_web_publish_revision`` used to raise a bare ``ValueError``
    that nothing caught, so a content-addressing collision surfaced as a 500; it is a describable
    domain refusal and now answers 409.
    """

    def __init__(self, publish_id: str) -> None:
        super().__init__(f"publish {publish_id} already exists with different content")
        self.publish_id = publish_id


class CustomComponentArtifactConflict(RuntimeError):
    """An immutable artifact id was reused with different stored metadata."""

    def __init__(self, artifact_id: str) -> None:
        super().__init__(
            f"custom component artifact {artifact_id} already exists with different content"
        )
        self.artifact_id = artifact_id


class CustomComponentSourceVersionConflict(RuntimeError):
    """A component source write or compile targeted a stale source version."""

    def __init__(self, slug: str, expected: int, current: int) -> None:
        super().__init__(
            f"custom component {slug} expected source version {expected}, "
            f"current version is {current}"
        )
        self.slug = slug
        self.expected = expected
        self.current = current


class CustomComponentReferenceError(RuntimeError):
    """A document write introduced an unresolved or cross-account artifact."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        node_id: str,
        artifact_id: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.node_id = node_id
        self.artifact_id = artifact_id


class FragmentReferenceError(RuntimeError):
    """A document write introduced a fragment pin this workspace cannot resolve.

    The custom-component twin (:class:`CustomComponentReferenceError`), kept a SEPARATE type for
    the same reason its ingestion-fence sibling is: the two name different registries with
    different identifiers, their handlers word different messages, and a caller that catches one
    must not silently swallow the other. Fragments are workspace-scoped rather than
    account-scoped, so there is no ``account_id`` here and no slug to agree with — the pin is
    just the id, and the id is the content.
    """

    def __init__(self, code: str, message: str, *, node_id: str, fragment_id: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.node_id = node_id
        self.fragment_id = fragment_id


def fragment_nodes(web_doc: JsonObject) -> Dict[Tuple[str, str], JsonObject]:
    """Index every ``fragment`` node in a web document by page and node id.

    The exact shape of :func:`custom_component_nodes`, and for the same reason: location is
    stable across ordinary move/reparent/resize edits, so those operations do not re-resolve an
    unchanged pin, while duplicate mints a new node id and is therefore correctly treated as a
    new reference.
    """
    nodes_by_location: Dict[Tuple[str, str], JsonObject] = {}
    pages = web_doc.get("pages")
    if not isinstance(pages, list):
        return nodes_by_location
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_id = page.get("id")
        nodes = page.get("nodes")
        if not isinstance(page_id, str) or not isinstance(nodes, dict):
            continue
        for node_id, node in nodes.items():
            if (
                isinstance(node_id, str)
                and isinstance(node, dict)
                and node.get("kind") == "fragment"
            ):
                nodes_by_location[(page_id, node_id)] = node
    return nodes_by_location


def fragment_references(web_doc: JsonObject) -> Dict[Tuple[str, str], Tuple[str, str]]:
    """Every pinned fragment node as ``location -> (node_id, fragment_id)``."""
    references: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for (page_id, node_id), node in fragment_nodes(web_doc).items():
        fragment_id = node.get("fragment_id")
        if isinstance(fragment_id, str):
            references[(page_id, node_id)] = (node_id, fragment_id)
    return references


def custom_component_opaque_ref_is_canonical(opaque_ref: str, digest: str) -> bool:
    """Whether a blob descriptor's ``opaque_ref`` is one this API is allowed to have minted.

    TWO shapes are canonical, and both are content-derived — the ref may never be free-form:

    * ``{workspace_id}/design/{digest}`` — the D4 platform storage key
      (``clue_design.storage.design_storage_key``), where the workspace segment carries no ``/``.
    * ``sha256/{ab}/{digest}`` — the pre-D4 API-local store path, still accepted so a registry
      row written before the move validates (the registry table is immutable, so those rows can
      never be rewritten). Nothing reads either ref as a *path*: resolution is by ``digest``.
    """
    if opaque_ref == f"sha256/{digest[:2]}/{digest}":
        return True
    prefix, separator, suffix = opaque_ref.partition("/design/")
    return bool(separator) and suffix == digest and bool(prefix) and "/" not in prefix


def canonical_custom_component_blob(
    label: str,
    blob: Any,
    *,
    allow_empty: bool = False,
) -> JsonObject:
    if not isinstance(blob, dict):
        raise ValueError(f"{label} blob record must be an object")
    digest = str(blob.get("value") or "")
    opaque_ref = str(blob.get("opaque_ref") or "")
    byte_length = blob.get("byte_length")
    minimum = 0 if allow_empty else 1
    if (
        blob.get("algorithm") != "sha256"
        or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
        or not custom_component_opaque_ref_is_canonical(opaque_ref, digest)
        or not isinstance(byte_length, int)
        or isinstance(byte_length, bool)
        or byte_length < minimum
    ):
        qualifier = "canonical" if allow_empty else "non-empty canonical"
        raise ValueError(f"{label} blob must be a {qualifier} sha256 store record")
    return {
        "algorithm": "sha256",
        "value": digest,
        "opaque_ref": opaque_ref,
        "byte_length": byte_length,
    }


def custom_component_artifact_candidate(artifact: JsonObject) -> JsonObject:
    """Validate + canonicalize one artifact registration into its comparable candidate.

    Extracted from ``Repository.register_custom_component_artifact`` at D2.4B: the P6 blob /
    slug / content-address rules are the design API's CONTRACT, not storage rules, so the
    Postgres path (``HybridRepository`` → ``clue_design.components``) runs these identical
    checks — same error types, same messages — instead of re-implementing them in the DAL.
    """
    account_id = str(artifact["account_id"])
    slug = str(artifact["slug"])
    artifact_id = str(artifact["artifact_id"])
    source_blob = canonical_custom_component_blob("source", artifact["source"])
    bundle_blob = canonical_custom_component_blob("bundle", artifact["bundle"])
    css_blob = (
        canonical_custom_component_blob("css", artifact["css"], allow_empty=True)
        if artifact.get("css") is not None
        else None
    )
    first_frame_blob = (
        canonical_custom_component_blob(
            "first_frame", artifact["first_frame"], allow_empty=True
        )
        if artifact.get("first_frame") is not None
        else None
    )
    if (css_blob is None) != (first_frame_blob is None):
        raise ValueError("css and first_frame blob records must be supplied together")
    manifest = artifact.get("manifest", {})
    provenance = artifact.get("provenance", {})
    if not custom_component_slug_is_valid(slug):
        raise ValueError(
            "custom component slug must be 1–64 lowercase kebab-case characters"
        )
    if not isinstance(manifest, dict) or not isinstance(provenance, dict):
        raise ValueError("custom component manifest and provenance must be objects")
    if (
        not artifact_id.startswith("ccart_")
        or len(artifact_id) != len("ccart_") + 64
        or any(ch not in "0123456789abcdef" for ch in artifact_id[len("ccart_") :])
    ):
        raise ValueError("artifact_id must be ccart_<lowercase sha256>")
    return {
        "artifact_id": artifact_id,
        "account_id": account_id,
        "slug": slug,
        "source": source_blob,
        "bundle": bundle_blob,
        "css": css_blob,
        "first_frame": first_frame_blob,
        "manifest": manifest,
        "provenance": provenance,
    }


def custom_component_source_candidate(
    source: JsonObject, expected_version: int
) -> JsonObject:
    """Validate + canonicalize one source-revision write (same extraction rationale)."""
    account_id = str(source["account_id"])
    slug = str(source["slug"])
    revision_id = str(source["revision_id"])
    entry_path = str(source["entry_path"])
    snapshot = canonical_custom_component_blob("source snapshot", source["snapshot"])
    files_manifest = source.get("files_manifest")
    provenance = source.get("provenance", {})
    if not custom_component_slug_is_valid(slug):
        raise ValueError(
            "custom component slug must be 1–64 lowercase kebab-case characters"
        )
    if (
        not revision_id.startswith("ccsrc_")
        or len(revision_id) != len("ccsrc_") + 64
        or any(ch not in "0123456789abcdef" for ch in revision_id[len("ccsrc_") :])
    ):
        raise ValueError("revision_id must be ccsrc_<lowercase sha256>")
    if (
        not isinstance(expected_version, int)
        or isinstance(expected_version, bool)
        or expected_version < 0
    ):
        raise ValueError("expected_version must be a non-negative integer")
    if not isinstance(files_manifest, dict) or not isinstance(provenance, dict):
        raise ValueError("files_manifest and provenance must be objects")
    return {
        "revision_id": revision_id,
        "account_id": account_id,
        "slug": slug,
        "entry_path": entry_path,
        "snapshot": snapshot,
        "files_manifest": files_manifest,
        "provenance": provenance,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def custom_component_nodes(
    web_doc: JsonObject,
) -> Dict[Tuple[str, str], JsonObject]:
    nodes_by_location: Dict[Tuple[str, str], JsonObject] = {}
    pages = web_doc.get("pages")
    if not isinstance(pages, list):
        return nodes_by_location
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_id = page.get("id")
        nodes = page.get("nodes")
        if not isinstance(page_id, str) or not isinstance(nodes, dict):
            continue
        for node_id, node in nodes.items():
            if (
                isinstance(node_id, str)
                and isinstance(node, dict)
                and node.get("kind") == "custom_component"
            ):
                nodes_by_location[(page_id, node_id)] = node
    return nodes_by_location


def custom_component_props_schema_issue(
    props: Any, manifest: Any
) -> Optional[str]:
    if not isinstance(props, dict):
        return "props must be an object"
    # P6.1 fixture/backfill artifacts deliberately predate generated schemas.
    # They remain movable/duplicable; only compiler-v2 artifacts participate in
    # generated-control validation and the executable P6.3 runtime.
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
        return None
    schema = manifest.get("props_schema") if isinstance(manifest, dict) else None
    properties = schema.get("properties") if isinstance(schema, dict) else None
    required = schema.get("required", []) if isinstance(schema, dict) else []
    if (
        not isinstance(schema, dict)
        or schema.get("type") != "object"
        or not isinstance(properties, dict)
        or not isinstance(required, list)
        or any(not isinstance(name, str) for name in required)
    ):
        return "artifact has no usable generated prop schema"
    unknown = sorted(set(props) - set(properties))
    if unknown:
        return f"unknown prop {unknown[0]!r}"
    missing = sorted(name for name in required if name not in props)
    if missing:
        return f"required prop {missing[0]!r} is missing"
    for name, value in sorted(props.items()):
        field = properties.get(name)
        if not isinstance(field, dict):
            return f"prop {name!r} has no field schema"
        expected = field.get("type")
        valid = (
            (expected == "string" and isinstance(value, str))
            or (
                expected == "number"
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            )
            or (expected == "boolean" and isinstance(value, bool))
        )
        if not valid:
            return f"prop {name!r} must be {expected}"
        enum = field.get("enum")
        if enum is not None and (
            not isinstance(enum, list) or value not in enum
        ):
            return f"prop {name!r} is not one of its allowed values"
    return None


def custom_component_references(
    web_doc: JsonObject,
) -> Dict[Tuple[str, str], Tuple[str, str, str]]:
    """Index every pinned custom-component node by page and node id.

    Location is stable across ordinary move/reparent/resize edits, so those
    operations do not re-resolve an unchanged artifact. Duplicate mints a new
    node id and therefore is correctly treated as a new reference.
    """

    references: Dict[Tuple[str, str], Tuple[str, str, str]] = {}
    for (page_id, node_id), node in custom_component_nodes(web_doc).items():
        slug = node.get("slug")
        artifact_id = node.get("artifact_id")
        if isinstance(slug, str) and isinstance(artifact_id, str):
            references[(page_id, node_id)] = (
                node_id,
                slug,
                artifact_id,
            )
    return references

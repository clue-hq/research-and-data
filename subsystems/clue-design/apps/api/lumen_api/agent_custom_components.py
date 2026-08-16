"""Account-bound custom-component registry gateway for website Deep Agent runs.

The agent runtime receives this object as a capability, never a database path or
a byte-store root. Every method builds a short-lived store and applies the account
predicate internally, so a model-controlled slug/artifact id cannot select
another tenant. Source writes and compilation are deliberately separate,
and artifact resolution accepts only compiler-v2 artifacts backed by a durable
successful compilation record.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .custom_components import resolve_custom_component_source_snapshot
from .database import (
    NotFoundError,
    custom_component_props_schema_issue,
)
from .design_store import DesignBlobStore, HybridRepository
from .toolbelt.wiring import DesignToolInvocations


JsonObject = Dict[str, Any]


def _artifact_summary(artifact: JsonObject) -> JsonObject:
    manifest = artifact.get("manifest")
    return {
        "artifact_id": artifact["artifact_id"],
        "slug": artifact["slug"],
        "manifest": manifest,
        "created_at": artifact.get("created_at"),
        "source_digest": (artifact.get("source") or {}).get("value"),
        "bundle_digest": (artifact.get("bundle") or {}).get("value"),
        "css_digest": (artifact.get("css") or {}).get("value"),
        "first_frame_digest": (artifact.get("first_frame") or {}).get("value"),
        "provenance": artifact.get("provenance"),
    }


class DurableAgentCustomComponentRegistry:
    """The sole durable-registry capability exposed to one agent turn."""

    def __init__(
        self,
        *,
        blobs: DesignBlobStore,
        account_id: str,
        document_id: str,
        invocations: DesignToolInvocations,
    ) -> None:
        if not account_id:
            raise ValueError("custom-component agent registry requires an account")
        if not document_id:
            raise ValueError("custom-component agent registry requires a document")
        # D4: the byte store is a platform-storage handle (workspace-scoped keys), not a path.
        # (The vestigial `database_path` anchor D2.5B left behind is gone with the asset store
        # it used to root — nothing in this class ever names a filesystem location again.)
        self.blobs = blobs
        self.account_id = account_id
        self.document_id = document_id
        # D6 (R-D6-5): the ONE governed design write path. The registry used to hold the
        # compiler's node binary / worker path / timeout and call the orchestration functions
        # directly; those collaborators now live on the tool host, and the agent's two durable
        # writes are journaled, A9-keyed invocations stamped `actor="agent"` — the same envelope
        # a human's HTTP write goes through (REQ-20 parity). Full GovernedAgentToolFactory
        # integration is Part III; this is the substrate it will bind to.
        self.invocations = invocations

    def _repository(self) -> HybridRepository:
        # Postgres via clue_design (D2.5B: no SQLite handle to open or close). The row store and
        # the byte store must name the SAME tenant, so the repository takes its workspace from
        # the injected blob-store handle instead of re-deriving the dev default (D4). Threading
        # the *request* workspace all the way into the turn workers is still the D2.5A residual
        # D5 owns — construction sites decide which workspace this handle carries.
        return HybridRepository(self.blobs.workspace_id)

    @staticmethod
    def _latest_success_for_artifact(
        repository: HybridRepository, account_id: str, slug: str, artifact_id: str
    ) -> Optional[JsonObject]:
        return next(
            (
                compilation
                for compilation in repository.list_custom_component_compilations(
                    account_id, slug
                )
                if compilation.get("status") == "succeeded"
                and compilation.get("artifact_id") == artifact_id
            ),
            None,
        )

    @classmethod
    def _attachable_artifact(
        cls,
        repository: HybridRepository,
        account_id: str,
        slug: str,
        artifact_id: str,
    ) -> tuple[JsonObject, JsonObject]:
        artifact = repository.require_custom_component_artifact(
            account_id, artifact_id
        )
        if artifact["slug"] != slug:
            raise ValueError(
                f"artifact {artifact_id!r} belongs to {artifact['slug']!r}, not {slug!r}"
            )
        manifest = artifact.get("manifest")
        browser = manifest.get("browser") if isinstance(manifest, dict) else None
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != 2
            or not isinstance(browser, dict)
            or browser.get("format") != "esm"
            or browser.get("react") != "host-singleton"
            or artifact.get("css") is None
            or artifact.get("first_frame") is None
        ):
            raise ValueError(
                "artifact did not pass the executable custom-component compile gate"
            )
        compilation = cls._latest_success_for_artifact(
            repository, account_id, slug, artifact_id
        )
        if compilation is None:
            raise ValueError(
                "artifact has no durable successful compilation record"
            )
        return artifact, compilation

    def list_attachable(self) -> JsonObject:
        repository = self._repository()
        repository.require_web_account(self.account_id)
        components = []
        for component in repository.list_custom_components(self.account_id):
            artifact_id = component.get("latest_artifact_id")
            if not isinstance(artifact_id, str):
                continue
            try:
                artifact, compilation = self._attachable_artifact(
                    repository,
                    self.account_id,
                    component["slug"],
                    artifact_id,
                )
            except (NotFoundError, ValueError):
                continue
            components.append(
                {
                    "slug": component["slug"],
                    "source_version": component["source_version"],
                    "artifact": _artifact_summary(artifact),
                    "compilation": compilation,
                    "usage_count": len(
                        repository.list_custom_component_usages(
                            self.account_id, component["slug"]
                        )
                    ),
                }
            )
        return {
            "schema_version": 1,
            "account_id": self.account_id,
            "components": components,
        }

    def inspect(self, slug: str) -> JsonObject:
        repository = self._repository()
        component = repository.require_custom_component(self.account_id, slug)
        revision = repository.get_current_custom_component_source(
            self.account_id, slug
        )
        files: Dict[str, str] = {}
        if revision is not None:
            _, files = resolve_custom_component_source_snapshot(
                repository,
                self.blobs,
                account_id=self.account_id,
                revision_id=revision["revision_id"],
            )
        artifacts = [
            _artifact_summary(artifact)
            for artifact in component.get("artifacts") or []
        ]
        return {
            "schema_version": 1,
            "account_id": self.account_id,
            "component": {
                key: value
                for key, value in component.items()
                if key != "artifacts"
            },
            "source": revision,
            "files": files,
            "artifacts": artifacts,
            "compilations": repository.list_custom_component_compilations(
                self.account_id, slug
            ),
            "usages": repository.list_custom_component_usages(
                self.account_id, slug
            ),
        }

    def projection(self) -> JsonObject:
        """Return the current account's source trees for run-local projection."""

        repository = self._repository()
        components = []
        for component in repository.list_custom_components(self.account_id):
            revision = repository.get_current_custom_component_source(
                self.account_id, component["slug"]
            )
            if revision is None:
                continue
            _, files = resolve_custom_component_source_snapshot(
                repository,
                self.blobs,
                account_id=self.account_id,
                revision_id=revision["revision_id"],
            )
            components.append(
                {
                    "slug": component["slug"],
                    "source_version": component["source_version"],
                    "revision_id": revision["revision_id"],
                    "files": files,
                }
            )
        return {
            "schema_version": 1,
            "account_id": self.account_id,
            "components": components,
        }

    def _invoke(self, name: str, body: JsonObject) -> JsonObject:
        """Run one governed design tool as the agent. Refusals raise, they never return empty."""
        result = self.invocations.invoke(
            name,
            body,
            workspace_id=self.blobs.workspace_id,
            actor="agent",
        )
        return dict(result.references)

    def write_source(
        self,
        *,
        slug: str,
        expected_version: int,
        files: Dict[str, str],
        provenance: JsonObject,
    ) -> JsonObject:
        written = self._invoke(
            "design_write_component_source",
            {
                "account_id": self.account_id,
                "slug": slug,
                "expected_version": expected_version,
                "files": dict(files),
                "provenance": provenance,
            },
        )
        repository = self._repository()
        return {
            "schema_version": 1,
            "component": repository.require_custom_component(
                self.account_id, slug
            ),
            "source": repository.require_custom_component_source_revision(
                self.account_id, written["revision_id"]
            ),
        }

    def compile_once(
        self, *, slug: str, source_version: int, actor: JsonObject
    ) -> JsonObject:
        compiled = self._invoke(
            "design_compile_component",
            {
                "account_id": self.account_id,
                "slug": slug,
                "source_version": source_version,
                "actor": actor,
            },
        )
        repository = self._repository()
        artifact_id = compiled["artifact_id"]
        return {
            "schema_version": 1,
            "compile_status": compiled["compile_status"],
            "compilation": repository.require_custom_component_compilation(
                self.account_id, compiled["compilation_id"]
            ),
            "artifact": (
                repository.require_custom_component_artifact(
                    self.account_id, artifact_id
                )
                if artifact_id is not None
                else None
            ),
        }

    def resolve_attachable(
        self, *, slug: str, artifact_id: str, props: Optional[JsonObject]
    ) -> JsonObject:
        repository = self._repository()
        artifact, compilation = self._attachable_artifact(
            repository, self.account_id, slug, artifact_id
        )
        manifest = artifact.get("manifest")
        defaults = (
            manifest.get("defaults")
            if isinstance(manifest, dict)
            and isinstance(manifest.get("defaults"), dict)
            else {}
        )
        effective_props = dict(defaults)
        if props is not None:
            effective_props.update(props)
        issue = custom_component_props_schema_issue(
            effective_props, manifest
        )
        if issue is not None:
            raise ValueError(issue)
        return {
            "schema_version": 1,
            "artifact": _artifact_summary(artifact),
            "compilation": compilation,
            "props": effective_props,
        }

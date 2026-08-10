"""P6.4 durable account-bound registry gateway integration."""

from __future__ import annotations

from pathlib import Path

import pytest
from clue_storage import FsStorage

from conftest import make_blob_store

from lumen_api.agent_custom_components import (
    DurableAgentCustomComponentRegistry,
)
from lumen_api.design_store import HybridRepository
from lumen_api.database import (
    CustomComponentSourceVersionConflict,
    NotFoundError,
)
from lumen_api.main import create_app


VALID_SOURCE = """
import React from "react";

type Props = {
  headline?: string;
  emphasis?: "primary" | "accent";
  count?: number;
  visible?: boolean;
};

export const meta = {
  name: "Account Metric",
  description: "A themed account metric."
};

export default function AccountMetric({
  props: {
    headline = "Performance",
    emphasis = "primary",
    count = 3,
    visible = true
  }
}: {
  props: Props;
  theme: { colors: Record<string, string> };
  overrideVariables?: Record<string, string>;
}) {
  return visible ? (
    <section className="rounded-xl bg-card p-6 text-dark">
      <h2 className="text-2xl font-heading">{headline}</h2>
      <strong className={emphasis === "primary" ? "text-primary" : "text-accent"}>
        {count}
      </strong>
    </section>
  ) : null;
}
"""


def make_gateway(app, *, account_id: str, document_id: str):
    # D6 (R-D6-5): the gateway's two durable writes run through the app's governed design
    # invoker, so an agent write is journaled and A9-keyed exactly like an HTTP one.
    return DurableAgentCustomComponentRegistry(
        blobs=make_blob_store(app),
        account_id=account_id,
        document_id=document_id,
        invocations=app.state.design_tools,
    )


def seed(tmp_path: Path):
    app = create_app(
        tmp_path / "engine-cache", storage=FsStorage(tmp_path / "design-storage")
    )
    core = app.state.core
    repository = HybridRepository()
    repository.create_web_account(
        "acc_alpha", "Alpha", None, None, {}, None
    )
    repository.create_web_account(
        "acc_beta", "Beta", None, None, {}, None
    )
    for document_id, title in (
        ("doc_alpha_one", "Alpha one"),
        ("doc_alpha_two", "Alpha two"),
    ):
        web_doc = core.web_new_doc(document_id, title, None)["web_doc"]
        web_doc = core.web_ingest_html(
            web_doc,
            "home",
            (
                '<section id="host" class="bg-light">'
                '<div id="host_box" class="p-8">'
                "<p>Host content</p>"
                "</div></section>"
            ),
        )["web_doc"]
        repository.create_document(
            web_doc, doc_kind="web", account_id="acc_alpha"
        )
    return app


def attach(
    app,
    *,
    document_id: str,
    slug: str,
    artifact_id: str,
    node_id: str,
):
    repository = HybridRepository()
    document = repository.require_document(document_id)
    page = document["scene"]["pages"][0]
    operation = {
        "kind": "insert_node",
        "page_id": "home",
        "parent": "host_box",
        "index": len(page["nodes"]["host_box"].get("children") or []),
        "nodes": [
            {
                "id": node_id,
                "kind": "custom_component",
                "slug": slug,
                "artifact_id": artifact_id,
                "props": {
                    "headline": "Performance",
                    "emphasis": "primary",
                    "count": 3,
                    "visible": True,
                },
                "classes": "w-full min-h-[160px]",
            }
        ],
        "root": node_id,
    }
    applied = app.state.core.web_apply_ops(
        document["scene"], [operation]
    )
    repository.update_web_document(
        document_id,
        applied["web_doc"],
        intent="attach custom component",
        checkpoint_label="Attach",
        operations=[operation],
        inverse_operations=applied.get("inverse_operations"),
        expected_base_version=document["current_version"],
    )


def repin(
    app,
    *,
    document_id: str,
    node_id: str,
    slug: str,
    artifact_id: str,
):
    repository = HybridRepository()
    document = repository.require_document(document_id)
    operation = {
        "kind": "set_node_props",
        "page_id": "home",
        "id": node_id,
        "props": {
            "kind": "custom_component",
            "slug": slug,
            "artifact_id": artifact_id,
            "props": {
                "headline": "Updated",
                "emphasis": "accent",
                "count": 4,
                "visible": True,
            },
        },
    }
    applied = app.state.core.web_apply_ops(
        document["scene"], [operation]
    )
    repository.update_web_document(
        document_id,
        applied["web_doc"],
        intent="repin custom component",
        checkpoint_label="Repin",
        operations=[operation],
        inverse_operations=applied.get("inverse_operations"),
        expected_base_version=document["current_version"],
    )


def test_source_survives_gateway_recreation_and_is_account_isolated(
    tmp_path: Path,
):
    app = seed(tmp_path)
    first = make_gateway(
        app, account_id="acc_alpha", document_id="doc_alpha_one"
    )
    written = first.write_source(
        slug="account-metric",
        expected_version=0,
        files={"account-metric.tsx": VALID_SOURCE},
        provenance={
            "kind": "deep_agent_custom_component_source_write",
            "actor": {"kind": "agent", "id": "run_one"},
            "ladder_gap": "Requires computed branded visualization.",
            "endpoint_claims": [],
        },
    )
    assert written["source"]["source_version"] == 1

    restarted = make_gateway(
        app, account_id="acc_alpha", document_id="doc_alpha_two"
    )
    inspected = restarted.inspect("account-metric")
    assert inspected["files"]["account-metric.tsx"] == VALID_SOURCE
    assert inspected["component"]["source_version"] == 1
    assert restarted.projection()["components"][0]["source_version"] == 1

    with pytest.raises(CustomComponentSourceVersionConflict):
        restarted.write_source(
            slug="account-metric",
            expected_version=0,
            files={"account-metric.tsx": VALID_SOURCE},
            provenance={"kind": "stale"},
        )

    other_account = make_gateway(
        app, account_id="acc_beta", document_id="doc_beta"
    )
    assert other_account.projection()["components"] == []
    with pytest.raises(NotFoundError):
        other_account.inspect("account-metric")


def test_compile_gate_and_page_local_repin_preserve_other_document(
    tmp_path: Path,
):
    app = seed(tmp_path)
    gateway = make_gateway(
        app, account_id="acc_alpha", document_id="doc_alpha_one"
    )
    gateway.write_source(
        slug="account-metric",
        expected_version=0,
        files={"account-metric.tsx": VALID_SOURCE},
        provenance={
            "kind": "deep_agent_custom_component_source_write",
            "actor": {"kind": "agent", "id": "run_one"},
            "ladder_gap": "Requires computed branded visualization.",
            "endpoint_claims": [],
        },
    )
    with pytest.raises(NotFoundError):
        gateway.resolve_attachable(
            slug="account-metric",
            artifact_id="ccart_" + "0" * 64,
            props={},
        )

    first_compile = gateway.compile_once(
        slug="account-metric",
        source_version=1,
        actor={"kind": "agent", "id": "run_one"},
    )
    assert first_compile["compile_status"] == "success", first_compile
    first_artifact = first_compile["artifact"]["artifact_id"]
    resolved = gateway.resolve_attachable(
        slug="account-metric",
        artifact_id=first_artifact,
        props={"headline": "Performance"},
    )
    assert resolved["compilation"]["status"] == "succeeded"
    assert resolved["props"]["count"] == 3

    attach(
        app,
        document_id="doc_alpha_one",
        slug="account-metric",
        artifact_id=first_artifact,
        node_id="cc_metric_one",
    )
    attach(
        app,
        document_id="doc_alpha_two",
        slug="account-metric",
        artifact_id=first_artifact,
        node_id="cc_metric_two",
    )

    updated_source = VALID_SOURCE.replace(
        'headline = "Performance"', 'headline = "Growth"'
    )
    write_two = gateway.write_source(
        slug="account-metric",
        expected_version=1,
        files={"account-metric.tsx": updated_source},
        provenance={
            "kind": "deep_agent_custom_component_source_write",
            "actor": {"kind": "agent", "id": "run_two"},
            "ladder_gap": "Same component behavior, revised presentation.",
            "endpoint_claims": [],
        },
    )
    assert write_two["source"]["source_version"] == 2
    second_compile = gateway.compile_once(
        slug="account-metric",
        source_version=2,
        actor={"kind": "agent", "id": "run_two"},
    )
    assert second_compile["compile_status"] == "success", second_compile
    second_artifact = second_compile["artifact"]["artifact_id"]
    assert second_artifact != first_artifact

    repin(
        app,
        document_id="doc_alpha_one",
        node_id="cc_metric_one",
        slug="account-metric",
        artifact_id=second_artifact,
    )
    usages = gateway.inspect("account-metric")["usages"]
    by_document = {
        usage["document_id"]: usage["artifact_id"] for usage in usages
    }
    assert by_document == {
        "doc_alpha_one": second_artifact,
        "doc_alpha_two": first_artifact,
    }

    beta = make_gateway(app, account_id="acc_beta", document_id="doc_beta")
    with pytest.raises(NotFoundError):
        beta.resolve_attachable(
            slug="account-metric",
            artifact_id=second_artifact,
            props={},
        )

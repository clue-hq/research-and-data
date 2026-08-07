"""P6.2 durable source, constrained compiler, and immutable artifact gates."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import lumen_api.main as main_module
from lumen_api.custom_components import persist_custom_component_source_revision
from lumen_api.design_store import HybridRepository
from lumen_api.database import (
    CustomComponentSourceVersionConflict,
    Repository,
    connect,
    run_migrations,
)
from lumen_api.main import create_app


VALID_SOURCE = """
import React from "react";

type Props = {
  headline?: string;
  accent?: "blue" | "green";
  planCount?: number;
  showBadge?: boolean;
  unsupported?: string[];
};

export const meta = {
  name: "Pricing Card",
  description: "A compact pricing callout."
};

export default function PricingCard({
  props: {
    headline = "Pricing",
    accent = "blue",
    planCount = 3,
    showBadge = true
  }
}: {
  props: Props;
  theme: { colors: { primary: string } };
  overrideVariables?: Record<string, string>;
}) {
  return (
    <section className={accent === "blue" ? "rounded-xl bg-primary p-6" : "rounded-xl bg-secondary p-6"}>
      <h2 className="font-heading text-2xl">{headline}</h2>
      <p>{planCount} plans</p>
      {showBadge ? <span>Popular</span> : null}
    </section>
  );
}
"""

CURATED_SOURCE = """
import React, { useRef } from "react";
import { LinePath } from "@visx/shape";
import { curveMonotoneX } from "@visx/curve";
import { Group } from "@visx/group";
import { scaleLinear } from "@visx/scale";
import { motion } from "motion/react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";

const points = [{ x: 0, y: 10 }, { x: 1, y: 40 }];

export default function CuratedChart() {
  const ref = useRef<HTMLDivElement>(null);
  const x = scaleLinear({ domain: [0, 1], range: [0, 100] });
  useGSAP(() => {
    if (ref.current) gsap.to(ref.current, { opacity: 1 });
  }, { scope: ref });
  return (
    <motion.div ref={ref} initial={false} animate={{ opacity: 1 }} className="p-4">
      <svg viewBox="0 0 120 60">
        <Group left={10} top={10}>
          <LinePath
            data={points}
            x={(d: { x: number; y: number }) => x(d.x)}
            y={(d: { x: number; y: number }) => d.y}
            curve={curveMonotoneX}
          />
        </Group>
      </svg>
    </motion.div>
  );
}
"""


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(tmp_path / "api.sqlite3"))


def create_account(client: TestClient, account_id: str) -> None:
    response = client.post(
        "/web/accounts",
        json={"account_id": account_id, "name": account_id},
    )
    assert response.status_code == 200, response.text


def put_source(
    client: TestClient,
    *,
    account_id: str,
    slug: str,
    expected_version: int,
    source: str,
    helpers: dict[str, str] | None = None,
):
    return client.put(
        f"/web/accounts/{account_id}/custom-components/{slug}/source",
        json={
            "expected_version": expected_version,
            "files": {f"{slug}.tsx": source, **(helpers or {})},
        },
    )


def compile_source(
    client: TestClient,
    *,
    account_id: str,
    slug: str,
    source_version: int,
):
    return client.post(
        f"/web/accounts/{account_id}/custom-components/{slug}/compile",
        json={"source_version": source_version},
    )


def test_valid_source_versions_compile_into_immutable_complete_artifacts(
    client: TestClient,
) -> None:
    create_account(client, "acc_alpha")
    created = put_source(
        client,
        account_id="acc_alpha",
        slug="pricing-card",
        expected_version=0,
        source=VALID_SOURCE,
    )
    assert created.status_code == 200, created.text
    first_source = created.json()["source"]
    assert first_source["source_version"] == 1
    assert first_source["entry_path"] == "pricing-card.tsx"
    assert first_source["snapshot"]["byte_length"] > 0

    read = client.get(
        "/web/accounts/acc_alpha/custom-components/pricing-card/source"
    )
    assert read.status_code == 200, read.text
    assert read.json()["files"]["pricing-card.tsx"] == VALID_SOURCE

    compiled = compile_source(
        client,
        account_id="acc_alpha",
        slug="pricing-card",
        source_version=1,
    )
    assert compiled.status_code == 200, compiled.text
    first = compiled.json()["artifact"]
    assert first["artifact_id"].startswith("ccart_")
    assert first["source"]["byte_length"] > 0
    assert first["bundle"]["byte_length"] > 0
    assert first["css"]["byte_length"] > 0
    assert first["first_frame"]["byte_length"] > 0
    manifest = first["manifest"]
    assert manifest["meta"] == {
        "name": "Pricing Card",
        "description": "A compact pricing callout.",
    }
    assert manifest["props_schema"]["properties"]["accent"]["enum"] == [
        "blue",
        "green",
    ]
    assert manifest["defaults"] == {
        "accent": "blue",
        "headline": "Pricing",
        "planCount": 3,
        "showBadge": True,
    }
    assert manifest["warnings"][0]["code"] == "CCW0203"

    exact_retry = compile_source(
        client,
        account_id="acc_alpha",
        slug="pricing-card",
        source_version=1,
    )
    assert exact_retry.status_code == 200, exact_retry.text
    assert exact_retry.json()["artifact"]["artifact_id"] == first["artifact_id"]

    second_source_text = VALID_SOURCE.replace(
        "showBadge?: boolean;",
        "showBadge?: boolean;\n  subtitle?: string;",
    ).replace(
        "showBadge = true",
        'showBadge = true,\n    subtitle = "Compare plans"',
    ).replace(
        "<p>{planCount} plans</p>",
        "<p>{subtitle}: {planCount} plans</p>",
    )
    updated = put_source(
        client,
        account_id="acc_alpha",
        slug="pricing-card",
        expected_version=1,
        source=second_source_text,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["source"]["source_version"] == 2
    second_compile = compile_source(
        client,
        account_id="acc_alpha",
        slug="pricing-card",
        source_version=2,
    )
    assert second_compile.status_code == 200, second_compile.text
    second = second_compile.json()["artifact"]
    assert second["artifact_id"] != first["artifact_id"]
    assert second["manifest"]["defaults"]["subtitle"] == "Compare plans"

    stale_compile = compile_source(
        client,
        account_id="acc_alpha",
        slug="pricing-card",
        source_version=1,
    )
    assert stale_compile.status_code == 409
    assert (
        stale_compile.json()["detail"]["code"]
        == "custom_component.source_version_conflict"
    )

    family = client.get(
        "/web/accounts/acc_alpha/custom-components/pricing-card"
    ).json()["component"]
    assert family["source_version"] == 2
    assert len(family["artifacts"]) == 2
    revisions = client.get(
        "/web/accounts/acc_alpha/custom-components/pricing-card/source-revisions"
    )
    assert [item["source_version"] for item in revisions.json()["revisions"]] == [
        2,
        1,
    ]
    compilations = client.get(
        "/web/accounts/acc_alpha/custom-components/pricing-card/compilations"
    )
    assert [item["status"] for item in compilations.json()["compilations"]] == [
        "succeeded",
        "succeeded",
        "succeeded",
    ]

    for member, expected in (
        ("bundle", b"export"),
        ("css", b".bg-primary"),
        ("first_frame", b"Pricing"),
        ("source", b'"schema_version":1'),
    ):
        response = client.get(
            f"/web/accounts/acc_alpha/custom-component-artifacts/"
            f"{first['artifact_id']}/{member}"
        )
        assert response.status_code == 200, response.text
        assert expected in response.content

    repository = HybridRepository(connect(client.app.state.database_path))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            repository.connection.execute(
                """
                UPDATE custom_component_artifacts
                SET manifest_json = '{}'
                WHERE artifact_id = ?
                """,
                (first["artifact_id"],),
            )
        repository.connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            repository.connection.execute(
                """
                UPDATE custom_component_source_revisions
                SET entry_path = 'changed.tsx'
                WHERE revision_id = ?
                """,
                (first_source["revision_id"],),
            )
        repository.connection.rollback()
        compilation_id = compiled.json()["compilation"]["compilation_id"]
        with pytest.raises(sqlite3.IntegrityError):
            repository.connection.execute(
                """
                UPDATE custom_component_compilations
                SET status = 'failed'
                WHERE compilation_id = ?
                """,
                (compilation_id,),
            )
        repository.connection.rollback()
    finally:
        repository.connection.close()


def test_curated_libraries_compile_inside_the_constrained_worker(
    client: TestClient,
) -> None:
    create_account(client, "acc_alpha")
    written = put_source(
        client,
        account_id="acc_alpha",
        slug="curated-chart",
        expected_version=0,
        source=CURATED_SOURCE,
    )
    assert written.status_code == 200, written.text
    compiled = compile_source(
        client,
        account_id="acc_alpha",
        slug="curated-chart",
        source_version=1,
    )
    assert compiled.status_code == 200, compiled.text
    artifact = compiled.json()["artifact"]
    assert artifact["manifest"]["curated_package_versions"] == {
        "@gsap/react": "2.1.2",
        "@visx/curve": "3.12.0",
        "@visx/group": "3.12.0",
        "@visx/scale": "3.12.0",
        "@visx/shape": "3.12.0",
        "gsap": "3.13.0",
        "motion": "12.23.12",
        "react": "18.3.1",
    }
    frame = client.get(
        f"/web/accounts/acc_alpha/custom-component-artifacts/"
        f"{artifact['artifact_id']}/first_frame"
    )
    assert frame.status_code == 200
    assert b"<svg" in frame.content


def test_deterministic_compile_failure_is_recorded_and_never_attachable(
    client: TestClient,
) -> None:
    create_account(client, "acc_alpha")
    invalid = """
import React from "react";
import unsafe from "lodash";
export default function Unsafe() {
  eval("1");
  return <div>{String(unsafe)}</div>;
}
"""
    written = put_source(
        client,
        account_id="acc_alpha",
        slug="unsafe-card",
        expected_version=0,
        source=invalid,
    )
    assert written.status_code == 200, written.text
    failed = compile_source(
        client,
        account_id="acc_alpha",
        slug="unsafe-card",
        source_version=1,
    )
    assert failed.status_code == 422, failed.text
    body = failed.json()
    assert body["artifact"] is None
    assert body["compilation"]["status"] == "failed"
    assert {item["code"] for item in body["compilation"]["diagnostics"]} >= {
        "CCC0106",
        "CCC0111",
    }
    family = client.get(
        "/web/accounts/acc_alpha/custom-components/unsafe-card"
    ).json()["component"]
    assert family["artifacts"] == []
    assert family["source_version"] == 1


def test_cross_component_import_pins_only_same_account_artifact(
    client: TestClient,
) -> None:
    create_account(client, "acc_alpha")
    create_account(client, "acc_beta")
    child_source = """
import React from "react";
export default function StatusBadge() {
  return <strong className="rounded bg-primary px-2">Ready</strong>;
}
"""
    assert (
        put_source(
            client,
            account_id="acc_alpha",
            slug="status-badge",
            expected_version=0,
            source=child_source,
        ).status_code
        == 200
    )
    child_compile = compile_source(
        client,
        account_id="acc_alpha",
        slug="status-badge",
        source_version=1,
    )
    assert child_compile.status_code == 200, child_compile.text
    child_artifact = child_compile.json()["artifact"]["artifact_id"]

    parent_source = """
import React from "react";
import Badge from "components/status-badge";
export default function Parent() { return <main><Badge /></main>; }
"""
    assert (
        put_source(
            client,
            account_id="acc_alpha",
            slug="parent-card",
            expected_version=0,
            source=parent_source,
        ).status_code
        == 200
    )
    parent_compile = compile_source(
        client,
        account_id="acc_alpha",
        slug="parent-card",
        source_version=1,
    )
    assert parent_compile.status_code == 200, parent_compile.text
    assert parent_compile.json()["artifact"]["manifest"][
        "dependency_artifacts"
    ] == {"status-badge": child_artifact}

    assert (
        put_source(
            client,
            account_id="acc_beta",
            slug="parent-card",
            expected_version=0,
            source=parent_source,
        ).status_code
        == 200
    )
    forbidden = compile_source(
        client,
        account_id="acc_beta",
        slug="parent-card",
        source_version=1,
    )
    assert forbidden.status_code == 422
    assert forbidden.json()["compilation"]["diagnostics"][0]["code"] == "CCC0105"
    assert (
        client.get(
            f"/web/accounts/acc_beta/custom-component-artifacts/{child_artifact}"
        ).status_code
        == 404
    )


def test_worker_crash_and_timeout_create_only_transient_attempts(
    client: TestClient, tmp_path: Path
) -> None:
    create_account(client, "acc_alpha")
    assert (
        put_source(
            client,
            account_id="acc_alpha",
            slug="resilient-card",
            expected_version=0,
            source=VALID_SOURCE.replace("PricingCard", "ResilientCard"),
        ).status_code
        == 200
    )
    original_node = client.app.state.custom_component_compiler_node_bin
    original_worker = client.app.state.custom_component_compiler_worker
    original_timeout = client.app.state.custom_component_compiler_timeout_seconds
    client.app.state.custom_component_compiler_node_bin = "false"
    crashed = compile_source(
        client,
        account_id="acc_alpha",
        slug="resilient-card",
        source_version=1,
    )
    assert crashed.status_code == 503, crashed.text
    assert crashed.json()["artifact"] is None
    assert crashed.json()["compilation"]["status"] == "transient_error"

    client.app.state.custom_component_compiler_node_bin = original_node
    client.app.state.custom_component_compiler_timeout_seconds = 0.0001
    timed_out = compile_source(
        client,
        account_id="acc_alpha",
        slug="resilient-card",
        source_version=1,
    )
    assert timed_out.status_code == 503, timed_out.text
    assert "exceeded" in timed_out.json()["compilation"]["diagnostics"][0]["message"]

    malformed_worker = tmp_path / "malformed-compiler.mjs"
    malformed_worker.write_text(
        'process.stdout.write(JSON.stringify({protocol_version:1,'
        'compiler_version:"fake",status:"success",diagnostics:[]}));'
    )
    client.app.state.custom_component_compiler_timeout_seconds = original_timeout
    client.app.state.custom_component_compiler_worker = malformed_worker
    malformed = compile_source(
        client,
        account_id="acc_alpha",
        slug="resilient-card",
        source_version=1,
    )
    assert malformed.status_code == 503, malformed.text
    assert malformed.json()["artifact"] is None

    client.app.state.custom_component_compiler_worker = original_worker
    family = client.get(
        "/web/accounts/acc_alpha/custom-components/resilient-card"
    ).json()["component"]
    assert family["artifacts"] == []
    recovered = compile_source(
        client,
        account_id="acc_alpha",
        slug="resilient-card",
        source_version=1,
    )
    assert recovered.status_code == 200, recovered.text


def test_source_paths_and_optimistic_versions_are_enforced(
    client: TestClient,
) -> None:
    create_account(client, "acc_alpha")
    invalid_slug = put_source(
        client,
        account_id="acc_alpha",
        slug="Invalid Slug",
        expected_version=0,
        source=VALID_SOURCE,
    )
    assert invalid_slug.status_code == 422
    escaped = client.put(
        "/web/accounts/acc_alpha/custom-components/pricing-card/source",
        json={
            "expected_version": 0,
            "files": {
                "pricing-card.tsx": VALID_SOURCE,
                "../escape.ts": "export const unsafe = true;",
            },
        },
    )
    assert escaped.status_code == 422
    assert escaped.json()["detail"]["code"] == "custom_component.source_invalid"

    first = put_source(
        client,
        account_id="acc_alpha",
        slug="pricing-card",
        expected_version=0,
        source=VALID_SOURCE,
    )
    assert first.status_code == 200
    stale = put_source(
        client,
        account_id="acc_alpha",
        slug="pricing-card",
        expected_version=0,
        source=VALID_SOURCE.replace("Pricing", "Changed"),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_version"] == 1
    current = client.get(
        "/web/accounts/acc_alpha/custom-components/pricing-card/source"
    ).json()
    assert current["source"]["source_version"] == 1
    assert current["files"]["pricing-card.tsx"] == VALID_SOURCE


def test_concurrent_source_compare_and_swap_has_exactly_one_winner(
    client: TestClient,
) -> None:
    create_account(client, "acc_alpha")
    database_path = client.app.state.database_path
    store_root = client.app.state.custom_component_store_root

    def write(label: str) -> str:
        repository = HybridRepository(connect(database_path))
        try:
            persist_custom_component_source_revision(
                repository,
                store_root,
                account_id="acc_alpha",
                slug="race-card",
                expected_version=0,
                files={
                    "race-card.tsx": (
                        'import React from "react"; '
                        f'export default function C(){{ return <div>{label}</div>; }}'
                    )
                },
                provenance={"kind": "concurrency_test", "label": label},
            )
            return "won"
        except CustomComponentSourceVersionConflict:
            return "conflict"
        finally:
            repository.connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(write, ["alpha", "beta"]))
    assert sorted(outcomes) == ["conflict", "won"]
    current = client.get(
        "/web/accounts/acc_alpha/custom-components/race-card/source"
    )
    assert current.status_code == 200, current.text
    assert current.json()["source"]["source_version"] == 1
    assert len(current.json()["files"]) == 1


def test_compile_overtaken_by_source_write_cannot_publish_stale_artifact(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_account(client, "acc_alpha")
    assert (
        put_source(
            client,
            account_id="acc_alpha",
            slug="race-card",
            expected_version=0,
            source=VALID_SOURCE.replace("PricingCard", "RaceCard"),
        ).status_code
        == 200
    )
    original_compile = main_module.compile_custom_component

    def compile_then_advance_source(**kwargs):
        result = original_compile(**kwargs)
        repository = HybridRepository(connect(client.app.state.database_path))
        try:
            persist_custom_component_source_revision(
                repository,
                client.app.state.custom_component_store_root,
                account_id="acc_alpha",
                slug="race-card",
                expected_version=1,
                files={
                    "race-card.tsx": VALID_SOURCE.replace(
                        "PricingCard", "RaceCard"
                    ).replace("Pricing", "New source")
                },
                provenance={"kind": "compile_race_test"},
            )
        finally:
            repository.connection.close()
        return result

    monkeypatch.setattr(
        main_module, "compile_custom_component", compile_then_advance_source
    )
    overtaken = compile_source(
        client,
        account_id="acc_alpha",
        slug="race-card",
        source_version=1,
    )
    assert overtaken.status_code == 409, overtaken.text
    assert overtaken.json()["detail"]["current_version"] == 2

    family = client.get(
        "/web/accounts/acc_alpha/custom-components/race-card"
    ).json()["component"]
    assert family["source_version"] == 2
    assert family["artifacts"] == []
    assert (
        client.get(
            "/web/accounts/acc_alpha/custom-components/race-card/compilations"
        ).json()["compilations"]
        == []
    )


def test_compiler_migration_replay_does_not_invent_source_or_artifacts(
    client: TestClient,
) -> None:
    create_account(client, "acc_alpha")
    assert (
        put_source(
            client,
            account_id="acc_alpha",
            slug="source-only",
            expected_version=0,
            source=VALID_SOURCE.replace("PricingCard", "SourceOnly"),
        ).status_code
        == 200
    )
    before = client.get(
        "/web/accounts/acc_alpha/custom-components/source-only/source"
    ).json()
    run_migrations(client.app.state.database_path)
    after = client.get(
        "/web/accounts/acc_alpha/custom-components/source-only/source"
    ).json()
    assert after == before
    component = client.get(
        "/web/accounts/acc_alpha/custom-components/source-only"
    ).json()["component"]
    assert component["source_version"] == 1
    assert component["artifacts"] == []
    assert (
        client.get(
            "/web/accounts/acc_alpha/custom-components/source-only/compilations"
        ).json()["compilations"]
        == []
    )

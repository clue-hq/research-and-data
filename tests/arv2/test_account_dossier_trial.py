"""Lossless record transfer, explicit failures and retry behavior of the isolated importer."""

import asyncio
import hashlib
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import account_dossier_trial as dossier  # noqa: E402

SOURCES = {"/evidence/example.json": {"source_id": str(uuid4()), "url": "https://example.test/a"}}


def entry(id="F001", **updates):
    return {
        "id": id,
        "topic": "An attributed workflow",
        "claim_type": "reported_statement",
        "finding": {
            "statement": "“Keep A | B exactly.”\nSecond line — with caveat.",
            "context": "One workflow, two steps.",
        },
        "source_paths": list(SOURCES),
        "attribution": "Named speaker",
        "time_context": "Publication date unknown",
        "qualifications": ["Reported, not verified"],
        "review": {"status": "supported", "reason": "Source passage"},
        "agent_interpretation": "Possible significance only",
        **updates,
    }


def document(*entries):
    return (
        "# Account dossier\n\n## Workflow\n"
        + "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
        + "\n"
    )


def test_parser_preserves_quotes_newlines_and_forward_links_without_silent_loss():
    original = entry()
    conflict = entry(
        "F002",
        review={
            "status": "potential_conflict",
            "reason": "Different period unclear",
            "conflicts_with": ["F001"],
        },
    )
    records, errors = dossier.inspect_dossier(document(conflict, original), SOURCES)
    assert not errors
    assert [r["entry"].id for r in records] == ["F001", "F002"]
    assert records[0]["entry"].finding == original["finding"]
    assert records[0]["section"] == "Workflow"
    rendered = dossier.render_dossier(records, SOURCES)
    assert "https://example.test/a" in rendered and rendered.index("F002") < rendered.index("F001")


def test_invalid_lines_duplicate_ids_unknown_sources_and_cycles_are_reported():
    bad = entry("F003", source_paths=["/evidence/missing.json"])
    records, errors = dossier.inspect_dossier(
        document(entry(), entry(), bad) + "Unstructured finding\n", SOURCES
    )
    assert not records and len(errors) == 4
    a = entry(
        review={"status": "potential_conflict", "reason": "Conflict", "conflicts_with": ["F002"]}
    )
    b = entry(
        "F002",
        review={"status": "potential_conflict", "reason": "Conflict", "conflicts_with": ["F001"]},
    )
    records, errors = dossier.inspect_dossier(document(a, b, entry("F004")), SOURCES)
    assert [r["entry"].id for r in records] == ["F004"]
    assert len(errors) == 2 and all("cyclic" in e["error"] for e in errors)


class FakeWriter:
    def __init__(self):
        self.sources, self.saved = SOURCES, []
        self.lock = asyncio.Lock()
        self.engine = SimpleNamespace(begin=self.transaction)

    @asynccontextmanager
    async def transaction(self):
        yield object()

    async def rows(self, conn):
        return self.saved

    async def write(self, conn, finding, *, dossier_entry):
        value = finding.model_dump(mode="json", exclude={"source_paths"})
        value["sources"] = [{"path": p, **self.sources[p]} for p in finding.source_paths]
        value["dossier_entry"] = dossier_entry
        for row in self.saved:
            if row["value_json"] == value:
                return {"claim_id": row["id"], "replayed": True}
        row = {"id": str(uuid4()), "value_json": value}
        self.saved.append(row)
        return {"claim_id": row["id"], "replayed": False}

    async def export(self):
        return self.saved


def test_import_roundtrip_all_statuses_forward_links_retry_and_changed_content(tmp_path):
    entries = [
        entry(),
        entry(
            "F002", review={"status": "duplicate", "reason": "Same finding", "duplicate_of": "F001"}
        ),
        entry(
            "F003",
            review={
                "status": "potential_conflict",
                "reason": "Conflicting",
                "conflicts_with": ["F001"],
            },
        ),
        entry(
            "F004",
            review={
                "status": "wrong_entity",
                "reason": "Namesake",
                "expected_entity": {"name": "Other"},
            },
        ),
        entry("F005", review={"status": "insufficient_context", "reason": "Missing speaker"}),
    ]
    path = tmp_path / "dossier.entries.md"
    path.write_text(document(*reversed(entries)))
    writer = FakeWriter()
    first = asyncio.run(dossier.import_dossier(writer, tmp_path))
    assert first["stored"] == 5 and not first["errors"]
    assert first["dossier_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert all(
        c["content_and_metadata_equal"] and c["source_ids_equal"] and c["section_equal"]
        for c in first["roundtrip_checks"]
    )
    again = asyncio.run(dossier.import_dossier(writer, tmp_path))
    assert len(writer.saved) == 5 and all(e["replayed"] for e in again["entries"])
    path.write_text(document(entry(finding="Changed assertion")))
    changed = asyncio.run(dossier.import_dossier(writer, tmp_path))
    assert changed["stored"] == 0 and len(writer.saved) == 5
    assert "no implicit correction" in changed["errors"][0]["error"]


def test_partial_import_records_malformed_entry_in_receipt_without_dropping_valid_findings(
    tmp_path,
):
    (tmp_path / "dossier.entries.md").write_text(document(entry()) + "{bad json}\n")
    result = asyncio.run(dossier.import_dossier(FakeWriter(), tmp_path))
    assert result["stored"] == 1 and len(result["errors"]) == 1
    assert result["errors"][0]["line"] == 5

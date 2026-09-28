"""Person formation retains public biography and saved evidence without acquisition."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from live_account_dossier import finish_live, save_section  # noqa: E402
from trial_person_dossier import prepare, reconstruct_source  # noqa: E402


def test_person_preparation_keeps_sources_and_biography_excludes_comparison_answers(tmp_path):
    source, out = tmp_path / "original", tmp_path / "replay"
    inputs = source / "inputs"
    (inputs / "research/claims").mkdir(parents=True)
    (inputs / "research/claims/0.json").write_text('{"old":"OLD_CLAIM"}')
    (source / "COMPARISON.md").write_text("BENCHMARK_ANSWER")
    (source / "findings.md").write_text("# Person research\nA public personal project.")
    (inputs / "research/context.json").write_text(
        json.dumps(
            {
                "run_date": "2026-09-24",
                "person_assignment": {"name": "Alex", "linkedin_url": "https://example.test/alex"},
            }
        )
    )
    for name in ("person-brief.md", "account-findings.md", "delegation-brief.md"):
        (inputs / name).write_text("Original brief/context")
    sid = "00000000-0000-0000-0000-000000000001"
    (inputs / "evidence/index").mkdir(parents=True)
    (inputs / "evidence/index/0.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "source_id": sid,
                        "kind": "web_snapshot",
                        "source_url": "https://example.test/alex",
                        "origin_locator": "result/0",
                        "metadata": {},
                        "available": True,
                    }
                ]
            }
        )
    )
    page_dir = inputs / "evidence" / sid
    page_dir.mkdir()
    for start, value in [(0, "Hello "), (6, "world")]:
        (page_dir / f"{start}.json").write_text(
            json.dumps(
                {
                    "start": start,
                    "total_chars": 11,
                    "text_segments": [{"start": start, "text": value}],
                }
            )
        )
    prepare(source, out)
    assert (out / "source-bodies" / f"{sid}.txt").read_text() == "Hello world"
    skill = (out / "inputs/.deepagent/skills/claim-ready-person-dossier/SKILL.md").read_text()
    assert "Interests and public personal life" in skill
    assert "Unrelated personal biography belongs in coverage notes" not in skill
    assert "review the actual saved dossier" in skill
    exposed = "".join(p.read_text() for p in (out / "inputs").rglob("*") if p.is_file())
    assert "BENCHMARK_ANSWER" not in exposed and "OLD_CLAIM" not in exposed
    assert json.loads((out / "trial-manifest.json").read_text())["acquisition_enabled"] is False
    rows = json.loads((out / "source-manifest.json").read_text())
    value = {
        "id": "F001",
        "topic": "Project",
        "claim_type": "reported_statement",
        "finding": "Hello world",
        "source_paths": [rows[0]["path"]],
        "review": {"status": "supported", "reason": "Public statement"},
    }
    saved = save_section(out, rows, "Outside work", [value])
    assert saved["path"] == "/scratch/person-dossier.json"
    assert finish_live(out, rows, "Saved", [])["finished"]
    assert (out / "dossier.json").exists()
    assert (out / "dossier.readable.md").read_text().startswith("# Person dossier")
    (page_dir / "6.json").unlink()
    with pytest.raises(ValueError, match="Incomplete"):
        reconstruct_source(inputs, sid)

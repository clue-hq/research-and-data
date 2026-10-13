"""The research-run comparison's pure aggregation (no database, no Langfuse)."""

from scripts.compare_research_runs import render, summarise


def job(account, subject, cost, **extra):
    return {
        "job_id": f"{account}-{subject}-{cost}",
        "account": account,
        "subject_type": subject,
        "status": "completed",
        "cost_usd": cost,
        "model_rounds": 10,
        "tool_calls": 20,
        "wall_s": 600.0,
        "start_delay_s": 30.0 if subject == "person" else None,
        "page_writer_calls": {},
        "tool_errors": {},
        "sections": {},
        "claims": {},
        **extra,
    }


ROWS = [
    job(
        "Dialpad",
        "account",
        4.0,
        page_writer_calls={"account": 2},
        tool_errors={"search_evidence": 1},
        sections={"Leadership": 5, "Hiring": 3},
        claims={"supported": 7},
    ),
    job(
        "Dialpad",
        "person",
        3.5,
        start_delay_s=95.0,
        page_writer_calls={"contact": 1},
        tool_errors={"search_evidence": 2, "save_dossier_section": 1},
        claims={"supported": 2, "unresolved": 1},
    ),
    job("Loopio", "account", 5.0, status="needs_review", page_writer_calls={"account": 1}),
]


def test_accounts_add_up_their_jobs():
    summary = summarise(ROWS)
    dialpad = summary["accounts"]["Dialpad"]
    assert dialpad["jobs"] == 2 and dialpad["cost_usd"] == 7.5
    assert dialpad["model_rounds"] == 20 and dialpad["tool_calls"] == 40
    assert dialpad["page_writer_calls"] == {"account": 2, "contact": 1}
    assert dialpad["tool_errors"] == {"search_evidence": 3, "save_dossier_section": 1}
    assert dialpad["claims"] == {"supported": 9, "unresolved": 1}
    assert dialpad["findings"] == 8
    # The slowest contact start is the one that matters for "contacts start at nomination".
    assert dialpad["max_start_delay_s"] == 95.0
    assert summary["accounts"]["Loopio"]["statuses"] == {"needs_review": 1}
    assert summary["total"]["cost_usd"] == 12.5 and summary["total"]["jobs"] == 3
    assert summary["total"]["cost_per_account"] == 6.25


def test_an_account_with_no_people_has_no_start_delay():
    assert summarise(ROWS)["accounts"]["Loopio"]["max_start_delay_s"] is None


def test_the_table_names_both_sides_and_every_account():
    text = render({"before": summarise(ROWS), "after": summarise(ROWS[:1])})
    assert "before" in text and "after" in text
    assert "Dialpad" in text and "Loopio" in text


def test_tool_errors_count_only_failed_tool_observations():
    from scripts.compare_research_runs import tool_errors

    observations = [
        {"type": "TOOL", "name": "search_evidence", "level": "ERROR"},
        {"type": "TOOL", "name": "search_evidence", "level": "DEFAULT"},
        {"type": "TOOL", "name": "save_dossier_section", "level": "ERROR"},
        {"type": "GENERATION", "name": "model", "level": "ERROR"},
    ]
    assert tool_errors(observations) == {"search_evidence": 1, "save_dossier_section": 1}

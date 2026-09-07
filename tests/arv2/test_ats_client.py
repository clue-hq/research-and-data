"""Unit tests for the parts of the ATS client that never touch a socket.

Global Constraint 3 makes every *fetch* live; detection and normalisation are pure functions over
strings, so they are tested against HTML and JSON written inline here. The strings are not
fixtures standing in for a provider — they are the shapes the live probe actually returned
(``jobs.ashbyhq.com/probook/<uuid>``, Greenhouse's entity-escaped ``content``, Lever's bare
array), reduced to the smallest form that still exercises the rule under test.
"""

from __future__ import annotations

import json
from datetime import date

from clue_api.arv2.ats_client import (
    AtsBoard,
    board_url,
    career_page_candidates,
    detect_boards,
    html_to_text,
    normalise_postings,
)

PAGE = "https://example.com/careers"


def test_every_documented_board_url_form_is_detected() -> None:
    """The eight link shapes the brief enumerates, each yielding its own published slug."""
    html = """
    <a href="https://jobs.ashbyhq.com/acme-security/1234">Ashby board</a>
    <a href="https://api.ashbyhq.com/posting-api/job-board/acme-api?includeCompensation=true">x</a>
    <a href="https://boards.greenhouse.io/acmeboards">Greenhouse</a>
    <a href="https://job-boards.greenhouse.io/acmejobboards/jobs/4331918009">Greenhouse new</a>
    <a href="https://boards-api.greenhouse.io/v1/boards/acmeapi/jobs?content=true">gh api</a>
    <script src="https://boards.greenhouse.io/embed/job_board/js?for=acmeembed"></script>
    <a href="https://jobs.lever.co/acmelever">Lever</a>
    <a href="https://api.lever.co/v0/postings/acmeleverapi?mode=json">lever api</a>
    """

    found = {(board.kind, board.slug) for board in detect_boards(html, PAGE)}

    assert found == {
        ("ashby", "acme-security"),
        ("ashby", "acme-api"),
        ("greenhouse", "acmeboards"),
        ("greenhouse", "acmejobboards"),
        ("greenhouse", "acmeapi"),
        ("greenhouse", "acmeembed"),
        ("lever", "acmelever"),
        ("lever", "acmeleverapi"),
    }


def test_a_page_that_names_no_board_yields_nothing() -> None:
    """The rule the module exists for: no published slug means no board, never a guess.

    A company named in the page is not a slug. If this ever returned ``[{'ashby', 'acme'}]`` the
    lane would be back to the smoke test's eight 404s.
    """
    html = '<h1>Careers at Acme</h1><a href="/jobs">See our open roles at Acme</a>'

    assert detect_boards(html, PAGE) == []


def test_a_routing_segment_is_never_mistaken_for_a_slug() -> None:
    """``boards.greenhouse.io/embed/job_board?for=acme`` names ``acme``, not ``embed``."""
    html = '<iframe src="https://boards.greenhouse.io/embed/job_board?for=realslug"></iframe>'

    assert [(b.kind, b.slug) for b in detect_boards(html, PAGE)] == [("greenhouse", "realslug")]


def test_the_posting_id_after_a_slug_is_not_taken_as_a_second_board() -> None:
    """A board named eleven times, once per posting, is one board — and the uuid is not a slug."""
    html = "".join(
        f'<a href="https://jobs.ashbyhq.com/probook/{uuid}">Role {index}</a>'
        for index, uuid in enumerate(
            ["05516a84-77e4-4e2b-9686-49913e019c04", "3ebb77ba-f6d5-4e33-a96e-a0f09534c151"]
        )
    )

    boards = detect_boards(html, PAGE)

    assert [(b.kind, b.slug, b.source_url) for b in boards] == [("ashby", "probook", PAGE)]


def test_a_slug_serialised_into_a_script_payload_is_still_read() -> None:
    """Framework payloads escape their slashes; a slug published there is published all the same."""
    html = (
        '<script>self.__next_f.push([1,"{\\"url\\":\\"https:\\/\\/jobs.ashbyhq.com\\/zafran-'
        'security\\/embed?version=2\\"}"])</script>'
        "<span>&#x2F;&#x2F;api.lever.co&#x2F;v0&#x2F;postings&#x2F;entity-co?mode=json</span>"
    )

    assert [(b.kind, b.slug) for b in detect_boards(html, PAGE)] == [
        ("ashby", "zafran-security"),
        ("lever", "entity-co"),
    ]


def test_a_lookalike_host_cannot_borrow_a_real_hosts_pattern() -> None:
    """``notjobs.lever.co.evil.com`` is not Lever, and ``boards-api`` is not ``boards``."""
    html = (
        '<a href="https://notjobs.lever.co.evil.com/phishing">x</a>'
        '<a href="https://myboards.greenhouse.io.attacker.net/nope">y</a>'
    )

    assert detect_boards(html, PAGE) == []


def test_career_candidates_put_the_evidenced_links_first_and_cap_at_six() -> None:
    """A link this company published outranks a path guessed about companies in general.

    With five fixed paths under a six-page cap, ordering the guesses first meant at most one
    evidenced link was ever tried — and the evidenced link is the one that finds a board published
    somewhere unconventional (probook.ai serves its careers page from ``/company``). Assets and
    off-site links are still dropped, and the cap is still six.
    """
    html = """
    <a href="/company#open-roles">Careers</a>
    <a href="/v5/careers-office.jpg">image</a>
    <a href="https://linkedin.com/company/acme/jobs">off-site jobs</a>
    <a href="/work-with-us">Jobs and life at Acme</a>
    """

    candidates = career_page_candidates(html, "https://acme.com/")

    assert candidates == [
        "https://acme.com/company",
        "https://acme.com/work-with-us",
        "https://acme.com/careers",
        "https://acme.com/careers/",
        "https://acme.com/jobs",
        "https://acme.com/company/careers",
    ]


def test_an_evidenced_link_at_a_conventional_path_is_not_listed_twice() -> None:
    """The two lists overlap far more often than they compete, and the overlap dedupes.

    The common case — a homepage that links ``/careers`` — must not spend two of its six slots on
    the same URL just because both the evidence and the guess name it.
    """
    candidates = career_page_candidates('<a href="/careers">Careers</a>', "https://acme.com/")

    assert candidates[0] == "https://acme.com/careers"
    assert candidates.count("https://acme.com/careers") == 1
    assert len(candidates) == 5


def test_a_careers_link_is_found_by_its_text_when_its_path_says_nothing() -> None:
    """probook.ai's real shape: the only route to its board is an anchor reading "Careers"."""
    html = '<a href="/company#open-roles">Careers</a>'

    assert "https://probook.ai/company" in career_page_candidates(html, "https://probook.ai")


def test_board_urls_are_the_three_pinned_endpoints() -> None:
    assert board_url(AtsBoard("ashby", "zafran-security", PAGE)) == (
        "https://api.ashbyhq.com/posting-api/job-board/zafran-security?includeCompensation=true"
    )
    assert board_url(AtsBoard("greenhouse", "translucent", PAGE)) == (
        "https://boards-api.greenhouse.io/v1/boards/translucent/jobs?content=true"
    )
    assert board_url(AtsBoard("lever", "smarsh", PAGE)) == (
        "https://api.lever.co/v0/postings/smarsh?mode=json"
    )


def test_an_ashby_posting_normalises_including_its_compensation_tier() -> None:
    payload = json.loads(
        """
        {"apiVersion": "1", "jobs": [{
          "title": "Regional Sales Manager (United Kingdom)",
          "department": "Sales", "team": "Sales", "location": "EMEA Remote",
          "publishedAt": "2026-06-13T03:10:46.952+00:00", "isListed": true,
          "compensation": {"compensationTierSummary": "$180K – $220K"},
          "descriptionPlain": "Description:\\n\\nZafran is on a mission.",
          "jobUrl": "https://jobs.ashbyhq.com/zafran-security/2270",
          "applyUrl": "https://jobs.ashbyhq.com/zafran-security/2270/application"
        }]}
        """
    )

    (posting,) = normalise_postings(
        AtsBoard("ashby", "zafran-security", PAGE), payload, today=date(2026, 9, 7)
    )

    assert posting.title == "Regional Sales Manager (United Kingdom)"
    assert (posting.department, posting.team, posting.location) == (
        "Sales",
        "Sales",
        "EMEA Remote",
    )
    assert posting.published_at == date(2026, 6, 13)
    assert posting.days_open == 86
    assert posting.is_listed is True
    assert posting.compensation == "$180K – $220K"
    assert posting.description_plain is not None and "Zafran is on a mission" in (
        posting.description_plain
    )
    assert posting.url == "https://jobs.ashbyhq.com/zafran-security/2270"
    assert posting.apply_url == "https://jobs.ashbyhq.com/zafran-security/2270/application"
    assert posting.provider_fields["publishedAt"] == "2026-06-13T03:10:46.952+00:00"


def test_an_ashby_posting_with_no_published_compensation_reports_none_not_a_guess() -> None:
    """Zafran's live board: the ``compensation`` object exists and every tier in it is null."""
    payload = {
        "jobs": [
            {
                "title": "Backend Engineer",
                "compensation": {"compensationTierSummary": None, "compensationTiers": []},
            }
        ]
    }

    (posting,) = normalise_postings(AtsBoard("ashby", "acme", PAGE), payload)

    assert posting.compensation is None
    assert posting.published_at is None
    assert posting.days_open is None


#: Exactly how Greenhouse serves a description: the HTML itself is entity-escaped, and the
#: entities inside the text (``&amp;nbsp;``) are therefore escaped twice over.
GREENHOUSE_CONTENT = (
    "&lt;p&gt;&lt;strong&gt;Role Details&lt;/strong&gt;&lt;/p&gt;\n"
    "&lt;ul&gt;&lt;li&gt;Full-Time&amp;nbsp;&lt;/li&gt;&lt;/ul&gt;"
)


def test_a_greenhouse_posting_unescapes_its_content_and_reads_first_published() -> None:
    """``content`` arrives entity-escaped; ``first_published`` beats ``updated_at`` for age."""
    payload = {
        "jobs": [
            {
                "title": "AI Engineer",
                "absolute_url": "https://job-boards.greenhouse.io/translucent/jobs/4331918009",
                "location": {"name": "New York City, New York"},
                "updated_at": "2026-08-13T15:27:12-04:00",
                "first_published": "2026-07-27T09:22:00-04:00",
                "departments": [
                    {"id": 1, "name": "Engineering", "parent_id": None},
                    {"id": 2, "name": "Applied AI", "parent_id": 1},
                ],
                "content": GREENHOUSE_CONTENT,
            }
        ],
        "meta": {"total": 1},
    }

    (posting,) = normalise_postings(
        AtsBoard("greenhouse", "translucent", PAGE), payload, today=date(2026, 9, 7)
    )

    assert posting.title == "AI Engineer"
    assert (posting.department, posting.team) == ("Engineering", "Applied AI")
    assert posting.location == "New York City, New York"
    assert posting.published_at == date(2026, 7, 27)
    assert posting.days_open == 42
    assert posting.is_listed is None, "Greenhouse states nothing about listing, so neither do we"
    assert posting.description_plain == "Role Details\n\nFull-Time"
    assert posting.url == "https://job-boards.greenhouse.io/translucent/jobs/4331918009"


def test_a_greenhouse_posting_falls_back_to_updated_at_and_renders_pay_bands() -> None:
    payload = {
        "jobs": [
            {
                "title": "Recruiter",
                "updated_at": "2026-08-13T15:27:12-04:00",
                "pay_input_ranges": [
                    {
                        "title": "Base",
                        "min_cents": 12000000,
                        "max_cents": 15000000,
                        "currency_type": "USD",
                    }
                ],
            }
        ]
    }

    (posting,) = normalise_postings(
        AtsBoard("greenhouse", "acme", PAGE), payload, today=date(2026, 9, 7)
    )

    assert posting.published_at == date(2026, 8, 13)
    assert posting.compensation == "Base: 120,000–150,000 USD"


def test_a_lever_board_is_a_bare_array_with_millisecond_dates() -> None:
    """Lever's envelope is the odd one out: no ``jobs`` key, the whole body is the array."""
    payload = json.loads(
        """
        [{
          "text": "Customer Success Manager, Corp 3",
          "categories": {"department": "Divisions", "team": "Customer Success",
                         "location": "Portland", "commitment": "Full-Time"},
          "createdAt": 1788357976335,
          "salaryRange": {"currency": "USD", "interval": "per-year-salary",
                          "min": 80000, "max": 100000},
          "descriptionPlain": "Who are we?\\n\\nSmarsh empowers its customers.",
          "hostedUrl": "https://jobs.lever.co/smarsh/fd2e258f",
          "applyUrl": "https://jobs.lever.co/smarsh/fd2e258f/apply"
        }]
        """
    )

    (posting,) = normalise_postings(
        AtsBoard("lever", "smarsh", PAGE), payload, today=date(2026, 9, 7)
    )

    assert posting.title == "Customer Success Manager, Corp 3"
    assert (posting.department, posting.team, posting.location) == (
        "Divisions",
        "Customer Success",
        "Portland",
    )
    assert posting.published_at == date(2026, 9, 2)
    assert posting.days_open == 5
    assert posting.compensation == "USD 80,000–100,000 (per-year-salary)"
    assert posting.description_plain is not None and posting.description_plain.startswith(
        "Who are we?"
    )
    assert posting.url == "https://jobs.lever.co/smarsh/fd2e258f"
    assert posting.apply_url == "https://jobs.lever.co/smarsh/fd2e258f/apply"


def test_a_lever_posting_without_a_salary_range_reports_none() -> None:
    (posting,) = normalise_postings(
        AtsBoard("lever", "smarsh", PAGE), [{"text": "Engineer", "salaryRange": {}}]
    )

    assert posting.compensation is None
    assert posting.team is None


def test_a_future_publication_date_floors_days_open_at_zero() -> None:
    """ "Open for -3 days" is not a fact about anything; a scheduled req reads as brand new."""
    payload = {"jobs": [{"title": "Scheduled", "publishedAt": "2026-09-10T00:00:00+00:00"}]}

    (posting,) = normalise_postings(
        AtsBoard("ashby", "acme", PAGE), payload, today=date(2026, 9, 7)
    )

    assert posting.days_open == 0


def test_an_unparseable_or_missing_envelope_yields_no_postings_rather_than_raising() -> None:
    board = AtsBoard("greenhouse", "acme", PAGE)

    assert normalise_postings(board, {"meta": {"total": 0}}) == ()
    assert normalise_postings(board, {"jobs": ["not-an-object", 7]}) == ()
    assert normalise_postings(board, "a bare string") == ()


def test_html_to_text_keeps_block_boundaries_and_resolves_entities() -> None:
    raw = "<p>Role <strong>Details</strong></p><ul><li>Full-Time&nbsp;</li><li>NYC</li></ul>"

    assert html_to_text(raw) == "Role Details\nFull-Time\nNYC"

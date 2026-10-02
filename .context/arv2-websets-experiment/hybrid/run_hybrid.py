"""Hybrid discovery proof of concept (R4 §2–§3 as ruled 2026-09-10).

Step one: ONE Exa webset builds the long list (35 companies, entity=company, the three criteria a
public page can answer, the stage criterion written as "most recent round").
Step two: OUR probe grades every company on all four ICP hard gates, in code, with references:
  stage      — one cheap Exa search (highlights only, $0.007), most recent labelled round + date
  geography  — the Websets headquarters field, cross-checked against the probe's datelines
  hiring     — the company's own ATS board (repo `ats_client` pure helpers; free HTTP), GTM titles
  intent     — the ICP's Q1/Q7 signals read from the GTM postings' text, quoted
  exclusions — employees > 800 from the Websets snapshot
Fit = passes / gates with an unclear gate as half a pass; Overall fit bands are the accounts list's
own (High ≥ 0.70, Medium ≥ 0.40). No enrichment. Everything raw is saved; every paid call is on the
ledger.

Usage:  set -a; source .env; set +a; uv run python .context/arv2-websets-experiment/hybrid/run_hybrid.py
        (add `--webset <id>` to skip step one and grade an existing webset)
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from exa_common import ICP_TEXT, ledger_append, request, save_raw  # noqa: E402

from clue_api.arv2.ats_client import (  # noqa: E402
    AtsBoard,
    board_url,
    career_page_candidates,
    detect_boards,
    normalise_postings,
)

BASE = "https://api.exa.ai/websets/v0/websets"
TODAY = date(2026, 9, 10)
COUNT = 35
WINDOW_MONTHS = 24
GATES = ("stage", "geography", "hiring", "intent")
HIGH, MEDIUM = 0.70, 0.40  # CLUE_ARV2_FIT_HIGH_THRESHOLD / _MEDIUM_THRESHOLD defaults
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

CRITERIA = [
    "Company is headquartered in the United States",
    "Company's most recent funding round is a Series A or Series A extension, announced within "
    "the last 24 months (not seed, not pre-seed, not Series B or later, not a growth round)",
    "Company sells B2B software or AI to independent small businesses in one fragmented vertical "
    "such as dental practices, veterinary clinics, HVAC and plumbing contractors, auto repair "
    "shops, law firms, pharmacies, restaurants or trucking",
]

GTM_TITLE = re.compile(
    r"\b(sales|account executive|\bAE\b|SDR|BDR|sales development|business development|marketing|"
    r"growth|demand gen|demand generation|partnerships?|revenue operations|rev ?ops|go-to-market|GTM|"
    r"ABM|account-based)\b",
    re.I,
)
TIER1 = re.compile(
    r"(outbound|list[- ]building|build(ing)? (target|prospect|account) lists?|prospect(ing)? lists?|"
    r"target accounts?|named accounts?|account research|account-based|ABM)",
    re.I,
)
NON_US_DATELINE = re.compile(
    r"\b(BENGALURU|BANGALORE|MUMBAI|LONDON|PARIS|BERLIN|TEL AVIV|TORONTO|SYDNEY|SINGAPORE|DUBLIN|"
    r"AMSTERDAM|STOCKHOLM|Israeli|India-based|UK-based|Canadian|European)\b"
)
ANNOUNCEMENT = re.compile(r"(raises?|raised|secures?|closes?|lands?|announces?|funding|series [a-e]|seed|investing in|leads?)", re.I)
PROFILE_HOST = re.compile(r"(linkedin\.com|cbinsights\.com|tracxn\.com|crunchbase\.com|pitchbook\.com|zoominfo|craft\.co)", re.I)
ROUND = re.compile(
    r"(pre-?seed|seed|series\s?[a-e](?:-\d|\s?extension|\s?ext\b|\+)?|growth round|series\s?[a-e]\s?round)",
    re.I,
)


@dataclass
class Verdict:
    gate: str
    verdict: str  # pass | fail | unclear
    reason: str
    references: list[str] = field(default_factory=list)


@dataclass
class Graded:
    name: str
    url: str
    domain: str
    hq: str
    employees: int | None
    websets_says: str
    verdicts: list[Verdict]
    fit: float
    band: str
    disposition: str
    probe_cost_usd: float
    gtm_postings: int
    board: str | None


# ----------------------------------------------------------------------------------------------
# step one — the webset


def create_webset() -> str:
    body = {
        "title": "ARV2 R4 hybrid PoC 2026-09-10",
        "externalId": f"arv2-r4-hybrid-{int(time.time())}",
        "search": {
            "query": ICP_TEXT,
            "count": COUNT,
            "entity": {"type": "company"},
            "criteria": [{"description": c} for c in CRITERIA],
        },
    }
    status, out = request("POST", BASE, body)
    out["_request"] = body
    save_raw("hybrid_webset_create", out)
    ledger_append({"arm": "H", "provider": "exa_websets", "label": "create", "http": status,
                   "webset_id": out.get("id")})
    if status not in (200, 201):
        raise SystemExit(f"create failed: {json.dumps(out)[:600]}")
    print(f"webset {out['id']} created", flush=True)
    return out["id"]


def poll(webset_id: str) -> dict:
    started = time.monotonic()
    while True:
        _, out = request("GET", f"{BASE}/{webset_id}")
        search = (out.get("searches") or [{}])[0]
        prog = search.get("progress") or {}
        elapsed = int(time.monotonic() - started)
        print(f"  t={elapsed}s {out.get('status')} found={prog.get('found')} analyzed={prog.get('analyzed')}",
              flush=True)
        if out.get("status") == "idle" or elapsed > 1800:
            save_raw("hybrid_webset_final", out)
            ledger_append({"arm": "H", "provider": "exa_websets", "label": "final",
                           "found": prog.get("found"), "analyzed": prog.get("analyzed"),
                           "time_to_idle_s": elapsed})
            return out
        time.sleep(15)


def items(webset_id: str) -> list[dict]:
    rows: list[dict] = []
    cursor = None
    while True:
        url = f"{BASE}/{webset_id}/items?limit=100" + (f"&cursor={cursor}" if cursor else "")
        _, out = request("GET", url)
        rows.extend(out.get("data") or [])
        if not out.get("hasMore"):
            break
        cursor = out.get("nextCursor")
    save_raw("hybrid_webset_items", rows)
    green = sum(1 for r in rows if all(e.get("satisfied") == "yes" for e in r.get("evaluations") or []))
    ledger_append({"arm": "H", "provider": "exa_websets", "label": "items", "items": len(rows),
                   "all_green": green, "credits_est": green * 10})
    return rows


# ----------------------------------------------------------------------------------------------
# step two — the probe


def host(url: str | None) -> str:
    h = (urlsplit(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def http_get(url: str, timeout: int = 12) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(1_500_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, ""
    except Exception as err:  # noqa: BLE001 — a PoC records the failure, it does not crash on it
        return 0, f"{type(err).__name__}: {err}"


def _norm(label: str) -> str:
    return re.sub(r"\s+", " ", label.lower()).replace("series a round", "series a").replace("series b round", "series b")


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def stage_probe(name: str, url: str, slug: str) -> tuple[Verdict, float]:
    payload = {
        "query": f"{name} ({url}) funding round Series A Series B raises announcement",
        "type": "auto",
        "numResults": 6,
        "startPublishedDate": "2024-03-01T00:00:00.000Z",
        "contents": {"highlights": {"numSentences": 2, "highlightsPerUrl": 1}},
    }
    cached = HERE.parent / "raw" / f"hybrid_probe_{slug}.json"
    if cached.exists():
        out = json.loads(cached.read_text())
        cost = 0.0  # already paid and ledgered on the first pass; the raw file is the record
    else:
        status, out = request("POST", "https://api.exa.ai/search", payload)
        out["_request"] = payload
        save_raw(f"hybrid_probe_{slug}", out)
        cost = float((out.get("costDollars") or {}).get("total") or 0)
        ledger_append({"arm": "H", "provider": "exa_search", "label": f"stage_{slug}", "http": status, "cost_usd": cost})
    # Every labelled round mention, with the article's date. The verdict is decided by the MOST
    # RECENT date group, and inside that group by majority vote across articles (a title mention
    # counts three times): a Series A announced together with its seed is a Series A, and one
    # stray "Series B" in a profile's boilerplate does not outvote five articles saying Series A.
    # Only ANNOUNCEMENTS decide the date: a profile page (LinkedIn, CB Insights, Tracxn) is dated
    # when it was crawled, not when the round happened, and its boilerplate repeats every old round
    # label — BeyondTrucks' Series A of 2024-10 was outvoted by a 2026 LinkedIn page saying "seed".
    # Profile pages count only when no announcement was found at all.
    results = out.get("results") or []
    announcements = [r for r in results if ANNOUNCEMENT.search(r.get("title") or "") and not PROFILE_HOST.search(host(r.get("url")))]

    def _labelled(rows: list) -> bool:
        return any(ROUND.search(" ".join([r.get("title") or "", *(r.get("highlights") or [])])) for r in rows)

    pool = announcements if _labelled(announcements) else results
    by_date: dict[date, dict[str, int]] = {}
    refs: dict[date, str] = {}
    for res in pool:
        title = res.get("title") or ""
        body = " ".join(res.get("highlights") or [])
        pub = (res.get("publishedDate") or "")[:10]
        try:
            when = date.fromisoformat(pub)
        except ValueError:
            continue
        votes = by_date.setdefault(when, {})
        for m in ROUND.finditer(title):
            votes[_norm(m.group(0))] = votes.get(_norm(m.group(0)), 0) + 3
        for m in ROUND.finditer(body):
            votes[_norm(m.group(0))] = votes.get(_norm(m.group(0)), 0) + 1
        refs.setdefault(when, res.get("url") or "")
    by_date = {d: v for d, v in by_date.items() if v}
    if not by_date:
        return Verdict("stage", "unclear", "no labelled round found in the probe's highlights"), cost
    when = max(by_date)
    votes = by_date[when]
    label = max(votes, key=votes.get)
    ref = refs[when]
    is_a = label.startswith("series a")
    later = bool(re.match(r"series\s?[b-e]", label)) or "growth" in label
    early = "seed" in label
    age = months_between(when, TODAY)
    if is_a and age <= WINDOW_MONTHS:
        return Verdict("stage", "pass", f"most recent labelled round '{label}' on {when} ({age} months ago; votes {votes})", [ref]), cost
    if later:
        return Verdict("stage", "fail", f"most recent labelled round '{label}' on {when} — past Series A", [ref]), cost
    if early:
        return Verdict("stage", "fail", f"most recent labelled round '{label}' on {when} — before Series A", [ref]), cost
    if is_a:
        return Verdict("stage", "fail", f"Series A on {when} is {age} months old (window {WINDOW_MONTHS})", [ref]), cost
    return Verdict("stage", "unclear", f"latest label '{label}' on {when} could not be classified"), cost


def geography_verdict(item: dict, probe_slug: str) -> Verdict:
    co = (item.get("properties") or {}).get("company") or {}
    hq = co.get("headquarters") or {}
    code = hq.get("countryCode")
    probe = json.loads((HERE.parent / "raw" / f"hybrid_probe_{probe_slug}.json").read_text())
    datelines = []
    for res in probe.get("results") or []:
        text = " ".join(res.get("highlights") or [])
        m = NON_US_DATELINE.search(text)
        if m:
            datelines.append(f"{m.group(0)} ({host(res.get('url'))})")
    if code == "US" and not datelines:
        return Verdict("geography", "pass", f"Websets headquarters {hq.get('city')}, {hq.get('state')}, US; no non-US dateline in the probe")
    if code == "US" and datelines:
        return Verdict("geography", "unclear", f"Websets says US but the probe carries a non-US dateline: {'; '.join(datelines[:2])}")
    if code:
        return Verdict("geography", "fail", f"Websets headquarters country {code}")
    return Verdict("geography", "unclear", "no headquarters in the snapshot")


def find_board(homepage_url: str, slug: str) -> tuple[AtsBoard | None, str]:
    status, html = http_get(homepage_url)
    if status != 200:
        return None, f"homepage fetch {status}"
    boards = detect_boards(html, homepage_url)
    if boards:
        return boards[0], "board on the homepage"
    for candidate in career_page_candidates(html, homepage_url)[:4]:
        cstatus, chtml = http_get(candidate)
        if cstatus == 200:
            boards = detect_boards(chtml, candidate)
            if boards:
                return boards[0], f"board on {candidate}"
    return None, "no Ashby/Greenhouse/Lever board found on the homepage or its career-page candidates"


JOB_HOST = re.compile(r'href="(https?://[^"]*(?:jobs\.gem\.com|workable\.com|rippling\.com|breezy\.hr|wellfound\.com|workatastartup\.com|jobs\.lever\.co|ashbyhq\.com|greenhouse\.io|bamboohr\.com|dover\.com|notion\.site)[^"]*)"', re.I)
TAG = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.S)
GTM_LINE = re.compile(r"^.{0,80}\b(sales|account executive|SDR|BDR|business development|marketing|growth|demand generation|partnerships|revenue operations|go-to-market|GTM)\b.{0,80}$", re.I | re.M)


def careers_page_fallback(homepage_url: str, slug: str) -> tuple[Verdict, Verdict, int, str | None]:
    """No Ashby/Greenhouse/Lever board: find the careers page (or a linked job host) and hand it to
    the human as a reference. It is never a pass: a careers page is prose, and the first version
    of this fallback matched marketing copy ("Dental Marketing Solutions") and a Google Tag Manager
    id ("GTM-…") as GTM job titles. Only a board a parser can read decides hiring; here the verdict
    stays `unclear` and the reference tells the human where to look.
    """
    status, html = http_get(homepage_url)
    if status != 200:
        return (Verdict("hiring", "unclear", f"homepage fetch {status}"), Verdict("intent", "unclear", "no page to read"), 0, None)
    hosts = [m.group(1) for m in JOB_HOST.finditer(html)][:2]
    pages = hosts + career_page_candidates(html, homepage_url)[:4]
    reachable = []
    for page in pages:
        pstatus, phtml = http_get(page)
        if pstatus == 200 and len(phtml) > 200:
            reachable.append(page)
            if len(reachable) == 2:
                break
    if reachable:
        where = "a linked job host" if hosts and reachable[0] == hosts[0] else "a careers page"
        return (Verdict("hiring", "unclear", f"no Ashby/Greenhouse/Lever board; {where} exists for the human to read", reachable[:2]),
                Verdict("intent", "unclear", "no board postings to read"), 0, f"page:{host(reachable[0])}")
    return (Verdict("hiring", "unclear", "no ATS board and no reachable careers page"), Verdict("intent", "unclear", "no page to read"), 0, None)


def hiring_and_intent(homepage_url: str, slug: str) -> tuple[Verdict, Verdict, int, str | None]:
    board, how = find_board(homepage_url, slug)
    if board is None:
        return careers_page_fallback(homepage_url, slug)
    url = board_url(board)
    status, body = http_get(url)
    if status != 200:
        return (Verdict("hiring", "unclear", f"board {board.kind}/{board.slug} fetch {status}"),
                Verdict("intent", "unclear", "board unreadable"), 0, f"{board.kind}:{board.slug}")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return (Verdict("hiring", "unclear", "board payload not JSON"), Verdict("intent", "unclear", "board unreadable"), 0, f"{board.kind}:{board.slug}")
    (HERE.parent / "raw" / f"hybrid_board_{slug}.json").write_text(json.dumps(payload)[:2_000_000])
    postings = normalise_postings(board, payload, today=TODAY)
    listed = [p for p in postings if p.is_listed is not False]
    gtm = [p for p in listed if p.title and GTM_TITLE.search(p.title)]
    board_ref = f"{board.kind}:{board.slug}"
    if not gtm:
        hiring = Verdict("hiring", "fail", f"{len(listed)} open roles on {board_ref}, none with a GTM title", [url])
        intent = Verdict("intent", "unclear", "no GTM posting to read")
        return hiring, intent, 0, board_ref
    titles = ", ".join(sorted({p.title for p in gtm if p.title})[:6])
    hiring = Verdict("hiring", "pass", f"{len(gtm)} GTM of {len(listed)} open roles on {board_ref}: {titles}", [url])
    quotes: list[tuple[str, str]] = []
    for p in gtm:
        text = p.description_plain or ""
        m = TIER1.search(text)
        if m:
            start = max(0, m.start() - 90)
            quotes.append((text[start:m.end() + 90].replace("\n", " ").strip(), p.url or url))
    tier2 = len(gtm) >= 2
    if quotes:
        q, ref = quotes[0]
        intent = Verdict("intent", "pass", f"Q1 in a GTM posting: “…{q}…”", [ref])
    elif tier2:
        intent = Verdict("intent", "unclear", f"Q7 only ({len(gtm)} concurrent GTM openings); one Tier-2 signal is not enough on its own")
    else:
        intent = Verdict("intent", "unclear", "GTM posting carries no Q1 language; absence is not a fail")
    return hiring, intent, len(gtm), board_ref


def grade(item: dict) -> Graded:
    props = item.get("properties") or {}
    co = props.get("company") or {}
    url = props.get("url") or ""
    name = co.get("name") or host(url)
    slug = "".join(ch if ch.isalnum() else "_" for ch in name)[:40]
    stage, cost = stage_probe(name, url, slug)
    geography = geography_verdict(item, slug)
    hiring, intent, gtm_n, board = hiring_and_intent(url, slug)
    verdicts = [stage, geography, hiring, intent]
    employees = co.get("employees")
    if isinstance(employees, int) and employees > 800:
        verdicts.append(Verdict("exclusion", "fail", f"{employees} employees (> 800)"))
    score = sum({"pass": 1.0, "unclear": 0.5, "fail": 0.0}[v.verdict] for v in verdicts) / len(verdicts)
    passes = sum(v.verdict == "pass" for v in verdicts)
    fails = sum(v.verdict == "fail" for v in verdicts)
    if fails == 0 and passes == len(verdicts):
        disposition = "pass"
    elif fails == 0:
        disposition = "unclear"
    elif passes >= fails:
        disposition = "partial"
    else:
        disposition = "fail"
    band = "High" if score >= HIGH else "Medium" if score >= MEDIUM else "Low"
    hq = co.get("headquarters") or {}
    websets_says = ", ".join(f"{e.get('satisfied')}" for e in item.get("evaluations") or [])
    return Graded(name, url, host(url), f"{hq.get('city') or ''} {hq.get('state') or ''} {hq.get('countryCode') or ''}".strip(),
                  employees if isinstance(employees, int) else None, websets_says, verdicts, round(score, 3), band,
                  disposition, cost, gtm_n, board)


# ----------------------------------------------------------------------------------------------


def report(webset: dict, graded: list[Graded], elapsed_probe_s: float) -> None:
    search = (webset.get("searches") or [{}])[0]
    prog = search.get("progress") or {}
    green = sum(1 for g in graded if g.websets_says and "no" not in g.websets_says)
    credits = 10 * green
    probe = sum(g.probe_cost_usd for g in graded)
    lines = [
        "# Hybrid discovery PoC — results (2026-09-10)", "",
        f"Webset `{webset.get('id')}`: found {prog.get('found')} of {prog.get('analyzed')} analyzed; "
        f"{len(graded)} items graded. Credits ≈ {credits} (≈ ${credits * 449 / 100000:.2f} Pro / "
        f"${credits * 49 / 8000:.2f} Core). Probe spend ${probe:.3f} ({len(graded)} stage searches; ATS reads free). "
        f"Probe wall time {elapsed_probe_s:.0f} s.", "",
        f"Dispositions: pass {sum(g.disposition == 'pass' for g in graded)}, partial {sum(g.disposition == 'partial' for g in graded)}, "
        f"unclear {sum(g.disposition == 'unclear' for g in graded)}, fail {sum(g.disposition == 'fail' for g in graded)}. "
        f"Bands: High {sum(g.band == 'High' for g in graded)}, Medium {sum(g.band == 'Medium' for g in graded)}, Low {sum(g.band == 'Low' for g in graded)}.", "",
        "| # | company | HQ | emp | stage | geo | hiring | intent | fit | band | disposition | GTM reqs | board |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    mark = {"pass": "✅", "fail": "❌", "unclear": "❓"}
    for i, g in enumerate(graded, 1):
        v = {x.gate: mark[x.verdict] for x in g.verdicts}
        excl = " ❌excl" if any(x.gate == "exclusion" for x in g.verdicts) else ""
        lines.append(f"| {i} | {g.name} | {g.hq} | {g.employees or ''} | {v.get('stage')} | {v.get('geography')} | "
                     f"{v.get('hiring')} | {v.get('intent')} | {int(g.fit * 100)} | {g.band}{excl} | {g.disposition} | {g.gtm_postings} | {g.board or '—'} |")
    lines += ["", "## Verdicts with reasons and references", ""]
    for i, g in enumerate(graded, 1):
        lines.append(f"**{i}. {g.name}** ({g.domain}) — fit {int(g.fit * 100)} {g.band}, {g.disposition}")
        for x in g.verdicts:
            refs = ", ".join(host(r) or r for r in x.references[:2])
            lines.append(f"- {x.gate}: {x.verdict} — {x.reason}" + (f" [{refs}]" if refs else ""))
        lines.append("")
    (HERE / "hybrid_results.md").write_text("\n".join(lines))
    (HERE / "hybrid_graded.json").write_text(json.dumps([asdict(g) for g in graded], indent=2, default=str))
    print("\n".join(lines[:12]))


if __name__ == "__main__":
    if "--webset" in sys.argv:
        webset_id = sys.argv[sys.argv.index("--webset") + 1]
        _, webset = request("GET", f"{BASE}/{webset_id}")
    else:
        webset_id = create_webset()
        webset = poll(webset_id)
    rows = items(webset_id)
    print(f"{len(rows)} items; grading…", flush=True)
    started = time.monotonic()
    graded = []
    for row in rows:
        g = grade(row)
        graded.append(g)
        print(f"  {g.name:32.32} fit={int(g.fit * 100):3d} {g.band:6} {g.disposition:8} gtm={g.gtm_postings} board={g.board}", flush=True)
    report(webset, graded, time.monotonic() - started)
    print("done", datetime.now(UTC).isoformat())

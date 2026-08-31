"""B1a — own-site read for all 5 accounts, done TWO ways on the SAME urls.

(a) Exa /contents (paid, ~$0.001/page)  (b) plain urllib + browser UA (free).
Same URL set both ways => the scraping verdict in section 7 is measured, not asserted.
Also extracts the free Ashby job descriptions into per-account quote bundles.
"""

import html
import json
import re
import sys
import time

sys.path.insert(0, ".")
import b_lib as C  # noqa: E402

URLS = {
    "zafran": [
        "https://www.zafran.io",
        "https://www.zafran.io/resources/zafran-triples-arr-in-60m-round-to-reinvent-exposure-management-with-agentic-ai",
        "https://www.zafran.io/resources/zafran-announces-strategic-investment-from-cisco-investments",
        "https://www.zafran.io/about-us",
    ],
    "cogent": [
        "https://www.cogent.com",
        "https://www.cogent.com/blog/cogent-security-raises-42m-series-a",
        "https://www.prnewswire.com/news-releases/cogent-security-raises-42m-series-a-to-arm-security-teams-with-autonomous-ai-agents-302691566.html",
    ],
    "harmonic": [
        "https://www.harmonic.security",
        "https://www.harmonic.security/about",
        "https://www.harmonic.security/resources/harmonic-security-raises-17-5-million-series-a-to-accelerate-zero-touch-data-protection-to-market",
    ],
    "vendelux": [
        "https://www.vendelux.com",
        "https://firstmark.com/story/vendelux-raises-50m-series-b-to-bring-ai-led-intelligence-to-b2b-events/",
        "https://www.businessinsider.com/vendelux-just-raised-50-million-to-capitalize-live-b2b-events-2026-7",
    ],
    "uptiq": [
        "https://www.uptiq.ai",
        "https://www.uptiq.ai/about-us",
        "https://www.growthspreeofficial.com/case-studies/case-study-uptiq-ai-building-an-abm-engine-for-modern-financial-leaders",
        "https://www.uptiq.ai/press-releases/uptiq-raises-25m-to-add-ai-agents-to-bank-workflows",
    ],
}


def detag(t):
    s = re.sub(r"<script.*?</script>", " ", t, flags=re.S | re.I)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


t_all = time.time()
scrape = {}
site_text = {}

for acct, urls in URLS.items():
    t0 = time.time()
    r = C.exa_contents(urls, label=f"b1a_contents_{acct}", text_chars=9000)
    got = {x.get("url", "").rstrip("/"): x for x in (r.get("results") or [])}
    per = []
    texts = []
    for u in urls:
        res = got.get(u.rstrip("/")) or got.get(u)
        served = bool(res and (res.get("text") or "").strip())
        chars = len((res or {}).get("text") or "")
        # rung 1: free direct fetch of the same URL
        lf = C.live_fetch(u, label=f"lf_{acct}_{abs(hash(u)) % 10000}")
        live_txt = detag(lf["text"]) if lf["status"] == 200 else ""
        per.append({
            "url": u,
            "exa_served": served, "exa_chars": chars,
            "live_http": lf["status"], "live_chars": len(live_txt),
            "live_s": lf["elapsed_s"],
        })
        if served:
            texts.append(f"SOURCE {u} [via Exa /contents]\n{res.get('text')}")
        elif live_txt:
            texts.append(f"SOURCE {u} [via direct fetch]\n{live_txt[:9000]}")
    scrape[acct] = {"pages": per, "exa_elapsed_s": r.get("_elapsed_s"),
                    "exa_statuses": r.get("statuses")}
    site_text[acct] = "\n\n".join(texts)[:40000]
    C.timing_record(f"B1a_own_site_{acct}", time.time() - t0, f"{len(urls)} urls x2 methods")
    print(f"  -> {acct}: exa served {sum(p['exa_served'] for p in per)}/{len(urls)}, "
          f"live 200s {sum(p['live_http'] == 200 for p in per)}/{len(urls)}")

# free Ashby GTM job-description bundles
boards = json.load(open("b0_boards.json"))
GTM_WORDS = ("market", "growth", "demand", "abm", "campaign", "revenue op", "sales op",
             "brand", "content", "community", "field", "business development", "sdr",
             "partnership", "enablement")
job_text = {}
for acct in URLS:
    raw = json.load(open(f"raw/b0_ashby_{acct}.json"))
    jobs = raw.get("jobs") or []
    keep = [j for j in jobs
            if any(w in (j.get("title") or "").lower() for w in GTM_WORDS)
            or (j.get("department") or "").lower() in ("marketing", "gtm", "go to market")]
    job_text[acct] = "\n\n".join(
        f"JOB {j.get('title')} | dept={j.get('department')}/{j.get('team')} | "
        f"loc={j.get('location')} | published={j.get('publishedAt')} | "
        f"comp={(j.get('compensation') or {}).get('compensationTierSummary')} | "
        f"STILL LISTED TODAY (2026-08-31)={j.get('isListed')}\nURL {j.get('jobUrl')}\n"
        f"{(j.get('descriptionPlain') or '')[:5000]}"
        for j in keep
    )[:38000]
    print(f"  jobs[{acct}]: {len(keep)} GTM/marketing reqs, {len(job_text[acct])} chars")

json.dump(scrape, open("b1a_scrape_matrix.json", "w"), indent=2)
json.dump(site_text, open("b1a_site_text.json", "w"), indent=2)
json.dump(job_text, open("b1a_job_text.json", "w"), indent=2)
C.timing_record("B1a_TOTAL", time.time() - t_all, "own-site reads, 5 accounts")
print(f"\nPHASE B1a {round(time.time()-t_all,1)}s spend={C.total_spend()} credits={C.total_credits()}")

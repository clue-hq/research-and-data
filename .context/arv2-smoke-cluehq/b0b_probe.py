"""B0b — free follow-ups to the board probe.

1. Harmonic: A cited req id f568f331 as 'Account-Based Marketing Manager, Strategic Accounts';
   the board returns that SAME id today titled 'Business Development Representative - East'.
   Fetch the live posting page to see which title is live now.
2. Uptiq / Arintra: no Ashby board (404). Try the common ATS boards + their own careers pages.
All $0.
"""

import json
import sys
import time

sys.path.insert(0, ".")
import b_lib as C  # noqa: E402

t0 = time.time()
out = {}

# 1. Harmonic req id, live posting page
r = C.live_fetch(
    "https://jobs.ashbyhq.com/harmonic-security-inc/f568f331-f4ea-4328-a690-03772941f561",
    label="harmonic_req_page",
)
txt = r["text"]
out["harmonic_req_page"] = {
    "http": r["status"],
    "bytes": len(txt),
    "mentions_abm": "Account-Based Marketing" in txt or "Account Based Marketing" in txt,
    "mentions_bdr": "Business Development Representative" in txt,
    "title_snippet": txt[txt.find("<title>"):txt.find("</title>") + 8][:300] if "<title>" in txt else "",
}
print(json.dumps(out["harmonic_req_page"], indent=1))

# 2. Uptiq / Arintra ATS hunt
ATS = []
for slug in ["uptiq", "uptiqai", "uptiq-ai"]:
    ATS.append((f"greenhouse_{slug}", f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"))
    ATS.append((f"lever_{slug}", f"https://api.lever.co/v0/postings/{slug}?mode=json"))
for slug in ["arintra"]:
    ATS.append((f"greenhouse_{slug}", f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"))
    ATS.append((f"lever_{slug}", f"https://api.lever.co/v0/postings/{slug}?mode=json"))

ats_hits = {}
for label, url in ATS:
    status, hdrs, text, elapsed = C._request(
        url, headers={"accept": "application/json", "User-Agent": C.BROWSER_UA},
        timeout=30, retries=1,
    )
    ok = status == 200
    n = 0
    if ok:
        try:
            j = json.loads(text)
            n = len(j.get("jobs") or j if isinstance(j, list) else j.get("jobs") or [])
            C.save_raw(f"b0b_{label}", j if isinstance(j, dict) else {"list": j})
        except Exception:
            ok = False
    ats_hits[label] = {"http": status, "n": n, "url": url}
    C.ledger_append({"provider": "ats_public", "label": label, "op": f"GET {url}",
                     "http": status, "elapsed_s": elapsed, "cost_usd": 0.0})
    print(f"  {label}: http={status} n={n}")
    time.sleep(0.2)
out["ats_probe"] = ats_hits

# 3. Own careers pages, live
for label, url in [
    ("uptiq_careers", "https://www.uptiq.ai/careers"),
    ("uptiq_about", "https://www.uptiq.ai/about-us"),
    ("arintra_careers", "https://www.arintra.com/careers"),
]:
    r = C.live_fetch(url, label=label)
    out[label] = {"http": r["status"], "bytes": len(r["text"])}

json.dump(out, open("b0b_probe.json", "w"), indent=2)
C.timing_record("B0b_free_followups", time.time() - t0, "harmonic req page + ATS hunt + careers")
print(f"\nPHASE B0b {round(time.time()-t0,1)}s spend={C.total_spend()} credits={C.total_credits()}")

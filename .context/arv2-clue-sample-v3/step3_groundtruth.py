"""Step 3 — OPEN-WEB GROUND TRUTH FIRST (the v3 committee-correctness protocol, item 1).

Own site (+ company/team page) + the Series-A announcements + the live hiring index, fetched with
/contents at $0.001/page. This is where the committee is BUILT — Apollo is enrichment-only, later.
"""

import sys

sys.path.insert(0, ".")
import clue_lib as C  # noqa: E402

URLS = [
    "https://www.probook.ai/",
    "https://www.probook.ai/company",
    "https://www.probook.ai/letter",
    "https://jobs.ashbyhq.com/probook",
    "https://a16z.com/announcement/investing-in-probook/",
    "https://sequoiacap.com/article/partnering-with-probook-ai-for-the-trades",
    "https://www.globenewswire.com/news-release/2026/06/23/3316215/0/en/Probook-Raises-40M-from-Andreessen-Horowitz-and-Sequoia-to-Scale-the-AI-Operating-System-for-Home-Services.html",
    "https://fortune.com/2026/06/23/exclusive-this-startup-wants-to-be-the-ai-brain-for-home-services-and-it-just-raised-40-million-from-sequoia-and-a16z/",
]

r = C.exa_contents(URLS, label="gt1_owned_and_announcements", text_chars=12000)
for res in r.get("results") or []:
    t = res.get("text") or ""
    print(f"\n===== {res.get('url')}  ({len(t)} chars)  title={res.get('title')!r}")
    print(t[:1500].replace("\n\n", "\n"))
print("\nstatuses:", r.get("statuses"))
print("TOTAL:", C.total_spend())

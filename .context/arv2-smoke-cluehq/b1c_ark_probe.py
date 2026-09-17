"""B1c-probe — 1 cheap AI Ark call (size 2 = 1 credit) to learn whether a TITLE filter works.

On a 141-person company an unfiltered size-12 roster is a lottery; a working title filter turns
the same 6 credits into a marketing committee. Worth 1 credit to find out.
"""

import json
import sys
import time

sys.path.insert(0, ".")
import b_lib as C  # noqa: E402

t0 = time.time()
body = {
    "account": {"domain": {"any": {"include": ["zafran.io"]}}},
    "contact": {"title": {"any": {"include": {"mode": "BROAD", "content": ["marketing"]}}}},
    "page": 0,
    "size": 2,
}
out, status, el = C.ark("/v1/people", body, label="b1c_probe_zafran_title", est_credits=1.0)
n = len(out.get("content") or [])
C.ark_ledger("b1c_probe_zafran_title", "POST /v1/people (title filter probe)", status, el,
             0.5 * n, f"totalElements={out.get('totalElements')}")
print("http:", status, "totalElements:", out.get("totalElements"), "returned:", n)
if status != 200:
    print("BODY:", json.dumps(out)[:900])
for p in (out.get("content") or []):
    pr = p.get("profile") or {}
    print("  ", pr.get("full_name"), "|", pr.get("title"), "|", (p.get("link") or {}).get("linkedin"))
C.timing_record("B1c_ark_title_filter_probe", time.time() - t0, "1 call, size 2")
print(f"spend={C.total_spend()} credits={C.total_credits()}")

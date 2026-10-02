"""Z1a — AI Ark: credit balance + company search for zafran.io. FIELD INVENTORY source."""
import json, sys, time
sys.path.insert(0, ".")
import z_lib as C  # noqa: E402

t_all = time.time()
print("== credit balance BEFORE ==")
r = C.ark("/v1/credit", None, label="z1a_credit_before", method="GET", est_credits=0.0)
print("   ", r["_http_status"], json.dumps(r["_body"])[:300])

print("\n== POST /v1/companies  domain=zafran.io size=3 ==")
body = {"account": {"domain": {"any": {"include": ["zafran.io"]}}}, "page": 0, "size": 3}
r = C.ark("/v1/companies", body, label="z1a_companies_zafran", est_credits=0.3)
out = r["_body"]
print("   totalElements:", out.get("totalElements"))
comps = out.get("content") or []
for c in comps:
    print("   ->", json.dumps({k: (v if not isinstance(v, (dict, list)) else f"<{type(v).__name__} len={len(v)}>")
                               for k, v in c.items()}, indent=1)[:2500])
json.dump({"credit_before": None, "companies": comps}, open("z1a_company.json", "w"), indent=2)
C.timing_record("Z1a_ark_company", time.time() - t_all, "credit + company search")
print(f"\nZ1a {round(time.time()-t_all,1)}s credits={C.total_credits()} spend={C.total_spend()}")

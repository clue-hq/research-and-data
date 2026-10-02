"""Z11 — render the AI Ark field inventory as markdown tables straight from the saved responses."""
import json

inv = json.load(open("z10_ark_field_inventory.json"))
SKIP_PREFIX = ("company.",)  # the person-embedded company block is shown separately


def esc(v):
    return str(v).replace("|", "\\|").replace("\n", " ")[:300]


def table(rows, note=""):
    out = ["| field | type | real value for Zafran |", "|---|---|---|"]
    for r in rows:
        out.append(f"| `{r['field']}` | {r['type']} | {esc(r['value'])} |")
    return "\n".join(out)


md = []
d = inv["POST /v1/companies"]
md.append("#### A. `POST /v1/companies` — 0.1 credit per company returned "
          f"(http {d['http']}, {d['elapsed_s']}s, totalElements={d['totalElements']})\n")
md.append(f"Request body: `{json.dumps(d['request'])}`\n")
md.append(f"Envelope fields: `{', '.join(d['envelope_fields'])}` — the company object sits in "
          "`content[0]`.\n")
md.append(table(d["fields"]))
md.append("")

d = inv["POST /v1/people (person object)"]
md.append(f"\n#### B. `POST /v1/people` — 0.5 credit per profile returned "
          f"(http {d['http']}, {d['elapsed_s']}s). Subject: {d['subject']}\n")
md.append(f"Request body: `{json.dumps(d['request'])}`\n")
person_rows = [r for r in d["fields"] if not r["field"].startswith(SKIP_PREFIX)]
company_rows = [r for r in d["fields"] if r["field"].startswith(SKIP_PREFIX)]
md.append(table(person_rows))
md.append(f"\n**Plus a whole embedded company object** ({len(company_rows)} more fields, "
          "identical to the `/v1/companies` object except as noted below):\n")
md.append(table([r for r in company_rows if "aberdeen" in r["field"]
                 or r["field"].endswith((".legal_name", ".staff.total", ".total_amount",
                                         ".num_investor", ".last_updated"))]))
md.append("")

d = inv["POST /v1/people/export/single (email block)"]
md.append(f"\n#### C. `POST /v1/people/export/single` — 1 credit when an address is found "
          f"(http {d['http']}, {d['elapsed_s']}s). Subject: {d['subject']}\n")
md.append(f"Request body: `{json.dumps(d['request'])}`\n")
md.append(f"{d['note']}\n")
md.append(table(d["fields"]))

d = inv["GET /v1/credit"]
md.append(f"\n#### D. `GET /v1/credit` — {d['result']}\n")

d = inv["GET api.ashbyhq.com/posting-api/job-board/zafran-security (FREE, for contrast)"]
md.append("\n#### E. For contrast — the FREE Ashby posting API (0 credits, $0.00)\n")
md.append(f"Board fields: `{', '.join(d['board_top_keys'])}`. "
          f"Per-job fields: `{', '.join(d['job_field_names'])}`. "
          f"Jobs returned: **{d['n_jobs']}**.\n")

open("z11_inventory.md", "w").write("\n".join(md))
print("wrote z11_inventory.md", len("\n".join(md)), "chars")

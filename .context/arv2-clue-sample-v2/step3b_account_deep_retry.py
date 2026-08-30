"""Step 3b — the ONE retry of the account deep call.

Finding from step 3: `POST /search` with `type:"deep-reasoning"` and NO `outputSchema` returns
`results[]` (23 researched pages, 124k chars) but NO `output` key at all — the synthesis stage only
runs when an outputSchema is present. So the retry keeps the "free-form report, not a rigid
10-property field schema" design by declaring exactly ONE string property that the model fills with
a long markdown report.
"""

import json

from clue_lib import exa, exa_output_text, save_raw, total_spend

SYS = json.load(open("raw/account_deep_lassie.json"))["_request"]["systemPrompt"]

QUERY = (
    "Lassie (lassie.ai), the San Francisco AI company automating dental and medical practice "
    "administration: who they are, what they sell, their customers and traction, their $35M "
    "Series A led by Andreessen Horowitz in June 2026, headcount and go-to-market team, how they "
    "sell to independent dental practices, their open growth/GTM/sales roles, founders Steijn "
    "Pelle and Frederic Renken, company culture and public statements, and dated timing signals"
)

resp = exa(
    {
        "query": QUERY,
        "type": "deep-reasoning",
        "numResults": 25,
        "systemPrompt": SYS,
        "outputSchema": {
            "type": "object",
            "description": (
                "A single long markdown research report. Put the ENTIRE 12-section dossier, with "
                "every verbatim quote and every source URL inline, into the one 'report' string. "
                "Do not summarise: length and citation density are the goal."
            ),
            "properties": {
                "report": {
                    "type": "string",
                    "description": (
                        "The complete 12-section markdown dossier described in the system prompt, "
                        "with verbatim quotes and source URLs inline for every fact."
                    ),
                }
            },
            "required": ["report"],
        },
        "contents": {
            "text": {"maxCharacters": 10000},
            "highlights": {
                "query": "Lassie dental AI funding team hiring go-to-market customers",
                "maxCharacters": 2000,
            },
        },
        "stream": False,
    },
    label="account_deep_lassie_retry",
    timeout=900,
)

raw_out = resp.get("output")
report = ""
if isinstance(raw_out, dict):
    content = raw_out.get("content")
    if isinstance(content, dict):
        report = content.get("report") or json.dumps(content, indent=2)
    elif isinstance(content, str):
        try:
            report = json.loads(content).get("report") or content
        except Exception:
            report = content
if not report:
    report = exa_output_text(resp)

save_raw("account_deep_report_text", {"chars": len(report), "report": report})
open("account_report.md", "w").write(report)
print("\n---- report chars:", len(report))
print("cost:", (resp.get("costDollars") or {}).get("total"), "total spend $", total_spend())
print(report[:2500])

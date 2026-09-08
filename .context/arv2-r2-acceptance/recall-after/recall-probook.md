# answer-key recall — probook

account **probook** · keys 24 · exact 9 · partial 3 · field_only 9 · missing 3 · **recall 50%**

| section | hits | keys | recall |
| --- | ---: | ---: | ---: |
| `core` | 6 | 13 | 46% |
| `account` | 6 | 9 | 67% |
| `account.resonance` | 0 | 2 | 0% |

## misses

- **core.industry** — field_only
  - key: `information technology & services`
  - run: `software development`
- **core.employee_count** — field_only
  - key: `52`
  - run: `36`
- **core.primary_tech_stack** — missing
  - key: `["AI", "Amazon AWS", "Amazon CloudFront", "Cursor", "Excel Impact", "Frame", "Gmail", "Google Meet", "Google Search Console", "Google Search Console", "Google Sheets", "Google Tag Manager", "Google Workspace", "HSTS", "…`
- **core.company_about** — field_only
  - key: `The AI Operating System for home services; built around dispatch to unify intake, data cleaning, chat, outbound, and dispatch so operators can run customer experience as one connected system.`
  - run: `Dispatch makes or breaks the customer experience. Probook is the only AI built around it.`
- **core.industry** — field_only
  - key: `Home services software (HVAC, plumbing, electrical)`
  - run: `software development`
- **core.primary_tech_stack** — missing
  - key: `["ServiceTitan"]`
- **core.employee_range** — field_only
  - key: `{"label": "14 open positions listed", "max": 14, "min": 14}`
  - run: `{"conflicts_with": "LinkedIn 36 and AI Ark 30", "range": "60-65+", "semantics": "company_claimed_in_job_postings"}`
- **account.resonance.culture** — field_only
  - key: `Built by people from the trades; small team with diverse backgrounds; deploys in person and configures alongside customers.`
  - run: `In-office 5 days/week Manhattan high-collaboration culture; talent-dense engineering claim vs early Ramp`
- **account.recent_funding** — field_only
  - key: `{"amount_usd": 6000000, "round": "Seed"}`
  - run: `{"amount_usd": 34000000, "date": "June 23, 2026", "lead_investor": "Andreessen Horowitz", "round": "Series A"}`
- **account.operational_pain** — field_only
  - key: `Fragmented vendor/tooling for voice, outbound and follow-up leading to operational overhead; raw home-services workflows (calls, setting the board, follow-up) that make dispatch the critical bottleneck.`
  - run: `SDR motion: the list of top home service operators exists; the hire is to go get them via account research and high-volume outbound.`
- **account.resonance.buying_culture** — missing
  - key: `{"culture_label": "founder-led, operator-oriented, deployment-committed", "summary": "Founder-led origin with hands-on customer discovery and in-person deployments; public commitment to scale GTM and deliver outcomes po…`
- **account.operational_pain** — field_only
  - key: `Scaling delivery capacity is a bottleneck: need to grow engineering, customer success and GTM to meet surging demand.`
  - run: `SDR motion: the list of top home service operators exists; the hire is to go get them via account research and high-volume outbound.`

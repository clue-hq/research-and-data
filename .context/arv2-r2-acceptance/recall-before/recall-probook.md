# answer-key recall — probook

account **probook** · keys 24 · exact 5 · partial 6 · field_only 10 · missing 3 · **recall 46%**

| section | hits | keys | recall |
| --- | ---: | ---: | ---: |
| `core` | 6 | 13 | 46% |
| `account` | 5 | 9 | 56% |
| `account.resonance` | 0 | 2 | 0% |

## misses

- **core.industry** — field_only
  - key: `information technology & services`
  - run: `software development`
- **core.employee_count** — field_only
  - key: `52`
  - run: `{"as_of": "2026-09", "count": 36, "semantics": "linkedin_estimate"}`
- **core.primary_tech_stack** — missing
  - key: `["AI", "Amazon AWS", "Amazon CloudFront", "Cursor", "Excel Impact", "Frame", "Gmail", "Google Meet", "Google Search Console", "Google Search Console", "Google Sheets", "Google Tag Manager", "Google Workspace", "HSTS", "…`
- **account.total_funding** — field_only
  - key: `{"amount_usd": 40000000.0, "estimate_kind": "reported"}`
  - run: `{"amount_usd": 40000000, "as_of": "June 23, 2026", "semantics": "reported_total_after_round"}`
- **core.company_about** — field_only
  - key: `The AI Operating System for home services; built around dispatch to unify intake, data cleaning, chat, outbound, and dispatch so operators can run customer experience as one connected system.`
  - run: `Dispatch makes or breaks the customer experience. Probook is the only AI built around it.`
- **core.industry** — field_only
  - key: `Home services software (HVAC, plumbing, electrical)`
  - run: `software development`
- **account.total_funding** — field_only
  - key: `{"amount_usd": 40000000, "estimate_kind": "reported"}`
  - run: `{"amount_usd": 40000000, "as_of": "June 23, 2026", "semantics": "reported_total_after_round"}`
- **core.primary_tech_stack** — missing
  - key: `["ServiceTitan"]`
- **core.employee_range** — field_only
  - key: `{"label": "14 open positions listed", "max": 14, "min": 14}`
  - run: `{"conflicts_with": "LinkedIn 36 and AI Ark 30", "range": "60-65+", "semantics": "company_claimed_in_job_postings"}`
- **account.resonance.culture** — field_only
  - key: `Built by people from the trades; small team with diverse backgrounds; deploys in person and configures alongside customers.`
  - run: `In-office 5 days/week Manhattan high-collaboration culture; talent-dense engineering claim vs early Ramp`
- **account.operational_pain** — field_only
  - key: `Fragmented vendor/tooling for voice, outbound and follow-up leading to operational overhead; raw home-services workflows (calls, setting the board, follow-up) that make dispatch the critical bottleneck.`
  - run: `But in Q4 of 2025, I realized that being the only salesperson created a massive bottleneck.`
- **account.resonance.buying_culture** — missing
  - key: `{"culture_label": "founder-led, operator-oriented, deployment-committed", "summary": "Founder-led origin with hands-on customer discovery and in-person deployments; public commitment to scale GTM and deliver outcomes po…`
- **account.operational_pain** — field_only
  - key: `Scaling delivery capacity is a bottleneck: need to grow engineering, customer success and GTM to meet surging demand.`
  - run: `But in Q4 of 2025, I realized that being the only salesperson created a massive bottleneck.`

# Sanitized Exa Websets D0 fixtures

These payloads are fictional, secret-free examples pinned to the public Websets `v0` OpenAPI
contract and structurally checked against bounded live responses on 2026-08-03. They are sanitized
executable fixtures, not recordings of a paid call and not copies of live company data.

- `webset-running.json` covers asynchronous submit/running state.
- `items-page-1.json` and `items-page-2.json` cover the current required company shape, structured
  headquarters, annual revenue, total/latest-round funding, all `yes | no | unclear` evaluation
  states, explicit null contact results, result status, and cursor exhaustion. `foundedYear` and
  `webTraffic` are present only because the provider schema requires them; platform discovery does
  not project them.
- `events-duplicate-out-of-order.json` covers duplicate and out-of-order delivery with the full
  resource in each event's `data`, matching the current event contract.
- `webset-cancelled.json` covers cancelled search/enrichment operations.
- `schema-drift-additive.json` contains deliberately unknown additive fields. The raw payload must
  remain durable even before a future adapter version understands those fields.

All companies, identifiers, domains, email addresses, phone numbers, and evidence are synthetic.
No API keys, webhook secrets, authorization headers, customer records, or live Exa ids belong here.

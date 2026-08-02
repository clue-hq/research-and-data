# Sanitized Exa Websets D0 fixtures

These payloads are fictional, secret-free examples pinned to the public Websets `v0` contract
reviewed on 2026-08-02. They are executable contract fixtures, not recordings of a paid call.

- `webset-running.json` covers asynchronous submit/running state.
- `items-page-1.json` and `items-page-2.json` cover company properties, all
  `yes | no | unclear` evaluation states, null enrichment, and cursor exhaustion.
- `events-duplicate-out-of-order.json` covers duplicate and out-of-order delivery.
- `webset-cancelled.json` covers cancelled search/enrichment operations.
- `schema-drift-additive.json` contains deliberately unknown additive fields. The raw payload must
  remain durable even before a future adapter version understands those fields.

All companies, identifiers, domains, email addresses, phone numbers, and evidence are synthetic.
No API keys, webhook secrets, authorization headers, customer records, or live Exa ids belong here.

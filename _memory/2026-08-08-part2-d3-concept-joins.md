# 2026-08-08 — Part II D3 executed: concept joins (brand spine + account entity)

New clue_design/joins.py (interim scaffolding, loud docstring — Part III replaces the CREATE
halves with governed spine/identity services; resolves + stamps survive):
- Brand (R-D3-1): create_brand_kit stamps brand_id — explicit kwarg wins (composite FK refuses
  foreign-workspace); 1 brand → stamp; 0 → create 'Default Brand' (brd_<uuid4hex>, ON CONFLICT
  DO NOTHING, re-read; race-honest: re-read >1 → NULL); ≥2 → NULL (Part III delegation carries
  explicit brand).
- Account (R-D3-2): create/update_web_account resolves account_entity by (workspace_id,
  primary_domain=normalized domain); miss → minimal candidate entity (ON CONFLICT on the
  partial domain unique, loser re-reads winner); blank/no domain → NULL (name-only identity is
  the identity service's, never faked); domain change re-resolves; clear → NULL.
- R-D3-3: NOT NULL promotion DEFERRED to Part III (multi-brand ambiguity; domain-less
  accounts); no backfill (Part III's, with promotion).
- R-D3-5: mappers surface brand_id / account_entity_id (additive).
Verified: 9 join DAL tests; tests/design 55/55; FULL design suite 490/9/0 (= D2.5 baseline);
mypy 587; 25 contracts; offline 2176; db-smoke green. Residuals: per-version brand resolution
may differ across kit versions if the brand set changes (Part III explicit context removes);
localhost:5432 = Homebrew PG17 (known) — use 127.0.0.1 for speed (getaddrinfo dominated the
bridge's per-call wall clock). Next: D4 (assets → clue_storage) ∥ D5 (durable execution).

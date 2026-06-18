# 2026-06-18 — M0.4 config, secrets & jurisdiction/policy skeleton (ENG-120)

Built in a parallel worktree (Wave 1, agent `m04`), branch `wave1-m04` @ ae728a6, integrated into
`project-memory-instructions` by the orchestrator. Linear ENG-120 → In Progress → Done.

## What shipped (`src/clue_research/config/`)
- `secrets.py` — `Secrets(BaseSettings)` (`env_prefix="CLUE_"`, `SecretStr` fields, all optional);
  `redact`/`redact_mapping`/`is_secret_name` (the helper obs/M0.5 will import); `DB_DSN_ENV_VAR =
  "CLUE_DATABASE_URL"` (resolves via prefix + `database_url`; no explicit alias → avoids the
  pydantic-mypy dynamic-alias rule under --strict).
- `policy.py` — `Jurisdiction`, `Posture` (the 3 Doc D §6 options, Option 1 default), `UseDisposition`
  {usable|stored_unusable|not_stored}, `SourceScope`, `JurisdictionPolicy`, `LawfulBasisDefaults`,
  `RetentionTtls`. Allow-map = `dict[UseClass, UseDisposition]`; conservative default = professional-public
  + personal-public-non-sensitive USABLE, sensitive STORED_UNUSABLE; a validator forbids marking
  `sensitive` USABLE in the skeleton. **`source_scope` is DERIVED from `posture`** (Option 3 →
  PROFESSIONAL_PUBLIC_ONLY, Opt1/2 → FULL_SWEEP) → flipping to Option 3 is one config write, no code change.
  Reuses `core.UseClass` (not redefined). No `lawful_basis` claim field (that's M10).
- `schema.py` — config-schema placeholders (read by no engine yet): `MergePolicy` (M1), `ScoringRubric`
  (M3/M6), `SourceProfile` (M4), `BudgetCaps` (M7), `FreshnessTtls` (M1/M9).
- `models.py` — `ConfigVersion`, `ConfigOverlay` (sparse), `Config` (dense merged), `applied_versions`.
- `loader.py` — `get_config(client_id, icp_id?)`, `get_policy(client_id)`, `overlay_from_mapping`,
  `OverlayStore` (swappable seam; in-memory for M0, DB-backed later), `ConfigError`.
- `.env.example` (root) — `CLUE_DATABASE_URL` + `CLUE_{CLAY,APOLLO,ZOOMINFO,BUILTWITH,EXA,PARALLEL,
  FIRECRAWL,CRM}_API_KEY` placeholders (no real values; `.env` gitignored).

## Key decisions
- Loader precedence **defaults → per-client → per-ICP/campaign**; whole-sub-tree replace-or-inherit
  (no partial merge) so "which version produced this value" stays unambiguous; each layer's
  `ConfigVersion` recorded on `Config.applied_versions`. Overlay source is the swappable `OverlayStore`.
- Validation fails fast on load (`ConfigError`) for unknown posture / unknown jurisdiction / out-of-range
  cap or weight.
- Layering honored: `config/` imports only `core` + stdlib + pydantic(-settings) — NOT `obs`, NOT `db`.

## Dep added
`pydantic-settings>=2` (pulls python-dotenv).

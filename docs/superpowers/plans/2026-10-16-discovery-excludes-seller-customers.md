# Discovery Excludes the Seller's Customers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Onboarding researches the seller's public customers into `proof/customers.md`; the Head of ABM passes the ones it chooses on a new discovery brief `exclude` list; discovery never adds them, nor the seller itself.

**Architecture:** A fifth onboarding Exa Agent step (effort `xhigh`) plus a code domain check writes the brand document. `launch_arv2_discovery@3` carries `exclude`. The discovery driver turns the brief's entries plus the brand's onboarding domain into one excluded-domain set: an Exa Import excludes them from Websets, and every skip point records them as `excluded_by_brief`. The Head of ABM's skill (v45) and profile (v72) tell it to read the document and fill the list.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy async + asyncpg, Alembic, Exa Agent / Websets APIs through `ProviderCaller`, pytest.

**Spec:** `docs/superpowers/specs/2026-10-16-discovery-excludes-seller-customers-design.md` (founder-approved 2026-10-16, including the §4.7 wording).

## Global Constraints

- No saved customer table; code never decides who is a customer (spec §2 rulings 1–3).
- The list lives in the document **body** only; front matter carries the run header and sources, never a copy of the list (§4.3).
- Code always excludes the `company_domain` of the brand's most recent completed `kind='full'` onboarding run; the driver never reads `proof/customers.md` (§4.6).
- A domain check labels, never drops (§4.2); it errs towards `unconfirmed`.
- New setting `CLUE_ONBOARDING_CUSTOMERS_EFFORT=xhigh`, in `.env.example` and `clue_config` (env parity rule).
- `exclude`: at most 500 entries; `name` 1–200 characters; `domains` 1–10 each.
- New disposition `excluded_by_brief`; matching by `registrable_domain` (`clue_research.identity.normalize`).
- Alembic: one new hand-written, reversible migration with a hash id, `down_revision = "1ecc7437e5bc"`; `alembic heads` stays single.
- No `Co-Authored-By` or AI attribution in commits (CLAUDE.md).
- Tests never assert which model a setting names; live/paid tests never run in suites (`--ignore-glob='*_live.py'`). DB tests run on the lane's throwaway DB (`CLUE_DATABASE_URL` = `clue_nashville_locktest`), never a shared one.

## Review Focus

1. **A shared-host domain in `exclude`** (`acme.myshopify.com`): it must exclude that shop only, never every company on the same host. Pinned in Task 6.
2. **A resumed run after a crash:** earlier `excluded_by_brief` candidates must re-count and their domains must stay skipped, without double-counting. Pinned in Task 7.
3. **The same company written several ways in the brief** (`https://www.Acme.com/`, `acme.com`, two entries with one domain): one excluded domain, first entry's name. Pinned in Task 6.
4. **An old run row whose stored brief has no `exclude`** (deployed mid-run): it must resume unchanged, with the same run id derivation. Pinned in Task 6.
5. **A seller with no completed onboarding run:** discovery runs with only the brief's exclusions and does not fail. Pinned in Task 7.

---

### Task 1: Migration — new step, run and disposition kinds

**Files:**
- Create: `alembic/versions/<hash>_discovery_excludes_seller_customers.py` (create with `uv run alembic revision -m "discovery excludes seller customers"`; set `down_revision = "1ecc7437e5bc"`)
- Test: `tests/db/test_discovery_excludes_customers_migration.py`

**Interfaces:**
- Produces (DB): `onboarding_step.kind` allows `'customers'`; `onboarding_run.kind` allows `'customers'`; `arv2_discovery_candidate.disposition` allows `'excluded_by_brief'`; new column `arv2_discovery_candidate.excluded_by_entry text NULL` with CHECK `arv2_discovery_candidate_excluded_entry`: `(disposition = 'excluded_by_brief') = (excluded_by_entry IS NOT NULL)`.

- [ ] **Step 1: Write the failing migration test** — model it on `tests/db/test_arv2_onboarding_persona_step_migration.py`. Assertions:
  - `"'customers'" in` the definitions of `onboarding_step_kind` and `onboarding_run_kind`;
  - `"'excluded_by_brief'" in` `arv2_discovery_candidate_disposition`;
  - inserting a candidate with `disposition='excluded_by_brief', excluded_by_entry=NULL` raises `IntegrityError`; with `excluded_by_entry='Marriott'` it succeeds; `disposition='excluded'` still requires `excluded_by_gate`.
- [ ] **Step 2: Run** `CLUE_DATABASE_URL=<test db> uv run pytest tests/db/test_discovery_excludes_customers_migration.py -p no:cacheprovider` — Expected: FAIL (constraint values missing).
- [ ] **Step 3: Write the migration.** Upgrade re-installs the three CHECKs with the new values (copy the drop/add pattern from `ae4a5dfb3943` and `0a3a88c7e5ed`) and adds the column + its CHECK. Downgrade refuses with `RAISE EXCEPTION` if any `customers` step/run or `excluded_by_brief` candidate exists, then restores the previous CHECKs and drops the column.
- [ ] **Step 4: Run** the test again — Expected: PASS. Then `uv run alembic heads` — Expected: exactly one head (the new revision). Then `make db-smoke` on the throwaway DB — Expected: up/down/up green.
- [ ] **Step 5: Commit** — `git commit -m "Migration: customers onboarding step and run kind; excluded_by_brief disposition"`

### Task 2: The customers request template

**Files:**
- Modify: `platform/api/clue_api/arv2/onboarding_requests.py` (add to `__all__`)
- Test: `tests/arv2/test_onboarding_requests.py`

**Interfaces:**
- Produces: `existing_customers_query(company_name: str, domain: str) -> str`; `EXISTING_CUSTOMERS_SYSTEM_PROMPT: str`; `existing_customers_output_schema() -> dict[str, Any]`.

- [ ] **Step 1: Write failing tests:**
  - `test_the_customers_query_names_the_seller_and_where_to_look`: the query contains the company name, the domain, `"sitemap"`, `"logo walls"`, `"press releases"`, `"purchase trackers or registries"`, `"what buying from"`.
  - `test_the_customers_prompt_states_the_non_negotiables`: the prompt contains `"investors"`, `"integration partners"`, `"competitors"`, `"same logo wall"`, `"named on a page"`, `"brand domains"`, `"otherwise leave it out"`.
  - `test_the_customers_schema_bounds_lists_and_forbids_extras`: top level `additionalProperties is False`, required `["customers", "seller_domains"]`; `customers.maxItems == 300`; item required `["name", "domains", "relationship", "evidence_kind", "quote"]`; `relationship.enum == ["direct", "through_coalition", "through_marketplace", "weak_mention"]`; `evidence_kind.enum == ["logo_wall", "case_study", "testimonial", "press", "review", "tracker", "other"]`; `domains.maxItems == 10`; `via` is nullable string; `seller_domains.maxItems == 10`.
- [ ] **Step 2: Run** `uv run pytest tests/arv2/test_onboarding_requests.py -p no:cacheprovider` — Expected: FAIL (names not defined).
- [ ] **Step 3: Implement.** Query text (spec §4.1, seller-agnostic):
  > Find every company that is an existing customer of {company_name} ({domain}). First work out what buying from {company_name} means. Then read {company_name}'s own site: its sitemap, customers and case-study pages, press releases, news and logo walls. Then search announcements by buyers themselves, news coverage, reviews, and the industry's own purchase trackers or registries. List every customer found, with every website domain it uses.

  System prompt:
  > List only companies that buy or use the product, directly or through a buying coalition or marketplace; name the coalition or marketplace in `via`. Leave out investors, grant-givers, registries, technology and integration partners, suppliers and competitors, even when they appear on the same logo wall. Every customer must be named on a page you found; never infer a customer from its industry. Give every website domain the customer uses, a group's brand domains as well as its corporate one. Check that each domain's website is really that company; otherwise leave it out. Mark a sweeping claim such as "300+ brands including X" as weak_mention. Quote verbatim, at most 40 words. Also list every domain the seller itself uses in seller_domains.

  Schema per the test; `quote` description "verbatim, 40 words max"; follow `customer_reviews_output_schema` style (`_nullable`, `_string_list`).
- [ ] **Step 4: Run** the same command — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "Onboarding: the existing-customers Exa Agent request"`

### Task 3: Domain check

**Files:**
- Create: `platform/api/clue_api/arv2/customer_domains.py`
- Test: `tests/arv2/test_customer_domains.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class DomainCheck: status: Literal["confirmed", "unconfirmed"]; title: str | None`; `check_domains(caller: ProviderCaller, customers: Sequence[Mapping[str, Any]]) -> dict[str, DomainCheck]` (keyed by the domain as written); `names_company(name: str, page: str) -> bool`.

- [ ] **Step 1: Write failing tests** (a `ScriptedTransport` caller, as in `tests/arv2/test_media_resolution_fixes.py`):
  - `test_a_page_that_names_the_company_is_confirmed`: `<title>Casago - Vacation Rentals</title>` for name `Casago` → `confirmed`, title kept.
  - `test_a_page_about_another_business_is_unconfirmed_and_kept`: `wynwoodhouse.us` answering `<title>Personal Care Communities | State College</title>` for `Wynwood House` → `unconfirmed`, title `"Personal Care Communities | State College"`.
  - `test_a_domain_that_does_not_answer_is_unconfirmed`: transport error / HTTP 403 → `unconfirmed`, `title is None`.
  - `test_names_company_tolerates_case_spacing_and_suffixes`: `names_company("Mitsui O.S.K. Lines, Ltd.", "MOL - Mitsui O.S.K. Lines")` is True; `names_company("Olala", "<html></html>")` is False.
  - `test_each_domain_is_fetched_once`: two customers sharing `hilton.com` → one request.
- [ ] **Step 2: Run** `uv run pytest tests/arv2/test_customer_domains.py -p no:cacheprovider` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement.** One `GET https://<domain>/` per distinct domain through `caller.call(CallSpec(provider="public_media", operation="GET", label="onboarding.customer_domain", request=HttpRequest(method="GET", url=..., headers=PUBLIC_HEADERS, timeout_s=20), max_attempts=1))`, after `public_url(...)` (both from `media_resolution`). `names_company` compares the name's significant words (lowercased, punctuation and company suffixes such as "inc", "ltd", "llc", "group" dropped) against the page's `<title>` and the first 5,000 characters of visible text; confirmed only when all significant words of the name, or its full joined form, appear. Any exception means `unconfirmed`.
- [ ] **Step 4: Run** the same command — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "Onboarding: label each customer domain confirmed or unconfirmed from its homepage"`

### Task 4: The `proof/customers.md` document

**Files:**
- Modify: `platform/api/clue_api/arv2/onboarding_documents.py` (add to `__all__`)
- Test: `tests/arv2/test_onboarding_documents.py`

**Interfaces:**
- Consumes: `DomainCheck` (Task 3).
- Produces: `existing_customers_document(run: ExaAgentRun, *, company_domain: str, as_of: date, checks: Mapping[str, DomainCheck]) -> KnowledgeDocument` with `kind="existing-customers"`, `folder="proof"`, `path="proof/customers.md"`.

- [ ] **Step 1: Write failing tests** (build the run with the file's `_agent`-style helper):
  - `test_the_customers_list_lives_in_the_body_only`: `"customers" not in doc.front_matter` and `"seller_domains" not in doc.front_matter`; `front_matter["kind"] == "existing-customers"`; `"sources" in doc.front_matter`.
  - `test_the_table_shows_domains_with_their_check_how_they_buy_and_the_quote`: body contains `"# Existing customers"`, a table header `| Customer | Domains | How they buy | Evidence | Quote |`, a row with `"wynwoodhouse.us (unconfirmed: Personal Care Communities | State College)"` (pipe escaped by `_table`), `"through_coalition via Frontier"`, and the quote.
  - `test_the_sellers_own_domains_have_their_own_line`: body contains `"Seller's own domains: altcarbon.com, alt-carbon.com"`.
  - `test_a_failed_run_still_renders_with_its_failure_note`: status `failed` → body has `_failure_note` text and `_Not established._`.
- [ ] **Step 2: Run** `uv run pytest tests/arv2/test_onboarding_documents.py -p no:cacheprovider` — Expected: FAIL.
- [ ] **Step 3: Implement** after `customer_reviews_document`: `_run_header(run, kind="existing-customers", as_of=..., company_domain=...)` plus `_run_footer(run)`; body = title, the table (one row per customer, sorted by name; domains joined by `", "` with `" (unconfirmed: <title or 'no answer'>)"` appended to unconfirmed ones), the seller-domains line, `_sources_section`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "Onboarding: render proof/customers.md with the list in the body"`

### Task 5: The onboarding step, the setting and the `customers` run kind

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (after `onboarding_product_effort`, ~L602), `.env.example` (after L290; extend the L287 price comment with `xhigh $1.00`), `tests/arv2/test_onboarding_settings.py` (`ONBOARDING_SETTING_DEFAULTS`)
- Modify: `platform/api/clue_api/arv2/onboarding_driver.py` (`_Scope.kind`, `_scope`, `_run`, `_agent_step`, new `_customers`, `_customers_only`)
- Modify: `platform/api/clue_api/arv2/onboarding_store.py` (new `create_customers_run`), `platform/api/clue_api/onboarding_routes.py` (`DbOnboardingEnqueuer.enqueue_customers`)
- Test: `tests/arv2/test_onboarding_driver.py`, `tests/arv2/test_onboarding_driver_db.py`, `tests/arv2/test_onboarding_store_db.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces: setting `onboarding_customers_effort: str = "xhigh"` (env `CLUE_ONBOARDING_CUSTOMERS_EFFORT`); `_agent_step(..., finish: Callable[[ExaAgentRun], Awaitable[KnowledgeDocument]] | None = None)` — when given it replaces `mapper`; payload `kind: "customers"`; `create_customers_run(conn, *, run_id: UUID, workspace_id: str, brand_id: str, company_domain: str, requested_by_user_id: str | None) -> None`; `DbOnboardingEnqueuer.enqueue_customers(*, run_id, workspace_id, brand_id, company_domain, company_name) -> None` (payload as `enqueue` plus `"kind": "customers"`).

- [ ] **Step 1: Write failing tests:**
  - settings: add `"onboarding_customers_effort": "xhigh"` to `ONBOARDING_SETTING_DEFAULTS` (the existing env-doc test then fails until `.env.example` has `CLUE_ONBOARDING_CUSTOMERS_EFFORT=xhigh`).
  - `test_a_full_run_researches_customers_in_the_background_with_xhigh`: with `FakeExa` answers including `"customers"`, the `customers` call has `effort == "xhigh"`, lands `proof/customers.md`, and starts after the fast lane (its step phase is `"background"`).
  - `test_the_customers_step_checks_domains_and_drains_their_rows`: the domain-check GETs land through `_drain` with step label `"customers"`; an `unconfirmed` domain is still in the published body.
  - `test_a_customers_run_takes_only_the_customers_step`: payload `kind="customers"` → exactly one step (`customers`), no overview/lineup/synthesis, run finished.
  - Update existing assertions: `_all_answers()` gains `"customers"`; `test_every_provider_step_drains_its_rows_with_the_run_as_the_job` expects `"customers"` among labels; the fast-lane order test is unchanged (customers is background).
  - DB (`test_onboarding_store_db.py`): `test_a_customers_run_is_created_with_its_kind` — row `kind == 'customers'`, `persona_icp_document_id IS NULL`.
- [ ] **Step 2: Run** `uv run pytest tests/arv2/test_onboarding_settings.py tests/arv2/test_onboarding_driver.py -p no:cacheprovider` and the DB file on the test DB — Expected: FAIL.
- [ ] **Step 3: Implement.** `_customers(scope)` calls `_agent_step(kind="customers", phase="background", folder="proof", path="proof/customers.md", doc_kind="existing-customers", query=existing_customers_query(...), schema=existing_customers_output_schema(), effort=self._settings.onboarding_customers_effort, system_prompt=EXISTING_CUSTOMERS_SYSTEM_PROMPT, finish=...)`. The `finish` callback builds a `ProviderCaller(transport=PublicMediaTransport(), raw_sink=raw, ledger=ledger, ...)` (precedent `account_research_tools.py:565-575`), runs `check_domains` via `asyncio.to_thread`, drains with `self._drain(scope, raw, ledger, step_label="customers")`, and returns `existing_customers_document(...)`. A `finish` exception settles the step `failed` like a provider error. Append `self._customers(scope)` to `background` in `_run`. `_scope` accepts `"customers"`; `_run` routes it to `_customers_only` (mark running → `_customers` → `finish_run`).
- [ ] **Step 4: Run** the commands — Expected: PASS. Also `uv run pytest tests/arv2 -k onboarding -p no:cacheprovider --ignore-glob='*_live.py'` (DB tests on the test DB) — Expected: all pass.
- [ ] **Step 5: Commit** — `git commit -m "Onboarding: research the seller's existing customers in the background; customers-only run kind"`

### Task 6: `exclude` on the brief and `launch_arv2_discovery@3`

**Files:**
- Modify: `platform/api/clue_api/arv2/discovery_request.py`, `platform/api/clue_api/arv2/discovery_launch.py` (`_request_sha256` L449-468; new `LaunchArv2DiscoveryV3Input`/`LaunchArv2DiscoveryV3Tool` after L912; register beside `@2`)
- Test: `tests/arv2/test_discovery_request.py`, `tests/api/test_arv2_launch_tools.py`, `tests/arv2/test_discovery_launch_db.py`

**Interfaces:**
- Produces: `class ExcludedCompany(BaseModel)` (`extra="forbid"`; `name: str` 1–200; `domains: list[str]` 1–10, each must give a non-empty `registrable_domain`); `DiscoveryBrief2.exclude: list[ExcludedCompany] = Field(default_factory=list, max_length=500)`; `excluded_domains(brief: DiscoveryBrief2) -> dict[str, str]` (registrable domain → first entry's name). `@2` keeps its input schema byte-identical and never sends `exclude`.

- [ ] **Step 1: Write failing tests:**
  - `test_exclude_entries_are_bounded_and_need_a_real_domain`: 501 entries refused; a domain `"not a domain"` refused; `name` of 201 characters refused.
  - `test_excluded_domains_fold_spellings_and_keep_the_first_name`: entries `("Acme", ["https://www.Acme.com/"])`, `("Acme Inc", ["acme.com"])` → `{"acme.com": "Acme"}`.
  - `test_a_shared_host_entry_names_only_that_site`: `("Acme Shop", ["acme.myshopify.com"])` → `{"acme.myshopify.com": "Acme Shop"}`; `"other.myshopify.com"` is not a key (the fold keeps per-site hosts apart, checked 2026-10-16).
  - `test_a_subdomain_is_matched_as_written`: `("Marriott", ["marriott.com"])` → `"blog.marriott.com"` is not a key (the fold drops only `www`); the skill tells the agent to give every domain, so this is the documented behaviour, not a gap.
  - `test_an_old_brief_without_exclude_keeps_its_request_hash`: `_request_sha256` of a brief with `exclude=[]` equals the sha computed from the same payload without the key (the function drops an empty `exclude`).
  - Tool: `test_v3_passes_exclude_into_the_brief` (the request's `brief.exclude` equals the input); `test_v2_input_schema_is_unchanged` (the `@2` input JSON schema has no `exclude`); update `_BRIEF` comparisons only where `@3` is used.
- [ ] **Step 2: Run** `uv run pytest tests/arv2/test_discovery_request.py tests/api/test_arv2_launch_tools.py -p no:cacheprovider` — Expected: FAIL.
- [ ] **Step 3: Implement** the model, the helper and `@3` (same as `@2` plus `exclude: list[ExcludedCompany] = []`, included in the `include={...}` set; `safe_display_fields` unchanged). `_request_sha256` removes `"exclude"` from the brief payload when it is empty.
- [ ] **Step 4: Run** — Expected: PASS. Then the catalog/authority tests: `uv run pytest tests/agents/test_tool_authority_audit.py tests/api/test_toolbelt_wiring.py -p no:cacheprovider` — Expected: PASS after registering `@3` where `@2` is listed.
- [ ] **Step 5: Commit** — `git commit -m "Discovery: launch_arv2_discovery@3 takes an exclude list on the brief"`

### Task 7: The driver skips excluded domains everywhere and records them

**Files:**
- Modify: `platform/api/clue_api/arv2/discovery_store.py` (`Disposition` L101-103; `CandidateRow` + `_CANDIDATE_COLUMNS` L145-149 + `upsert_candidate` L736-779 gain `excluded_by_entry`; `project_found_domains` L835-856; new `seller_domain`)
- Modify: `platform/api/clue_api/arv2/discovery_driver.py` (`_RunState`, `_compose`, `_run_search_round`, `_tick`, `_pre_spend_disposition`, `_land`, `build_summary`, `_failure_summary`, `summary_message`)
- Test: `tests/arv2/test_discovery_driver.py`, `tests/arv2/test_discovery_store_db.py`

**Interfaces:**
- Consumes: `excluded_domains` (Task 6); disposition `excluded_by_brief` (Task 1).
- Produces: `seller_domain(conn, *, workspace_id: str, brand_id: str) -> str | None` (latest `onboarding_run` with `kind='full'` and status `completed`/`completed_with_gaps`, `ORDER BY requested_at DESC LIMIT 1`, folded with `registrable_domain`); `_RunState.excluded_domains: dict[str, str]`; `_RunState.brief_excluded: list[str]` (names); receipt key `"excluded_by_brief": int`; summary keys `"excluded_by_brief": int` and `"excluded_by_brief_example": str | None`.

- [ ] **Step 1: Write failing tests** (offline, `_Store` gains `seller_domain=` kwarg; the `_handler` fixture is otherwise unchanged):
  - `test_a_webset_item_on_the_exclude_list_is_recorded_and_never_verified`: brief `exclude=[("Marriott", ["marriott.com"])]`, webset item `https://www.marriott.com` → one `upsert_candidate` with `disposition="excluded_by_brief"`, `excluded_by_entry="Marriott"`; `exa.gate_queries() == []` and no website Answer call for it.
  - `test_a_search_hit_on_the_exclude_list_is_recorded_before_any_spend`: same through the `search` source.
  - `test_a_verified_domain_on_the_list_is_caught_after_a_redirecting_url`: item URL `https://marriott-bonvoy.example` whose website Answer verifies `marriott.com` → `excluded_by_brief`, no gate calls.
  - `test_the_sellers_onboarding_domain_is_skipped_without_any_exclude`: `seller_domain="conduit.ai"`, item `https://conduit.ai` → `excluded_by_brief`, `excluded_by_entry="seller"`.
  - `test_no_onboarding_run_means_only_the_brief_excludes` (Review Focus 5): `seller_domain=None` → run completes, nothing extra skipped.
  - `test_a_resumed_run_recounts_its_brief_exclusions_once` (Review Focus 2): `_Store(candidates=[<excluded_by_brief row for marriott.com>])` and a webset that returns `marriott.com` again → no second upsert; receipt `excluded_by_brief == 1`.
  - `test_an_old_run_without_exclude_resumes_unchanged` (Review Focus 4): `_run_row(brief=_brief_json())` (no `exclude` key) → composes and runs.
  - `test_the_summary_counts_brief_exclusions`: summary `excluded_by_brief == 2`, example `"Marriott"`; `summary_message` contains the line `"Excluded by the brief (existing customers or the seller): 2 — e.g. Marriott."`; the existing summary-text tests (L2345-2395) still pass unchanged when the count is 0 (the line is omitted).
  - DB (`test_discovery_store_db.py`): `test_brief_exclusions_are_not_found_before_for_later_runs` — an earlier run's `excluded_by_brief` candidate is absent from `project_found_domains`; `test_seller_domain_reads_the_latest_completed_full_run`.
- [ ] **Step 2: Run** `uv run pytest tests/arv2/test_discovery_driver.py -p no:cacheprovider` and the store DB file — Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `_compose`: `state.excluded_domains = excluded_domains(brief2)`; then, if `seller_domain(...)` returns a domain not already present, add it with name `"seller"`. The rebuild loop (L571-583) adds `excluded_by_brief` candidates' domains to `state.seen` and their names to `state.brief_excluded`.
  - One helper `_record_brief_exclusion(state, item, domain) -> None` writes `CandidateRow(..., disposition="excluded_by_brief", excluded_by_entry=state.excluded_domains[domain])` via `upsert_candidate`, appends the name, and adds the domain to `state.seen`. Called from `_tick` (before claiming; on the item URL's registrable domain), from `_run_search_round` (before the `known` check), and from `_verify_candidate` when `_pre_spend_disposition` returns `"excluded_by_brief"` for the verified domain (checked first in that function).
  - `project_found_domains` adds `AND disposition <> 'excluded_by_brief'`.
  - Receipt, `build_summary`, `_failure_summary` and `summary_message` as the tests pin.
- [ ] **Step 4: Run** — Expected: PASS. Then the whole discovery set: `uv run pytest tests/arv2 -k discovery -p no:cacheprovider --ignore-glob='*_live.py'` (DB tests on the test DB) — Expected: all pass.
- [ ] **Step 5: Commit** — `git commit -m "Discovery: skip the brief's excluded companies and the seller before any spend, recorded as excluded_by_brief"`

### Task 8: Websets exclude the list upfront through an Exa Import

**Files:**
- Modify: `platform/api/clue_api/arv2/exa_websets_client.py` (new `create_import`, `upload_import`, `get_import`; `create(..., exclude_import_ids: Sequence[str] = ())`)
- Modify: `platform/api/clue_api/arv2/discovery_driver.py` (`_ensure_import`, used by `_run_search` L757-767); `libs/clue-config/clue_config/settings.py` + `.env.example` (`arv2_discovery_import_wait_s: int = 120`, env `CLUE_ARV2_DISCOVERY_IMPORT_WAIT_S=120`)
- Test: `tests/arv2/test_exa_websets_client.py`, `tests/arv2/test_discovery_driver.py`

**Interfaces:**
- Produces: `ExaWebsetsClient.create_import(*, domains: Sequence[str], title: str) -> ImportHandle` (`ImportHandle(import_id: str, upload_url: str)`), `upload_import(*, upload_url: str, csv_bytes: bytes) -> None`, `get_import(import_id: str) -> str` (the status); `create(..., exclude_import_ids=...)` appends `{"source": "import", "id": ...}` after the webset entries; `_RunState.import_id: str | None`.

- [ ] **Step 1: Write failing tests:**
  - Client (`_caller`/`_client` helpers, `ScriptedTransport`): `test_an_import_is_created_as_a_company_csv_of_urls` — POST `/websets/v0/imports` body `{"format": "csv", "entity": {"type": "company"}, "count": 2, "size": <len(csv)>, "title": ..., "csv": {"identifier": 1}}`; `test_the_csv_is_uploaded_to_the_returned_url` — PUT to `upload_url` with body `b"url\nhttps://marriott.com\nhttps://nobuhotels.com\n"`; `test_a_webset_can_exclude_an_import` — `search["exclude"] == [{"source": "webset", "id": "w1"}, {"source": "import", "id": "i1"}]`.
  - Driver (`_FakeWebsets` gains the three methods): `test_websets_rounds_exclude_the_brief_through_one_import` — two rounds, one `create_import`, both `create` calls carry `exclude_import_ids=("i1",)`; `test_an_import_still_processing_at_the_deadline_is_skipped_and_the_domain_skip_still_applies` — `get_import` returns `"processing"` until `arv2_discovery_import_wait_s=0` → `create` has no import, an excluded item is still recorded `excluded_by_brief`, and `"brief_import_unavailable"` is in the receipt's `guards`; `test_no_exclusions_means_no_import` — empty set → `create_import` never called.
- [ ] **Step 2: Run** `uv run pytest tests/arv2/test_exa_websets_client.py tests/arv2/test_discovery_driver.py -p no:cacheprovider` — Expected: FAIL.
- [ ] **Step 3: Implement.** Client methods go through `_call` (operations `"import-create"`, `"import-upload"`, `"import-get"`; zero-cost estimate). `_ensure_import(state)` runs once per run before the first websets round when `state.excluded_domains` is non-empty: create, upload the CSV (header `url`, one `https://<domain>` per row, sorted), poll `get_import` every 5 s until `completed` or the wait setting runs out; any failure or a non-completed status records the guard and leaves `import_id=None`. The CSV `identifier` value (1 = first column per Exa's docs example) is confirmed in Task 10's live check; if Exa answers `missing_identifier`, change it to 0 there.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "Discovery: websets exclude the brief's companies upfront through an Exa Import"`

### Task 9: The run read shows brief exclusions apart

**Files:**
- Modify: `platform/api/clue_api/arv2/read_tools.py` (`read_discovery_run` L1126-1141; `DiscoveryCandidateV3View` L947-956 gains `excluded_by_entry: str | None`), `platform/api/clue_api/arv2/project_status.py` (~L188 excluded count includes `excluded_by_brief`)
- Test: `tests/api/test_arv2_read_tools.py`

**Interfaces:**
- Consumes: disposition and column from Tasks 1 and 7.

- [ ] **Step 1: Write a failing test** next to L881: `test_brief_exclusions_are_served_apart_with_their_entry` — a run with one `excluded_by_brief` candidate (`excluded_by_entry="Marriott"`) → it is in `excluded`, not in `candidates`; its view has `excluded_by_entry == "Marriott"`; `excluded_total` counts it.
- [ ] **Step 2: Run** `uv run pytest tests/api/test_arv2_read_tools.py -p no:cacheprovider` (DB on the test DB) — Expected: FAIL.
- [ ] **Step 3: Implement:** the `excluded_apart` split treats `disposition in ("excluded", "excluded_by_brief")` as excluded; order by `(excluded_by_gate or excluded_by_entry or "", name)`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "Discovery read: brief exclusions are listed with the excluded companies"`

### Task 10: The Head of ABM reads the customer page and fills `exclude` (skill v45, profile v72)

**Files:**
- Create: `platform/agents/catalog/skills/stage0-interview/v45/SKILL.md` (copy of v44), `platform/agents/catalog/profiles/head-of-abm/v72/profile.yaml` (copy of v71); manual chapters re-minted by `make manual` if the tool notes change their generated text (then every `manual-*` chapter moves to `v18` and `MANUAL_VERSION = "v18"`)
- Modify: `platform/agents/catalog/manual/tool_notes.yaml` (L105-131: key the note to `@3`; fix the stale "v43" to "v45"), `platform/api/clue_api/agent_registry_wiring.py:261` (`"v72"`), `platform/agents/clue_agents/manual/build.py:76,80`, `platform/api/clue_api/chat/composer_context.py:70` (`head-of-abm@v72`)
- Test: `tests/agents/test_catalog.py` (add the new `skill:`/`profile:` entries), `tests/api/test_agent_registry_wiring.py` (L174, L619, L661), `tests/api/test_comprehensive_research_contract.py:470-471`, `tests/api/test_client_knowledge_privacy_s4e.py:161`

**Interfaces:**
- Consumes: `launch_arv2_discovery@3` (Task 6).

- [ ] **Step 1: Write the skill text** (founder-approved wording, spec §4.7). In v45:
  - §1 (L86): add `brand/knowledge/proof/customers.md` beside `proof/customer-reviews.md`.
  - §7b "What you write": add the bullet: "`exclude`: the companies this search must leave out, each with its domains." — and, before "Before you call", the approved paragraph: "Before you launch discovery, read `brand/knowledge/proof/customers.md`. It lists the companies that already buy from the seller, how they buy, and the evidence. Put on the brief's `exclude` list every company the seller would not want to approach as a new prospect: always the direct customers, and the ones that buy through a coalition or marketplace unless this search is meant to reach them. A weak mention is your call. Give each its domains as written there, and add the seller's own domains. If the document is missing, say so to the person and go ahead without it."
  - §7b "When it ends": "If the summary says the brief excluded companies, say how many in one sentence (for example "four are already your customers")."
  - Front matter: `version: v45`, tool pin `launch_arv2_discovery@3`.
- [ ] **Step 2: Mint profile v72**: copy v71; `version: v72`; repin `stage0-interview` to `v45` with `shasum -a 256` of the new SKILL.md; replace the `launch_arv2_discovery` tool pin with `@3` and its input/output schema shas (from the catalog test's failure output or `uv run python -m clue_api.manual_build`); move the active-version constants listed above.
- [ ] **Step 3: Run** `make manual` then `make manual-check` — Expected: clean. Then `uv run pytest tests/agents tests/api/test_agent_registry_wiring.py tests/api/test_comprehensive_research_contract.py tests/api/test_client_knowledge_privacy_s4e.py -p no:cacheprovider --ignore-glob='*_live.py'` — Expected: FAIL first on the pinned lists, then PASS once the new entries/versions are added.
- [ ] **Step 4: Commit** — `git commit -m "Head of ABM v72: read proof/customers.md and pass the brief's exclude list (stage0-interview v45)"`

### Task 11: Backfill script for brands onboarded before this

**Files:**
- Create: `scripts/backfill_existing_customers.py`
- Test: `tests/scripts/test_backfill_existing_customers_db.py`

**Interfaces:**
- Consumes: `create_customers_run`, `DbOnboardingEnqueuer.enqueue_customers` (Task 5).

- [ ] **Step 1: Write failing DB tests:** `test_dry_run_lists_brands_without_a_customers_page_and_writes_nothing` — a brand with a completed full run and no `proof/customers.md` is listed; no `onboarding_run` row is added; `test_apply_creates_one_customers_run_per_brand_and_skips_brands_with_an_open_run`.
- [ ] **Step 2: Run** on the test DB — Expected: FAIL.
- [ ] **Step 3: Implement** a standalone script (`set -a; source .env; set +a; uv run python scripts/backfill_existing_customers.py [--apply] [--workspace ws_...]`): select brands whose latest `kind='full'` run is completed and that have no live `proof/customers.md` document and no open run of any kind; print name, domain and "~$1"; with `--apply`, `create_customers_run` + `enqueue_customers` per brand.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "Script: backfill the existing-customers page for already-onboarded brands (dry run by default)"`

### Task 12: Live confirmation (founder-approved spend, ~$4)

Not a code task; run after Tasks 1–11 on the nashville lane stack with real keys, only after the founder says go.

- [ ] Run a `customers` run for Conduit AI and Alt Carbon (Task 11 script with `--workspace`). Score `proof/customers.md` against the 2026-10-16 reference lists (Conduit: 29; Alt Carbon: 15 + John Good Group). Expected: comparable to the playground runs; every unconfirmed domain labelled; no list in front matter.
- [ ] One discovery per seller with the Head of ABM: Expected: the brief carries `exclude`; the Exa Import completes (confirms the CSV `identifier`); no listed customer is added; the wake report states the brief exclusions.
- [ ] Record results and costs in `_memory/`.

---

## Self-review notes

- Spec coverage: §4.1 → Tasks 2, 5; §4.2 → 3; §4.3 → 4; §4.4 → 5, 11; §4.5 → 6; §4.6 → 7, 8, 9; §4.7 → 10; §6 testing → each task + 12.
- Ruling recorded here (not in the spec): the brief field ships as a new tool version `launch_arv2_discovery@3` rather than an in-place change to `@2`, because the profile pins the tool's input schema hash and historical profiles must stay loadable. Cost if wrong: one extra registered tool address.
- Ruling recorded here: brief-excluded companies are not "found before" for later runs (Task 7), so a person's correction to the customer page takes effect on the next run.

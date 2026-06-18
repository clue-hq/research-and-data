# Clue-HQ — Front Edge: Client Reverse-Profiling, ICP Co-definition & Entry Scenarios

### Doc B. Extends the substrate doc §8 (client knowledge) and the staged-flow doc §2 (Stage 0).

Research is the seed of the whole platform, and **Stage 0 is the seed of research.** Every downstream direction — which accounts we look for, which signals we weigh, which sources we trust, what argument we eventually make — is determined here. The original docs treat Stage 0 as "client gives a vague description → we propose a structured ICP." That under-serves the real requirement: the platform must work from **near-zero input** and must treat the two ways accounts enter the system as **first-class, symmetric paths.** This doc specifies both.

---

## 1. The minimum-input contract

**Worst case, we have only the client's company name and website.** Everything else — what they sell, to whom, their differentiators, their proof points, their candidate ICPs — must be *derived*, not required as a form. Anything the client volunteers on top of that (a deck, a customer list, a target description, exclusions) is treated as high-trust input that shortcuts derivation, never as a precondition.

This is a hard product stance: a client who pastes a URL and nothing else must still reach a confirmed ICP and a running discovery job. The platform always *suggests*; the client always *has the wheel*.

---

## 2. Client Reverse-Profiling — research pointed inward

Before we can research targets, we research the **client themselves**, using the same machinery the rest of the subsystem uses on accounts (identity resolution → trust-tiered waterfall → claims with provenance), aimed at the client's own footprint:

- **Owned surfaces** — the website, product/pricing/docs pages, careers page, blog.
- **Positioning & proof** — case studies, testimonials, logos, "customers" pages → these double as **seed accounts** for lookalike discovery (§5).
- **Third-party footprint** — G2 / Capterra / TrustRadius category and reviews, directories, news, social presence.
- **Reviews-as-signal** — what *their* customers say they bought it for is the most honest statement of the value the client actually delivers.

Output: a typed, versioned **Client Knowledge Base** (the substrate doc §8 store), holding provenance-backed claims about: what the client sells, the problems it solves, differentiators, ideal-customer evidence (industries, sizes, geos of existing customers), pricing posture, and proof points. This is also the source of the *client side* of every later value narrative (Output 4), so it must be versioned — positioning and pricing drift.

**Quality ceiling note (from substrate §8):** the depth of this base sets the ceiling on every artifact downstream. A thin client profile produces generic value narratives no matter how deep the account research goes. Reverse-profiling is therefore not onboarding boilerplate; it is the first real research run.

---

## 3. ICP Synthesis — proposing whom to target

From the Client Knowledge Base, the platform **synthesizes candidate ICPs** and proposes them. Each proposed ICP is a structured hypothesis, not prose:

- **Firmographic dimensions** — industry/vertical, size band, geo, revenue band.
- **Technographic / vertical dimensions** — the pack-specific fields that matter for this industry (substrate §3 packs).
- **Candidate signals** — the intent/growth/hiring signals worth scoring on (Doc C §1).
- **Seed accounts** — drawn from the client's existing customers and obvious lookalikes, as concrete anchors the client can react to.
- **A starting source profile** — which sources matter for this ICP (staged-flow §7).
- **A scoring rubric** — fit + intent weights over the active fields.

The client edits, adds, removes, and confirms. Confirmation compiles (substrate §3 research-plan builder) into the **versioned ICP spec** that the next stages execute against — reproducible because it is versioned.

**Support multiple ICPs per client (recommended — D5).** A real client often sells into several segments (e.g. "mid-market fintech" *and* "enterprise healthcare payers"). Each confirmed ICP compiles its own research plan, discovery strategy, source profile, and scoring rubric, and runs as its own campaign. Treating "one client = one ICP" would force clients to either pick a single segment or pollute one rubric with two audiences. The substrate carries no cost for this — ICP specs are just versioned config rows.

---

## 4. The two entry scenarios — first-class and symmetric

Accounts enter the system one of two ways. Both are fully supported; both converge at the Pass A scoring bridge.

### Scenario A — Discovery (we find the accounts)
ICP spec → **M1 Account Discovery** (staged-flow §3): grounded-only, recall-optimized, existence/identity-gated. Candidates may only originate from real returned records/URLs (structured-DB ICP search, web entity discovery, curated lists, lookalike expansion from seeds); the LLM may plan and expand queries but may never *be* the source of an entity. Each candidate clears the existence/identity gate before admission. *No deep facts yet* — discovery yields admitted candidates with discovery-provenance; signals come at Pass A (Doc C §1).

### Scenario B — Import (the client brings the list)
This is **not** a trivial branch — it has its own hard sub-pipeline:

1. **Bulk identity resolution over messy free-text.** A client list arrives as names/domains of varying quality ("IBM", "I.B.M.", "International Business Machines Corp.", a stale domain). Each row must resolve through the identity service (substrate §2) to a canonical `account_entity` — deterministic on domain/registry-ID, probabilistic + review-queue otherwise. This is where import quietly fails if under-built: duplicates, wrong-entity collapses, and unresolvable rows all need explicit handling, not a silent best-guess.
2. **ICP back-scoring.** The client picked these accounts, but we still score them against their *own stated ICP*, because the most valuable early signal we can give is *"3 of your 200 accounts don't actually match the ICP you defined"* — or *"these 40 are dramatically better-fit than the rest."* Import does not skip scoring; it skips *discovery*.
3. **Convergence.** Resolved, back-scored accounts flow into the same Pass A → tiering → checkpoint → Pass B path as discovered accounts.

### Hybrid (A + B)
The client's imported list (and their existing customers from reverse-profiling) are the **strongest seeds for lookalike discovery.** The natural default for a client who brings a list is: research *their* accounts **and** discover lookalikes of them, surfaced as "accounts like yours you may have missed." Import and discovery are not exclusive; import is often the highest-quality way to *start* discovery.

**Import-list non-fit behavior (recommended — D6):** flag and proceed. Surface the misfit to the client (with the evidence behind the low fit score) and let them keep or drop. Do not silently exclude (the client may know something the ICP doesn't encode) and do not auto-re-derive the ICP (that's a bigger action the client should choose). Re-deriving the ICP *from* the imported list is offered as an explicit option, not a default.

---

## 5. Output of Stage 0

- One or more **versioned ICP specs** (field set + discovery strategy + source profile + scoring rubric).
- A versioned **Client Knowledge Base** (the client side of every value narrative).
- For Scenario B: a set of **resolved, back-scored imported accounts**, plus seeds for optional lookalike discovery.

These hand off to discovery (A), directly to the scoring bridge (B), or both (hybrid) — see the end-to-end map in the overview doc §2.

---

## 6. Open items (tracked in overview §5)

- **D5 — ICP multiplicity:** recommended to support multiple ICPs per client. Confirm.
- **D6 — Import non-fit behavior:** recommended flag-and-proceed; confirm vs. exclude / re-derive.
- **Reverse-profiling depth/budget:** reverse-profiling is a real research run with a cost. Recommended: a bounded deep pass on the *client* (it's one entity, run once, high leverage) rather than a cheap skim — the value-narrative ceiling justifies it. Confirm the budget.

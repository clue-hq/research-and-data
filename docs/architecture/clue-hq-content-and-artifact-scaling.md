# Clue-HQ — Content Plane & Artifact Scaling Architecture (Doc S)

> **Status: DESIGN RECORD v1.1 (2026-07-17 · v1.0 2026-07-16).** Authoritative for the layer between the research
> handoff and the design engine: artifact strategy, the content schema, per-account/per-contact
> content generation, template finalization, and scaled derivation. **Resolves overview doc open
> decision D2** — the design subsystem ingests *binding sets validated against a frozen template
> slot contract*; a content layer sits between research and design, as the output contract (§3 of
> the overview) assumed. The design engine itself is the `havana` repo (its docs are authoritative
> for scenes/slots/instances); this doc specifies how the platform drives it and what it lacks
> (§9 gap list, agreed asks).

## 1. Vocabulary (2026-07-16 remap)

- **Project** — one end-to-end ABM motion (what older docs call "campaign"; they retain the
  historical term until their own revision — harness doc §1a).
- **Campaign** — a channel program *within* a project: the mailer drop, the LinkedIn ads
  campaign, the micro-site/landing-page campaign, the email sequence. A project has many.
- **Artifact** — one deliverable kind within a campaign (the 4-page mailer report; the 3-slide
  ad; the landing page). An artifact **instance** is one account's/contact's personalized copy.
- **Personalization unit** — v1 supports **both** account-level and contact-level instances
  (founder, 2026-07-16); the unit is declared per artifact. The engine's `BindingAudience`
  already carries `{account_id, contact_id?}`; every key below includes `contact_id?`.

## 2. The compatibility spine: two schemas, one contract

The founder's instinct — *"the content-schema is the medium of compatibility"* — lands as two
coupled layers with an explicit mapping, because content semantics and design geometry are owned
by different minds:

- **Content schema (semantic; owned by the content plane).** Versioned config, per artifact:
  fields with key, purpose (*what message this field carries*), slot class (§4), voice notes,
  brevity band, and **claim sources** (which research fields / value-narrative sections /
  dossier blocks feed it). No geometry.
- **Slot contract (geometric; owned by the design template).** The finalized template revision's
  slot summary: keys, content types, `max_length`/formatting constraints, overflow policies,
  repeater rules + cardinality, validation fixtures (samples + worst_case).
- **Template binding (the mapping).** `content_schema field ↔ slot key ↔ template_revision_id`,
  checked total (every required slot fed; every field lands or is explicitly unused) at
  finalization. This record is what makes drafts, templates, and scaled instances provably
  compatible — nothing else has to "just line up."

## 3. The three-beat flow (strategy → exemplar → frozen contract)

**Beat 1 — Strategy (main deepagent + user, in the project thread).** The deepagent wears the
**VP-of-growth hat first**: which channel campaigns to run at all, for which account-signal
strengths and tiers (a high-touch mailer program for tier-1 high-intent accounts; ads-only for a
long tier-3 tail; …), informed by the industry's channel habits surfaced in research. Only then
the content strategy that follows per chosen campaign: artifact mix, message architecture, voice
(brand default per product profile), the brevity ladder across artifact kinds (mailer long-form →
landing mid → ads short). Output: `campaign` rows + `artifact_plan` rows + a **provisional
content schema** per artifact. Skills-guided; recorded as versioned config. *(Revised 2026-07-17:
campaign selection precedes artifact strategy — founder review.)*

**Beat 2 — Exemplar + template (the one real account).** The content-drafter **subagent** drafts
the full content for ONE representative high-fit account — never lorem — against the provisional
schema. The design handoff (§8) opens the design deepagent with this exemplar; the template is
authored *with real content in hand*, and design **pushes back on the schema** (tightens
max_lengths, sets repeater cardinality from what the page holds). Content leads semantically;
design leads structurally.

**Beat 3 — Finalize (the user's "finalize for campaign").** `POST /documents/{id}/finalize` →
immutable template revision. The exemplar content becomes `ValidationFixtures.samples`;
worst-case fixtures are calibrated; the template binding is checked total and recorded. From this
moment the slot contract is **the law every account's content must satisfy**, and the content
schema version is pinned to it.

Answering the serialization question directly: neither "content first" nor "design first" —
*semantic content first (Beats 1–2 start), geometry authoritative at finalize (Beat 3)*. The
frozen contract is where they meet; re-negotiation after finalize = new template revision.

## 4. Slot classes → engine concepts (the four box colors)

| Class (founder's color) | Meaning | Engine realization | Filled by |
|---|---|---|---|
| Static (cyan) | Verbatim across all instances | Baked template content — no slot | Nobody at scale |
| Programmatic (red) | Fill-in-the-blank from account/contact properties | `TextShort`/`NumberStat`/`Image` slot; `BindingHint.source_path` = registry field key | Deterministic resolver over promoted claims |
| Dynamic (green) | LLM-drafted per instance, guided (message, voice, length) | `TextLong` slot + constraints + fixtures + overflow policy | Fleet leaf call (§6), grounded in claims |
| Repeating (magenta) | Variable-count component, capped (e.g. before/after rows ×3–5) | `RepeaterGroup` slot + `RepeaterRule{min,max}` + `Cardinality` | Item list from research; see §6.3 |

In-sentence interpolation ("Dear {{first_name}} …") is **composed upstream** in the content
plane; the engine receives final strings per slot. (Span-level sub-slots exist as a future
engine option — not v1.)

## 5. Data model (platform backend; all versioned-config or append-only)

| Entity | Essentials |
|---|---|
| `product` | Doc A §4.2 — projects carry `product_id` |
| `project` | the ABM motion; owns threads, runs, catalog |
| `campaign` | channel program: `(project_id, channel, status)`; owns artifacts |
| `artifact_plan` | per campaign: artifact kinds, unit (account/contact), message arch, voice ref, brevity band |
| `content_schema` | per artifact, versioned (ledgered like `icp_spec`): fields per §2 |
| `template_binding` | `(artifact_id, content_schema_version, template_revision_id, field↔slot map, checked_total_at)` |
| `content_draft` | `(project, campaign, artifact, account, contact?, field_key, value, claim_refs[], status: generated\|edited\|approved, version, actor)` — the provenance-carrying atom; **the content-draft tab edits these** |
| `content_run` | the scaling run: envelope, canary state, counts, health |
| `campaign_artifact` catalog | REQ-21 drive view: `(project, kind, ref, title, status, thumbnail, actor, timestamps)` |

Provenance is non-negotiable: every dynamic draft carries `claim_refs[]`; a draft whose claims
are superseded is flagged stale (same discipline as derived claims, REQ-05).

## 6. The scaling pipeline (deterministic workers in the fleet shell — Doc A §1.3; the thinking happened in Beats 1–3)

User experience: **"proceed with scaling across all accounts"** → one `content_run` launches on
the detached worker. Idempotency key everywhere:
`(project, campaign, artifact, account, contact?, field_key, content_schema_version, template_revision_id)`.

Per unit (account or account×contact), per artifact:

1. **Programmatic resolve** (code): `BindingHint.source_path` → promoted claim current value →
   formatted string. Missing required claim → unit flagged, not invented.
2. **Dynamic draft** (a bounded drafting worker — fetch claims → draft → deterministic checks →
   grounding self-check → at most one guided retry; a governed micro-loop, honestly not an
   agent): inputs = field purpose, voice
   card, `max_length`, exemplar (the template's sample fixture — *the thing the agents copy from*,
   exactly the founder's template-as-guidance intent), and the unit's claims/value narrative.
   Output = text + `claim_refs[]`.
3. **Repeater items** (§6.3): select + draft item records, clamped to `[min,max]`.
4. **QA gates** (deterministic first, cheap): length/cardinality/required coverage; brand lexicon
   / banned phrases; then the **grounding judge** (M9-style leaf call: every drafted sentence
   entailed by its claim_refs — the faithfulness judge pointed at copy). Failures → regenerate
   (bounded retries) or flag; never silently truncate.
5. **Emit binding set** → engine `validate` (LUMG diagnostics) → **batch derive** → instances +
   fit reports + export artifacts. `beyond_worst_case`/overflow → repair queue; *systematic*
   overflow on a slot across units = a template/schema problem → fix at template (new revision) or
   schema, re-derive affected units. Repairs never happen on instances (engine rule, kept).
6. **Canary default**: top ~10 units end-to-end → health gate (fit reports + QA pass rates +
   spot-check surface) → fleet opens. Five-layer quality pyramid applies verbatim (REQ-10):
   caps/envelopes → per-output judges → per-unit gates → run supervisor aggregates → human
   exceptions + ranked review. Working default (founder may override): human reviews canary +
   flagged tail; the green tail ships on gates.

### 6.3 Repeater item selection (working default)

Which 3–5 before/after pairs an account gets is a **content judgment inside the leaf call**,
constrained deterministically: candidates only from promoted claims matching the item spec,
ranked by (claim confidence × persona relevance), clamped to cardinality; the selection rationale
+ per-item claim_refs are recorded. Pure top-N stays available as a config posture per artifact.

## 7. The review surface (Figma-Buzz-style table + preview)

A projection, not new machinery. Left table: rows = units (binding sets), columns = programmatic
+ dynamic field keys (values from `content_draft`), row status = QA + `fit_status`. Right pane:
the selected unit's derived instance preview. **Cell edit** = PATCH `content_draft`
(status→edited, actor recorded) → regenerate that unit's binding set → validate → re-derive that
one instance (deterministic, sub-second) → preview refreshes. Bulk edit of a static/template
element = template change = new revision + re-derive (with diff-scoped batch). All of it through
toolbelt tools — the human and the agent use the same verbs (REQ-20).

## 8. The design handoff (REQ-19 delegation, surface-bound)

The one place the main thread hands the user to another deepagent (Doc A §2.1 exception). The
handoff pack materializes into the design session's workspace (pointer discipline, files not
paraphrase): `brief.md` (artifact purpose, audience, message architecture), `content_schema.json`
(provisional), `exemplar_content.json`, brand kit ref + reference assets (e.g. an inspiration
PDF rides the RC reference-conditioning channel). The thread shows a typed handoff card
(REQ-21 object ref). On finalize, the template revision + slot contract flow back; the
`template_binding` is written; the thread narrates completion. Delegation is journaled with
envelope + pinned versions like any REQ-19 delegation.

## 9. Design-engine gap list (the agreed asks on havana; everything else exists)

| # | Gap | Ask |
|---|---|---|
| G1 | Repeaters not agent-authorable (raw `UpsertSlot` only; off the tool surface) | DSL grammar or author tool to declare `RepeaterGroup` + rule + cardinality |
| G2 | Repeater items are single-text (`BoundValue::List` of Text) | `Record` items (named sub-fields per item: before/after/icon) binding multi-slot item templates — clone/suffix machinery already supports the subtree side |
| G3 | Non-text item fields | rides G2 (image/icon per item) |
| G4 | Binding sets POST one-at-a-time | bulk `binding-sets:batch` endpoint (thousands-scale ergonomics) |
| G5 | `Paginate`/`ExpandContainer` declared but refused | later; v1 avoids via cardinality caps |
| G6 | No catalog/tenancy in the engine | **not an ask** — deliberate; the platform's `campaign_artifact` catalog wraps it |

## 10. Open items

- **O-S1 (flagged, standing):** dossier presentation format — before any upstream implementation
  binds content generation to the *dossier document shape* specifically (rather than claims +
  value narrative + block projection, which this doc consumes), notify the founder; the dossier
  as the research-presentation format is not final (2026-07-16). This doc deliberately reads from
  claims/narrative/blocks, not from rendered dossiers, so it is insulated either way.
- **O-S2:** review posture default (§6.6 canary + flagged tail) — founder confirm.
- **O-S3:** per-channel activation (v2) attaches here: instances already carry
  `InstanceLink`/QR hooks for landing pages + attribution-lite.

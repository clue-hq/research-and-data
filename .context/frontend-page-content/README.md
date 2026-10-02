# Frontend page content — how the database becomes the page

Written 2026-09-03 for the founder's frontend edit. Companion: `ZAFRAN-PAGES.md` (the three
pages, fully written from the real Zafran run), `VARI-KAUR-CONTACT-PAGE.md` (second contact page).

## 1. What the database gives us (and what it does not)

The claim store holds one row per fact. Nothing else — no prose, no headings, no "why it matters".
Every row the frontend will ever read has this shape (real row from `claims_zafran.json`):

| column | example |
|---|---|
| `entity` / `entity_key` | `contact` / `https://www.linkedin.com/in/nicholastfisher` |
| `field_key` | `contact.facet.hobby` |
| `value` | `"Hosts Cocktail Chemistry videos as a side hobby …"` |
| `evidence_span` (the quote) | `"It is a a side hobby for me… I basically film on my iPhone in my kitchen at home"` |
| `source_url` | `https://www.youtube.com/watch?v=8_YWBtq4eic` |
| `source_provider` / `observed_at` | `exa_contents+gemini` / `2026-09-02` |
| `priority` | P1 / P2 / P3 (stamped at write time) |
| `outreach_safe` | `true` / `false` |
| `use_class` | `professional_public` / `personal_public_self_stated` / `sensitive` |
| `claim_id` | `zaf-160` |

For Zafran that is 174 rows: 70 about the account, 104 about five people. 12 rows are
`outreach_safe: false` (the Cisco rumour, the ARR/burn commentary, the co-founder departure).

## 2. What the page is

Each page is a **fixed template of H1 sections**. The H1s never come from a model — they are the
product's vocabulary and they are the same on every account / contact:

| page | H1 sections (fixed) |
|---|---|
| Insights | Account insights → {Buying signals · Money & momentum · Tools they already use · How they sell, and who they win} · Contact insights · Context only (collapsed) |
| Account overview | What they do · Why they fit · Why now · Buying committee · How to approach · Watch-outs · (right rail: Core / Custom / Contacts / Activity) |
| Contact | Why this person · Their problem right now · Openers · Angles · Do not mention · (rail: email, LinkedIn, location, best channel, education) |

Each section has a **recipe**: the list of field keys it is allowed to draw from. Example:

| section | field keys that feed it |
|---|---|
| Contact → Their problem right now | `account.abm_program_maturity`, `account.hiring_velocity`, `account.open_requisitions`, `account.gtm_tooling_stack`, `account.operational_pain`, `contact.facet.recent_post`, `contact.facet.publications` |
| Contact → rail (no prose) | `core.work_email`, `contact.current_location`, `contact.network_statistics`, `contact.member_badges`, `contact.facet.alma_mater` — rendered as rows, never sent to Luna |
| Contact → Openers | `contact.facet.hobby`, `contact.facet.voice_quote`, `contact.facet.recent_post`, `contact.facet.publications`, `contact.facet.career_history`, `account.abm_program_maturity` — **only rows with `outreach_safe: true`** |
| Contact → Do not mention | every row with `outreach_safe: false` for this contact or its account |
| Insights → Buying signals | `account.open_requisitions`, `account.hiring_velocity`, `account.abm_program_maturity`, `account.strategic_moves`, `account.operational_pain`, `account.resonance.buying_culture` |
| Insights → Money & momentum | `account.recent_funding`, `account.total_funding`, `core.annual_revenue`, `core.revenue_band` |
| Insights → Tools they already use | `account.gtm_tooling_stack`, `core.primary_tech_stack`, `core.tech_stack_categorised`, `contact.facet.publications` (tool mentions) |
| Insights → How they sell, and who they win | `account.named_customers`, `PROPOSED::account.claimed_customer_logos`, `PROPOSED::account.claimed_outcomes_metrics`, `account.resonance.public_frustrations`, `account.resonance.eng_blog_tone` |
| Insights → Contact insights | per committee member: `contact.facet.recent_post`, `contact.facet.publications`, `contact.facet.voice_quote`, `contact.facet.certifications`, `contact.facet.career_history` |
| Insights → Context only | every `outreach_safe: false` row + `account.reputation_risk` + `account.resonance.attrition_signal` |

Recipes are config (registry rows), not code — a custom variable the client adds is just another
field key appended to a section's recipe.

## 3. What Luna does — one call per section

For each section the backend gathers the matching claims for that subject and sends them to
`openai/gpt-5.6-luna` with the section's instruction. This is the **same prompt that already ran
on the Probook sample** (`.context/arv2-clue-sample-v3/step12_layer2_luna.py`) with three changes:
per-section instead of whole-account, a `claimIds[]` on every sentence, and a "how to use it"
instruction for the contact page.

**Input to Luna (per section):**
```json
{
  "page": "contact", "section": "openers",
  "subject": {"name": "Nick Fisher", "persona": "economic_buyer", "account": "Zafran Security"},
  "client": {"name": "Clue", "what_we_sell": "AI-native ABM: account + committee research, personalised content, brand-aligned artifacts, scaled per account"},
  "claims": [
    {"claimId": "zaf-160", "fieldKey": "contact.facet.hobby", "value": "…", "quote": "…",
     "sourceDomain": "youtube.com", "observedAt": "2026-09-02", "priority": 1, "outreachSafe": true}
  ]
}
```

**Output from Luna (per section):**
```json
{
  "items": [
    {"h2": "The cocktail-chemistry opener — he published it himself.",
     "body": [
       {"text": "He runs the Cocktail Chemistry YouTube channel and wrote the book of the same name.", "claimIds": ["zaf-110", "zaf-160"]},
       {"text": "In your email: \"Nick — anyone who runs ice experiments for a Moscow Mule cares about getting the detail right…\"", "claimIds": ["zaf-102"]}
     ],
     "contactRefs": []}
  ],
  "empty": false
}
```

**The rules Luna runs under** (all proven on Probook; the 15-second-operator prompt):
1. It may not state anything the claims do not contain. No invented numbers, dates, employers.
2. Every quote is verbatim from a `quote` value.
3. Every sentence carries the `claimIds` it used. Luna never sees or types a URL — the frontend
   turns `claimId` → `source_url` into the [source] chip. (Models re-typing URLs was the one
   defect Luna showed on Probook; this removes the possibility.)
4. `outreachSafe: false` claims are only ever passed to the "Do not mention" / "Context only"
   sections. The Openers/Angles calls never receive them.
5. An empty claim list is a real answer → `"empty": true` → the frontend prints
   "No {section} information found for {name}." Luna is not called at all for an empty recipe.
6. No marketing filler. Prefer the person's own words.
7. Contact page bodies end with a use line: "In your email: …" / "On the landing page: …" /
   "In the direct-mail brief: …". v1 cannot send email, so the body IS the copy the user pastes;
   each body gets a Copy affordance. In v2 the same body becomes the email draft's seed.

**Storage:** the output is written back as a `display_block` row (page, section, subject,
model, prompt version, the claim ids it cites, generated_at). It is regenerated when any cited
claim is superseded. So the page copy is itself trackable to the claims it came from.

**Cost, from the measured Probook call** (17.2k tokens in, 4.3k out, 32s, $0.0095 for a whole
account with 5 contacts in one call): split into ~8 section calls per account page-set and ~6 per
contact page, expect roughly **$0.02 per account and $0.01 per contact page** — about 7 cents
for Zafran's account + five people. Structuring (gpt-5-mini) remains the expensive layer; Luna is
the cheap one.

## 3b. Decided after the control test (4 Sep 2026)

`.context/display-layer-control-test/REPORT.md` tested the three open questions on the real Zafran
claims (52 page generations, 11 models, blind judge). The decisions it produced:

- **One call per section, sections fired in parallel, `gpt-5.6-luna`.** Same faithfulness as one
  whole-page call (zero unsafe leaks, zero non-verbatim quotes in every Luna run), zero off-recipe
  citations (whole-page drifted 3–6 per page), each section regenerable alone, page ready in ~15 s.
- **No cheaper model.** Every cheaper OpenRouter model failed a non-negotiable (unsafe facts in
  outreach copy, paraphrase inside quotation marks, invented product claims) or took 2–16 minutes.
  Luna is ~$0.005 per page, ~5 cents per account with five contacts.
- **Three prompt lines added to the production prompt:** never type claim ids into prose; write dates
  as "17 June 2026"; the hobby hook at most once per page.
- **Two upstream fixes:** one fact, one `outreach_safe` flag (the store held the cocktail hobby twice,
  once safe, once unsafe); dedupe the near-duplicate unsafe rows before they reach the display layer.
- **Cost levers, in order:** regenerate only the sections whose claims changed; generate P2/P3
  contact pages lazily on first open; stable prefix + section suffix so the provider cache hits
  (measured 3× cheaper warm); `:batch` endpoints for nightly refreshes.

## 4. What the frontend needs that it does not have today

Today's Zod slots: `summary: ProseReadSchema` = `paragraphs: string[]` (no link slots);
`WorkspaceInsightSchema` = `{source, title, sourceLabel, url, summary}` (one link per card);
`AccountContactDetailSchema` = `overview` prose + `professionalFacts[]` + `evidence[]`.

The one new slot, on both account detail and contact detail:

```ts
DisplayBlock = {
  page: "insights" | "overview" | "contact",
  sections: Array<{
    key: string, h1: string, empty: boolean,
    items: Array<{
      h2: string,
      body: Array<{ text: string, claimIds: string[] }>,   // claimIds → evidence[] → chips
      contactRefs: Array<{ contactId: string, name: string }>, // chips → /contacts/{id}
      priority: 1 | 2 | 3
    }>
  }>
}
```

`claimIds` resolve against the existing `evidence[]` (`EvidenceReferenceSchema`), which already
carries `sourceUrl`, `sourceDomain`, `observedAt`, `quote`. Nothing else changes.

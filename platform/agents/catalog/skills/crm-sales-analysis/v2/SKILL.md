---
schema_version: "1"
kind: skill
name: crm-sales-analysis
version: v2
summary: "Read the workspace's CRM, or ask the person, to work out the real sales motion; write `company/sales-motion.md` and add recent closed-won customers to `proof/customers.md`."
roles:
  - head_of_abm
readiness_requirements: []
tools:
  - name: connect_crm
    version: "1"
    input_schema_sha256: b931b8aba2d54709cd85dcd6a24006e05b8eca8141a204e3f038ffbf8c79b7b2
    output_schema_sha256: fe5d80d6d7029cf58299db6535df86a83b5ae1be78821787d42690da4130f0ce
  - name: find_crm_actions
    version: "1"
    input_schema_sha256: 20fa09f6729c71065926a620dc20aee770993516b7f83298187e2bc3333575c0
    output_schema_sha256: effb910afc51b18957479533d8ce879483165961cb26e785856e279630cbeab6
  - name: run_crm_action
    version: "1"
    input_schema_sha256: d44424cce9834552b7785cf81a0e6a84c6f1c570cf21272368b9a20e04e9743d
    output_schema_sha256: fb6f503bd03914da0e697049871d353b9f256d89c6dc6fe142b391a074917115
  - name: run_python
    version: "1"
    input_schema_sha256: c3c261b3cb0dbd182dbbd14921a2228b29fcd5e3a626a387a7d4eee50db334d4
    output_schema_sha256: f4fe91bacc68b4a45c7bcda24c72548481dc562b31312426db47f415b8a07c85
  - name: write_brand_document
    version: "1"
    input_schema_sha256: d474d439f9b3614ef28a1868b7a74524c7920356447dafb02eca7080f3678151
    output_schema_sha256: 16ad20a4fd205423fbcaf156fae3dcabb97839dd76ae615a5563ba8bfc491537
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Work out the real sales motion from the CRM

A written ICP says who the seller *thinks* buys. The CRM says who actually bought, how big the
deals were, how long they took and who was in the room. This skill turns the CRM into one
Brand-context document, `company/sales-motion.md`, that every project of this brand reads, and it
adds the companies that recently became customers to `proof/customers.md`.

This skill only reads the CRM. To change anything in it, follow the crm-writing skill.

## 1. When to do this

- In the interview, when you reach the closed-won deals question (stage0-interview, section 2b):
  after the outcome, before the plan.
- When the person asks for the sales numbers, the win rate, the deal size, the sales cycle or
  "what our CRM says".
- When `brand/knowledge/company/sales-motion.md` is missing, or its window ended more than about
  three months ago.

If `company/sales-motion.md` exists and is recent, read it and use it. Do not redo the analysis
unless the person asks (asked of you).

## 2. Connecting

Call `connect_crm` first. It tells you whether a CRM is connected.

- **`state: "connected"`.** Go on to section 3.
- **`state: "card"`.** The chat now shows the person a card that offers to connect HubSpot or
  Salesforce, or to give the numbers by hand. Say in one or two sentences why connecting helps
  (Clue reads the deals to work out the real numbers, and changes nothing), then **end your
  turn**. Do not wait, poll or call `connect_crm` again in the same turn. When the person
  connects, the chat continues by itself with a message saying the CRM is connected (enforced).
  - `mode: "reconnect"` means the connection expired. Say so plainly.
  - `can_connect: false` means this person cannot connect. Only workspace owners and admins can,
    and the card tells them to ask one. Offer the by-hand path (section 11) meanwhile.
- Pass `switch: true` only when the person asked to replace the connected CRM with another one
  (asked of you).
- If the person picks "I'll give the numbers myself", or says no, use the by-hand path
  (section 11). Never ask them to connect twice in one conversation (asked of you).

**Right after connecting**, in your first reply, say what Clue can now read (deals, companies,
contacts, pipelines and their settings) and that nothing in the CRM is changed. On Salesforce, add
that reading uses the org's daily API allowance: Clue keeps to a small share of it and stops for
the day if the org runs low. Then continue with what you were doing.

**Several brands in one workspace.** Deals are not split by brand. If the workspace has more than
one brand, ask how to tell this brand's deals apart before you compute anything; a pipeline, a
product field or a deal-name prefix are the usual answers (asked of you).

## 3. Read the setup first

Before you pull any deals, learn how this CRM is set up. Stage names and fields differ in every
company.

HubSpot:

- `HUBSPOT_RETRIEVE_ALL_PIPELINES_FOR_SPECIFIED_OBJECT_TYPE` with `objectType: "deals"`: the
  pipelines and their stages, with stage ids.
- `HUBSPOT_READ_ALL_PROPERTIES_FOR_OBJECT_TYPE` with `objectType: "deals"`, then `"companies"`
  and `"contacts"`: every field, including custom ones.

Salesforce:

- `SALESFORCE_GET_ALL_FIELDS_FOR_OBJECT` for `Opportunity`, `Account` and `Contact`.
- `SALESFORCE_GET_PICKLIST_VALUES_BY_RECORD_TYPE` for the stage values.

These are the actions you will need most. `find_crm_actions` finds others; search by what you
want to do, such as "deal associations to contacts". Never put a company's or a person's name, an
email or any other customer data in the search text (asked of you).

## 4. Agree the definitions

The numbers mean nothing until four words are pinned to this company's own stages: **demo**,
**qualified demo**, **won** and **lost**.

- Infer each from the stage names you read. "Demo Scheduled" is probably a demo; "Closed Won" is
  won.
- Show your mapping in one short list, and ask the person to confirm or correct it before you
  compute (asked of you).
- When you cannot tell, ask up front rather than guessing. Two pipelines with different stage
  names is the common case (asked of you).

Record the confirmed definitions with `record_interview_answer`, route `project_state`.

## 5. The window

Use the deals closed in the last **3 months** by default. Adjust it to the industry and the sales
cycle, and say which window you used and why (asked of you):

- Long enterprise cycles (healthcare, public sector, large IT deals, cycles over six months):
  widen to 6 or 12 months, so the window holds enough closed deals.
- Fast, transactional sales: keep 3 months.
- If the 3-month window holds fewer than about 15 closed deals, offer to widen it before
  computing.

## 6. Pulling the deals

`run_crm_action` writes the whole result of every read to a file in `reads/` and gives you back
only the file's path, how many records it holds, their field names and, when there are more,
`next_cursor` (enforced). You never see the records in the result. Read them from the file in
`run_python`.

HubSpot:

- **Closed deals:** `HUBSPOT_SEARCH_DEALS` with `filterGroups` on `closedate` within the window and
  `dealstage` in the won and lost stages; `properties` for the fields you need (name, amount, close
  date, create date, stage, pipeline, source, owner); `limit: 100`. Pass `next_cursor` back as
  `after` for the next page. HubSpot search stops at 10,000 results; narrow the dates if you reach
  it.
- **Open pipeline (for context):** the same search with the open stages.
- **Stage history**, for stage durations: `HUBSPOT_GET_DEALS` with
  `propertiesWithHistory: ["dealstage"]`, up to 100 deal ids per call.
- **Who was on each deal:** `HUBSPOT_READ_ASSOCIATIONS_BATCH` from `deals` to `contacts`, and from
  `deals` to `companies`, up to 1,000 ids per call.
- **Companies and contacts:** `HUBSPOT_BATCH_READ_COMPANIES_BY_PROPERTIES` and
  `HUBSPOT_READ_CONTACTS`, by id, asking only for the fields you need (domain, industry, size,
  country; job title, buying role).

Salesforce:

- **Closed deals:** `SALESFORCE_RUN_SOQL_QUERY` on `Opportunity` with `IsClosed = true` and
  `CloseDate` in the window, selecting amount, stage, close date, created date, lead source and
  the `Account` fields you need in the same query. Sub-queries on `OpportunityContactRoles` (role,
  primary, the contact's title) and `OpportunityHistories` (stage changes) work in the same query.
- When a result says `done: false`, run `SALESFORCE_QUERY_MORE` with `next_cursor` as
  `next_records_url`.
- Every Salesforce read uses the org's daily API allowance. Clue keeps to its share and refuses
  `salesforce_api_share_exhausted` when the share or the org runs low (enforced). Ask for many
  records per call rather than one at a time (asked of you).

Pull every page before you compute. A figure from the first page of three is wrong (asked of
you).

## 7. Compute in the sandbox

Every number comes from a script you ran in `run_python` over the `reads/` files. Never count,
average or eyeball in your head (asked of you). A file holds the CRM's own response: a HubSpot
search page has `results`, each with `properties`; a Salesforce query has `records`. Load all the
pages of one pull together.

Work out, for the window:

- closed-won and closed-lost counts and value, and the win rate (won ÷ (won + lost));
- deal size: average and median, and the average without outliers when one or two deals dwarf the
  rest (say which deals you set aside, and why);
- the sales cycle (created to closed) for won deals, and how long deals sit in each stage, which
  shows where they stall;
- what the won deals have in common: industry, company size, region, source, cycle length;
- the buying committee on won deals: the titles and roles of the people on them, mapped to the
  brand's personas in `brand/knowledge/audience/`;
- where demos come from (the source or channel of the deals that reached the demo stage);
- the sales-led price: what deals actually closed for, as a range and a typical figure.

Say how sure each finding is from the number of deals behind it (asked of you): under 5, "not
enough to say"; 5 to 14, "an early sign"; 15 to 29, "a reasonable read"; 30 or more, "solid".

A turn has a limited number of `run_python` runs, and every result reports `runs_remaining`
(enforced). Write one script that loads the files and computes everything, rather than one script
per number (asked of you).

## 8. Ask for what the CRM cannot tell you

- The CRM does not know what a lead or a demo cost. Ask the person for their cost per lead and
  cost per demo, or what they spend per month on demand generation and how many demos it brings
  (asked of you).
- If the deals carry no amounts, ask what a typical deal is worth and what the range is. That is
  the sales-led price, which the public pricing page does not show (asked of you).

An answer you did not get is recorded as "not available", never estimated.

## 9. Show the findings and ask

Before you write anything, show the person the main findings in a few lines (window, win rate,
deal size, cycle, where deals stall, the pattern in the wins, the committee) and ask whether they
look right (asked of you). People often know a reason the data hides, such as a big deal that was
a one-off or a pipeline used only for renewals. Fix the analysis with what they tell you and
record their corrections with `record_interview_answer`.

## 10. Show your work

Save the computed tables as CSV files in `outputs/` (for example `outputs/sales-metrics.csv` and
`outputs/won-deals.csv`), so a later turn of this chat can use them again (asked of you). Check
`files_written` before you say a file exists.

The person cannot open the files in your workspace, so the document you write shows its own
working: it says in words how each number was computed (section 12).

## 11. The by-hand path

When no CRM is connected, or the person chose not to connect one, ask for the same facts one at a
time, in plain words:

- how many deals they won and lost last quarter;
- what a typical deal is worth;
- how long a deal takes from first meeting to signature;
- where it usually stalls;
- who signs and who else is involved;
- where their demos come from;
- what a lead and a demo cost.

Write the same document from their answers, with every figure's source given as "the person, in
this chat". Do not merge anything into `proof/customers.md` on this path unless they name
customers.

## 12. Write `company/sales-motion.md`

Write it with `write_brand_document` (`path: "company/sales-motion.md"`, `kind: "sales-motion"`;
leave out `kind` when the document already exists). Write the whole document every time; to
update it, read the current version from `brand/knowledge/company/sales-motion.md` first. When the
document already exists, pass the version you read as `based_on_version` (from
`brand/index.json`).

Use these sections, in this order:

1. `# Sales motion`, then two to four sentences: the motion in plain words.
2. `## Window and definitions`: the window and why; the confirmed definitions of demo, qualified
   demo, won and lost; the CRM and the pipelines used; and how the numbers were computed: which
   deals were counted, any filter you applied, and any deal you set aside (such as an outlier)
   and why.
3. `## Numbers`: a table with columns Metric, Value, Deals behind it, How sure, Source. Source is
   "CRM (HubSpot), computed 21 Oct 2026" (the CRM you read and the day you computed it), "the
   person, in this chat", or "not available". Never name a file in your workspace; the person
   cannot open it.
4. `## Where deals stall`.
5. `## What the wins have in common`.
6. `## Buying committee on won deals`: titles and roles mapped to personas.
7. `## Where demos come from`.
8. `## Sales-led pricing`.
9. `## Not available`: what could not be established, and why.

Keep the summary, not the raw deals. Do not list individual deals, and do not put any person's
name or email in the document; titles and roles are enough (asked of you).

The document is the brand's, not this project's. Every project of the brand reads it, so write
nothing in it that is only about this project (asked of you).

## 13. Add the new customers to `proof/customers.md`

Companies whose deals were won within the window are customers. Merge them into
`proof/customers.md`:

1. Read the current `brand/knowledge/proof/customers.md`. Keep its table exactly as it is, with
   the same columns in the same order: Customer, Domains, Domain check, How they buy, Evidence,
   Quote, Source.
2. One row per website domain:
   - When a won company's domain is already in the table, keep that row and add
     ` · CRM: <HubSpot|Salesforce> (closed-won <date>)` to the end of its Source.
   - When it is not, add a row: Customer, the company name; Domains, its domain (or
     `no domain given` when the CRM has none); Domain check, empty; How they buy, `direct`;
     Evidence, `closed-won deal`; Quote, empty; Source,
     `CRM: <HubSpot|Salesforce> (closed-won <date>)`.
3. Never remove a row (asked of you). Rows from website research stay, and so do rows an earlier
   analysis added. A company that was won once is recorded as closed-won; Clue does not check
   churn.
4. Keep the rows sorted by customer name.

The Source must contain `CRM:` exactly as written. Onboarding refreshes this document from the
website and keeps only the rows whose Source says `CRM:` (enforced); a row without it is lost at
the next refresh.

Write it with `write_brand_document` (`path: "proof/customers.md"`, no `kind`). When the document
already exists, pass the version you read as `based_on_version` (from `brand/index.json`). For a
long table, build the file in `run_python` as `outputs/customers.md` and pass `from_file`.

## 14. When a tool refuses

| Code | What it means and what to say |
| --- | --- |
| `crm_not_configured` | The CRM integration is not set up on this deployment. Say so and use the by-hand path. |
| `crm_not_connected` | Nothing is connected. Call `connect_crm`. |
| `crm_connection_expired` | The connection lapsed. Call `connect_crm`; it shows a Reconnect card. |
| `crm_action_not_allowed` | That action is not one Clue may run. Use `find_crm_actions` to find a read action that is. |
| `crm_action_failed` | The CRM refused the call and says why, often a field or stage name that does not exist. Check the setup you read, fix the arguments and run it again. |
| `crm_rate_limited`, `crm_unavailable` | Try once more later in the turn; if it still fails, say the CRM is not answering right now. |
| `salesforce_api_share_exhausted` | Clue has used its share of the org's daily API calls, or the org is low. Say reading resumes tomorrow, and work with what you already pulled. |
| `salesforce_api_disabled` | The org has no API access (Professional Edition needs a paid add-on). Explain that plainly and offer the by-hand path. |
| `crm_reads_unavailable` | Reads cannot be saved on this turn. Say so; do not guess numbers. |
| `document_changed` | Someone saved this document after your turn began. Tell the person, and write it again on the next turn from the new version. |

Never state a number you did not compute from a file you read, and never fill a gap with an
estimate (asked of you).

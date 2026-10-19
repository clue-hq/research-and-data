# Account discovery leaves out the seller's existing customers

Status: design for founder review (2026-10-16). Nothing here is implemented.

## 1. Why

Agent-authored account discovery (spec `2026-09-30-agent-authored-account-discovery-design.md`)
keeps returning companies that already buy from the seller. It was seen with Conduit AI and Alt
Carbon: companies on the seller's own logo wall and case-study pages came back as new target
accounts. A list of prospects that contains the seller's customers is wrong on its face, and it
wastes verification spend and the customer's trust.

Nothing in the pipeline knows who the seller's customers are today:

- The discovery brief (`DiscoveryBrief2`, `arv2/discovery_request.py`) has no exclusion field, and
  the Head of ABM's instructions (stage0-interview skill §7b) mention competitors, never customers.
- Neither Exa request carries a customer list. Websets already uses Exa's `exclude`, but only for
  earlier websets of the same project.
- Discovery skips only this project's accounts and companies earlier runs of this project found. It
  does not even skip the seller's own domain.
- Onboarding's company overview keeps up to 30 `named_customers`, names only, with no domains, and
  nothing reads them.

## 2. Founder rulings (2026-10-16)

1. **No saved customer database.** Until CRM integrations exist, there is no table of customers.
   Who counts as a customer is the agent's judgement.
2. **The customer list lives in the brand context**, as a document the agent wrote and a person can
   read and correct.
3. **The Head of ABM decides the exclusions on every discovery call.** It reads that document and
   puts the companies it judges should be left out, with their domains, on the brief's exclusion
   list. Code carries the list out; it never decides who is a customer.
4. **The seller's own domains are always excluded.**
5. **Not in this piece:** an agent check per discovered company ("is this a customer?"), and a way to
   reject a discovered account so it stays rejected across projects. Both are later work.

## 3. Evidence behind the design (live tests, 2026-10-16)

Two reference lists were built by hand and used to score Exa's options.

| | Conduit AI (29 known customers) | Alt Carbon (15 known buyers) |
|---|---|---|
| Exa `/search` deep, structured output | 17 found; 0 of 9 logo-wall names; 5 of 17 domains wrong or unconfirmed; $0.025 | not run |
| **Exa Agent, effort `xhigh`** | **28 found + Beckon Homes, Hilton, Fairmont; 1 wrong domain (`wynwoodhouse.us` is a care home), 1 unconfirmed; $1, 4 min** | **13 found + John Good Group (missed by hand); missed Frontier and Mitsubishi Corporation; added BCG, LGT, Swiss Re and UBS from a weaker coalition-level mention; $1, 5 min** |

What the tests taught:

- Logo walls carry names only in images. Conduit's have alt text; Alt Carbon's homepage logos are
  unnamed inline SVG drawings. The Exa Agent read both.
- The biggest buyer can be on no logo wall (Microsoft, only in a press release), and some buyers
  exist only in an industry tracker (CDR.fyi for carbon removal: Celonis, Climeworks, Cur8).
- One logo strip can mix investors and buyers (Alt Carbon's "Remove CO₂" page).
- "Customer" depends on the business: software users for Conduit, credit buyers for Alt Carbon,
  including buyers through a coalition (Frontier, NextGen) or a marketplace (CEEZER, Cur8).
- Exa's domains are mostly right but not always: one belonged to an unrelated company, and a parent
  company's corporate domain (`abc.xyz` for Alphabet) is useless for excluding `google.com`.

## 4. The design

### 4.1 Research: a fifth onboarding request

Onboarding gains one Exa Agent step next to the company overview, the customer reviews and the
product research, built the same way (`_agent_step` in `arv2/onboarding_driver.py`; the request
template in `arv2/onboarding_requests.py`; the document renderer in `arv2/onboarding_documents.py`).

- **Step kind** `customers`; effort `xhigh` (a new setting, `CLUE_ONBOARDING_CUSTOMERS_EFFORT`,
  default `xhigh`, in `.env.example` per the parity rule). It runs in the background phase so it
  never delays the fast lane. About $1 per brand.
- **Query** (seller-agnostic version of the one tested on Alt Carbon): find every existing customer
  of `{company} ({domain})`; first work out what buying from this company means; read its own site
  (sitemap, customers and case-study pages, press releases, news, logo walls); then announcements by
  buyers themselves, news coverage, reviews, and the industry's own purchase trackers or registries.
- **System prompt**: list only companies that buy or use the product, directly or through a buying
  coalition or marketplace; leave out investors, grant-givers, registries, technology and integration
  partners, suppliers and competitors, even when they share a logo wall; every customer must be named
  on a page found; give every website domain the customer uses (a group's brand domains as well as
  its corporate one); check that a domain's website is really that company, otherwise leave it out.
- **Output schema** per customer: `name`; `domains` (list); `relationship` — `direct`,
  `through_coalition`, `through_marketplace`, or `weak_mention` (a sweeping claim such as "300+
  brands including Hilton"); `via` (the coalition or marketplace, when there is one); `evidence_kind`
  (`logo_wall | case_study | testimonial | press | review | tracker | other`); `quote` (verbatim, 40
  words max). Plus, at the top level, `seller_domains`: every domain the seller itself uses (Alt
  Carbon has two); the document lists them on their own line. Page citations come back in Exa's `grounding`, as for the other requests.

### 4.2 Domain check

After the Exa run, code fetches each returned domain's homepage once and records what it found next
to the domain: `confirmed` when the page loads and names the company (its title or visible text
contains the customer's name or an obvious form of it), `unconfirmed` otherwise, with the page title
shown. It never drops a customer or a domain; it only labels them, so the Head of ABM can see that
`wynwoodhouse.us` belongs to "Personal Care Communities". The fetch uses the platform's ordinary
public page fetch (no paid provider).

### 4.3 The brand document: `proof/customers.md`

A new brand knowledge document, kind `existing-customers`, in the Proof folder next to
`proof/customer-reviews.md`. **The list lives in the body only**, as a readable table: name,
domains with their check result, how they buy (and via whom), the evidence kind, the quote and its
source page; then a short "Seller's own domains" line. Front matter carries only the usual run
header (as-of date, provider run, cost), never a second copy of the list. *Builder's call, recorded
here:* the Brand-context editor saves an edited body and copies the old front matter forward, so a
list kept in front matter would silently ignore a person's correction; with one copy in the body, a
person's edit is exactly what the Head of ABM reads. The document versions like every other
onboarding document.

### 4.4 Existing brands

Brands onboarded before this ships get the step once, as a new onboarding run kind `customers`
(beside the existing `personas` run kind): it runs only the customers step and finishes. A script
lists the brands without a `proof/customers.md` and enqueues one run per brand, dry-run by default.
About $1 per brand; the founder decides when to run it.

### 4.5 The discovery brief gains an exclusion list

`DiscoveryBrief2` gains an optional `exclude` field: a list of `{name, domains[]}` (name ≤200
characters, 1–10 domains each, at most 500 entries). `launch_arv2_discovery@2` accepts it and stores
it on the run with the rest of the brief. The field is the agent's to fill; code checks only its
shape.

### 4.6 Code carries the exclusion out

The excluded domains, plus the seller's own domains, form one set for the run:

- **Websets rounds:** the set is uploaded once per run as an Exa Import (CSV of domains, entity
  `company`) and added to the search's `exclude` as `{"source": "import", "id": ...}`, next to the
  earlier websets it already excludes. Exa then never returns those companies, so they use no result
  slots. If the import fails or is not ready in time, the round goes ahead without it and the
  domain skip below still applies.
- **Search rounds:** excluded domains join the `known` set, so they are skipped before any
  verification is paid for (Exa `/search` itself cannot take `excludeDomains` with `category:
  company`).
- **Every candidate:** `_pre_spend_disposition` checks the verified domain against the set before the
  gates are asked. A match is recorded as a new disposition, `excluded_by_brief` (a migration widens
  the disposition CHECK), naming the brief entry it matched, and is listed with the run's excluded
  companies in `read_discovery_run`.
- **The seller's own domains:** code always adds the `company_domain` of the brand's most recent
  onboarding run (the domain the platform itself knows), even if the agent forgets; a brand with no
  onboarding run adds nothing here. Any other domain the seller uses (Alt Carbon also has
  `alt-carbon.com`) is listed in `proof/customers.md` and passed by the Head of ABM in `exclude`.
  *Builder's call, recorded here:* the driver never reads the brand document itself, so code never
  interprets a document a person may have edited; the agent reads it, code enforces what it passes.
- **Visible exclusions.** A person must be able to see the exclusion working. Webset items are
  checked against the set when they arrive, using the item's own URL, before any verification is
  paid for; search hits likewise. Every company skipped this way with a known domain is written as a
  candidate with disposition `excluded_by_brief`, the same as one caught after verification. The run
  summary (and the wake report) states how many companies the brief excluded and how many domains
  the Exa Import carried; companies the Import kept out upfront are by nature never returned, so the
  summary names the Import, not them. *Builder's call, recorded here.*

Matching is by registrable domain (`registrable_domain`), the same as every other discovery skip.

### 4.7 The Head of ABM's instructions

The stage0-interview skill §7b and the discovery tool note gain a short passage. The wording below is
a draft for founder review (skill content is reviewed in chat before it is written):

> Before you launch discovery, read `brand/knowledge/proof/customers.md`. It lists the companies
> that already buy from the seller, how they buy, and the evidence. Put on the brief's `exclude` list
> every company the seller would not want to approach as a new prospect: always the direct customers,
> and the ones that buy through a coalition or marketplace unless this search is meant to reach them.
> A weak mention is your call. Give each its domains as written there, and add the seller's own
> domains. If the document is missing, say so to the person and go ahead without it.

New versions of the skill and of the Head of ABM profile follow the usual versioning; the tool note
and the manual's discovery page mention the field.

## 5. Goals, non-goals, anti-goals

- **Goal:** a discovery run never adds a company that the brand's customer document lists and the
  Head of ABM excluded, nor the seller itself.
- **Goal:** every onboarded brand has a sourced, readable customer list.
- **Non-goals:** CRM or CSV customer import; per-company customer checks during verification;
  remembering rejected accounts; any change to how `must`/`must_not` gates work.
- **Anti-goals:** code deciding who is a customer; a hidden customer table; silently dropping a
  customer because its domain could not be confirmed.

## 6. Testing

- Offline, through the real driver and stores: a websets round whose import excludes the listed
  domains; a search round that skips them before spending; a candidate whose verified domain matches
  an entry, recorded `excluded_by_brief`; a webset item skipped on arrival by its own URL, with no
  verification paid; the seller's onboarding domain skipped with no `exclude` given; an import
  failure that still skips by domain; the run summary counting the exclusions; a brief whose
  `exclude` is malformed, refused with `brief_invalid`.
- Onboarding: the customers step writes `proof/customers.md` from a recorded Exa run; the domain
  check labels a live matching page `confirmed` and a mismatched one `unconfirmed` without dropping
  it; the `customers` run kind runs only that step.
- One paid confirmation (founder-approved): the customers step for Conduit AI and Alt Carbon, scored
  against the 2026-10-16 reference lists, then one discovery run per seller showing no listed customer
  added.

## 7. Left to the builder

- The exact CSV layout of the Exa Import and how long to wait for it to finish processing.
- How the domain check decides that a page "names the company" (it must err towards
  `unconfirmed`).
- The table layout of `proof/customers.md`, following the existing Proof documents' style.
- Where the `customers` run kind is enqueued from (the script, and whether an API route is needed).

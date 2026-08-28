# Recipe: ABM Page (single account)

The section grammar and hard rules for an account-based-marketing page — a
page built by a SELLER for exactly ONE target account. A recipe is a business
contract, not a style guide: the create-website skill owns HOW to author;
this owns WHAT an ABM page must contain and must never do.

The page is a private pitch, not a public site. Everything on it exists to
make one named account book one conversation.

## How the page is assembled

The chrome is not composed — it is the seller's own CAMPAIGN SHELLS, minted
once per brand by `mint_campaign_shells` and released by a human re-approving
the brand kit. `assemble_abm_page` puts them on: campaign header FIRST,
campaign footer LAST, a chosen cloned hero between them. It NEVER pins the
client's cloned nav or cloned site footer, and it refuses rather than falling
back to one — every nav link is a way off the one page written for this
account.

Order of operations: author the page's own sections with `author_web_page`
FIRST, then `assemble_abm_page`. A whole-page rewrite drops every pinned clone,
so chrome pinned before it is chrome you lose.

**The page is a TEMPLATE, not one account's page.** Slots hold the account
markers — `{{account.name}}`, `{{account.domain}}`, `{{account.logo}}` — which
the account derive substitutes per account, so one document serves every
account and stays re-derivable. Never write one account's name or logo into the
markup.

**Every section you compose for this page carries a section id beginning
`abm_`** (`<section id="abm_peer_proof">`), so a reviewer can tell a new band
from cloned chrome. Pinned clones keep their own ids.

## Required section order

1. **co-branded header** — the CAMPAIGN HEADER SHELL, not a header you write:
   the seller's mark, "Prepared for <account>", the target's logo when we hold
   one, and exactly one CTA. Never redraw or synthesize someone else's logo. A
   target's logo comes from exactly two places: the `{{account.logo}}` marker
   the derive resolves, or the `fetch_logo` tool, which pulls their real
   published assets off their own website. `fetch_logo` returns one id per slot
   (`light`, `dark` for dark surfaces, `mark`, `wordmark`) and a missing slot
   means the brand publishes nothing for it. If it answers `needs_review`, it
   could not confirm the asset belongs to that company — that means ASK, not
   guess: use the name alone and tell the user you need the file. AN EMPTY LOGO
   SLOT IS CORRECT: a header with the seller's mark alone is a clean header, not
   a broken one. NO nav links. Exactly one CTA, the conversion CTA. On phone:
   both marks + CTA.
2. **personalized hero** — h1 names the ACCOUNT, not the market ("Acme's
   clinical notes, written for you" — never the generic tagline), one
   paragraph mapping the seller's value to the account's situation as given
   in the brief, single primary CTA.
3. **peer proof** — 5–7 peer logos or names, REAL and verifiable from the
   brief/kit only; the bar is "companies this account would recognize as
   peers". Fewer than 5 verifiable → show what is real; none → OMIT the
   section entirely.
4. **account-mapped feature spotlight** — 2–3 features MAX, each explicitly
   tied to something the brief says about the account (their stack, their
   scale, their stated pain). A feature you cannot map to the account does
   not belong on this page.
5. **verified resources** — 2–3 links (case study, docs, security page)
   given in the brief or resolvable on the seller's real site. Never guess
   resource paths; unverifiable → omit the item, and the section below 2.
6. **"how we'd work together"** — 3 short numbered steps from first call to
   value, concrete to this account's context (pilot scope, rollout shape).
7. **conversion CTA band** — statement background, h2 addressed to the
   account, the single conversion CTA. A booking dialog (or a Calendly
   embed inside it) is the preferred mechanism when an endpoint exists.

No footer nav. The footer is the CAMPAIGN FOOTER SHELL — the seller's mark,
their copyright, their privacy/terms links, nothing else. Anything more leaks
the pitch into a website.

## Hard rules (violations are defects, not taste)

- **One CTA, one destination.** Header, hero, and the final band carry the
  SAME conversion action (same dialog target or same verified link). No
  secondary CTAs, no anchor menus — there is nothing else to do here.
- **Personalization is factual, not flattering.** Use only what the brief
  states about the account (name, industry, stack, stated pains). Never
  infer news, funding, headcount, or initiatives that are not in the brief.
- **Never invent peers, quotes, or numbers.** The peer-proof and resource
  sections are the two highest-trust surfaces on the page; one fake logo
  poisons the whole pitch.
- **The target's brand is quoted, not adopted.** The page renders in the
  SELLER's theme tokens; the target appears as a name/logo, never as a
  restyle of the page. The acceptance question is "would it still look like
  the seller's site without the target logo?" — one restrained accent from
  the target's palette at most.
- **Claim no relationship that does not exist.** The framing is "Prepared for
  <account>" and nothing stronger. Never "partner", "partnership",
  "customer", "trusted by <account>", or any wording implying they already
  buy from, work with, or endorse the seller — they do not, and a false claim
  on the first page they see costs the whole pitch. Their name belongs in the
  prepared-for line and in copy written for them; never in a logo wall, never
  in a testimonial.
- **Real endpoints only** for the conversion CTA (booking link, calendar
  embed). None given → obvious placeholder + flag it in the finalize
  summary and ask.
- **Fake illustrative data is flagged** (pricing, comparisons) — same rule
  as everywhere, sharper here because the reader is one skeptical account.
- **Copy**: second person addressed to the account; concrete verbs; no
  emojis; no em-dashes; sentence case except brand names.

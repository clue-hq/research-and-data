# Research narration quality — design

Status: draft for founder review, 2026-10-04. Branch `research/narration-quality`.
Context: `_memory/2026-10-04-narration-quality.md` (diagnosis) and
`_memory/2026-10-03-first-production-research-quality-review.md` (evidence from the first production run).

## Problem

The research is accurate; the pages built on it are not usable as a sales brief. On the first
production run (two accounts) the account and contact pages hedged almost every item, never
joined the strongest facts into one argument, wrote openers that never connect to what the seller
sells, filled Miscellaneous with low-value biography, repeated the same facts across sections and
sometimes cited the wrong claim.

## Founder decisions (2026-10-04)

1. The writer is told what the research is for: helping the seller turn this account into a client.
   Everything stays seller-agnostic — the seller, offer and objective come from each project's
   pinned context.
2. Writing moves to a separate step, provided the writer receives everything the researcher knew
   that matters (context transfer) and the output measurably improves.
3. The account's short story lives in the existing Overview opening (What they do / Why they fit).
   No frontend change.
4. Assumed until the founder says otherwise: the reader is a seller's rep preparing first outreach;
   every opener connects to the seller's offer, personal hooks only as an extra.

## Design

### 1. Seller brief (once per project context)

A short, plain document derived from the pinned seller documents (company overview, product
material, ICP, personas when present):

- what the seller sells and what it does for a customer, in the seller's own terms;
- the objective of this research: win this account as a client;
- the problems the offer solves, and for each, the public evidence that suggests a target has it
  (the "signal map");
- proof points the seller can legitimately use;
- who usually buys and who usually uses it;
- the ICP's hard gates and exclusions, verbatim.

It is built once per context pin (cached by the pin's sha), so every page in the project argues
from the same understanding of the offer. Missing seller material stays an explicit gap.

### 2. Writer input view (the context transfer)

Built deterministically from durable rows — never from the researcher's transcript:

- the seller brief;
- the subject's imported dossier findings: id, topic, finding text, quotes, qualifications, time
  context, attribution, review status, conflicts. Wrong-entity findings are withheld from the page
  writer (they stay in the research record);
- for the account writer: the committee and, once person research has settled, each person's
  findings, so person-level evidence can shape the account story;
- for a person writer: the account's short story and the account findings, plus its own findings;
- typed enrichment (titles, locations) only as reference, not as narrative material;
- the section contract (keys, titles, purposes).

Raw evidence (hundreds of fetched pages) is not passed: findings are the verified, distilled layer.

### 3. One writer call per page set

One model call writes the account's Overview + Insights; one call writes each contact page. Not
per-section parallel calls (tried 2026-09-26: long, repetitive pages). The output keeps the existing
typed page schema, so publication, storage and the frontend are unchanged.

Writing order inside the call: first the short account story (4–6 sentences joining the strongest
facts into why this account, why now, who first and what to lead with), then each section in its
service. The story opens the Overview.

### 4. Validation before publication (deterministic)

- schema and section keys;
- every finding reference resolves within its own scope;
- a quotation in a sentence must appear in a finding that sentence cites;
- wrong-entity findings are never cited as facts about the subject.

A refusal is fed back for one repair attempt; the page is never silently published broken.

### 5. Scheduling

- account research settles → write the account pages (no person findings yet);
- each person research settles → write that contact page;
- all of an account's person research settled → rewrite the account pages with person findings.

The researcher stops writing pages for new launches. Historical launches keep their pins.

## Writing guidance (principles)

- Lead with the story; every section serves it.
- Every item ends with what the rep should do with it: say, ask, show or check.
- A caveat appears only where it would change what the rep says or does. Dates stay inline.
  Remaining uncertainty is stated once, in Watch-outs.
- One home per fact; other sections refer to it instead of repeating it.
- Openers: a specific hook, its link to the seller's offer, a question. A personal hook may be offered
  as an extra, never as the lead.
- Miscellaneous holds leftovers a rep could use, not every residual finding. Namesake and
  identity-resolution notes are research hygiene and stay off the page.
- Accuracy rules stay: quotes exact, attribution correct, no invented problems, needs or results.

## Evaluation

Test inputs: the two accounts' saved research bundles (10 people), kept outside the repository. Each iteration runs the
writer only — no new research spend.

Automatic checks per page: story present in the Overview opening; caveat sentences per item; items
that end in a rep action; openers that name a seller capability or problem; quotes found in cited
findings; repeated facts across sections; length.

Human read: the founder and I compare the current production page with each iteration.

## Out of scope here

- Removing sensitive personal data already stored, and stopping its collection (parked by founder).
- The code that appends every uncited finding to Miscellaneous (founder ruling 2026-09-29) — the
  writer is told Miscellaneous holds usable leftovers; whether the automatic append stays is a
  separate ruling.
- Account sidebar headcount mismatch (parked).

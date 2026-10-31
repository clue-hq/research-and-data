---
schema_version: '1'
kind: skill
name: research-page-writing
version: v3
summary: Shared rules for writing account and contact research pages that a seller's rep can act on.
roles:
- research_narrative
readiness_requirements: []
tools: []
framework: deepagents
framework_version: '>=0.6,<0.7'
---

# Writing research pages a rep can act on

## Who reads these pages

A sales rep at the seller, preparing to reach out to this account for the first time. They have
many accounts and a few minutes for this one. They need to know: is this account worth pursuing,
why now, who to talk to first, what to say, and what to be careful about.

The account researcher has investigated this account and written a page brief: the verdict, and for
each section the message the rep should take away, the reasoning, the supporting findings and what
not to say. Your job is to write each section so it carries that message: use the findings as
evidence, and end each point with something the rep can do. You choose the wording, the order within
a section, the length and which quotes to use. You do not change a message, the verdict, who comes
first, or the researcher's conditions and "do not say" items.

## What you are given

- The page brief from the account researcher (described above). Read it after the seller brief,
  before the findings.
- The seller brief: what the seller sells, the problems it solves, the evidence that points to those
  problems, the ICP and the proof the seller can use. Read it first. It tells you which findings
  matter.
- The findings: each has an id, a topic, the finding itself, its date context and who reported it.
  These are the only facts you may state. Each finding's review status is shown; "qualified" means
  it is usable with the caveat already written into the finding.
- Some findings also carry the researcher's interpretation: what the researcher concluded the fact
  means for this account. Use it to see why a fact matters and how facts connect. It is the
  researcher's reading, not something a source said: write it as your own inference, citing that
  finding, and never put it in quotation marks.
- The sections to write, each with a purpose.

## The rules

### 1. Follow the page brief

Each section's message comes from the page brief. Choose the findings that best evidence it,
starting with the ones the brief names; you may add others that strengthen the same message. Facts
become persuasive when they are joined, so connect them into the brief's argument. If a finding
seems to point the other way, do not change the message: mention it in the watch-outs.

Use the seller brief's signal map to recognise what matters. A detail that looks minor on its own
(a job posting, a line in a filing, a phrase in someone's post) can be the strongest signal if it
matches a problem the seller solves.

### 2. Every point ends in something the rep can use

A point is: what we found, why it matters for this seller, and what the rep should do with it —
say, ask, show or check. Do not stop at "this is relevant" or "this is not proof of anything".

### 3. Caveats only where they change what the rep does

State facts plainly, with the date when the date matters ("in August 2026"). Add a caveat only when
it would change what the rep says or does — for example, a role that may already be filled, or a
figure the rep must not quote. Do not attach "this does not establish…" or "this is not a buying
signal" to points. If something is not a signal, leave it out of the signal sections.

General uncertainty (conflicting headcounts, what was not found) belongs once, in the watch-outs.

### Keep the researcher's warnings

When the brief says not to claim or promise something, the page must not claim or promise it. That
includes timelines, integrations and results the seller cannot yet show for this account. An open
question stays open: never turn "not established" into "met" or "not met", or into a rule the rep
must follow. The researcher's conditions for pursuing always appear, because they change what the
rep does.

### Realistic, with a path

Where the brief says the account is weak or not now, say so plainly, and always carry its
suggestions for how the seller could still improve its chances.

### 4. One home for each fact

Use each finding in the section where it does the most work. If another section needs it, refer to
it in a few words ("the staffing problem above") instead of repeating the sentence, the
numbers or the quote. Never repeat the same quotation in two sections. The short version at the top
of the Overview is the one place that deliberately restates the strongest points; everywhere else,
say a thing once. Repetition usually happens with the account's biggest fact, such as an incumbent
vendor, a big hiring wave or a new leader. Describe it fully once; elsewhere refer to it in a few
words and add only what is new for that section.

### 5. Each item stands on its own

Each item stands on its own. A reader may open any item without the ones above it. Name the person
or subject in the heading or the first sentence; never open with "he", "she", "they" or "in the
same interview". When an item is about a committee member, list their contact id on it.

### 6. Quote people when their words carry the point

When a person's own words make the point, name them, give their role, say where and when they said
it, and quote the words that matter exactly. Quotation marks contain only exact words from the
finding. Shorten your own explanation before you shorten the quote.

### 7. Stay accurate

- Only state what a finding supports, and cite that finding on the sentence that uses it. Do not
  add facts from your own general knowledge, such as who owns a company or which group a vendor
  belongs to. If a finding says "Acme Logistics is the freight partner", write exactly that — do
  not add "Acme Logistics, part of Big Holding Group" even if you believe it is true. The seller's
  own proof points (customer stories, published results) come from the seller brief; mention them
as advice and do not cite target findings for them.
- A quote you use must appear in a finding you cite on that sentence.
- Do not invent problems, needs, budgets, deadlines, results or relationships. A job posting shows a
  role is advertised, not that the team is struggling. Prior-employer work is that person's
  experience, not the current company's situation — but it can be very relevant experience.
- Do not claim the seller has done something for this target, or that the rep knows the person.
- Keep findings about other people with the same name out of the page entirely.

### 8. Never write about private matters

Some findings describe a person's health, therapy or medication, family, personal finances or
investments, legal or disciplinary records, or where they live. Do not use them anywhere on the
page — not as a point, not as an opener and not as a warning in "do not mention". Leave them out
entirely, as if they were not in the research.

### 9. Plain, short writing

Short paragraphs. Specific nouns and numbers. No filler ("exciting opportunity", "strong fit for our
solution"), no internal labels, finding ids, field names or instructions in the visible text.
Headings say what the point is ("Head of operations just left"), not the category ("Hiring signal").

Follow the length guidance each page gives. Most items need two or three
sentences: what we found, why it matters, what to do. A rep reads these pages between other work;
length is a cost to them. When you must cut, cut background and explanation, never the strongest
evidence or the action.

## Output

Return the JSON object described in the request. Every sentence has:

- `text`: the visible sentence;
- `kind`: `fact` (stated from findings), `quote` (contains a quotation), `inference` (your reasoning
  or advice), or `gap` (something the research did not establish);
- `refs`: the ids of the findings that support it. Facts and quotes need at least one ref.
  Inference and advice cite the findings they reason from when there are any.

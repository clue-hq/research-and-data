---
schema_version: '1'
kind: skill
name: contact-page
version: v1
summary: Write a contact's page so a rep knows why to talk to this person, what they care about, and exactly how to open the conversation.
roles:
- research_narrative
readiness_requirements: []
tools: []
framework: deepagents
framework_version: '>=0.6,<0.7'
---

# Write the contact page

Follow the shared page-writing rules. You are given the seller brief, the account's short story
(why the account matters), the account findings (ids like `A:F012`) and this person's findings
(ids like `F007`). Write about this person: what they own, what they have said and done, and how a
rep should approach them about the seller's offer.

The account page already explains the account; refer to it rather than retelling it.

## Length

Stay within these numbers; use fewer items when the evidence is thin:

| Section | Intro | Items |
|---|---|---|
| why-this-person | up to 1 sentence | up to 3 |
| problem-right-now | none | up to 3 |
| openers | none | 2 or 3 |
| angles | none | up to 3 |
| do-not-mention | none | up to 4 |
| miscellaneous | none | up to 4 |

Give each item at most three sentences. Short sentences read faster than long ones. If you have more
good material than fits, keep the strongest and drop the rest — the research record keeps everything.

### why-this-person — Why this person

Two to four items. Start with the single most important reason this person matters for the seller:
what they own that the seller's product touches, and the evidence. Then the evidence that makes them
more than a title match: something they said, decided, built or bought, especially anything that
shows they have dealt with the problem the seller solves, here or at a previous employer.

If there is well-documented public material about their life outside work (a cause they ride for,
a book they wrote), add one item for it. It helps a rep be human. Keep it to what they themselves
made public, and keep it short.

### problem-right-now — What they are dealing with now

Their current priorities and pressures, from their own words and recent actions where possible:
what they are hiring for, building, changing or talking about. For each, how it connects to the
seller's offer. If their stated priorities do not touch the seller's offer, say so in one line;
do not invent a connection.

### openers — Openers

Two or three opening lines a rep could send, each in `send_line`, with its hook in `body`.

Each opener:

1. starts from something specific this person said or did (quote it in the hook);
2. connects it to a problem the seller solves, in the person's terms, without naming the product
   or pitching;
3. ends with one easy question about how they handle that today.

The first opener must be the strongest business opener. A personal opener (based on public material
about their life outside work) may be offered last, only if it is natural and the person made that
material public themselves. Never build an opener on health, family, finances or anything they would
not expect a stranger to bring up.

Example of the shape (fictional; the seller here sells scheduling software): hook — the operations
director posted that "half our technicians are on the road every week". Opener — "With half your
technicians on the road each week, how do you keep their schedules current when jobs change?"

### angles — Angles

Two or three ways to make the seller's case to this person: what to emphasise, what to show, what
proof to bring and what question decides whether it is worth their time. Ground each in their
remit and evidence, and in what the seller actually offers.

### do-not-mention — Do not mention

Things the rep must not say or assume with this person: an unconfirmed role, a vacancy they may be
sensitive about, a past employer's project presented as the current company's, a competitor they
chose. At most four items, one or two lines each. Do not list other people who share their name.
Private matters (health, family, finances, legal records, where they live) are left out of the page
entirely, so do not mention them here either, not even as something to avoid.

### miscellaneous — Miscellaneous

Other useful background in short items: career steps relevant to the seller's offer, education,
memberships, public talks. At most four items. Leave out trivia, social-media likes, where they
live and anything about other people who share the name.

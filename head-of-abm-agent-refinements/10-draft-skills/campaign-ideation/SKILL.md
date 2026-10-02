---
schema_version: "1"
kind: skill
name: campaign-ideation
version: v1-draft
summary: Propose creative, signal-anchored campaign plays per account and tier, with divergent options and honest kill criteria.
roles:
  - head_of_abm
framework: deepagents
framework_version: ">=0.6,<0.7"
---

# Campaign ideation

Open this skill when the user wants ideas: plays for an account or a cluster, a campaign concept,
a channel plan, or "what would you do with these accounts." Ideation is an open field. Diverge
boldly, then let evidence and the user converge.

## The law: plays attach to signals, not to accounts

Every play you propose names the researched claims it rides. "Send the CEO a letter" is not a
play; "the CEO posted that founder-led sales stopped scaling, the ABM seat has been open 105
days, and no ABM tool appears in their stack: send the letter that speaks to exactly that" is a
play. If an account has no signal worth riding, the honest proposal is more research or patience,
and you say so.

Stack independent signals. Signals from different categories (funding, hiring, tooling gaps,
public statements, leadership changes, reviews) compound; three independent categories on one
account is a green light, one repeated signal is not. And remember what alpha means: a signal
everyone can see in a press release is weaker than one your research dug out of a job req body,
a review thread, or a podcast answer.

## The shape of a proposal

Always bring three genuinely divergent angles, never three variants of one idea. For each angle:

1. the signal citation (which claims, verbatim quote available on click)
2. the persona it lands on and why that person specifically
3. the channel and artifact (what the design leg would produce)
4. effort class and rough cost, using the tier economics from abm-craft
5. a kill criterion: what observed result kills this angle, and by when

Then recommend one and say why. When the user picks or rejects, record the reasoning as a
preference through the governed memory path; taste learned this week should shape next week's
first draft.

## The play library, by tier

Working repertoire distilled from the canon. Adapt freely; these are starting points, not a menu
the user must order from.

**Tier 1 (strategic, few accounts, human-heavy):**
- Executive dinner or micro-event: 8 to 15 seats, invite three times the seats, all-in cost in
  the $5k to $10k range, target four or more qualified meetings inside 30 days, expect a 60 to
  90 day lag. The best per-unit economics in the current canon when the list is right.
- Founder letter by verified direct mail: the physical letter to a named executive, address
  verified to the business suite, one researched observation carried in the first sentence.
- Custom asset plays: a teardown, benchmark, or book built for the account or its niche. The
  documented ceiling on this play family is very high when the asset is genuinely useful.
- Surround-sound ads: a padded company-targeted audience so the committee sees the story before
  and after every human touch.

**Tier 2 (scenario and cluster plays):**
- New-buying-center expansion inside existing customers: the highest-adoption motion in the
  field right now. Research the sibling division the way you would a cold account.
- Cluster campaigns: one sharp asset for a niche of 20 to 50 lookalike accounts sharing a signal
  (same regulation hitting, same tool sunsetting, same hiring wave), personalized at the cluster
  level, one-to-one only for the warmest few.
- Podcast-as-ABM: invite the economic buyer as a guest; the relationship is the play and the
  content is the byproduct.

**Tier 3 (programmatic, volume with dignity):**
- Signal-triggered sequences: new-in-seat, fresh funding plus GTM hiring, tooling gap confirmed.
  Trigger quality is everything; a stale trigger reads as spam with homework.
- LinkedIn-led resequencing: profile view, then connect, then email. Documented to more than
  double positive reply rates versus email-first in the agency canon.
- Gifting used sparingly and specifically; a $30 relevant book outperforms a $5 gift card and an
  irrelevant $200 basket alike.

## Channel doctrine, held in tension

The canon disagrees with itself and you should hold both ends: multichannel orchestration wins at
tier 1 and 2 (running one channel means ignoring half the committee), while at tier-3 volume some
of the best operators deliberately keep LinkedIn and email un-orchestrated to protect
deliverability and sanity. Pick per tier and say which doctrine you are applying.

## Boundaries, held softly

- Relevance over personalization: reference what the person said or what the company is doing,
  never their dog, their vacation, or anything that signals surveillance instead of homework.
- No play built on sensitive-class claims, ever. That line is hard and lives in the platform.
- Do not fake scarcity, invent deadlines, or manufacture intimacy. One honest observation beats
  three manufactured ones.
- Respect the long game: for six-figure deals the canon says hundreds of touches over many
  months. Frame every play as a chapter and show the user where it sits in the arc.

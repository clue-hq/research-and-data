# r18 section-input review

These are saved-claim examples, not generated narrative or newly verified facts. The complete offline selection is also prepared.

- [Start with the full selection review](../../../../.artifacts/narrative-selection-20260926/REVIEW.md).
- [Every claim, its categories and destinations](../../../../.artifacts/narrative-selection-20260926/claim-routing.csv).
- [Full original context documents](../../../../.artifacts/narrative-selection-20260926/shared-context.json).
- [Every retained finding, including non-narrative records](../../../../.artifacts/narrative-selection-20260926/complete-findings.md).

## What has been prepared

Nineteen candidate packets cover Zafran Overview (six), Insights (seven), and Nick’s Contact page (six). All 481 records are accounted for: 336 selected, 24 direct fields, and 121 complete-findings-only outside these pages. There are no currently unmapped records. 321 claims occur in more than one packet.

The 121 are not deleted or judged unimportant. For example, the other four people have no contact pages in this trial, so much of their education and personal history stays in complete findings. Their relevant professional evidence remains eligible for account pages.

Mappings are explicit fixture annotations, not code deployed into research. The script uses r18 entity/finding IDs deliberately to make the example reproducible; the system prompt and proposed production categories remain generalized.

## Important limitation before a model trial

These are broad review packets. Why-they-fit currently contains 235 primary records and four linked companions. That selection needs review for relevance and a lossless model view before paid calls; its large size cannot be assumed to meet the 60-second target. Original entry copies and provenance are retained for audit. Removing repeated structural copies later must not shorten the substantive findings.

All three selected document bodies match the original pinned hashes. Each packet references the shared context file; a future request assembler must inline those documents with stable evidence IDs, not give a tool-free model an unreadable local path. No rendered model requests or generated sections exist yet.

## Concrete reuse examples

### Hiring language about team and resources

Claim `2cdd3f41-95b0-4c1c-bca4-77d5725e27dd` · Account `F021` · `account.research_finding`

**Stored finding, unchanged:**

The Senior Manager, ABM & Integrated Campaigns posting states: "We're looking for a builder and operator, someone who can think strategically but also execute hands-on, and thrive in a fast-moving environment. If you need a large team and a large budget to do great work, this role is probably not for you. But if you know how to move quickly, and build meaningful programs with focus and creativity, we'd love to talk."

**Stored qualifications and interpretation, unchanged:**

```json
{
  "attribution": "Zafran Security Ashby job posting",
  "time_context": "Observed 2026-09-26",
  "qualifications": [],
  "agent_interpretation": "This is hiring copy describing the role's constraints, not a disclosed marketing budget figure.",
  "review": {
    "reason": "Quoted from the Ashby posting body.",
    "status": "supported",
    "duplicate_of": null,
    "conflicts_with": [],
    "expected_entity": null
  }
}
```

**Stored source URLs:**

- [web_snapshot](https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf)

**Proposed destinations:** `overview/why-they-fit`, `overview/why-now`, `overview/how-to-approach`, `insights/buying-signals`, `insights/organization-and-teams`, `insights/contact-insights`, `nick/why-this-person`, `nick/problem-right-now`, `nick/angles`

**Review instruction:** Why-they-fit may relate the described working constraints to a documented seller capability; buying-signals explains the actual hiring mandate. Neither may turn this wording into a disclosed budget or a proven purchase intention.

### Named tools in an employer job posting

Claim `7bc7298f-2de4-4f6a-b464-cbf9fcd71c11` · Account `F042` · `account.research_finding`

**Stored finding, unchanged:**

Under "Execution & Optimization," the posting says: "Build and launch campaigns yourself in HubSpot: workflows, nurture journeys, landing pages, email sequences, the whole thing." It also says: "Run paid media, retargeting, social, content syndication, webinars, and event programs in a coordinated way, not in silos." Additional bullets include A/B testing constantly, iterating weekly, using "analytics, dashboards, intent data, pipeline reports," partnering with Sales Enablement on materials and outreach sequences, and "Own budget allocation, vendor, contractors and channels with a clear ROI lens."

**Stored qualifications and interpretation, unchanged:**

```json
{
  "attribution": "Zafran Security Ashby job posting",
  "time_context": "Observed 2026-09-26",
  "qualifications": [
    "HubSpot is named as the execution environment the hire is expected to use; this is not independent proof of current HubSpot configuration."
  ],
  "agent_interpretation": null,
  "review": {
    "reason": "Quoted from the Ashby posting Execution section.",
    "status": "supported",
    "duplicate_of": null,
    "conflicts_with": [],
    "expected_entity": null
  }
}
```

**Stored source URLs:**

- [web_snapshot](https://jobs.ashbyhq.com/zafran-security/c879de63-c999-47cc-99a3-e35cf9ba7cdf)

**Proposed destinations:** `overview/why-they-fit`, `overview/buying-committee`, `overview/how-to-approach`, `insights/buying-signals`, `insights/organization-and-teams`, `insights/tools-they-already-use`, `insights/contact-insights`, `nick/why-this-person`, `nick/problem-right-now`, `nick/angles`

**Review instruction:** Systems/workflows should preserve that the evidence is a job posting. It cannot establish every named system is installed, or that the seller integrates with those systems.

### Public wording with mixed attribution

Claim `31d97e22-ecb6-4172-b912-c66c1b742bc7` · Nick `F031` · `contact.research_finding`

**Stored finding, unchanged:**

On 2026-03-15 Fisher posted: "If your GTM team is anything like ours, you're in the messy middle of AI adoption right now. Everyone's experimenting. Some people are building workflows that save hours a week. Others are one click away from letting an AI overwrite your pipeline data or blast prospects with something no human would ever send. The hard part isn't saying yes to AI. It's figuring out where to say yes and where to put guardrails." He then relayed five practices from "Jason M. Lemkin at SaaStr Ai" in his own framing, including "AI in GTM fails when it's siloed in either data/engineering or sales alone" and "Tools aren't a silver bullet; the real work is cleaning your CRM data, connecting your systems, and layering in company-specific context (ICPs, pitch decks, product docs) so the LLMs actually produce useful output." He tagged Ross Brown, Tom Anthony, Rotem Peled-Dvir, and Tomer Admon. URL: https://www.linkedin.com/posts/nicholastfisher_if-your-gtm-team-is-anything-like-ours-youre-activity-7438938896102707200-o5P5

**Stored qualifications and interpretation, unchanged:**

```json
{
  "attribution": "Nick Fisher, LinkedIn post; numbered practices attributed by Fisher to Jason M. Lemkin / SaaStr",
  "time_context": "2026-03-15",
  "qualifications": [
    "The five numbered practices are Fisher's restatement of Lemkin, not original empirical findings.",
    "\"Like ours\" is Fisher's characterization of Zafran GTM, not a measured adoption metric."
  ],
  "agent_interpretation": null,
  "review": {
    "reason": "Opening paragraphs are Fisher's; the five practices are explicitly attributed by him to Lemkin/SaaStr while restated in the post.",
    "status": "supported",
    "duplicate_of": null,
    "conflicts_with": [],
    "expected_entity": null
  }
}
```

**Stored source URLs:**

- [web_snapshot](https://www.linkedin.com/posts/nicholastfisher_if-your-gtm-team-is-anything-like-ours-youre-activity-7438938896102707200-o5P5)

**Proposed destinations:** `overview/why-they-fit`, `overview/why-now`, `overview/how-to-approach`, `insights/buying-signals`, `insights/strategy-and-initiatives`, `insights/tools-they-already-use`, `insights/contact-insights`, `nick/why-this-person`, `nick/problem-right-now`, `nick/experience-and-perspective`, `nick/openers`, `nick/angles`

**Review instruction:** People/public statements can preserve the public wording; approach/angles can discuss a possible conversation theme. The author’s framing and practices attributed to somebody else must remain distinguishable.

## Reproduce and verify

From the repository root:

```sh
python3 docs/superpowers/drafts/2026-09-26-parallel-narrative/prepare_r18_inputs.py
```

The script reads local retained files and writes only `.artifacts/narrative-selection-20260926/`. It checks unique IDs, full value/evidence preservation and reverse routing; its output manifest records input/output hashes. It performs no network/model/database operations.

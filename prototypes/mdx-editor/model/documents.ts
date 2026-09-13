export type DemoDocument = { id: string; title: string; label: string; path: string; body: string };

export const documents: DemoDocument[] = [
  {
    id: "plan", title: "New logo campaign", label: "Campaign plan", path: "project/plan.md",
    body: `# New logo campaign

Build a focused campaign for regional healthcare teams. Start with the accounts where our product can make the clearest difference.

## What success looks like

Create **10 qualified conversations** with operations leaders in the next quarter. Lead with a useful, specific point of view—not a generic product pitch.

> A smaller, well-researched account list is more valuable than a broad list with weak fit.

## Campaign approach

1. Confirm the ideal customer profile.
2. Research each account and its buying committee.
   - Identify the operational challenge.
   - Find a relevant reason to reach out.
3. Draft and review the first message.

| Audience | Message focus | First channel |
| --- | --- | --- |
| Operations leaders | Reduce repetitive intake work | Email |
| Clinical champions | More time for patient care | LinkedIn |

## Before launch

- [x] Confirm the target market
- [ ] Review the account shortlist
- [ ] Approve the first outreach message

Use the \`account.research.status\` field to check readiness. Keep the [campaign brief](https://example.com/campaign-brief) nearby during review.

---

### Message outline

\`\`\`text
Open with a relevant observation.
Connect it to the team's day-to-day work.
Offer one useful next step.
\`\`\`
`,
  },
  {
    id: "knowledge", title: "Company overview", label: "Knowledge document", path: "company/overview.md",
    body: `# Company overview

Northstar helps healthcare teams simplify everyday administrative work.

## Brand voice

Be **clear**, *considerate* and specific. ~~Unmatched synergy~~ is not how we describe a useful product.

### Who we serve

- Regional clinics
- Growing care networks
- Operations and patient-access teams

#### Supporting detail

This fourth-level heading should survive editing.

##### Reference note

Fifth-level headings should stay intact too.

###### Small print

This sixth-level heading is included to check content preservation.

Read [our positioning note](https://example.com/positioning) before writing a campaign.
`,
  },
  {
    id: "long", title: "Long content check", label: "Long text & tables", path: "examples/long-content.md",
    body: `# Long content check

This document checks that long content stays inside the document panel.

## Inline code and links

Here is a long identifier: \`account.research.${"regional_healthcare_network_".repeat(10)}status\`.

https://example.com/research/${"regional-healthcare-network/".repeat(16)}overview

## A wide table

| Account | Region | Primary audience | Research finding | Proposed next step |
| --- | --- | --- | --- | --- |
| Northstar Regional Healthcare and Community Services | North America | Operations and patient access leadership | ${"A long finding with supporting detail. ".repeat(8)} | Review the opportunity together |

## Long code

\`\`\`text
${"a_long_unbroken_identifier_".repeat(25)}
\`\`\`
`,
  },
  {
    id: "recovery", title: "Source recovery check", label: "Unsupported content", path: "examples/recovery.md",
    body: `# Source recovery check

This paragraph must remain available even if visual import fails.

<CampaignCard audience="operations"

The tag above is intentionally unfinished. In Source mode, remove that line, then switch back to Rich text.
`,
  },
];

export const storageKey = (id: string) => `clue:mdx-prototype:v1:${id}`;

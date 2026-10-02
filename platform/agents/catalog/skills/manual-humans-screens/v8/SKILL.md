---
schema_version: "1"
kind: skill
name: manual-humans-screens
version: v8
summary: "Manual: what a human does on which screen, what the buttons are called, what they see for each of your tool calls, and how you learn any of it happened."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
<!-- sources: research/2026-09-13-head-of-abm-manual/D-authority-gates-and-human-surfaces.md §3.1 (the table), §3.2 (discovery approval), §3.3 (the gate card), §3.4 (not found), §3.5 (brand kit actions), §3.6 (the three channels), §3.7 (what the human sees per tool call) -->
# Humans and screens: where the work you cannot do gets done

Use the names the interface uses when you tell a human where to go. Guessing a control into
existence wastes their time.

| What the human does | Screen, as it is labelled | The control they click | How you learn it happened |
| --- | --- | --- | --- |
| Add discovered accounts to a project | "Account" in the nav, "Accounts" as the page title | "Add to project", after picking a project under "Choose a project" | the accounts count and the discovery approved count in `project/status.md`; the accounts read |
| The same, inside a project | "Target accounts" | "Add accounts", then "Add {n} account(s)" in the dialog | the same |
| Edit a knowledge document | "Brand context", section "Knowledge" | "Edit", then "Save changes" | the file itself, re-seeded next turn. Also: an ICP gate you already opened refuses if that document moved |
| Attach accounts or contacts to a message | the "Add to chat" dialog, or the "@" button in the composer | "Add to chat" | they arrive as this turn's attached refs, in `inputs/current-context/` |
| Answer one of your gates | the card in the chat transcript | see the buttons below | the answer arrives as their next message, and its consequences appear in `project/status.md` |
| Onboard a brand | the onboarding flow at `/onboarding`, which shows "Setting up your workspace, this will take a few minutes..." | "Continue" on the profile step; the run then starts on its own | brand documents and the brand index appear in your workspace |
| Rename a chat, archive a chat | the chat header menu | "Rename chat", "Archive chat" | a rename is invisible to you. An archived thread accepts no further turns, so you never run on it again |
| Rename a project | the project menu in the sidebar | "Rename project", then "Save" | the project title line in `project/status.md` |
| Stop your turn | the composer, where send becomes a stop square | "Stop response" | you do not learn it. Committed effects stay committed, and the thread queue is held until the human presses "Resume" |
| Resume a held queue | the banner saying "{n} message(s) queued" | "Resume" | the next turn runs |

## Things that do not exist, and must not be offered

- **There is no onboarding control on the Knowledge page.** That page only shows results.
  Brand onboarding runs from the `/onboarding` pages and starts on its own after the profile
  step. Say that, not "start onboarding on the Knowledge page".
- **There is no Plan tab.** The route to save an edited plan exists in the backend, but nothing
  in the interface calls it. Do not tell a human to edit the plan on a screen.
- **"Delete chat" and "Pin project" are rendered but do nothing.** They are not wired to
  anything.
- There is no screen for adjusting a run's budget cap, and no "Add to chat" for contacts
  outside a project.
- There is no reject control for a discovered company. Adding to the project and approving are
  the only decisions, and unapproved is not rejected. See `.deepagent/skills/manual-discovery/v8/SKILL.md`.

## The gate card the human clicks

| Gate | Card title | Buttons |
| --- | --- | --- |
| product set selection | "Choose this project's products" | "Use these products" / "Not now" / "Request changes" |
| ICP confirmation | "Review your ideal customer profile" | "Approve profile" / "Reject proposal" / "Request changes" |
| directive confirmation | "Review the research plan" | "Start research" / "Don't start" / "Request changes" |

Afterwards the card reads back as "Products selected", "Profile approved", "Research approved"
or "Changes requested". Asking for changes opens a box labelled "What would you like changed?".
The product card groups candidates under Products, Platforms, Integrations, Partner programs,
Services and Other, and badges an uncertain lineage match "Possible duplicate", which means the
catalog research could not tell it apart from another product. Point that out in your own
message so the human can decide.

Your message is the explanation; the gate is the decision control beside it. Do not write the
explanation into the gate, and do not treat the card as having said what you did not say.

## What the human sees for each of your tool calls

A tool call appears as a card whose state reads "Preparing", then "Running", then "Completed",
"Denied" or "Failed". A failure reads "This step could not be completed. Ask the assistant to
try again."

Only a few of your tools have a label: "Draft an ideal customer profile", "Write the buyer
personas", "Write the project plan", "Prepare the profile for your review", "Save your answer",
"Review the project's accounts", "Review an account's research", "Review the discovery run",
"Prepare the research plan".

**Everything else you call renders as "Complete a project step".** That includes the product
set gate, all three research and discovery launches, opening a design leg, the run read, the
field and source proposals, and the statement history read. So the card tells the human almost
nothing about what you just did. Say it in words in your own message rather than assuming the
card explained it.

## The three ways you learn anything

1. `project/status.md`, recompiled from the rows each turn.
2. `project/decisions.md`, the human's own recorded words.
3. The seeded files and their index cards, plus the live read tools.

**There is no event feed, no notification and no diff.** You learn by re-reading and by
calling a read. Nothing will tell you that a human edited a document, answered a gate in
another thread, or approved accounts while you were working; look, and say what you find.

---
schema_version: "1"
kind: skill
name: persona-authoring
version: v1
summary: "Write the personas for this project's pinned ICP at project/audience/persona-<key>.md, one section per role."
roles:
  - head_of_abm
readiness_requirements: []
tools: []
framework: deepagents
framework_version: ">=0.6,<0.7"
---
# Audience personas

You write the personas for this project's confirmed profile, as a customer research strategist
writing for a B2B account-based marketing team. The ICP is the one this project pinned:
`project/audience/icp-<key>.md`, for that key only — never another key, and never a proposal the
human has not confirmed. Write `project/audience/persona-<key>.md` for that ICP with one section
per role in its persona_map, in this order: economic_buyer, champion, user, technical_evaluator,
blocker. Skip a role only if the ICP omits it.

You have no web tool here, so there is no evidence pass to run. Sections 3, 6 and 10 are written
from the ICP, the product files under `brand/knowledge/product/` and
`brand/knowledge/proof/customer-reviews.md`, and each such claim is marked as inference.

For each role, write:
1. Role and snapshot (3–4 sentences). Who holds this role at an account that passes the hard
   gates, what they own, why this problem is theirs. No fictional names. Firmographic ranges come
   from the ICP, not from you.
2. Titles that hold this role (up to 8). Exact title strings and common variants as they appear
   on LinkedIn and org pages. These are search keys.
3. Daily reality (up to 6 bullets, one sentence each). Responsibilities, tools, where friction
   shows up. Name a tool or a number only if a file supports it; otherwise mark it inference.
4. Core fears (up to 5 bullets, 15 words or fewer each).
5. Deep motivations (up to 4 bullets). Practical and aspirational.
6. Critical pain points (up to 6 bullets). Industry-specific, phrased as the pain.
7. Buying triggers (up to 6 bullets). Observable events on the account that mean this person is
   in motion: a job posting, a regulation date, a system migration, a leadership change, a
   complaint pattern. Each must be something a researcher could find.
8. Trust builders (up to 5 bullets), customer-first: "Show me...", "Prove you...".
9. Trust killers (up to 5 bullets), blunt.
10. Language and channels (up to 5 bullets). Words and phrases they use for the problem, and
    where they read or ask: communities, publications, events.
11. How the products serve them (1 paragraph). Only capabilities the product files state, cited
    by file. Tie each capability to a fear or pain above.

Rules. Cite the source of any specific fact in parentheses, as the file path it came from. Mark
inference as inference. Prefer fewer sourced bullets over the maximum count. No platitudes. No
em-dashes. 300–450 words per role. Put titles (2) and buying triggers (7) in the front matter as
well as the body.

Write the personas only when the human asks for them, on or after the turn the ICP was confirmed.
Save the file with `write_file` at `project/audience/persona-<key>.md`. A redraft is a new write
of the same path.

## The persona artifact format (write exactly this front matter)

```yaml
---
kind: audience-persona
icp_key: <the ICP's key>
icp_version: <the version of the confirmed ICP you wrote these from>
personas:
  - role: economic_buyer
    titles: [<the section-2 titles>]
    buying_triggers: [<the section-7 triggers>]
---
```

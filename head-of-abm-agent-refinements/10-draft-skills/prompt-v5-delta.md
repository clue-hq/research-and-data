# Draft: prompt v5 delta for `prompts/head-of-abm/v5/SYSTEM.md`

Prompt v4 survives verbatim. v5 inserts two blocks. Nothing is removed; the governance text is
untouched. Total addition is about 20 lines, respecting the context budget (file 06, principle:
smallest set of high-signal tokens).

## Block 1: identity layer

Insert after the opening paragraph ("You are the platform Head of ABM..."):

> You are also a senior ABM practitioner, and the user hired that seniority. Diagnose before you
> prescribe. Commit to a recommendation and name what would change your mind. Push back on plans
> the evidence argues against, including the user's, and update on evidence rather than on
> displeasure. Prefer one concrete proposal the user can edit over an open question, and one
> material question over a form. When the user teaches you a preference, restate it, apply it,
> and route it to memory in the same turn.
>
> In every word a client-facing artifact or reply carries, follow the copy-voice constitution.
> Two of its rules are absolute: no em dashes anywhere, and no specific fact that does not trace
> to a claim or to the user's own words.

## Block 2: skill routing

Extend the existing routing paragraph ("Open the disclosed skill that matches...") with:

> For strategy, program shape, qualification, measurement, or "what should we do," open the ABM
> craft skill. For campaign ideas, plays, or channel plans, open the campaign ideation skill. For
> any writing a human outside the team will read, and before reviewing any draft, open the
> copy-voice skill. These skills are counsel, not workflow: the user may take, adapt, or refuse
> any recommendation, and gates stay where they are.

## Wiring notes

1. Copy `prompts/head-of-abm/v4/` to `v5/`, apply the two blocks, bump frontmatter `version: v5`.
2. `shasum -a 256` the new SYSTEM.md; pin digest in `profiles/head-of-abm/v39/profile.yaml`
   together with the three new skill pins (abm-craft v1, campaign-ideation v1, copy-voice v1).
3. copy-voice is also pinned into the content-drafter and reviewer profiles at their next
   versions, and its three absolute rules ride the design-leg delegation bundle.
4. Update `C6_ACTIVE_PROFILE_VERSIONS`, the aggregate manifest digests in
   `tests/api/test_agent_registry_wiring.py`, and add qualitative fixtures per the authoring
   guide. Run the full gate (`pytest tests/agents tests/api/test_agent_registry_wiring.py`,
   `make check`, `make db-smoke`).

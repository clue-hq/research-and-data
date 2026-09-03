# Draft skills: status and wiring caveats

These are **drafts for founder + Aryan review**, not wired catalog files. They live here, outside
`platform/agents/catalog/`, on purpose: catalog bytes are immutable once published, so nothing
should land there until the text is ratified.

Contents:

- `abm-craft/SKILL.md`: the worldview skill (thinking, qualifying, planning, questioning, learning).
- `campaign-ideation/SKILL.md`: the signal-anchored play proposal system.
- `copy-voice/SKILL.md`: the writing constitution (granted to head_of_abm, content_drafter, reviewer).
- `prompt-v5-delta.md`: the exact ~20-line addition that turns prompt v4 into v5.

Known gaps to close at wiring time (deliberate, per `docs/agents/skill-and-profile-authoring.md`):

1. **No `tools:` pins in the frontmatter yet.** These skills grant no new tools, but if any pin is
   wanted (e.g. memory routing), take live descriptors from `build_toolbelt(...)`, never guessed
   schemas.
2. **`version: v1-draft` must become `v1`** when copied into the catalog, with folder name and
   frontmatter matching.
3. **Knowledge packs referenced by abm-craft** (`context/knowledge/abm-canon-pack.md`,
   `agency-playbook-pack.md`) do not exist yet; they are produced by corpus Phase 1 + distillation
   (file 08). Until they exist, the skill's numbers stand on the research files in this folder.
4. The three skill files contain **zero em dashes** by design; keep it that way in review edits.
   Verify with: `grep -c '—' 10-draft-skills/*/SKILL.md` (expect 0 for each).

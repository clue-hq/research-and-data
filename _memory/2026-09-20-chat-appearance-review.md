# Chat appearance review documented

- Founder asked to record the preceding read-only visual review for later frontend work.
- Canonical record: `apps/frontend/docs/figma/projects-chat-flow.md`, section
  `Chat appearance inconsistency register (2026-09-20)`; linked from the frontend docs index.
- Open findings: CHAT-VIS-01 body typography (15/22 composer versus 14/20 transcript),
  CHAT-VIS-02 mention appearance/icon drift, CHAT-VIS-03 attachment-chip size/geometry drift.
- Baselines: Damascus `074f038e3` on `rebase-and-expand-attachment-types`, port 3027;
  dummy port-of-spain `9fc902a` on `codex/projects-home`, port 3000. Generated tokens identical.
- Record distinguishes measured browser evidence from source-only comparisons. The current
  dummy has no populated agent transcript; 15/22 throughout is the proposed direction based
  on the founder's preferred composer, not a claimed newer dummy transcript.
- Includes source pointers, preserved properties, presentation-only boundary and unchecked
  acceptance criteria. Appearance implementation remains open; no runtime code changed.
- Documentation links and whitespace checked before the local commit; no runtime tests
  required for this documentation-only update. No remote publication.

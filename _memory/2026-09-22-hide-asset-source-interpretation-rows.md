# Hide incomplete asset source rows — 2026-09-22

- User requested removing Observed use, Logo relationship and Messaging & tone for now.
- Prior read-only investigation found 415/489 image inputs had only resource-level provenance, 29 had surrounding text, and the paragraph-only trust section was missed by the heading/caption heuristic. The original page HTML is retained. Those capture/schema improvements were discussed, but the user chose this display-only removal for now.
- Removed those three display rows from `AssetContextDetails`. Empty source-interpretation sections now render nothing. Stored analysis, prompts, API contracts and other inspector fields are unchanged.
- Verified the live city-image inspector: Agent context expands, all three labels are absent, and remaining interpretation/visual fields render. Closed the verification modal and preserved the user's existing browser tabs.
- Design-system token generation passed. Full lint passed with the two existing unused-variable canvas warnings.
- Initial isolated production build compiled and type-checked, then failed during standalone tracing because a symlinked dependency tree produced an invalid temporary output path. Replaced that temporary symlink with a local dependency tree for the build rerun; live development output was never touched.
- No new tests added for this small display-only removal. Final isolated production build passed, including TypeScript and standalone packaging. Build/lint logs: `/tmp/san-diego-hide-source-rows-{build,lint}.log`.

# Native Clue website baseline — 2026-09-20

Four authenticated Clue chats created and saved four website artifacts. This is native platform execution, not the isolated gallery at port 8052. All four initial Design runs succeeded technically and finalized `completed_with_warnings`; none establishes the full source-fidelity and account-personalization quality target.

## Runtime brought online

- Docker Desktop engine 29.8.0 and `clue-agent-sandbox:latest` verified. Eight sandbox checks passed, including real containers. Docker executable resolution was fixed without weakening the sanitized environment, mount restrictions, or network isolation.
- Obsolete recipe versions stopped being promoted at startup; historical replay remains intact. Twenty-five focused offline recipe tests passed.
- Four detached platform fleet workers, four slots each, execute the normal platform runtime. The design API's embedded worker is disabled for this local launch so jobs retain platform account/brand read access.
- APIs 8010/8020/8030 and brand frontends 3021–3024 remain available. Existing authentication, workspace bindings, storage, models and databases were retained.
- Website-binding migration `d27183d13445` was rehearsed up/down/up on a restored disposable database before application to the local database. A fresh local backup was retained. No remote push or deployment was performed.

## Native creation results

| Workspace | Target | Design duration | Metered Design model calls | Recorded Design cost | Core website skills read |
|---|---|---:|---:|---:|---:|
| Clue | Google | 6m 20s | 21 | $1.7603 | 9/11 |
| AWS | Insight Health | 6m 29s | 15 | $1.4655 | 8/11 |
| Google Cloud | NVIDIA | 7m 58s | 24 | $1.8814 | 9/11 |
| Conduit | Hyatt | 8m 30s | 35 | $2.5612 | 8/11 |

Durations include Design queue time, not preceding Head-of-ABM planning. The $7.6684 total excludes Head-of-ABM, logo/provider, ingestion and other costs outside persisted Design results. Assets and layouts were selected/authored by Clue after ordinary chat prompts; no finished test pages or manually selected source assets were inserted into these projects. These four runs reused imagery rather than generating new raster images.

### Saved native outputs

- [Clue for Google](http://localhost:3021/projects/prj_4756bac44df3538ea17a27552dd75289/chats/thr_57bc4ae644da520ba2a398c600bf604e?surface=web)
- [AWS for Insight Health](http://localhost:3022/projects/prj_fa693a2dcf685057a65da030211ccde4/chats/thr_31ded94b16f555449126a32073534fc2?surface=web)
- [Google Cloud for NVIDIA](http://localhost:3023/projects/prj_1648861065545d93a1f228ff2f651a2a/chats/thr_cdb4d02af39952fa8ce42365101a5803?surface=web)
- [Conduit for Hyatt](http://localhost:3024/projects/prj_5edcb7b02e9e5f43aefe4667fecf410e/chats/thr_ac2766b1a6925dd8941667ac157576b5?surface=web)

## What this proves about skills

The deployed library contains 11 core website entry skills and 14 detailed references, alongside the broader design library. Across these four initial runs, 9/11 core entries were actually read. All four read source readiness, creation, campaign workflow, campaign landing page, account personalization, conversion copywriting, media composition and website review. Clue and Google also read cloned-section repair. Supporting plan/design guidance was used; Google additionally read brand imagery.

No initial run read `edit-website` or `web-motion-fidelity`. The subsequent Conduit identity edit successfully read `edit-website`, bringing observed core-entry coverage to **10/11**. Motion remains untested. Reading a skill does not prove its output meets the skill's acceptance criteria. The four cases also do not test contact personalization, one-to-few/many pages, event pages, batch derivation, custom TSX or publication. Unfinished capture prototypes and unwired Head-of-ABM draft skills were not promoted as ready.

## Quality failures and evidence limits

1. **The live source libraries are older than the isolated fresh captures.** Clue and Google selected prior agent-composed fragments, not captured source-site components. AWS had a small captured library but could not inherit the complete hero CSS through the bounded inspection response. Conduit had zero released sections and composed all eight bands using the native vocabulary. The deeper captures in the separate test database were not copied into live brand context.
2. **Source comparison did not run successfully.** Clue, AWS and Google returned `broken_clones=[]` but `comparison=null`, `reference_unavailable=no_snapshot_provenance` and LUMA0801. That is not a source-fidelity pass. Conduit skipped clone comparison because it had no clones.
3. **Hyatt corporate identity failed on the first pass and was corrected through chat.** The original Conduit run used a World of Hyatt loyalty lockup and admitted the mismatch. The focused edit took 4m25s and reused the existing corporate wordmark `asset_ing_62d4dc88d9037565`, created by the logo ladder on September 16. Parent verified its recorded source URL against the current official [Hyatt investor page](https://investors.hyatt.com/overview/default.aspx): the page references the same Q4 CDN logo path. No logo was manually added this turn. The content diff changes only the header image reference; asset metadata also adds the corporate asset and updates two capture timestamps. Fresh logo lookup still returned the loyalty mark or failed, so generic logo selection/reuse needs improvement despite this successful correction.
4. **Account relevance is shallow.** The new projects contain no researched target-account rows. These are named-account invitations using seller evidence, not deeply researched or batch-bound account pages. No discovery or account research was restarted.
5. **Copy still needs judgment.** Google visibly includes internal caveats in visitor-facing copy; AWS similarly exposes uncertainty in its copy. The Clue hero is largely generic. Factual restraint does not by itself create persuasive account copy.
6. **Motion remains unqualified.** These runs did not demonstrate recovered source JavaScript/WebGL or exercise the motion skill.

Parent inspected all four native desktop top viewports and all four mobile screenshots, including Conduit's corrected corporate wordmark. Read-only DOM checks at the actual mobile preview widths (356–357 CSS px) found no horizontal document overflow and no completed broken images across all four original documents (6/4/7/8 images respectively). These are bounded checks, not full-page visual acceptance or export/publish verification. The 4m25s identity-only edit is also a latency failure for a small change; four repeated logo lookups contributed, and it should not be presented as a fast edit path.

## Next implementation boundary

First repair the governed capture-to-approved-brand-library handoff in the native workspaces, preserving existing brand edits and asset provenance. Source readiness must distinguish captured originals from agent-composed variants and report missing captures explicitly. Do not seed assets or transplant completed isolated pages to conceal that gap.

Then repeat the same four chat prompts against genuinely available source components, add a scoped-edit case and a source-supported motion case, and inspect full desktop/mobile outputs. Corporate-versus-sub-brand identity selection and account-grounded copy remain acceptance gates. Expanding skill count is not the immediate bottleneck.

## Local evidence

Detailed, non-published receipts are under `.local-setup/native-website-runtime/`: `manifest.json`, `native-run-audit-summary.json`, `native-run-audit-summary.md`, `native-run-trace-audit.json`, and `docker-smoke-green.log`. The baseline audit pins the original four run IDs and excludes later correction turns. Separate edit receipts: `conduit-identity-edit-snapshot.json`, `conduit-identity-edit-verification.json`, and `hyatt-existing-logo-source-verification.json`.

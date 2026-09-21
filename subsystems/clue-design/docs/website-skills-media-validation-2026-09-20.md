# Website media and motion skills — validation record

Branch: `codex/website-capture-v1`; tool contract inspection started at `f122a52a`. Scope is application guidance in `knowledge_docs`, not a new runtime, capture pipeline, brand seed pack, or changed live asset. The four named workspaces are regression samples; the guidance uses no brand-specific constants or asset ids.

## Observed baseline before authoring

The actual four-run baseline in `website-abm-baseline-2026-09-19.md` produced four persisted drafts and zero pages meeting the proposed full fidelity/account-grounding bar. Media-specific observed failures were Clue's source landscape/centered composition replaced with a flat left-aligned block; Google imagery that poorly explained adjacent claims and repeated seller marks; and Conduit's incomplete footer mark with the target logo absent after a loyalty-program candidate was correctly rejected. The baseline traces showed image reuse/fetching, no generation event. A mandatory-generate rule would misdiagnose these failures.

`website-source-capture-2026-09-20.md` records exact-byte verification of Conduit 48×72/64×64 downloaded renditions and 480×720/128×128 counterparts. URL requests were larger than decoded pixels. Source-family search now addresses selection mechanics; it does not enforce placement suitability, infer rich asset roles, or create higher-resolution originals. The documented preview fix is an isolated implementation, not a live-UI claim.

Motion baseline evidence is an **unverified capability boundary**, not a demonstrated animation-quality pass: source keyframes and four Google video files were retained; AWS canvas tags were present without recovered runtime. The recorded page review did not verify carousel/tab motion or video playback. A missing video fallback caused refusal, and recovered wrapper fragments retain explicit context gaps. No recorded agent quotation claiming recovered WebGL is invented here.

## Pressure scenarios frozen before skill text

These are three independent application scenarios for a later fresh-agent check. Give the candidate the current tool descriptions and relevant skill catalog, then ask for concrete decisions and an evidence plan. Preserve its response and score the decisions, not the appearance of keywords. The scenarios do not require paid generation or live mutation.

### 1. “Use the 2048 image; the client is waiting”

A new brand's source has a named customer photo. An exact asset id points to 48×72 bytes; its URL includes width=2048. Search lists a proven 480×720 ready family alternative and a visually similar crop from another capture. The page needs 600×900 CSS pixels at 2×. The stakeholder calls the largest rendition “the original” and requests delivery now.

Expected decisions: retain the exact-id meaning; calculate 1200×1800 required usable pixels; inspect the 480×720 alternative but call it insufficient; keep the other capture/crop distinct; avoid query stripping, fabricated upscaling and generated customer replacement; choose a justified smaller layout/verified adequate alternative or report governed acquisition as a gap. Record source role, provenance, chosen treatment and final viewport evidence. Search success and ready status cannot imply quality acceptance.

### 2. “Rebuild this product hero with a logo from the first result”

A source hero layers an alpha product UI over a photographic horizon. The screenshot includes its own rounded corners. The source inspector is truncated. The target has a verified account/domain, but logo retrieval returns a loyalty-program mark and no proven parent-company lockup. A request asks for a new decorative background while preserving the real UI; the first generation response includes a placeholder warning. Delivery time is short and a palette-matched flat block is easy.

Expected decisions: preserve original product pixels, crop/corners/alpha and source-derived layering; name the incomplete source evidence; make a separate decorative derivative decision, with source composition and provenance, and reject the placeholder as successful generation. Reuse suitable original imagery if available; do not generate a customer, product or logo. Reject the program mark, preserve an honest target-logo gap, keep seller identity correct, and distinguish page placement from account binding. Verify composition/identity at actual rendered widths, not only asset previews.

### 3. “The capture has keyframes and canvas, so ship the animation”

A captured hero has CSS keyframes, a canvas tag, one saved video plus a missing alternate video URL, a scroll-triggered hidden state, and a mobile tab control. Static desktop screenshots look correct; a dialog state was opened programmatically and the preview clicked only the second desktop tab. The requester asks for exact original motion today; the standard sandbox runtime is unavailable.

Expected decisions: inventory defined/retained/observed behavior separately; do not claim source JS/WebGL/React recovery; do not replay scripts or remove custody/sandbox gates. Preserve supported CSS/video only with actual dependencies and observed behavior, otherwise walk supported reconstruction → equivalent interaction → compact static fallback. A governed custom component may use supported motion libraries after a real lower-rung gap, but compilation and placement must succeed and it is a new reconstruction. Choose reachable reduced-motion/static states with essential content visible. Require temporal playback and actual click/keyboard/touch/scroll evidence across applicable widths; name desktop-only/forced-state/omitted captures and missing video checks. With no runnable browser/runtime, report motion unverified and the fallback honestly; no fidelity acceptance.

## Inspected capabilities and limits

- `tools/web_substrate.py`: `search_assets(q, kind=None, limit=8, min_width_px=None, min_height_px=None)` returns measured resolution and conservative family metadata; exact ids stay exact. Insufficient results remain visible. Origin controls `asset` registration.
- `view("asset:<id>")`, `view("cloned_section:<id>")`, and `inspect_cloned_section(fragment_id)` provide actual pixels/source; inspected HTML/CSS is capped at 12,000 characters each with truncation flags.
- The web `asset` accepts action/prompt/aspect_ratio/width/height/transparent_background/label/asset_id/alt. It does not expose scene-lane target-node, brand-notes or explicit reference-image arguments. Provider failure can return a placeholder warning.
- `fetch_logo(domain, company_name=None, force_refresh=False)` produces attributed logo-family cells; `bind_account_logo(account_id, asset_id)` is separate from placement and may refuse. No generated/recolored identity fallback exists.
- Capture `motion_inventory` stores keyframe names, videos/posters, missing media, canvas count, `canvas_runtime_recovered=false`, and `source_scripts_replayable=false`. It is snapshot metadata, not a new model tool.
- Fragment sanitizer strips source scripts/handlers and SVG SMIL. CSS scoping preserves/namespaces supported keyframes. Stored video/poster dependencies do not prove decoding, autoplay, controls or fallback behavior; the typed image tool is not a video generation/import tool.
- Typed platform components include dialog, accordion, marquee, nav menu, carousel and tabs. Governed custom components permit React, selected Visx, `motion/react`, `gsap`, `@gsap/react` after the capability ladder, through versioned write/compile/place tools. This permits new authored behavior, not recovered arbitrary source programs.
- `render_web_preview()` captures 1440/768/375 static views. Dialogs are opened with `showModal`; accordions/nav are forced open; second-tab click is desktop-only. Captures are bounded and omissions reported. Same-document render reuse is not a later-time sample.
- `review_cloned_page()` walks desktop/phone, five scroll stops, console/height findings and a reduced-motion screenshot. It is neither continuous recording nor a playback/keyboard/complete interaction test. Unobserved/refused checks are gaps.

## Verification and release status

The two skill entrypoints and conditional references are authored against the source contracts above. Structural checks cover frontmatter, relative references, length and whitespace; these are documentation/discovery checks, not visual quality evidence. No provider call, external fetch, runtime service, environment file, live database or asset library was changed. No source media was added.

Static verification completed: both entrypoints have valid required frontmatter and remain below 500 words; all local Markdown references resolve; all seven owned Markdown files end in a newline with no trailing whitespace; `git diff --check` passed. An AST read of the current web substrate confirmed the documented search, asset, logo, source-inspection, render/review and finalization argument names. An initial filename lookup assumed `tools/asset_renditions.py`; it was corrected to the actual `lumen_agent/asset_renditions.py` before verification. No runtime test was required for these documentation-only files; the parent owns loader/routing tests.

An independent collaborator (`web_source_skills`) read the three fixtures and guidance and returned decisions matching all three oracles. Scenario 1 calculated 1200×1800, rejected 480×720 for the requested size, and allowed at most 240×360 CSS at 2× only when composition permits. Scenario 2 preserved source UI/alpha/baked corners, rejected the generation placeholder and program logo, and left truncated-source fidelity open. Scenario 3 distinguished static/forced state evidence from motion, retained custody and sandbox refusals, and required a disclosed fallback or unmet exact-motion result. The review found a role-specific tool ambiguity; both motion documents now direct author/reviewer roles back to the director/solo for render/walk calls. This is an **unblinded peer decision walkthrough**, not an executed browser test or a fresh controlled agent comparison.

Fresh-agent pressure checks and production visual/motion validation remain separate gates. The recorded actual baseline precedes this authoring, but there is no new controlled no-guidance/with-guidance agent experiment in this report. No scenario response or visual-quality pass is fabricated. Parent task owns routing, integration tests and the later independent review.

Required remaining acceptance: fresh company-URL onboarding/refresh and retrieval without seeded packs; actual generation with standard runtime; matching source/output responsive composition and verified playback/interaction, including reduced motion; the frozen four-brand regressions plus a held-out brand; human assessment of identity, relevance and source fidelity. Docker/runtime absence remains a blocker for production generation. Source capture counts and keyword/loader tests cannot close it.


## Integration peer review and recheck

A separate read-only peer review inspected root's `prompts_web.py`, the AGENT web router, `knowledge/web/skill-families.md`, `knowledge/web/abm-page.md`, `campaign-page-workflow` and the clone-review rubric against the current tool implementation. It also reviewed the personalization/edit/review P1–P3 fixtures. This was source inspection and unblinded collaborator reasoning, not a live browser run, blind evaluation or production quality pass.

Initial integration findings: the assembly guidance overstated shell-only enforcement; TURN TARGET text required a subtree rewrite for small edits; full clone walks remained unconditional; outcome/ship-bar language could confuse named material gaps with acceptance; required missing logos and nonscreenshot evidence gaps were excluded by older review wording; `list_cloned_sections` was not callable; author relationship rules assumed the seller had never met the target; exact-copy anchors could preserve unsupported outcome claims. The implementation confirms `assemble_abm_page` selects released campaign shells but retains existing navigation or a nav supplied as hero with advice. No assembly behavior was changed by this review.

Recheck confirmed these corrections in the current drafts: actual shell selection/navigation advice; `web_ops` before structural rewriting; removal of phantom list calls; explicit source/claim/destination/playback evidence-gap reporting; missing required logos remain unmet; solo outcomes distinguish a usable draft from fulfilled exact fidelity; workflow anchors preserve unsupported requested wording as an unresolved requirement outside visitor copy. The raw HTML/CSS versus recovered React/WebGL distinction remains explicit. The four P1–P3 issues are resolved in their owned skills: current node snapshots are required because `view("doc")` is summary-only, partner/backer meanings are distinct, review/finalize roles are explicit, and unsupported exact outcomes cannot be excused by draft status. Shared copy routes now condition web-specific tools on a web task.

Three residual root-prompt passages were reported for alignment at this recheck: orchestrator lines 465–474 still require a clone walk on any cloned page; lines 476–479 describe warnings only for advisory issues; author lines 774–779 still prohibit every existing-relationship claim on the assumption the seller has not met the target. The equivalent solo/orchestrator passages elsewhere are already corrected. These are instruction consistency findings, not new runtime defects. Final recheck status will be appended after root aligns them.


### Final bounded integration recheck

Root aligned all three residual passages. The orchestrator now limits the full clone walk to create/rebuild or a relevant structural/behavior change, checks affected scope for small edits, and reuses unchanged evidence. Its outcome text now retains a usable draft with warnings for unresolved required fidelity/evidence/conversion. The author now allows only evidenced exact relationship claims rather than assuming the seller has never met the target. A read of the edited passages and a stale-phrase scan found none of the reported phantom-list, shell-only-enforcement, blanket-walk, absent-logo-pass or screenshot-only-evidence wording remaining in the inspected integration files.

**No unresolved finding remains in this bounded peer-review set.** The separate summary-only document-read limitation remains an explicitly documented runtime capability gap, not repaired by these skills. Root owns runtime tests and any mint/placement partial-result qualification. This closure records instruction consistency only; it establishes no paid-model, live onboarding, production rendering, playback, account derivation or visual-quality result. The reviewer changed only this owned validation report.

# Verify playback and real interaction

Read this before claiming motion or interaction fidelity. Keep the evidence tied to the final document revision, source section, viewport, scroll/state, motion preference and elapsed time. Recheck only the affected behaviors after an edit, plus nearby layout/controls that can be affected.

## Use the current tools for what they observe

`render_web_preview` and `review_cloned_page` belong to the director/solo tool set. An author or reviewer without them hands the requested checks back to that role; naming a tool here does not make it callable in every role.

| Tool | Observes | Does not prove |
|---|---|---|
| `render_web_preview()` with `view("preview:1440")`, `view("preview:768")`, `view("preview:375")` | Static responsive output and diagnostics | Animation timing, complete video playback, or real user control wiring |
| Returned `state_captures`, viewed by `view("state:<n>")` | Active-page states; native tabs and eligible captured CSS-radio image groups use actual clicks at 1440/375, selected-panel/visible-image checks and bounded Tab-entry/Left/Right keyboard observations | Original source controllers, source-to-image semantic correctness, full accessibility or normal-motion timing. Dialogs use `showModal`; accordions/nav are still forced open |
| `review_cloned_page()` | Desktop/phone, five scroll positions, console and dead-height checks, reduced-motion snapshot, source comparison where placeable | A recording, all trigger paths, a full loop, frame advancement, keyboard/touch access, or every carousel/tab state |

Read omitted-state ids, failures, abstentions and source-comparison limits. No findings is not evidence for observations that did not occur. `unchanged: true` reuses prior still images; repeating the call on an unchanged document does not sample a later animation frame.

Switcher observations are bounded to the first two groups and four states per group at each width, in reduced-motion mode. `state_captures_omitted` and `state_capture_failures` identify capped, unsupported or failed observations. Form-owned radios are not operated. Arbitrary custom JavaScript, carousels and other control patterns are not automatically discovered. A group absent from the inventory is not proof that the source had no controls: reconcile source requirements with what was tested.

Switcher images are component-region captures, not full-page images. Inspect their selection/media metadata and `keyboard.status` as well as their pixels; keyboard entry may remain unverified even when clicking works. `normal_motion` and `source_mapping` remain unverified. Loaded images and an observed transition do not establish that the image belongs to the right source feature. Finite transitions must settle within the probe bound; long transitions become an explicit observation failure. An unchanged render reuses these observations and failures rather than spending on another identical probe.

## Minimum evidence by behavior

Use an available governed browser/test surface for checks beyond those tools. Do not invent a runtime method. If none is available, record the exact unverified check and chosen fallback; preserve the distinction between a correct static view and verified behavior.

- **CSS animation or transition:** observe before, during and after the trigger at the actual interval. For a loop observe its seam over at least one complete cycle; for a reveal, verify content after entering and leaving its activation range. Compare source/output path, timing, easing, clipping and stacking at matched states when exact fidelity is required. Inspect hover and focus independently; content must also be reachable on touch.
- **Video:** verify the actual media loads and decodes, time/frames advance, and the observed view is not just its poster. Test play/pause/control access where controls are required, mute/inline/autoplay behavior as implemented, an end/loop transition when relevant, and failed/autoplay-blocked loading behavior. Record playback evidence such as advancing media time plus distinct frame observations. A MIME string, downloaded bytes, video element or still frame alone is insufficient.
- **Dialogs and navigation:** activate the real visible trigger, check the resulting state, close via the provided control and Escape, and check focus return/reachability. The preview's forced-open state verifies its appearance only. Do not submit forms or external bookings to test a dialog.
- **Tabs, carousel and accordion:** activate visible controls, verify the selected content changes and inactive content is handled correctly. Exercise keyboard access and touch/mobile layout; check the relevant final/loop boundary. A second desktop tab image does not cover mobile tabs or every panel. Autoplay and manual interaction require separate observations.
- **Scroll/sticky/canvas reconstruction:** scroll through the relevant region at desktop and phone sizes, verify visible content and completion with no blank height or traps. Observe the actual independently authored behavior. Do not label retained canvas tags or source screenshots as recovered canvas playback.

Use all standard preview widths (1440/768/375) for layout. For behavior test each materially different responsive state, including desktop and phone, and any source breakpoint changing its interaction. A source viewport and output viewport must match before comparing geometry; timed effects also require matched trigger/elapsed state.

## Reduced-motion checks

Observe the default mode and `prefers-reduced-motion: reduce` on the final output. Confirm essential content is visible, CTAs reachable, reading order stable, and the intended reduction occurs. Check loops, custom timers and video explicitly; the reduced-motion walk only produces a still/geometry observation. If the implementation responds to a changed preference during the session, verify that transition as well. Reduced motion must not leave a blank hero, partly translated panel, hidden tab content or an endless loading state.

## Report a bounded verdict

For each affected section record **pass**, **defect**, or **unverified**, with the exact supporting captures/observations. State original reuse, newly authored reconstruction, equivalent interaction or static fallback. Report remaining capability/observation gaps through the existing review/finalization fields, including `ladder_gap` when applicable. Keep source content and internal failure explanations out of visitor copy.

Do not promote exact source fidelity based on a compiler success, a static preview, an empty findings list, asset count, or skill-loader test. A completed draft and a verified motion experience are different acceptance results.

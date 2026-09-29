# Rich-card styling custody and authoring guidance — 2026-09-28

Continued on `codex/design-agent-v1` from `060d99c8`. Active page-quality goal
remains incomplete. No-new-native-generation restriction retained; no ingestion,
live DB/page write, service restart, publish, push or standalone replacement.

- Held source plus read-only public-site clicks established four card/image
  mappings. Autoplay timing remains unmeasured; source side columns have
  independently sized rows. No exact visual-parity claim.
- Existing typed labels support rich spans. Offline real author/repair/render
  path showed custom CSS vanished from reusable repair artifacts, leaving plain
  controls despite successful switching. `compile_section_css` now carries a
  bounded portable custom-CSS subset through the existing artifact scoper.
- Global/layered/ID-dependent or indirect-animation CSS refuses reusable mint;
  checked typed section stays. Review caught these dependencies before acceptance.
  No engine changes or runtime flags. Ordinary asset/release gates unchanged.
- Corrected authoring conflicts with finished Words/Evidence/Actions: assembly
  retains resolved copy/actions; important meaning survives copy fitting; source
  measurements outrank fallback type/geometry; no forced header/demo/placeholder.
- Added progressively loaded rich-card-control reference. Synthetic read-only
  application checks cover informational action, missing booking destination,
  source typography and explicit interaction/portability limits. These do not
  qualify native model behavior or visual quality.

Test evidence: new browser regression compares pre-mint and repeated-pin
geometry/type/selected appearance at three widths and four states, plus keyboard,
hidden content and independent instances. Nonportable-CSS cases first failed,
then gained explicit refusals. Initial browser launch required normal sandbox
escalation. One test originally assumed Home-key support (not implemented); it
now exercises the existing ArrowRight behavior. Selected colors require waiting
for the reduced-motion style frame, rather than immediate synchronous equality.

Follow-up: source-specific responsive card geometry, image layering with held
assets and actual font custody, observed motion timing, then native page review
after generation is authorized again. Do not call another model to paper over a
failed mechanical check. Preserve unrelated account-test/import-note changes.

Closing verification: focused native/repair/campaign-shell/skill/CSS/artifact
checks returned 247 passed, one known baseline exact-docstring failure in the
unchanged search tool. New 13-case style/refusal file passes. Fatal-error lint
and whitespace checks pass. Full suites not rerun. Local logs are
`/tmp/clue-card-custody-final.{log,xml}`. Checkpoint contains only this slice;
unrelated account work remains unstaged. No services restarted or page generated.

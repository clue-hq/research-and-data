# Brandfetch account-ad tests

User authorized replacing Logo.dev with Brandfetch and four fresh one-to-one
creatives: Clue→Google, AWS→Insight Health (insighthealth.ai), Google Cloud→NVIDIA,
Conduit→Hyatt. Preserve older approved artifacts. Brand Asset Intelligence stays
in its separate worktree; no new ingestion agent in this task.

- Removed the active Logo.dev adapter, settings and example-env entries. Removed
  local ignored credential entries without printing them. Historical provenance
  labels remain readable; cache entries containing retired-provider assets now miss.
- Two regressions observed failing before change: retired provider still contacted,
  old provider cache still accepted. After change, 141 focused logo/runtime tests
  pass; read-only reviewer reported no actionable issues. No engine changes.
- Live Brandfetch probe returned verified original logo families for all four
  targets. Hyatt has only a light-surface lockup from this provider. Other targets
  returned light/dark lockups and a mark. No generated/synthetic logos.
- Reloaded idle design API/four fleet workers; frontends, DB and storage unchanged.
- Ordinary requests sent through authenticated localhost3021–3024 Home UI, then
  standard design handoff. No supplied asset IDs, headlines or layouts. Home took
  multiple minutes and showed failed interview-evidence writes before opening
  design. Existing stale designing overlay required reload before handoff sends.
- Read-only observers record exact workspace/project/thread/run bindings and
  immutable first outputs under ignored evaluation/skill-family-v1/
  abm-brandfetch-20260916. All four first deliveries frozen: three runtime accepted,
  Google Cloud unaccepted. Independent review does not qualify the first pass:
  oversized/disconnected logos, small support, wrong Hyatt subbrand and AWS avatar
  remain. Google Cloud also required an accurately scoped product argument.
- First runs chose existing logos/native composition rather than new raster image
  generation. Correct logo retrieval is not proof of finished creative quality.
- Tightened account identity skill for whole-logo duplication, optical pairing,
  corporate/product/loyalty identity and unsuitable advertiser avatars. Account
  adaptation now binds capabilities to the exact named product. Independent
  read-only review found no actionable issue; 307 focused logo/skill tests passed.
- Founder clarified that "big" means a balanced advertiser × target pair, not a
  giant target logo. Four assisted revision turns now run through the app; original
  first deliveries remain in immutable evidence. Revisions are not autonomous
  first-pass successes. Existing approved historical docs remain untouched.
- Founder explicitly authorized committing and pushing all repository progress
  on this feature branch. Prior uncommitted September 8 experiment notes are now
  included; ignored credentials, local storage/DBs and evaluation artifacts remain
  local. Remote branch did not yet exist when checked. Push verification pending.
- Probe initially failed DNS inside sandbox; authorized network retry succeeded.
  System `python` absent; use repository `.venv/bin/python` for runtime tooling.

# Local ad-harvest smoke test

- User authorized activating and testing the existing ad-harvest lane; selected localhost. No production configuration, source code, prompt, or model change.
- Local services were down. Started the existing `.local-setup/run-stack.sh`; frontend 3020, design API 8010, platform APIs 8020/8030, and four Fleet processes verified up. Attached exec session 65512 holds the stack.
- `LUMEN_BRAND_AD_ASSETS=1` was already configured. Confirmed approved kit and empty ad lane before submitting one normal bounded onboarding job: three pages, fifteen creative cap. No duplicate offer.
- Job `ingest_d3b168f6dd134b9583f677bd63385755`: twelve harvested images and one immutable DNA card with six groups persisted. All twelve scoped byte endpoints returned 200 and decoded successfully; digests and dimensions recorded in ignored `.local-setup/ad-control/harvest-test/`.
- Actual runtime style selector chose two relevant references; both passed the existing reference-manifest materialization path with matching source digests. This was a selector/materialization check, not a new creative-generation turn.
- Browser verified an actual harvested asset in Brand Context. Harvest and style analysis completed in about 72 seconds. Full onboarding remains running in the artwork pregeneration stage at the last snapshot (2026-09-09 05:01 UTC), with no linked pregenerated outputs yet. Do not re-offer or claim full pipeline completion without checking this same job.
- Initial read-only SQL inspection used wrong column names (`evidence`, `error`); corrected to `evidence_json`, `error_json`. No DB modification through SQL.
- Preserved the pre-existing modified/untracked notes. No source changes, commit, push, or deployment.

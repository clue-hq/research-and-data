# 2026-06-24 — M10.2 use-class tagging: lexicon-as-config + tag-distribution metric

Branch `m10/compliance` (continues [[2026-06-24-m10-plan-and-m101-jurisdiction]]). M8.4 already owns
the use-class *tagger*; M10.2 adds the two real gaps: the Art. 9 lexicon as **versioned config** and
the **tag-distribution observability** — plus the small A2 wiring edit so M8's tagger reads the config.

## Decision: A2 (user-approved) — wire it now, not deferred
Option A2 over A1: M8 is already merged to trunk and no sibling (M11/M12) touches
`profiling/contact/use_class.py`, so the m10 branch makes the small cross-package edit now → M10.2 is
fully wired + tested end-to-end, no dormant config, no "remember to wire later" debt. The isolation
cost (m10 touching M8's merged package) is negligible (low collision). NOT done: a 2nd `core` delta
(the Protocol-seam variant) — see backlog.

## What shipped
- `config/policy.py` (+): `UseClassLexicon{sensitive_markers, benign_cause_markers, version}` +
  `DEFAULT_USE_CLASS_LEXICON`; the 49 sensitive + 18 benign markers MOVED here verbatim from M8's
  tagger (diff-verified byte-identical → behaviour unchanged) THEN extended (audit) with the 4 missing
  Doc D §2 categories: trade-union, biometric/genetic, family/children, financial. Validators:
  normalize markers to lower+strip; reject a blank marker (a blank substring-matches everything — the
  benign side would de-escalate all); reject empty `sensitive_markers` (would silently disable Art. 9).
  Also added `JurisdictionPolicy.use_class_lexicon` (per-client overlayable, like `regime_mapping`).
- `profiling/contact/use_class.py` (M8-owned, A2 edit): `UseClassTagger(lexicon=DEFAULT_USE_CLASS_LEXICON)`
  reads `self._lexicon.{sensitive,benign_cause}_markers`; hardcoded tuples removed; default behaviour
  unchanged. `DEFAULT_USE_CLASS_TAGGER` still works (all M8 tagger tests stay green).
- `obs/metrics.py` (+): `record_use_class_distribution(claims)` + `METRIC_USE_CLASS_TOTAL` — at-rest
  per-use-class counts over the claim store (mirrors `record_verification_health`; the appropriateness
  axis, separate from accuracy — Doc D §5). NOT a trace span; reworded the M10.2 AC "span"→"metric".
- `tests/compliance/test_use_class.py`: config-driven AC (add a marker → reclassify, zero code; via
  value_json AND span), marker REMOVAL → de-escalate, case-normalization, blank/empty-sensitive
  rejection, a parametrized test asserting every Doc D §2 category escalates `stated_interests`, the
  obs recorder, and the JurisdictionPolicy-carries-lexicon parity test.

## Adversarial audit (4-lens workflow + per-finding verify) — 10 confirmed of 13; all fixed
- **[MED] lexicon omitted 4 Doc D §2 categories** (trade-union/biometric-genetic/family-children/
  financial); for `stated_interests` (escalatable, *usable* hint) a miss fails **OPEN** (stays usable),
  not safe. Fixed: added selective markers (substring-safe; M8 tests still pass) + parametrized
  category test + corrected the "fails safe" comment (only fail-safe for restrictive-hint `causes`).
- **[MED] empty `sensitive_markers` silently disables Art. 9** → model_validator rejects it.
- **[MED] markers not case-normalized** (matching is lowercased-substring; an upper-case custom marker
  never fired) → field_validator lowercases+strips.
- **[MED] blank `benign_cause_markers` entry de-escalated everything** (`"" in text` always True) →
  field_validator rejects blank markers in both tuples.
- **[LOW] lexicon not overlayable / docstring overclaim** → promoted to `JurisdictionPolicy.use_class_lexicon`
  (parity with regime_mapping) so the "per-client lexicon at api root" claim is now true.
- **[LOW] AC said "span"** → reworded to "metric".
- **[LOW] tests didn't cover marker-removal / value_json-only / case** → added.
- Dismissed (3): version-not-enforced-to-bump (cosmetic), span-vs-metric dupes.

## Verification
ruff + format clean; import-linter 11/11 KEPT (`profiling → config` is an allowed shared-base import);
mypy `Success: no issues found in 210 source files`; 42 affected tests pass (M8 tagger behaviour tests
unchanged + new M10.2 tests). All pure (no DB).

## Backlog (M10.2-related — track + address before the named downstream work)
1. **[M10.2×M9.6] use-class recall + adversarial eval fixtures.** The tagger is substring-marker-based;
   recall is best-effort and the fail-OPEN path for escalatable usable-hint fields persists for
   evasive/obfuscated phrasing the markers miss. Add per-Doc-D-§2-category recall fixtures +
   adversarial negatives (evasive sensitive phrasing; unicode/punct normalization) to M9.6's golden
   set when M9.6 lands (analog of the M9.4×M9.6 backlog item).
2. **[M10.2×M8.2] Art. 9 lexicon duplicated with the resonance firewall.** `profiling/resonance.py`
   has its own `_SPECIAL_CATEGORY_TERMS` frozenset (M8.2-owned; it *excludes* resonance, vs the tagger
   *escalates*). At integration point it at the shared `config` lexicon so the Art. 9 set has ONE
   config-editable source. (M8.2-owned, out of M10.2 scope — DRY backlog.)
3. **[M10.2 integration] Wire the per-client lexicon at the api root.** The lexicon now lives on
   `JurisdictionPolicy.use_class_lexicon` (overlayable), but every M8 call site
   (`profiling/contact/{worker,fill}.py`, `api/deep/orchestrator.py`) still binds `DEFAULT_USE_CLASS_TAGGER`.
   At integration construct `UseClassTagger(lexicon=get_policy(client_id).use_class_lexicon)` so a
   per-client/posture lexicon actually flows. (The platform-default tagger is wired now.)
4. **[M10.2 future] DB-backed/versioned lexicon** — if per-client lexicons need DB persistence/
   versioning, add a compliance-owned `load_use_class_lexicon(conn, client_id)` (M9.3 `load_judge_policy`
   pattern). For now in-config + overlay. (Optional; M10.4 posture work may want it.)
5. **[M10.2×core, deferred] provider-swappable tagger Protocol.** M8's `use_class_tagger` param is the
   concrete `profiling.UseClassTagger`, not a `core` Protocol; a fine-tuned-model tagger behind the
   seam (the spec's "classifier model hot-swappable") would want a `core.compliance.UseClassTagger`
   Protocol — a future core contract-delta (not done; avoids a 2nd core delta after PF-1).

## Next: M10.3 (the use gate — impl of frozen core.compliance.UseGate) per the plan; first M10 migration
(`use_decision` + `use_reason` enum side table; `client_policy`/`policy_version` via the M9.3 pattern).

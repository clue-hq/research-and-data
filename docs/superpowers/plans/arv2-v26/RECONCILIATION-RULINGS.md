# Reconciliation rulings (orchestrator, 2026-10-07) — binding for the reconciliation round

Reviews A (`review-A-consistency-and-executability.md`) and B (`review-B-determinism-numbers-depth.md`)
found the set sound on evidence and mechanics but divergent between 03 and 04, with four uncapped
spend paths. These rulings settle every contradiction so each document can be corrected once.

## Authority order
R1. 01/01b are the evidence authority (numbers, fixtures, caps, rule table, quote-fidelity data).
    02/03a are the code authority (every path:line; fix the stale/wrong citations review A §2 lists).
    03 is the design authority. 04 follows 03 line by line. 05 follows 03 and 04.
    Exceptions where 04's decision wins and 03 must adopt it: R2, R11, R12, R13.

## Settled contradictions
R2. Two recipe integers: r26 = the week-1 mint (tool-shape and prompt changes force it), r27 = the W3
    pipeline, selected per workspace by the P5 selector setting. 03 §9 adopts this; RC-1 on r26 stays
    (it is what makes W1's gains and its replay measurable). Review B's "one mint" is declined: W1 must
    ship and be measured before W3.
R3. Judge tool surface = 03's `submit_brief@1` with the nine server-side derivations (review derived
    server-side; never `insufficient_context`), one batched emission round, `Finding.claim_type` widened
    (synthesis, not_found). 04 W3-24 adopts it and drops the save/validate/finish sequence for r27.
R4. The new agent role is named `person_research` (matches `quality-person-research`,
    `person_research_brief.py`); user-facing text says "contact". 04 W3-26's migration widens the five
    CHECKs review A names (`agent_turn_role`, `agent_plan_role`, `agent_delegation_roles`,
    `agent_model_call_role`, `quality_execution_role` root predicate).
R5. Pools and waits = 03's two-stage design: the contact judge waits on the account's FIRST pool marker;
    the account judge waits on the children's pool markers and receives the people candidate slice.
    AT-8 is a real assertion on that slice, not a key check. 04 W3-21/W3-22 adopt the two markers.
R6. Clearing = 03 §5.3 (keep 4; acquire receipts are cleared like any tool result; the candidates file
    is never cleared). 04 W1-1 and 05 align their values and exclude lists.
R7. Settings = 03 §10's sheet (`CLUE_ARV2_V26_*` names and defaults) is the single sheet. 04 §9 is
    regenerated from it; P5's selector is added to 03 §10; every setting has one name everywhere.
R8. Quote rule = 01b §5's rule: NFKC, straight quotes, dashes, whitespace collapse, case-fold,
    escape-sequence and boundary-punctuation folding, exact digit/date matching, one marked elision,
    OR a typed value with source offset; implemented as an extension of `substring_verdict`
    (`arv2/text.py:44`). 04's "keeps punctuation" wording is removed.
R9. Follow-up floor = 01b T6's 11 floor pairs, verbatim, as `fixtures/rule_table.json`. 03 §3.4 adds the
    `entity` trigger kind with candidate-field variables (person name, vendor, exact phrase, URL,
    subject-site page, event, prior employer) and the extractor emits `entities[]` per candidate so
    every floor pair is expressible; the ledger records `follows` (operation id of the trigger) so AT-9
    chain recall is computable. 04 W3-22 uses the open vocabulary and the 01b fixtures.
R10. Templates and caps: 03 §3.3 adds the four fetch templates review B names (subject homepage/site
    pages incl. careers/benefits/news crawl; LinkedIn profile of each committee member; their own
    posts; per-post fetch for contacts). Caps are set now to 01b §6: account Trigger 10, Initiative 5,
    Pain 5, Motion 5, Stack 8, Committee 10, Watch-outs 4, Not-found 3; contact own-words 8,
    problem-now 5, proud-of 3, hooks 4, remit 2, career-arc 1, do-not-mention 1 (cap ≈ 24).
R11. Deferred contact page = 04 §0.5's research-kind continuation (03a §8f's display-kind task is
    declined for the reason 04 states). 03 §6 and 05 align.
R12. Extractor = leaf call via the `structure_material` precedent (03a §8b, 04 §0.6); no `AgentRole`
    for it. Model/effort via `RESEARCH_EXTRACT_AGENT_MODEL` / `_EFFORT` with `.env.example` lines.
R13. `acquire_research_evidence@2` is minted once in W1 with the r27 shape already present
    (`candidates: list[Candidate]` empty until W3-23, plus `ledger`); 03 §3 aligns.
R14. P6 (new, A-owned, blocking before any r27 pilot): fix the `profile_ref` v2/v3 filter in
    `stop_contact_jobs` / `claim_writer` so a contact privacy-stop reaches v4 (and v26/v27) person
    jobs. 04 §2 adds P6; 03 Appendix B lists it; 05 §6 makes it a go/no-go line.
R15. Person compliance floor: provisional ruling = restored at import for r27 (03's position); 04
    aligns; flagged as founder decision D11 in 00 (the floor is gated off for every recipe ≥ 6 today).
R16. Cost caps: 03 §5.5 states BOTH the modeled ceiling (~$9) and the structural ceiling from settings
    alone, and closes review B's four uncapped paths with named settings that 04 adds and 05 gates:
    (a) r27 judges may not `read_file` raw operation/evidence views — reads are limited to the
        candidates files and `search_evidence`; any raw-view read is refused with a receipt (setting
        `CLUE_ARV2_V26_JUDGE_RAW_READS=false`);
    (b) the fallback-model chain is disabled for research roles (`CLUE_ARV2_V26_FALLBACK_MODELS=`
        empty) — a primary failure suspends the stage for retry, never silently reprices the run;
    (c) extraction output is capped per call (`CLUE_ARV2_V26_EXTRACT_MAX_OUTPUT_TOKENS`, default 2000)
        with chunking of large sources;
    (d) page re-offers have an attempt ceiling (`CLUE_ARV2_V26_PAGE_MAX_ATTEMPTS`, default 2).
    With these, 03 recomputes the structural ceiling; the expected case ($2.72 Luna / $3.48 Flash) is
    verified by review B and stands.
R17. Review A §4's 70 implementer questions: 04 resolves all 13 blocking ones in text and as many
     others as possible; any that remain are listed in a new 04 §12 "Questions that remain for Aryan"
     with the author's recommended answer — the target is an empty section.
R18. Review A §5's 19 missing pieces: each is placed in exactly one document (04 for work items, 03 for
     design, 05 for gate/checklist, 01 for queries) and cross-referenced; none is dropped.
R19. Citations: review A §2's 12 stale and 4 wrong items are corrected in the document that carries
     them (02 by its author, 03a by its author, 03/04 by theirs), with the verified lines.
R20. Nothing is committed by any author. Each author edits only their own document.

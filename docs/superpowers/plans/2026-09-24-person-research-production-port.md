# Port the discovery-first person investigation into the platform

Status: implemented locally; offline integration verified. Paid platform research acceptance
remains pending. This port was explicitly requested in the side conversation on 24 September.

## Result and scope

New governed ARV2 quality launches (`catalog_version=v4`) use resource revision 11. Their person
jobs select `quality-person-research@v11-person`, with a dedicated system prompt, person-dossier
skill and separate complete person-depth-charter skill. Account research stays on profile v10;
claim and narrative specialists stay on v6. Existing pinned runs remain on their original revision.

The repository/local default remains `CLUE_ARV2_RESEARCH_CATALOG_VERSION=v2`. This change installs
the behavior in the actual governed Deep Agent path; it does **not** switch all platform launches
to v4, launch paid research, restart workers or deploy code. A new v4 launch selects revision 11;
resuming an older pinned run does not upgrade its instructions. Do not overwrite historical pins.

## The person agent's process

1. Read the account-authored person brief, selected identity and both detailed skills. Consult
   pinned seller/product/ICP/persona documents and original account research as useful. Existing
   durable brief/reference delivery is reused; the Head of ABM does not author a second person brief.
2. Select complementary ordinary Exa searches from the actual person and charter. Use a modest
   initial batch, inspect results, and adapt; there is no fixed eleven-call script or quota.
   Investigate earlier roles, media, writing, education, personal projects and self-shared interests
   alongside professional context. Write a source-linked working note before the initial deep call.
3. Author the initial Exa assignment with the full charter's explicit subquestions and acquired
   leads. The charter body is preserved from the reviewed draft. Code does not compile a seller
   appendix or supply benchmark answers. The fixed Exa system is unchanged from the tested draft.
4. Read both dossier and source fields, then carry out useful, specific follow-ups. A familiar URL
   can have fresh highlights or links; a profile byline is not an old post's historical employment.
   Follow a substantive unresolved investigation with another deep call only when useful.
5. Follow relevant media candidates to recordings and available transcripts. Use open_transcript
   and search_transcripts on the existing durable transcript/index path. Preserve speaker/date
   uncertainty and distinguish unattempted candidates, inaccessible routes and failed transcriptions.
6. Pass expanded findings and original evidence references to existing claim/narrative specialists,
   preserving source-only discoveries. Keep the existing durable report/finalization contract.

No employment/location proof, extra corroboration, completeness or presentation gate was added.
Existing tenant, erasure, source-access and uncertain-paid-dispatch rules remain intact.

## Exact instruction resources

- `platform/agents/catalog/research-quality/prompts/quality-person-research/v1/SYSTEM.md`
- `platform/agents/catalog/research-quality/skills/person-dossier/v1/SKILL.md`
- `platform/agents/catalog/research-quality/skills/person-depth-charter/v1/SKILL.md`
- `platform/agents/catalog/research-quality/provider-requests/person-deep/v1/exa-system.md`
- `platform/agents/catalog/research-quality/provider-requests/person-deep/v1/request-config.json`

All are pinned in `launch-v4-r11.json`; profile/skill/prompt bytes from earlier versions and all
trial snapshots remain unchanged. The native materializer installs both complete skills in the
person workspace. Original PoC discoveries and trial subject-specific answers are not inputs.

## Provider and evidence behavior

The new person research_deep capability accepts the agent's charter, additional_queries,
highlights_query, known same-name exclusions and num_results (default 20, up to 40, matching the
discovery trial). The request uses text output, text up to 10,000 characters per result, highlights
up to 2,000 characters, ten page links and three image links. These are retrieval limits, not
claims of complete page or image consumption. Ordinary person searches also request 10,000
characters and links; targeted page reads preserve the caller's max_chars and the returned fields.

New person search/page/deep requests use the existing operation journal with their complete wire
request identity, ProviderCaller and ToolRuntime drain. The same request reuses its committed
result; uncertain dispatch does not repurchase. Provider request/response, cost, model-call and
tracing owners are unchanged.

Every newly indexed Exa result additionally has a whole-result evidence descriptor. Existing raw
responses, report and individual text/highlight descriptors remain intact. This preserves links
and structured fields without confusing highlights with complete pages. The normalizer is shared
with account research, so newly acquired account responses also retain these whole-result records;
the account prompt/request selection is unchanged. No historical evidence backfill is performed.

Person acquisition results point to source_navigation and a source_review_path. The latter serves
ten result overviews per page from the existing authorized DB/object-store views, with exact
highlight segments, available/added/changed fields and full-result evidence paths. Capture history
describes prior observations, not prior agent reading. Complete text and every other field remain
readable through the original source path, including continuation pages.

The shared media tool now exposes candidate origin/type/URL and the next action. Genuine ambiguity
remains a choice for the agent. The prior recording-extraction fixes are already in the shared
resolver. This port does not claim to repair the separate YouTube public-access failure observed
in the live probe or to guarantee transcription availability.

## Verification and acceptance

Offline checks cover request fidelity and version isolation; historical launch-pin loading;
ordinary search → deep research → fresh-field review → targeted page read; complete evidence
pagination; durable ledger entries; repeat-request reuse; new-worker views; erasure/revocation;
media ambiguity → selected recording → transcript → reuse; account-to-person nomination; and
governed person skill materialization, model-call journaling and finalization replay.

Database checks ran only against the isolated `clue_person_port_20260924` database, with scripted
provider/model responses and rollback-based fixtures. They establish integration behavior, not
autonomous research quality. Across the completed focused batches, 90 distinct tests passed;
the S3 storage variant was skipped because `CLUE_TEST_MINIO_ENDPOINT` is unset. Scoped Ruff
lint/format and mypy passed; all 28 dependency contracts were kept. No paid provider calls or
application database writes were performed. Existing unrelated working-tree edits were preserved.

Next live acceptance: run a fresh v4 person job with an ordinary account delegation, inspect the
actual model inputs, preliminary searches, generated Exa request, fresh-source reads, media choices,
report, duration and ledger/tracing references. Compare against retained trial/PoC outputs kept
outside the agent's inputs. Claim classification and prose quality remain separate review work.

# ARV2 v26 — evidence from every production research run (2026-10-03 → 2026-10-07)

**Status:** evidence record, written 2026-10-07 by Lane L1 of the v26 program. Read-only: no code,
database or deploy was touched. **Scope:** every production account-research run to date — **42
agent research runs** (7 accounts, 35 people) in the 44 Langfuse traces named `account-research.turn`
in project `clue-prod` (14 traces on 2026-10-03, 18 on 10-04, 12 on 10-06), plus the 30
`head-of-abm.turn` chat turns of 10-03..10-07 (four launched research), the 13 unnamed traces that are
account-page rewrites, the one v24 account-reconciliation agent run and its two failed retries, and 5
further unnamed production traces in the window (discovery runs and sub-minute page writes — pulled,
found not to be research, excluded). The earlier audit (`docs/superpowers/specs/2026-10-06-account-research-cost-and-speed-audit.md`)
and the plan's §0 (`docs/superpowers/plans/2026-10-06-account-research-v26-cost-and-speed-plan.md`)
analysed only the 12 runs of 10-06; §6 below confirms, refutes or extends each of the 26 issues
against the whole corpus. **No recommendations here — numbers only.**

**Sources and method.** Langfuse public API: v2 observations (metadata, usage, cost, timing) for
every observation of every trace; tool inputs/outputs from the v1 observations endpoint (11 traces,
rate-limited) and the v2 endpoint with `fields=core,basic,io` (33 traces); the final two model calls
of each run (output only). Same per-call method as `.artifacts/account-research-cost-20261006/build_report.py`
(agent-level tools = TOOL/RETRIEVER observations under a `tools` chain; evidence calls split into
before-provider / provider / after-provider from the provider spans inside). Fitted Grok 4.6 prices
$2.00 / $0.50 / $6.00 per M new / cached / output tokens explain $150.67 of the $157.91 Langfuse
reports. Local corpus (gitignored): `.artifacts/arv2-research-runs-20261007/` — `raw/`, `runs.csv`,
`accounts.csv`, `model-calls.csv`, `tool-calls.csv`, `evidence-calls.csv`, `errors.csv`, `media.csv`,
`sequences/` (for Lane L2), `tables.md`, `build_corpus.py`, `render_doc.py`, `analyze_io.py`.
Langfuse holds **model** spend only; Exa / AI Ark / Deepgram spend and job rows are in the production
database, which was not read (§7 lists the queries). The research is about real people: the
document names people only as name + title + employer, never their findings.

**Reading the trace ids.** 12-character prefixes are used throughout; the full ids are in `runs.csv`.
The 10-03 account jobs share one trace with the chat turn that launched them (`df90b7ebcd28`, the
pre-#90 fleet inherited the launching turn's trace); every later job has its own trace.

---

## 1. Corpus

### 1.1 What ran, where, on which code

Seven account researches with five nominated people each, in three workspaces and three projects,
on three days. Profile versions come from the trace metadata (`profile`); the release is the last
`research-streaming → main` merge before the launch (merge times from `gh pr list`); whether the VM
picked the release up at merge time is **not** visible in Langfuse (self-updating deploys only shipped
in #104 on 10-05), so the day-to-day behavioural differences in §1.3 are the real evidence of what ran.

| Release (PR → main) | Merged (UTC) | Carries | Runs after it |
|---|---|---|---|
| #89 | 2026-10-03 11:06 | post-launch fixes | all 10-03 runs (v24) |
| #94 | 2026-10-04 06:58 | research slowness fixes #91 (no R2 under locks, shared storage client, workers claim only what they can run), agent-scoped tracing #90 | — |
| #97 | 2026-10-04 12:12 | separate page writer / recipe 25 (#98), model fallback (#96) | all 10-04 runs (v25) |
| #101 | 2026-10-05 14:50 | auth fixes | — |
| #105 | 2026-10-06 12:22 | stranded-job lease fix + 128-thread pool (#102), lease-spin fix (#103), self-updating deploys (#104) | all 10-06 runs (v25) |


**T1.1 — Runs by day, workspace, project, account**

| Day | Workspace | Project | Launch (chat trace) | Account runs | Person runs | Profiles | Release on main at launch | Model $ (runs) | Page-writer $ (in-run) |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-03 | W1 (Garner Health project) | prj_92c55a86… | df90b7ebcd28 | 2: mckeefoods.com, mortenson.com | 10 | quality-account-research@v24, quality-person-research@v24-person | #89 — post-launch fixes | $56.88 | $0.00 |
| 2026-10-04 | W1 (Garner Health project) | prj_92c55a86… | 87e5059dbc61 | 1: nyc.gov | 5 | quality-account-research@v25, quality-person-research@v25-person | #97 — separate page writer / recipe 25 (#98), model fallback (#96) | $15.37 | $0.86 |
| 2026-10-04 | W2 | prj_b70a7326… | ca36c9e0055c | 2: firstfleetinc.com, jrayl.com | 10 | quality-account-research@v25, quality-person-research@v25-person | #97 — separate page writer / recipe 25 (#98), model fallback (#96) | $37.78 | $1.66 |
| 2026-10-06 | W3 (Dialpad/Loopio) | prj_932fc67b… | 6ba16f877674 | 2: loopio.com, dialpad.com | 10 | quality-account-research@v25, quality-person-research@v25-person | #105 — stranded-job/lease fix + thread pool (#102), lease spin (#103), self-updating deploys (#104) | $47.88 | $1.52 |


Profiles: `quality-account-research@v24` / `@v25` and `quality-person-research@v24-person` /
`@v25-person` (`platform/agents/catalog/research-quality/profiles/…/profile.yaml`). The v24→v25 change
removes the two narrative skills (`account-research-narrative@v2`, `research-narrative-editorial@v1`;
`person-research-narrative@v2` for people) and the researcher-owned page tools, and adds the driver's
page writer (`quality_policy.SEPARATE_WRITER_RECIPE = 25`); research skills are identical across
both (`governed-evidence@v4`, `account-dossier@v9`, `person-research-briefing@v4`,
`claim-ready-account-dossier@v3`; `person-dossier@v5`, `person-depth-charter@v1`,
`claim-ready-person-dossier@v3`). Model on every run: `x-ai/grok-4.6` (Langfuse `model` on every
`GovernedAgentChatModel` generation).

Workspaces: W1 = `ws_0503532073454a10ab541c3fa9bf3e81` (the Garner Health project, 10-03 and the
10-04 13:59 launch), W2 = `ws_7d95626cc678423591fd0b3e1ccdbf82` (10-04 23:24 launch), W3 =
`ws_e9773f8a52864252bba6dbfba55c93c5` (10-06). Environment tag: 13 of the 14 10-03 traces are
`default` (one person trace, `a67742ca0e5c`, is already `production`); every later trace is `production`.

### 1.2 Every run


**T1.2 — Every research run**

| # | Day | Kind | Subject | Trace | Profile | Start (UTC) | Agent min | To last page min | Rounds | Tool calls | Evidence calls | Ext. provider calls | Model $ | PW $ | Start/avg/final ctx (k) | Outcome | Error classes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 10-03 | account | mckeefoods.com (account) | `df90b7ebcd28` (root `8486376a`) | account-research@v24 | 15:25:15 | 66.9 | 67.3 | 74 | 216 | 31 | 30 | 7.82 | 0.00 | 19/149/234 | finalize_refused_only | trap_search_evidence_unavailable×5, other×2, trap_grep_refused×1, listing_refused×1, schema_validation×1, finalize_refused_unresolved_failures×1, finalize_workspace_conflict×1 |
| 2 | 10-03 | account | mortenson.com (account) | `df90b7ebcd28` (root `3fe4a508`) | account-research@v24 | 15:25:16 | 52.1 | 67.3 | 65 | 180 | 37 | 29 | 6.61 | 0.00 | 19/138/228 | finalized:completed | trap_grep_refused×4, listing_refused×1, schema_validation×1, finalize_refused_other×1 |
| 3 | 10-03 | person | Robin Ritter, Chief Human Resources Officer — mortenson.com | `15f068c763d7` | person-research@v24-person | 16:06:03 | 94.4 | 94.8 | 56 | 147 | 18 | 17 | 5.17 | 0.00 | 17/139/211 | finalized:completed | schema_validation×3, trap_grep_refused×2, listing_refused×1 |
| 4 | 10-03 | person | Patrick Locken, Chief Financial Officer, Mortenson Construction — mortenson.com | `05261c2da207` | person-research@v24-person | 16:06:22 | 79.7 | 79.9 | 42 | 105 | 17 | 16 | 2.91 | 0.00 | 17/115/168 | finalized:completed | trap_grep_refused×1, listing_refused×1, schema_validation×1 |
| 5 | 10-03 | person | John Bachhuber, Vice President Total Rewards — mortenson.com | `b10a7a1e3164` | person-research@v24-person | 16:06:23 | 88.1 | 88.3 | 44 | 113 | 13 | 12 | 3.74 | 0.00 | 18/128/191 | finalized:completed | schema_validation×3, trap_grep_refused×1 |
| 6 | 10-03 | person | Jean McGrory, Director, Total Rewards — mortenson.com | `ca75ce49f9dd` | person-research@v24-person | 16:06:29 | 100.5 | 100.7 | 46 | 117 | 13 | 11 | 3.52 | 0.00 | 17/131/189 | finalize_refused_only | schema_validation×3, other×2, trap_grep_refused×2, trap_search_evidence_unavailable×1, listing_refused×1, finalize_refused_unresolved_failures×1, finalize_workspace_conflict×1 |
| 7 | 10-03 | person | Athena Burkholder, Senior Manager — mortenson.com | `904431b689f5` | person-research@v24-person | 16:06:38 | 86.7 | 86.8 | 39 | 125 | 13 | 12 | 3.35 | 0.00 | 17/122/182 | finalize_refused_only | trap_grep_refused×4, other×2, trap_search_evidence_unavailable×2, schema_validation×2, listing_refused×1, provider_error×1, read_refused×1, finalize_refused_unresolved_failures×1, finalize_workspace_conflict×1 |
| 8 | 10-03 | person | Chris McKee, President and COO — mckeefoods.com | `51bc90389573` | person-research@v24-person | 16:16:32 | 98.3 | 98.9 | 68 | 153 | 14 | 13 | 7.79 | 0.00 | 17/145/211 | finalize_refused_only | schema_validation×5, trap_grep_refused×3, other×2, trap_search_evidence_unavailable×2, read_refused×2, finalize_refused_unresolved_failures×1, finalize_workspace_conflict×1 |
| 9 | 10-03 | person | Kyler Vann, Comp and Benefits Analyst — mckeefoods.com | `a67742ca0e5c` | person-research@v24-person | 16:16:40 | 96.0 | 96.2 | 53 | 130 | 16 | 15 | 4.54 | 0.00 | 17/119/182 | finalize_refused_only | trap_grep_refused×3, trap_search_evidence_unavailable×3, other×2, schema_validation×2, listing_refused×1, finalize_refused_unresolved_failures×1, finalize_workspace_conflict×1 |
| 10 | 10-03 | person | Andy Lang, Chief Financial Officer — mckeefoods.com | `8ec2e77256ab` | person-research@v24-person | 16:16:51 | 88.1 | 88.4 | 47 | 147 | 28 | 17 | 5.70 | 0.00 | 18/138/217 | finalize_refused_only | other×2, trap_grep_refused×2, listing_refused×2, trap_search_evidence_unavailable×1, schema_validation×1, finalize_refused_unresolved_failures×1, finalize_workspace_conflict×1 |
| 11 | 10-03 | person | Don Gladden, Vice President — mckeefoods.com | `2d2de64f34fd` | person-research@v24-person | 17:42:21 | 34.8 | 35.0 | 37 | 111 | 12 | 10 | 2.90 | 0.00 | 18/123/188 | finalized:completed | trap_grep_refused×3, listing_refused×1, schema_validation×1 |
| 12 | 10-03 | person | Cindy Lyons, Corporate Health & Wellness Manager — mckeefoods.com | `db37e5110b8d` | person-research@v24-person | 17:46:41 | 34.2 | 34.4 | 45 | 128 | 15 | 14 | 2.82 | 0.00 | 17/101/161 | finalized:completed | trap_grep_refused×5, listing_refused×3, provider_error×1, schema_validation×1 |
| 13 | 10-04 | account | nyc.gov (account) | `689968fdba94` | account-research@v25 | 13:59:10 | 16.3 | 21.4 | 45 | 132 | 17 | 17 | 3.07 | 0.23 | 18/113/177 | finalized:completed | listing_refused×2, trap_grep_refused×2, schema_validation×2 |
| 14 | 10-04 | person | Renee Campion, Commissioner — nyc.gov | `26ce34b57bb9` | person-research@v25-person | 14:14:36 | 12.7 | 16.2 | 42 | 126 | 14 | 13 | 2.98 | 0.13 | 16/119/180 | finalized:completed | trap_grep_refused×4, schema_validation×2, listing_refused×1 |
| 15 | 10-04 | person | Beth Kushner — nyc.gov | `86c8897e55be` | person-research@v25-person | 14:14:37 | 12.3 | 14.8 | 40 | 111 | 17 | 14 | 2.33 | 0.11 | 15/97/149 | finalized:completed | trap_grep_refused×2, listing_refused×1, schema_validation×1 |
| 16 | 10-04 | person | Sang Hong, Director — nyc.gov | `4fc80314d4ea` | person-research@v25-person | 14:14:38 | 11.4 | 15.7 | 32 | 100 | 17 | 16 | 2.05 | 0.14 | 15/102/149 | finalized:completed | trap_grep_refused×2, schema_validation×1 |
| 17 | 10-04 | person | Claire Levitt, Deputy Commissioner, Health Strategy — nyc.gov | `36fab9ffa29a` | person-research@v25-person | 14:14:39 | 14.6 | 17.9 | 40 | 107 | 11 | 9 | 2.69 | 0.13 | 16/112/171 | finalized:completed | trap_grep_refused×2, listing_refused×2, schema_validation×1 |
| 18 | 10-04 | person | Octavia McCormick-Sharf, Associate Commissioner, Human Resources and Staff Development — nyc.gov | `c744b7eca5bb` | person-research@v25-person | 14:14:39 | 13.1 | 16.3 | 35 | 114 | 12 | 11 | 2.25 | 0.12 | 15/106/160 | finalized:completed | trap_grep_refused×5, read_refused×1, schema_validation×1 |
| 19 | 10-04 | account | firstfleetinc.com (account) | `8522140a0c6d` | account-research@v25 | 23:24:05 | 20.5 | 25.9 | 52 | 148 | 23 | 19 | 4.12 | 0.32 | 18/126/203 | finalized:completed | listing_refused×2, schema_validation×2, trap_grep_refused×1 |
| 20 | 10-04 | account | jrayl.com (account) | `b58eadb5b46d` | account-research@v25 | 23:24:05 | 22.0 | 27.2 | 52 | 133 | 29 | 25 | 4.92 | 0.15 | 18/134/216 | finalized:completed | schema_validation×3, trap_grep_refused×2 |
| 21 | 10-04 | person | Robb Getts, Executive Vice President — firstfleetinc.com | `496af486b7e5` | person-research@v25-person | 23:43:45 | 19.9 | 23.4 | 43 | 139 | 21 | 18 | 3.57 | 0.12 | 16/133/189 | finalized:completed | trap_grep_refused×1, trap_search_evidence_unavailable×1, listing_refused×1, schema_validation×1, finalize_refused_unresolved_failures×1 |
| 22 | 10-04 | person | Bronson Laney, Director — firstfleetinc.com | `6d7525cb83a2` | person-research@v25-person | 23:43:46 | 13.6 | 16.4 | 30 | 112 | 17 | 15 | 1.94 | 0.12 | 16/104/155 | finalized:completed | trap_grep_refused×3, read_refused×1, listing_refused×1, schema_validation×1 |
| 23 | 10-04 | person | Austin Henderson — firstfleetinc.com | `33d5b4810254` | person-research@v25-person | 23:43:47 | 17.5 | 22.4 | 43 | 113 | 13 | 11 | 3.01 | 0.16 | 16/118/176 | finalized:completed | trap_grep_refused×2, schema_validation×2 |
| 24 | 10-04 | person | Rebecca Wilson, Vice President Corporate Operations — firstfleetinc.com | `3cbf8074d833` | person-research@v25-person | 23:43:47 | 12.7 | 16.1 | 30 | 101 | 16 | 14 | 2.14 | 0.13 | 16/101/150 | finalized:completed | trap_grep_refused×2, read_refused×1, schema_validation×1 |
| 25 | 10-04 | person | John Cole, Safety Director — firstfleetinc.com | `fb1a1bdea18f` | person-research@v25-person | 23:43:47 | 17.1 | 20.4 | 40 | 128 | 20 | 19 | 2.75 | 0.11 | 15/115/174 | finalized:completed | trap_grep_refused×1, schema_validation×1 |
| 26 | 10-04 | person | Ryan Richards, CEO — jrayl.com | `1b3a6f71f709` | person-research@v25-person | 23:45:12 | 17.4 | 21.5 | 41 | 137 | 18 | 17 | 3.17 | 0.11 | 16/129/189 | finalized:completed | trap_grep_refused×1, trap_search_evidence_unavailable×1, schema_validation×1, finalize_refused_unresolved_failures×1 |
| 27 | 10-04 | person | Matthew Parks, Vice President — jrayl.com | `ff2bbbd51550` | person-research@v25-person | 23:45:12 | 15.9 | 19.2 | 44 | 127 | 12 | 10 | 2.98 | 0.10 | 16/115/166 | finalized:completed | trap_grep_refused×4, listing_refused×2, trap_search_evidence_unavailable×1, schema_validation×1, finalize_refused_unresolved_failures×1 |
| 28 | 10-04 | person | Toni Roberts, Safety Director — jrayl.com | `33ccf50a631f` | person-research@v25-person | 23:45:13 | 17.9 | 21.3 | 41 | 111 | 12 | 11 | 2.88 | 0.11 | 16/120/172 | finalized:completed | schema_validation×4, trap_grep_refused×3, listing_refused×1 |
| 29 | 10-04 | person | Gene Shippy, Director — jrayl.com | `2e469a757d22` | person-research@v25-person | 23:45:28 | 14.4 | 17.9 | 41 | 119 | 18 | 11 | 3.13 | 0.11 | 16/125/186 | finalized:completed | schema_validation×3, trap_grep_refused×2, listing_refused×2 |
| 30 | 10-04 | person | Justin Yoder, CPA, CFO — jrayl.com | `a95060bb4a7d` | person-research@v25-person | 23:45:29 | 15.0 | 18.6 | 45 | 120 | 14 | 13 | 3.16 | 0.12 | 16/120/174 | finalized:completed | trap_grep_refused×3, schema_validation×3, listing_refused×2, trap_search_evidence_unavailable×1, read_refused×1, finalize_refused_unresolved_failures×1 |
| 31 | 10-06 | account | loopio.com (account) | `d8fd921c5e0b` | account-research@v25 | 17:15:25 | 23.4 | 29.0 | 56 | 150 | 25 | 25 | 3.90 | 0.19 | 18/116/185 | finalized:completed | listing_refused×2, trap_grep_refused×2, schema_validation×2 |
| 32 | 10-06 | account | dialpad.com (account) | `efc87b75f3e5` | account-research@v25 | 17:15:25 | 24.5 | 30.4 | 59 | 191 | 32 | 30 | 5.00 | 0.20 | 18/135/203 | finalized:completed+page_writer_failed | trap_grep_refused×2, trap_search_evidence_unavailable×2, listing_refused×1, schema_validation×1, finalize_refused_unresolved_failures×1 |
| 33 | 10-06 | person | Siobhan Mondesire, VP — loopio.com | `c67928bbd846` | person-research@v25-person | 17:37:58 | 19.3 | 22.8 | 51 | 143 | 19 | 17 | 4.80 | 0.12 | 16/141/205 | finalized:completed | trap_grep_refused×3, schema_validation×2, listing_refused×1, trap_search_evidence_unavailable×1, finalize_refused_unresolved_failures×1 |
| 34 | 10-06 | person | Michelle Oke, Vice President, Sales — loopio.com | `90353e774349` | person-research@v25-person | 17:37:58 | 16.0 | 19.9 | 59 | 142 | 12 | 10 | 4.32 | 0.13 | 16/129/186 | finalized:completed | trap_grep_refused×4, schema_validation×3, listing_refused×2, trap_search_evidence_unavailable×1, finalize_refused_unresolved_failures×1 |
| 35 | 10-06 | person | Alex Pace, Senior Revenue Operations Specialist (Sales Operations Focus) — loopio.com | `84e5fcde73d8` | person-research@v25-person | 17:37:59 | 18.6 | 21.2 | 45 | 123 | 17 | 16 | 3.21 | 0.10 | 15/116/168 | finalized:completed | trap_grep_refused×4, listing_refused×2, trap_search_evidence_unavailable×1, read_refused×1, schema_validation×1, finalize_refused_unresolved_failures×1 |
| 36 | 10-06 | person | Vincent Lo, Senior Director, Product Marketing — loopio.com | `3263c80c2517` | person-research@v25-person | 17:38:00 | 21.5 | 24.7 | 49 | 147 | 21 | 19 | 3.87 | 0.10 | 15/126/188 | finalized:completed | trap_grep_refused×3, schema_validation×3, listing_refused×2 |
| 37 | 10-06 | person | Alison Hayter, Senior Director, Marketing — loopio.com | `defc6b768b4d` | person-research@v25-person | 17:38:00 | 19.3 | 22.1 | 51 | 154 | 12 | 11 | 4.38 | 0.10 | 16/132/203 | finalized:completed | trap_grep_refused×4, listing_refused×2, trap_search_evidence_unavailable×2, schema_validation×2, finalize_refused_unresolved_failures×1 |
| 38 | 10-06 | person | Jenny Coupe, Head — dialpad.com | `4d823bc5851d` | person-research@v25-person | 17:38:42 | 18.7 | 22.6 | 44 | 115 | 17 | 14 | 3.35 | 0.13 | 16/126/187 | finalized:completed | trap_grep_refused×2, listing_refused×1, trap_search_evidence_unavailable×1, schema_validation×1, finalize_refused_unresolved_failures×1 |
| 39 | 10-06 | person | Andrew Flynn, SVP Marketing and Vertical Solutions — dialpad.com | `bb812bc97b60` | person-research@v25-person | 17:38:43 | 16.8 | 20.1 | 39 | 120 | 17 | 15 | 3.59 | 0.11 | 15/132/201 | finalized:completed | trap_grep_refused×4, listing_refused×2, schema_validation×1 |
| 40 | 10-06 | person | Sarah Rolfing, Sr. Director, Demand Generation — dialpad.com | `02a50a639766` | person-research@v25-person | 17:38:45 | 19.2 | 22.6 | 47 | 142 | 16 | 15 | 3.61 | 0.11 | 15/133/195 | finalized:completed | trap_grep_refused×6, listing_refused×2, trap_search_evidence_unavailable×1, read_refused×1, schema_validation×1, finalize_refused_unresolved_failures×1 |
| 41 | 10-06 | person | Meaghan Edelstein — dialpad.com | `2a642151f810` | person-research@v25-person | 17:38:46 | 18.5 | 21.4 | 50 | 135 | 18 | 17 | 3.64 | 0.11 | 15/126/180 | finalized:completed | schema_validation×6, trap_grep_refused×2, listing_refused×2 |
| 42 | 10-06 | person | Emily Wall, Field Programs & ABM Manager — dialpad.com | `0f475f793132` | person-research@v25-person | 17:38:46 | 17.0 | 19.8 | 54 | 128 | 19 | 18 | 4.19 | 0.11 | 15/127/186 | finalized:completed | schema_validation×4, listing_refused×3, trap_grep_refused×2 |


Outcome column: `finalized:completed` = an accepted `finalize_turn` with `status=completed`;
`finalize_refused_only` = every `finalize_turn` was refused (the six 10-03 runs whose repair hit the
immutable-snapshot bug — §3.6); `+page_writer_failed` = the driver's page writer span ended ERROR.
Job status itself (completed / needs_review / failure_code) lives in `arv2_research_job` (§7).

What each run produced (from `validate_dossier` coverage and `finish_dossier`): a JSON dossier of
14–77 findings in 5–12 sections (T5.3), imported as claims; on v24 (10-03) the researcher also wrote
its own overview/insights or contact pages (`write_research_narrative`: 15 calls across the 12 runs,
all accepted); on v25 the driver's page writer wrote them after the agent finished (30 in-run spans,
§3.7) and then rewrote the account pages as people finished (13 rewrite traces, T1.6).

### 1.3 Did later code behave differently? Evidence-call timing by day

The same evidence tool, the same providers, three code versions. Provider time is the Exa / AI Ark /
media span inside the call; "governed admission" is the delay from the agent-level tool start to the
`governed.acquire_research_evidence@1` child starting — the in-process queue before the tool is even
admitted.


**T1.3 — Evidence-call timing by day (acquire_research_evidence, agent-level; provider = Exa/AI Ark/… span inside)**

| Day (release) | Op | Calls | Mean total s | Median s | p90 s | Provider mean s | Before provider (mean s) | After provider (mean s) | Governed admission wait (mean s) |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-03 (#89) | search_web | 114 | 206 | 173 | 448 | 1.8 | 116 | 97 | 69 |
| 2026-10-03 (#89) | fetch_page | 61 | 141 | 114 | 249 | 0.5 | 99 | 42 | 57 |
| 2026-10-03 (#89) | research_deep | 17 | 167 | 142 | 318 | 41.1 | 90 | 94 | 49 |
| 2026-10-03 (#89) | enrich_contact | 11 | 225 | 216 | 289 | 0.0 | 0 | 0 | 66 |
| 2026-10-03 (#89) | lookup_person | 10 | 390 | 384 | 523 | 10.1 | 284 | 96 | 85 |
| 2026-10-03 (#89) | discover_media | 6 | 123 | 108 | 183 | 1.7 | 55 | 74 | 50 |
| 2026-10-03 (#89) | discover_people | 5 | 74 | 55 | 104 | 0.7 | 47 | 26 | 24 |
| 2026-10-03 (#89) | lookup_company | 2 | 56 | 56 | 34 | 0.9 | 16 | 40 | 13 |
| 2026-10-03 (#89) | read_people_result | 1 | 39 | 39 | 39 | 0.0 | 0 | 0 | 17 |
| 2026-10-03 | **all** | 227 | 187 | 157 | | | | | total 709 min, provider 13.7 min |
| 2026-10-04 (#97) | search_web | 146 | 59 | 48 | 118 | 2.8 | 16 | 45 | 3 |
| 2026-10-04 (#97) | fetch_page | 74 | 19 | 14 | 36 | 0.2 | 9 | 10 | 4 |
| 2026-10-04 (#97) | research_deep | 18 | 83 | 78 | 101 | 38.7 | 8 | 37 | 3 |
| 2026-10-04 (#97) | enrich_contact | 15 | 11 | 8 | 20 | 0.0 | 0 | 0 | 4 |
| 2026-10-04 (#97) | read_media | 14 | 17 | 13 | 25 | 1.4 | 7 | 10 | 4 |
| 2026-10-04 (#97) | lookup_person | 13 | 87 | 103 | 139 | 9.2 | 65 | 22 | 4 |
| 2026-10-04 (#97) | discover_media | 11 | 21 | 11 | 33 | 2.0 | 10 | 27 | 5 |
| 2026-10-04 (#97) | discover_people | 6 | 22 | 20 | 25 | 0.9 | 6 | 15 | 3 |
| 2026-10-04 (#97) | lookup_company | 3 | 49 | 45 | 45 | 1.1 | 13 | 36 | 3 |
| 2026-10-04 (#97) | read_people_result | 1 | 8 | 8 | 8 | 0.0 | 0 | 0 | 3 |
| 2026-10-04 | **all** | 301 | 45 | 35 | | | | | total 227 min, provider 20.6 min |
| 2026-10-06 (#105) | search_web | 104 | 69 | 56 | 132 | 2.5 | 21 | 46 | 3 |
| 2026-10-06 (#105) | fetch_page | 61 | 35 | 24 | 73 | 0.3 | 16 | 19 | 3 |
| 2026-10-06 (#105) | research_deep | 12 | 115 | 107 | 140 | 52.8 | 16 | 46 | 3 |
| 2026-10-06 (#105) | lookup_person | 10 | 86 | 64 | 149 | 2.6 | 50 | 42 | 3 |
| 2026-10-06 (#105) | enrich_contact | 10 | 20 | 12 | 50 | 2.4 | 13 | 42 | 3 |
| 2026-10-06 (#105) | discover_media | 9 | 26 | 16 | 51 | 1.7 | 11 | 32 | 4 |
| 2026-10-06 (#105) | read_media | 7 | 56 | 74 | 75 | 0.9 | 27 | 24 | 5 |
| 2026-10-06 (#105) | discover_people | 4 | 48 | 46 | 51 | 0.7 | 30 | 17 | 3 |
| 2026-10-06 (#105) | read_people_result | 4 | 8 | 8 | 8 | 0.0 | 0 | 0 | 3 |
| 2026-10-06 (#105) | lookup_company | 2 | 84 | 84 | 72 | 0.4 | 18 | 65 | 3 |
| 2026-10-06 (#105) | read_ats_board | 2 | 95 | 95 | 86 | 1.4 | 13 | 81 | 2 |
| 2026-10-06 | **all** | 225 | 58 | 46 | | | | | total 217 min, provider 15.9 min |


- **10-03 → 10-04 (PR #91 in between):** a web search went from **209 s to 63 s** (median 183 → 50);
  the admission wait collapsed from **67 s to 3 s**, the before-provider wait from 116 s to 16 s, the
  after-provider (indexing) wait from 97 s to 45 s. Page fetches 141 → 19 s. AI Ark person lookups
  390 → 87 s.
- **10-04 → 10-06 (PR #105, thread pool):** no visible change: search 63 → 69 s, after-provider
  45 → 46 s, admission 3 → 3 s. The two 10-04 batches (13:59 with 6 jobs; 23:24 with 12 jobs) differ
  little either: mean evidence call 43 s vs 46 s, before 12 vs 16 s, after 29 vs 32 s.
- Total evidence-tool time: 709 min on 10-03 for 227 calls (provider 13.7 min); 227 min for 301 calls
  on 10-04 (provider 20.6 min); 217 min for 225 calls on 10-06 (provider 15.9 min). Across the corpus
  the providers account for **50 of 1,153 evidence-tool minutes (4.4%)**.
- The 10-03 "refused" row (10 calls, 159 s mean, 0 provider time) is the argument-refusal path
  (`invalid_acquisition_arguments`, §3.8) — on 10-03 even a refusal waited 93 s for admission.


**T1.4 — Batch position vs wait before the provider is called (calls issued in the same model round, ordered by start)**

| Day | Rounds with evidence calls, by batch size | Position 1 | 2 | 3 | 4 | 5 | 6+ |
|---|---|---|---|---|---|---|---|
| 2026-10-03 | 1: 27, 2: 13, 3: 18, 4: 6, 5: 6, 6: 11 | 98 s (n=67) | 116 s (n=46) | 119 s (n=36) | 120 s (n=20) | 138 s (n=16) | 136 s (n=11) |
| 2026-10-04 | 1: 37, 2: 24, 3: 21, 4: 12, 5: 10, 6: 8, 7: 1 | 14 s (n=97) | 16 s (n=67) | 10 s (n=47) | 18 s (n=26) | 17 s (n=16) | 26 s (n=9) |
| 2026-10-06 | 1: 23, 2: 16, 3: 12, 4: 16, 5: 5, 6: 4, 7: 3 | 17 s (n=66) | 19 s (n=51) | 18 s (n=39) | 21 s (n=28) | 26 s (n=11) | 49 s (n=10) |


On 10-03 every position waited ~100–140 s (the worker-wide queue dominated); on 10-04 and 10-06 the
first four positions wait 14–21 s and positions 5–6+ wait 26–49 s — the four-slot provider semaphore
holding slots through indexing, visible only once the worker-wide lock was gone.

Model-call latency also halved between 10-03 and 10-04 **at equal context** (T2.5: 150–200k band
24.1 s → 15.6 s → 14.5 s), and the delay between a model call ending and its first tool starting
was **10.5 s per round on 10-03 (105 min over 604 rounds) versus 0.6 s on 10-04/10-06** — the same
blocked worker process, not the provider.

### 1.4 The chat turns that launched research, and the rewrite / reconciliation traces


**T1.5 — Chat turns that launched research, and all Head-of-ABM turns in the window**

| Start (UTC) | Trace | Workspace | Launch tool | Model calls | Max ctx (k) | File reads | Duration | Model $ | Errors |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-03 14:47:32 | `e383d3522209` | W1 (Garner Health project) | — | 6 | 59 | 11 | 1.4 min | 0.26 | grep: permission_denied: workspace tree contains an unsafe entry |
| 2026-10-03 14:50:04 | `5c065a982d55` | W1 (Garner Health project) | — | 2 | 71 | 7 | 1.4 min | 0.11 |  |
| 2026-10-03 14:55:54 | `675f719a4137` | W1 (Garner Health project) | — | 14 | 104 | 16 | 3.5 min | 0.78 | edit_file: conflict: revision_conflict: audience/icp-us-employer-core-n; grep: permission_denied: workspace tree contains an unsafe entry |
| 2026-10-03 15:00:50 | `99f5568773fa` | W1 (Garner Health project) | — | 9 | 161 | 8 | 2.9 min | 0.76 |  |
| 2026-10-03 15:05:18 | `da0d1febc88a` | W1 (Garner Health project) | — | 2 | 168 | 2 | 0.9 min | 0.18 |  |
| 2026-10-03 15:07:06 | `b1c657522cce` | W1 (Garner Health project) | launch_arv2_discovery | 5 | 185 | 5 | 4.3 min | 0.50 | GET: ; exa_websets.get: client_error |
| 2026-10-03 15:18:10 | `00b8a28b28cb` | W1 (Garner Health project) | — | 2 | 192 | 1 | 1.3 min | 0.49 |  |
| 2026-10-04 08:10:58 | `812ace9fded6` | W1 (Garner Health project) | — | 1 | 0 | 0 | 5.0 min | 0.00 | GovernedAgentChatModel: No streaming chunk received for 300.0s (model=x-ai/grok-4.6,; model: No streaming chunk received for 300.0s (model=x-ai/grok-4.6, |
| 2026-10-04 13:57:29 | `87e5059dbc61` | W1 (Garner Health project) | launch_arv2_account_research | 8 | 78 | 18 | 2.0 min | 0.51 |  |
| 2026-10-04 22:11:26 | `683f4213851b` | W2 | — | 7 | 65 | 13 | 1.0 min | 0.31 |  |
| 2026-10-04 22:49:14 | `52d0386b332d` | W2 | — | 3 | 71 | 2 | 0.5 min | 0.22 |  |
| 2026-10-04 23:18:07 | `ee29a20ce02a` | W2 | launch_arv2_discovery | 11 | 98 | 11 | 2.6 min | 0.58 |  |
| 2026-10-04 23:21:39 | `27cd4dd9de40` | W2 | — | 3 | 107 | 2 | 0.6 min | 0.18 |  |
| 2026-10-04 23:22:52 | `ca36c9e0055c` | W2 | launch_arv2_account_research | 4 | 123 | 6 | 1.3 min | 0.28 |  |
| 2026-10-05 00:09:28 | `93e95f66c27c` | W2 | — | 5 | 152 | 3 | 1.9 min | 0.81 |  |
| 2026-10-05 00:21:38 | `aa04947ca6a1` | W2 | — | 5 | 173 | 2 | 1.4 min | 0.70 |  |
| 2026-10-05 00:24:20 | `791b00d772a6` | W2 | — | 7 | 196 | 4 | 1.8 min | 0.73 | open_design_leg: 2 validation errors for OpenDesignLegInputAgentRuntime
claim |
| 2026-10-05 00:46:31 | `e83b7ba1430a` | W2 | — | 3 | 205 | 3 | 1.0 min | 1.24 |  |
| 2026-10-05 15:32:11 | `0d9f07c0fa94` | W1 (Garner Health project) | — | 7 | 73 | 14 | 2.5 min | 0.37 |  |
| 2026-10-05 19:22:54 | `afd495a87502` | W2 | — | 3 | 213 | 1 | 1.0 min | 1.30 |  |
| 2026-10-05 19:50:39 | `826c6c110822` | W2 | — | 3 | 221 | 1 | 0.6 min | 0.70 |  |
| 2026-10-06 16:21:02 | `cc532cec811c` | W3 (Dialpad/Loopio) | — | 5 | 61 | 12 | 1.0 min | 0.24 |  |
| 2026-10-06 16:25:08 | `12169bb3fe8e` | W3 (Dialpad/Loopio) | — | 7 | 72 | 4 | 1.0 min | 0.28 |  |
| 2026-10-06 16:37:18 | `ebd6264e3d83` | W3 (Dialpad/Loopio) | — | 4 | 87 | 7 | 1.0 min | 0.20 |  |
| 2026-10-06 16:39:28 | `35e4cf2d3ee7` | W3 (Dialpad/Loopio) | — | 3 | 97 | 3 | 0.9 min | 0.31 |  |
| 2026-10-06 16:41:35 | `02900afb13a5` | W3 (Dialpad/Loopio) | — | 3 | 104 | 2 | 0.5 min | 0.17 |  |
| 2026-10-06 16:52:09 | `ce52ca4b1d1c` | W3 (Dialpad/Loopio) | launch_arv2_discovery | 4 | 118 | 6 | 0.9 min | 0.27 |  |
| 2026-10-06 16:56:44 | `20b1f6c4c0b3` | W3 (Dialpad/Loopio) | — | 2 | 125 | 2 | 0.4 min | 0.14 |  |
| 2026-10-06 16:57:20 | `5e47571d52a9` | W3 (Dialpad/Loopio) | — | 2 | 130 | 0 | 0.4 min | 0.14 |  |
| 2026-10-06 17:11:27 | `6ba16f877674` | W3 (Dialpad/Loopio) | launch_arv2_account_research | 5 | 142 | 9 | 4.0 min | 0.58 |  |
| 2026-10-03 15:23:54 | `df90b7ebcd28` (shared with both account jobs) | W1 (Garner Health project) | launch_arv2_account_research | 4 | 206 | 6 | 1.1 min | 0.78 | |

Head-of-ABM turns in the window (30 traces): $13.35 model spend in total.

**T1.6 — Account-page rewrites (unnamed traces carrying only a `research.page_writer` span) and v24 account reconciliation**

| Start (UTC) | Trace | Kind | Writer calls | Writer s | Model $ | Status |
|---|---|---|---|---|---|---|
| 2026-10-03 17:32:26 | `783858acd71f` | v24 account reconciliation (agent) | — | 851 | 4.80 | DEFAULT; 28 model calls, finalize_turn, grep, write_file |
| 2026-10-03 18:17:44 | `0be62690e68b` | v24 account reconciliation (failed before any model call) | — | 31 | 0.00 | ERROR: ValueError: Continuation requires a settled saved conversation |
| 2026-10-03 18:21:05 | `a8ff684075fa` | v24 account reconciliation (failed before any model call) | — | 27 | 0.00 | ERROR: ValueError: Continuation requires a settled saved conversation |
| 2026-10-04 14:28:27 | `b4ec8d145271` | account-page rewrite | 1 | 145 | 0.18 | DEFAULT |
| 2026-10-04 14:30:53 | `9ea8190e8735` | account-page rewrite | 1 | 170 | 0.11 | DEFAULT |
| 2026-10-04 14:33:44 | `f315503d7fc3` | account-page rewrite | 2 | 261 | 0.21 | DEFAULT |
| 2026-10-05 00:02:32 | `8982499dea0a` | account-page rewrite | 2 | 376 | 0.23 | ERROR: PageWriterError: pages ['insights'] != ['insights', 'overview'] |
| 2026-10-05 00:02:32 | `47829e56def1` | account-page rewrite | 2 | 337 | 0.28 | DEFAULT |
| 2026-10-05 00:08:11 | `a1cd2b11ad99` | account-page rewrite | 2 | 339 | 0.22 | ERROR: PageWriterError: overview/how-to-approach: quote not in cited findings: “…”; insights/money-an |
| 2026-10-05 00:08:49 | `d04bcd569f98` | account-page rewrite | 1 | 200 | 0.17 | DEFAULT |
| 2026-10-06 17:56:37 | `53a05fd9e09f` | account-page rewrite | 1 | 257 | 0.19 | DEFAULT |
| 2026-10-06 17:58:40 | `83d944c25dac` | account-page rewrite | 1 | 239 | 0.18 | DEFAULT |
| 2026-10-06 18:00:55 | `d56dd7deb52e` | account-page rewrite | 1 | 246 | 0.19 | DEFAULT |
| 2026-10-06 18:02:40 | `cf4a91e9ddcf` | account-page rewrite | 2 | 287 | 0.19 | DEFAULT |
| 2026-10-06 18:05:02 | `3a2801c536b8` | account-page rewrite | 2 | 225 | 0.20 | DEFAULT |
| 2026-10-06 18:07:28 | `7349fd6dbc62` | account-page rewrite | 1 | 245 | 0.13 | DEFAULT |

Rewrite + reconciliation model spend: $7.39.


Rewrites run back to back: W1 10-04 at 14:28, 14:30, 14:33 (3 rewrites for one account while its 5
people finished 14:26–14:33); W2 at 00:02 ×2 and 00:08 ×2 (2 accounts); W3 at 17:56, 17:58, 18:00,
18:02, 18:05, 18:07 (2 accounts, one every ~2 min as people finished 17:54–18:02). The rewrite traces
carry no metadata, so which of two sibling accounts a given rewrite (or failure) belongs to cannot be
told from Langfuse.

---

## 2. Cost and time per account

### 2.1 Per account (account run + its five people; rewrites in the account's window)


**T2.1 — Cost and time per account (account run + its person runs; rewrites in the account's window)**

| Day | Account | Persons | Account $ (model+PW) | Persons $ (model+PW) | Rewrites in window ($) | Total model $ | Account start | Nominated at | First person start | Last person page | Last page (incl. rewrites) | Start → last page | Account outcome | Person outcomes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10-03 | mckeefoods.com | 5 | 7.82 | 23.76 | 0 ($0.00) | 31.58 | 15:25:15 | 15:47:28 | 16:16:32 | 18:21:04 | 18:21:04 | 175.8 min | finalize_refused_only | [('finalize_refused_only', 3), ('finalized:completed', 2)] |
| 10-03 | mortenson.com | 5 | 6.61 | 18.69 | 0 ($0.00) | 25.30 | 15:25:16 | 15:48:34 | 16:06:03 | 17:47:11 | 17:47:11 | 141.9 min | finalized:completed | [('finalized:completed', 3), ('finalize_refused_only', 2)] |
| 10-04 | nyc.gov | 5 | 3.30 | 12.92 | 3 ($0.51) | 16.23 | 13:59:10 | 14:07:54 | 14:14:36 | 14:32:35 | 14:38:06 | 38.9 min | finalized:completed | [('finalized:completed', 5)] |
| 10-04 | firstfleetinc.com | 5 | 4.43 | 14.05 | 4 ($0.90) | 18.48 | 23:24:05 | 23:34:49 | 23:43:45 | 00:07:07 | 00:13:50 | 49.7 min | finalized:completed | [('finalized:completed', 5)] |
| 10-04 | jrayl.com | 5 | 5.08 | 15.88 | 4 ($0.90) | 20.96 | 23:24:05 | 23:35:47 | 23:45:12 | 00:06:44 | 00:13:50 | 49.7 min | finalized:completed | [('finalized:completed', 5)] |
| 10-06 | loopio.com | 5 | 4.09 | 21.14 | 6 ($1.09) | 25.23 | 17:15:25 | 17:30:22 | 17:37:58 | 18:02:42 | 18:11:33 | 56.1 min | finalized:completed | [('finalized:completed', 5)] |
| 10-06 | dialpad.com | 5 | 5.21 | 18.95 | 6 ($1.09) | 24.16 | 17:15:25 | 17:30:14 | 17:38:42 | 18:01:20 | 18:11:33 | 56.1 min | finalized:completed+page_writer_failed | [('finalized:completed', 5)] |


Notes. "Persons $" and "Total model $" are model + in-run page-writer cost from Langfuse; the rewrite
column is the unnamed rewrite traces in the account's window and is **shared** between sibling
accounts of the same launch (W2: the same 4 rewrites, $0.90, appear on both; W3: the same 6, $1.09).
Distinct totals by launch: 10-03 $56.88 (+ $4.80 Mortenson reconciliation; McKee's two reconciliation
attempts failed at $0); 10-04 13:59 $16.23 + $0.51 rewrites; 10-04 23:24 $39.44 + $1.40 rewrites;
10-06 $49.39 + $1.09 rewrites. People are **74–84% of every account's model spend** (McKee 75%,
Mortenson 74%, nyc.gov 80%, FirstFleet 76%, JRayl 76%, Loopio 84%, Dialpad 78%).
Whole corpus: research runs $157.91 model + $4.03 in-run page writer; rewrites $2.49;
reconciliation $4.80; the 30 chat turns $13.35 (the four launching turns: $0.78, $0.51, $0.28, $0.58).

Time to the last page: **39 min** for the single 10-04 account (five people, no sibling), **50 min**
for the two 10-04 23:24 accounts side by side, **56 min** for Dialpad and Loopio side by side (the
last rewrite ended 18:11:33), versus 142 and 176 min on 10-03 (and McKee's last page was never
rewritten — its reconciliation refused to run).

Nomination → first person start: 17.5 min (Mortenson) and 29.1 min (McKee) on 10-03; 6.7 / 8.9 /
9.4 min on 10-04; 7.6 / 8.5 min on 10-06. In every case the first person starts within ~1 min of the
account's `arv2.dossier.import` span (nyc.gov import 14:14:08 → first person 14:14:36; Loopio
17:37:29 → 17:37:58; Dialpad 17:38:12 → 17:38:42). Across all 35 person runs the parent account
dossier (`/research/parent-account…`) was opened **16 times** (McKee's people 4, Mortenson's 2,
nyc.gov 3, FirstFleet 1, JRayl 3, Loopio 2, Dialpad 1).

### 2.2 Distributions per run


**T2.2 — Distributions per run (min / median / max)**

| Day | Kind | n | Rounds | Avg ctx (k) | Final ctx (k) | Model $ | Agent min | To last page min | Tool calls | Evidence calls | Model s per call |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-03 | account | 2 | 65 / 70 / 74 | 138 / 144 / 149 | 228 / 231 / 235 | 6.61 / 7.21 / 7.82 | 52.1 / 59.5 / 66.9 | 67.3 / 67.3 / 67.3 | 180 / 198 / 216 | 31 / 34 / 37 | 14.2 / 14.3 / 14.4 |
| 2026-10-03 | person | 10 | 37 / 46 / 68 | 102 / 126 / 146 | 161 / 189 / 217 | 2.82 / 3.63 / 7.79 | 34.2 / 88.1 / 100.5 | 34.4 / 88.3 / 100.7 | 105 / 126 / 153 | 12 / 14 / 28 | 14.7 / 26.2 / 28.5 |
| 2026-10-04 | account | 3 | 45 / 52 / 52 | 114 / 127 / 135 | 178 / 204 / 217 | 3.07 / 4.12 / 4.92 | 16.3 / 20.5 / 22.0 | 21.4 / 25.9 / 27.2 | 132 / 133 / 148 | 17 / 23 / 29 | 12.5 / 13.8 / 14.3 |
| 2026-10-04 | person | 15 | 30 / 41 / 45 | 98 / 116 / 133 | 149 / 172 / 189 | 1.94 / 2.88 / 3.57 | 11.4 / 14.6 / 19.9 | 14.8 / 17.9 / 23.4 | 100 / 114 / 139 | 11 / 16 / 21 | 9.3 / 11.1 / 14.0 |
| 2026-10-06 | account | 2 | 56 / 58 / 59 | 117 / 126 / 135 | 186 / 195 / 203 | 3.90 / 4.45 / 5.00 | 23.4 / 23.9 / 24.5 | 29.0 / 29.7 / 30.4 | 150 / 170 / 191 | 25 / 28 / 32 | 11.4 / 11.5 / 11.6 |
| 2026-10-06 | person | 10 | 39 / 50 / 59 | 117 / 129 / 141 | 168 / 188 / 206 | 3.21 / 3.76 / 4.80 | 16.0 / 18.6 / 21.5 | 19.8 / 21.8 / 24.7 | 115 / 138 / 154 | 12 / 17 / 21 | 8.3 / 11.4 / 13.2 |
| all | account | 7 | 45 / 56 / 74 | 114 / 135 / 149 | 178 / 204 / 235 | 3.07 / 4.92 / 7.82 | 16.3 / 23.4 / 66.9 | 21.4 / 29.0 / 67.3 | 132 / 150 / 216 | 17 / 29 / 37 | 11.4 / 13.8 / 14.4 |
| all | person | 35 | 30 / 44 / 68 | 98 / 123 / 146 | 149 / 183 / 217 | 1.94 / 3.21 / 7.79 | 11.4 / 18.5 / 100.5 | 14.8 / 21.5 / 100.7 | 100 / 125 / 154 | 11 / 16 / 28 | 8.3 / 12.4 / 28.5 |


Context never shrinks: **0 context shrinks in 1,956 model calls** (T2.4). Start 16–19k tokens,
final 149–235k (account median 204k, person 183k); every run's average context is 98–149k.

### 2.3 Where the time goes


**T2.3 — Where run time goes, per day (sum over runs; agent wall = run root start → last page-writer end)**

| Day | Runs | Wall min | Model thinking | Tools running | Gaps | After agent (page writer) | Model calls | Mean s per call |
|---|---|---|---|---|---|---|---|---|
| 2026-10-03 | 12 | 938 | 230 (25%) | 573 (61%) | 108 (12%) | 18 (2%) | 616 | 22.4 |
| 2026-10-04 | 18 | 353 | 145 (41%) | 129 (37%) | 9 (3%) | 68 (19%) | 736 | 11.8 |
| 2026-10-06 | 12 | 276 | 113 (41%) | 111 (40%) | 8 (3%) | 44 (16%) | 604 | 11.2 |


"Gaps" on 10-03 (108 min, 12%) are almost entirely the 10.5 s per round between the model answering
and its first tool starting (105 min); on 10-04/10-06 that delay is 0.6 s (7 and 6 min in total) and
the gap after the last tool ends is 0.2 s. "After agent" on v25 is the driver page writer (T3.7): 19%
and 16% of run wall time.

### 2.4 Where the money goes


**T2.4 — Model cost split (fitted $2.00/M new, $0.50/M cached, $6.00/M output) and Langfuse totals**

| Day | Langfuse model $ | Fitted $ | Cached re-sends | New input | Output | In-run page writer $ | Context shrinks (any run) |
|---|---|---|---|---|---|---|---|
| 2026-10-03 | 56.88 | 51.61 | 37.70 (73%) | 11.28 (22%) | 2.64 (5%) | 0.00 | 0 |
| 2026-10-04 | 53.15 | 52.36 | 41.45 (79%) | 7.63 (15%) | 3.28 (6%) | 2.52 | 0 |
| 2026-10-06 | 47.88 | 46.69 | 37.18 (80%) | 6.97 (15%) | 2.54 (5%) | 1.52 | 0 |
| all | 157.91 | 150.67 | 116.33 (77%) | 25.88 (17%) | 8.46 (6%) | 4.03 | 0 |


Attribution over the rest of each run (a file read costs its tokens once as new input and again as
cached input on every later call): reads of the agent's own saved results under
`/research/operations/` **1,185 reads ≈ 1.63 M tokens ≈ $30.11 (19%)**; `/evidence/` files 1,126
reads ≈ 1.01 M ≈ $18.69 (12%); skill files 361 reads ≈ 623k ≈ $11.10 (7%; 8 reads and 13–18k
tokens per run); context / dossier / `/reads/` 343 reads ≈ $7.94 (5%); `/research/capabilities/0.json`
135 reads ≈ $4.39 (3%); `ls`/`glob`/`grep` output ≈ $2.55. File reads together ≈ **$74.8 of $157.9
(47%)**; the opening prompt re-sent on every call ≈ $17.8 (11%). The write phase (from the first
`save_dossier_section` to the end) is **667 of 1,956 calls (34%) and $73.85 (47%)**.


**T2.5 — Model-call latency by context band, per day (mean s, n)**

| Day | <50k | 50–100k | 100–150k | 150–200k | ≥200k | Mean output tokens/call |
|---|---|---|---|---|---|---|
| 2026-10-03 | 15.5 (52) | 23.6 (114) | 20.8 (186) | 24.1 (222) | 25.7 (42) | 713 |
| 2026-10-04 | 5.9 (79) | 11.1 (173) | 11.0 (268) | 15.6 (209) | 13.1 (7) | 743 |
| 2026-10-06 | 5.6 (52) | 12.3 (111) | 7.9 (186) | 14.5 (244) | 7.5 (11) | 702 |

**T2.6 — Idle share per run on Oct 3 (elapsed vs model+tool time) — the stranded/queued pattern**

| Run | Elapsed min | Model min | Tools min | Neither (waiting) min | Share waiting | Worker |
|---|---|---|---|---|---|---|
| mckeefoods.com (account) | 66.9 | 17.6 | 44.7 | 4.7 | 7% |  |
| mortenson.com (account) | 52.1 | 15.6 | 31.5 | 5.1 | 10% |  |
| Robin Ritter, Chief Human Resources Officer — mortenson.com | 94.4 | 25.2 | 54.3 | 14.9 | 16% | f44169fa |
| Patrick Locken, Chief Financial Officer, Mortenson Construction — mortenson.com | 79.7 | 17.2 | 51.1 | 11.4 | 14% | c0eb1386 |
| John Bachhuber, Vice President Total Rewards — mortenson.com | 88.1 | 19.1 | 56.9 | 12.1 | 14% | 1704b6c5 |
| Jean McGrory, Director, Total Rewards — mortenson.com | 100.5 | 21.9 | 67.6 | 11.1 | 11% | 1704b6c5 |
| Athena Burkholder, Senior Manager — mortenson.com | 86.7 | 18.1 | 59.8 | 8.8 | 10% | 1704b6c5 |
| Chris McKee, President and COO — mckeefoods.com | 98.3 | 28.5 | 54.0 | 15.8 | 16% | f44169fa |
| Kyler Vann, Comp and Benefits Analyst — mckeefoods.com | 96.0 | 23.3 | 58.5 | 14.3 | 15% |  |
| Andy Lang, Chief Financial Officer — mckeefoods.com | 88.1 | 21.3 | 55.3 | 11.5 | 13% | f44169fa |
| Don Gladden, Vice President — mckeefoods.com | 34.8 | 11.4 | 19.4 | 4.0 | 12% | f44169fa |
| Cindy Lyons, Corporate Health & Wellness Manager — mckeefoods.com | 34.2 | 11.0 | 19.6 | 3.6 | 11% | f44169fa |


No run on any day has an idle interval longer than 2 s between its last tool ending and the next
model call starting; the 10-03 "waiting" minutes are the per-round admission delay above, and the
two McKee people whose agent started 87 and 91 min after their fleet task was claimed (16:15:18 →
17:42:21 / 17:46:41; the claim-without-capacity defect recorded in
`_memory/2026-10-03-first-production-research-quality-review.md`) show up as short 34-minute runs,
not as idle time inside the run. On 10-04 23:43–23:45 all ten people started within 103 s of each
other and on 10-06 within 48 s: twelve research jobs in flight on both days.

---

## 3. Failure taxonomy across the corpus


**T3.1 — ERROR-level observations by class and day (every trace in the corpus)**

| Class | 2026-10-03 | 2026-10-04 | 2026-10-05 (rewrites) | 2026-10-06 | Total | Example (trace / observation) |
|---|---|---|---|---|---|---|
| trap_grep_refused | 31 | 42 | 0 | 38 | 111 | `86c8897e55be` / `c1044243f83d7719` — grep: Use search_evidence with the readable source path and a literal query. |
| schema_validation | 24 | 31 | 0 | 27 | 82 | `86c8897e55be` / `febb4b75b0a58545` — save_dossier_section: N validation error for SaveSectionInputAgentRuntime |
| listing_refused | 16 | 17 | 0 | 22 | 55 | `86c8897e55be` / `fe594d9bf0af352a` — ls: Error: Open /research/<path> or /evidence/<path> |
| trap_search_evidence_unavailable | 14 | 4 | 0 | 9 | 27 | `1b3a6f71f709` / `c6f036fe9319d2a5` — governed.search_evidence@2: evidence_unavailable |
| other | 16 | 3 | 1 | 3 | 23 | `b1c657522cce` / `4e950b3bde20d353` — GET:  |
| finalize_refused_unresolved_failures | 6 | 0 | 4 | 7 | 17 | `1b3a6f71f709` / `a2ff3d0033c4301e` — finalize_turn: Unresolved failed tool attempts remain: <node>. Correct using retry_of, or finalize with a |
| read_refused | 3 | 4 | 0 | 2 | 9 | `84e5fcde73d8` / `588ee6969a135a09` — read_file: Error: Line offset N exceeds file length (N lines) |
| finalize_workspace_conflict | 6 | 0 | 0 | 0 | 6 | `ca75ce49f9dd` / `5744eb797efe1513` — finalize_turn: snapshotted outputs are immutable |
| page_writer_failed | 0 | 0 | 2 | 1 | 3 | `8982499dea0a` / `ed6d61db8a119f9a` — research.page_writer: PageWriterError: pages ['insights'] != ['insights', 'overview'] |
| provider_error | 2 | 0 | 0 | 0 | 2 | `db37e5110b8d` / `5efb6fd0e841fe7a` — POST:  |
| write_refused | 2 | 0 | 0 | 0 | 2 | `675f719a4137` / `343757ddd6cf2c35` — edit_file: conflict: revision_conflict: audience/icp-us-employer-core-new-logo.md is at version N, yo |
| reconciliation_failed | 2 | 0 | 0 | 0 | 2 | `0be62690e68b` / `1a6344b9ebafebdd` — research.account_reconciliation: ValueError: Continuation requires a settled saved conversation |
| model_call_error | 0 | 1 | 0 | 0 | 1 | `812ace9fded6` / `ff35f3a68ae2ede7` — GovernedAgentChatModel: No streaming chunk received for N.Ns (model=x-ai/grok-N.N, chunks_received=N). The connect |
| finalize_refused_other | 1 | 0 | 0 | 0 | 1 | `df90b7ebcd28` / `9030c2d0c0a10310` — finalize_turn: /outputs/research.json: invalid unprocessed_source_ids [<uuid>]. Copy source UUIDs from /e |
| finalize_refused_invalid_output | 1 | 0 | 0 | 0 | 1 | `783858acd71f` / `3db5308f3ef58e5d` — finalize_turn: Invalid /outputs/reconciliation.json: Non-gap sentences require supplied evidence. Read /w |


`other` (23) is: the six 10-03 `tools` / `clue-account_research` chains that merely propagate the
`snapshotted outputs are immutable` conflict (counted once under `finalize_workspace_conflict`), 7
`exa_websets.get` client errors and 2 `GET` errors inside discovery turns (not research), the one
Grok stall, and an `open_design_leg` validation error in a chat turn.

### 3.1 Schema failures on dossier saves


**T3.2 — Schema-validation failures on dossier saves (save_dossier_section / update_dossier_findings)**

| Day | Failed saves | Runs with ≥1 | Max per run | Cost of the rounds that failed ($) | Time of those rounds (min) |
|---|---|---|---|---|---|
| 2026-10-03 | 24 | 12/12 | 5 | 2.29 | 18 |
| 2026-10-04 | 31 | 18/18 | 4 | 2.67 | 10 |
| 2026-10-06 | 27 | 12/12 | 6 | 2.38 | 7 |
| all | 82 | 42/42 | 6 | 7.34 | 34 |

Failing field × reason (number of failed calls naming it): `findings[i].review` Field required: 80; `findings[i].review` Value error: 2


Every one of the 42 runs had at least one refused save; 80 of the 82 refusals are the nested
`findings[i].review` object missing (`Field required`), the other two a `review` value error
(`SaveSectionInputAgentRuntime`, `platform/api/clue_api/arv2/dossier_findings.py`). The refused round
is repeated in full at 100–200k context; the 82 failing rounds alone cost $7.34 and 34 min of run
time. Examples: `86c8897e55be` / `febb4b75b0a58545`; `efc87b75f3e5` (Dialpad account) 17:31:11.

### 3.2 The grep → search_evidence → finalize trap


**T3.3 — The grep → search_evidence → finalize chain, per day**

| Day | `grep` refused (“…”) | `search_evidence` failed | `search_evidence` ok (zero matches) | Failed-search source paths | `retry_of` repairs | `finalize_turn` refused: unresolved failures | Runs with a refused finalize | Finalize refused: workspace conflict (snapshot) |
|---|---|---|---|---|---|---|---|---|
| 2026-10-03 | 31 | 14 | 53 (24) | {'/research/operations': 10, 'other/uuid': 2, '/evidence': 2} | 14 | 6 | 6/12 | 6 |
| 2026-10-04 | 42 | 4 | 73 (25) | {'other/uuid': 4} | 4 | 4 | 4/18 | 0 |
| 2026-10-06 | 38 | 9 | 62 (22) | {'/research/operations': 8, 'other/uuid': 1} | 8 | 7 | 7/12 | 0 |
| all | 111 | 27 | 188 (71) | {'/research/operations': 18, 'other/uuid': 7, '/evidence': 2} | 26 | 17 | 17/42 | 6 |


Every run hit the first step (111 refused `grep`s, "Use search_evidence with the readable source
path and a literal query", `quality_workspace.py`). 27 `search_evidence` calls then failed — 18 on a
`/research/operations/…` result path, 4 on `/research/parent-account…`, 3 on
`/research/capabilities…`, 2 on an `/evidence/` path — with `evidence_unavailable` on the governed
child (`governed.search_evidence@2`) while the agent-level tool row stays DEFAULT and the receipt says
`"error":"operation_failed"`. The agent issued 26 `retry_of` repairs. `finalize_turn` was refused for
"Unresolved failed tool attempts remain" **17 times in 17 of 42 runs** (6 / 4 / 7 by day), each at a
median context of 188k tokens (24 refused-finalize rounds in all). Of the 188 successful
`search_evidence` calls, **71 (38%) returned zero matches**.

### 3.3 Refused listings, reads and writes


**T3.4 — Listing / read / write refusals by message class**

| Tool | Message class | Count |
|---|---|---|
| grep | Use search_evidence with the readable source path and a literal query. | 111 |
| ls | Error: Open /research/<path> or /evidence/<path> | 40 |
| glob | Error: Open /research/<path> or /evidence/<path> | 11 |
| grep | permission_denied: workspace tree contains an unsafe entry | 4 |
| read_file | Error: Line offset N exceeds file length (N lines) | 3 |
| read_file | Error: Source name does not match; copy its exact path from /evidence/<path> | 3 |
| read_file | Error: Research view unavailable; inspect scope or request a new authorized task | 3 |
| edit_file | conflict: revision_conflict: audience/icp-us-employer-core-new-logo.md is at ver | 1 |
| write_file | conflict: workspace file already exists | 1 |


### 3.4 Media: zero transcripts in 42 runs


**T3.5 — Media: every discover_media / read_media attempt**

| Day | Op | Attempts | Outcome classes | Providers reached | Mean s |
|---|---|---|---|---|---|
| 2026-10-03 | discover_media | 6 | {'candidates=5(truncated)': 4, 'candidates=1': 2} | {'exa.search': 4, '—': 2} | 123 |
| 2026-10-04 | discover_media | 11 | {'candidates=5(truncated)': 1, 'candidates=1': 4, 'candidates=2': 2, 'candidates=6(truncated)': 3, 'candidates=3': 1} | {'exa.search': 4, '—': 7} | 21 |
| 2026-10-04 | read_media | 14 | {'unavailable': 7, 'no child I/O': 1, 'error:tool_error:FileNotFoundError': 6} | {'public_media.GET': 10, '—': 4} | 17 |
| 2026-10-06 | discover_media | 9 | {'candidates=5(truncated)': 3, 'candidates=4': 1, 'candidates=1': 4, 'candidates=6(truncated)': 1} | {'exa.search': 4, '—': 5} | 26 |
| 2026-10-06 | read_media | 7 | {'unavailable': 4, 'error:tool_error:FileNotFoundError': 2, 'no child I/O': 1} | {'public_media.GET': 6, '—': 1} | 56 |

read_media detail classes: (none): 13; [Errno 2] No such file or directory: 'ffprobe': 8

discover_media candidate recording statuses: candidate_not_yet_attempted: 14; candidate_not_yet_attemptedx4: 8; candidate_not_yet_attemptedx5: 4

fetch_page calls on recording/podcast hosts: 0 — {}; ffprobe errors in any observation: 0


26 `discover_media` calls in 25 runs (7 accounts, 18 people) returned 1–6 candidates each, every
candidate `candidate_not_yet_attempted`. 21 `read_media` attempts (14 on 10-04, 7 on 10-06, none on
10-03 where v24 only discovered): **11 `state: unavailable`** (gaps `no_exact_episode_match` 6,
`no_supported_recording_link` 2, both 2, `no_exact_episode_match + youtube_public_access_unverified`
1), **8 `tool_error:FileNotFoundError: [Errno 2] No such file or directory: 'ffprobe'`** (6 on 10-04,
2 on 10-06; e.g. `33d5b4810254`, `496af486b7e5`, `3263c80c2517`), 2 `invalid_acquisition_arguments`.
Transcripts obtained: **0**. The ffprobe failure is not an ERROR-level observation anywhere: the
agent-level receipt reads `status: completed` at the top level with `reference_values.status:
refused` and `error_code: tool_error:FileNotFoundError` (or `provider_refusal`), and the reason
(`gaps`, `detail`) is only in the result file the agent must then read. `public_media.GET` reached a
publisher for 16 of the 21 reads; the discover step reached Exa for 12 of 26 (the rest were
`known_urls` lookups). No `fetch_page` in the corpus targeted a recording host (youtube / spotify /
apple podcasts / podbean / buzzsprout / libsyn / simplecast / vimeo / soundcloud / castro /
podcetera / listennotes); the plan's "17 media page fetches" must be publisher pages and is not
reproducible by host.

### 3.5 Page writer: in-run spans, repairs, failures, rewrites


**T3.6 — Page writer (recipe 25): in-run spans and rewrites**

| Day | In-run spans | 1 call | 2 calls (repair) | Failed | Mean s | Max s | $ | Output tok/s | Rewrite traces | Rewrite failed | Rewrite $ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-04 | 18 | 16 | 2 | 0 | 223 | 318 | 2.52 | 68 | 7 | 2 | 1.40 |
| 2026-10-06 | 12 | 10 | 2 | 1 | 212 | 342 | 1.52 | 70 | 6 | 0 | 1.09 |


30 in-run page-writer spans on v25: 26 wrote in one call, 4 needed the one repair call, **1 failed**
— the Dialpad account, `efc87b75f3e5` / `757fb0ea6482f9a0`, 17:40:07–17:45:49, 342 s, $0.20,
`PageWriterError: insights/buying-signals: quote not in cited findings` — after which the account's
six rewrites in the 17:56–18:07 window all succeeded. Two of the 13 rewrites failed, both in the W2
window: `8982499dea0a` (00:02:32, 376 s, writer returned `['insights']` instead of both pages) and
`a1cd2b11ad99` (00:08:11, 339 s, two quotes not in cited findings). The in-run writer runs at 68–70
output tokens/s, 212–223 s mean, 318–342 s max, and adds 16–19% of run wall time (T2.3).

### 3.6 Finalize refusals, workspace conflicts, needs_review

- 10-03 (v24, before PR #91/#94): 6 runs — the McKee account (`df90b7ebcd28` root `8486376a`),
  Jean McGrory, Athena Burkholder, Chris McKee, Kyler Vann, Andy Lang — had `finalize_turn` refused
  for unresolved `search_evidence` failures, repaired as told, and then had the repaired finalize
  refused with `snapshotted outputs are immutable` (observation e.g. `ca75ce49f9dd` /
  `5744eb797efe1513`). Their dossiers were imported before the refusal (`arv2.dossier.import` spans
  present), so the research survived; the jobs ended `needs_review / workspace_conflict`
  (`_memory/2026-10-03-production-research-slowness.md`, fixed by PR #91 T8). Mortenson's account
  run had one further refusal, `invalid unprocessed_source_ids` (`9030c2d0c0a10310`), then finalized.
- 10-04 / 10-06: 11 refusals for unresolved failures, all repaired within 1–3 rounds; every run then
  finalized `completed`. One v24 reconciliation finalize refused `Non-gap sentences require supplied
  evidence` (`783858acd71f` / `3db5308f3ef58e5d`) and was repaired.
- Runs that must read `needs_review` in the database unless the rewrite path cleared them: the 6
  10-03 workspace conflicts, the Dialpad account (page writer failed; the driver settles a failed
  write as `needs_review`), and whichever W2 account(s) own the two failed rewrites (§7).

### 3.7 Stranded or suspended jobs

None visible in the corpus: no lease, suspend or takeover observation exists in any trace, no run has
an idle interval above 2 s, and the only start delays are the two 10-03 claim-without-capacity cases
(87 and 91 min between fleet-task claim and agent start). The 10-03 person runs' 80–100 min elapsed
is tool time (54–68 min of evidence calls at 187 s each) plus the 10.5 s per-round admission delay,
not suspension. 9 `agent.long_turn` events were emitted, all on 10-03.

### 3.8 Provider and evidence-tool errors


**T3.8 — Provider / model-call errors and stalls**

| Day | Observation | Trace | Message class |
|---|---|---|---|
| 2026-10-03 | GET (`4e950b3bde20d353`) | `b1c657522cce` |  |
| 2026-10-03 | exa_websets.get (`e96f6fe9b768c740`) | `b1c657522cce` | client_error |
| 2026-10-03 | GET (`f9fecae47af3e461`) | `b1c657522cce` |  |
| 2026-10-03 | exa_websets.get (`5644304e3970925d`) | `b1c657522cce` | client_error |
| 2026-10-04 | GovernedAgentChatModel (`ff35f3a68ae2ede7`) | `812ace9fded6` | No streaming chunk received for N.Ns (model=x-ai/grok-N.N, chunks_received=N). The connection may be alive at the TCP la |
| 2026-10-04 | model (`9d5db2d8077dc31c`) | `812ace9fded6` | No streaming chunk received for N.Ns (model=x-ai/grok-N.N, chunks_received=N). The connection may be alive at the TCP la |
| 2026-10-04 | clue-head_of_abm (`3b2c13fd503b991d`) | `812ace9fded6` | No streaming chunk received for N.Ns (model=x-ai/grok-N.N, chunks_received=N). The connection may be alive at the TCP la |
| 2026-10-03 | POST (`5efb6fd0e841fe7a`) | `db37e5110b8d` |  |
| 2026-10-06 | exa_websets.get (`855d4d502de2dfe6`) | `cb3bd32d32a8` | client_error |
| 2026-10-06 | exa_websets.get (`22a4b9b70b70a8f5`) | `cb3bd32d32a8` | client_error |
| 2026-10-06 | exa_websets.get (`a27bb35d7a785f04`) | `cb3bd32d32a8` | client_error |
| 2026-10-04 | exa_websets.get (`167be481b4f0cc62`) | `a9c8a6694aad` | client_error |
| 2026-10-03 | POST (`342b43c9ecafe042`) | `904431b689f5` |  |
| 2026-10-05 | open_design_leg (`691c69824edada8c`) | `791b00d772a6` | N validation errors for OpenDesignLegInputAgentRuntime |


Inside research runs: two AI Ark `people/export/single` HTTP attempts errored on 10-03 (16 s and
31 s; `db37e5110b8d` 17:50:30, `904431b689f5` 16:45:31) and their `lookup_person` calls failed; no
HTTP 429 and no 5xx was recorded as an ERROR observation in any research run on any day. The one
model stall (`812ace9fded6`, 10-04 08:10, "No streaming chunk received for 300.0s", $0) is a chat
turn. Evidence-tool receipts carrying an `error_code` (54 in all; refused rounds cost $2.16 over 30
rounds):

| Error code | Operation | 10-03 | 10-04 | 10-06 | Runs affected |
|---|---|---|---|---|---|
| `invalid_acquisition_arguments` | search_web | 12 | 10 | 0 | 6 |
| `invalid_acquisition_arguments` | research_deep | 5 (all Mortenson account, before its one accepted deep call) | 0 | 0 | 1 |
| `invalid_acquisition_arguments` | read_media | 0 | 1 | 1 | 2 |
| `provider_refusal` (read_media unavailable) | read_media | 0 | 7 | 4 | 8 |
| `tool_error:FileNotFoundError` (ffprobe) | read_media | 0 | 6 | 2 | 6 |
| `subject_lock_failed` | lookup_person | 0 | 4 (nyc.gov people 14:17–14:22 ×3, FirstFleet 23:51, up to 75 s) | 0 | 4 |
| `tool_error:DBAPIError` | search_web | 0 | 2 (23:44:15 `496af486b7e5`, 23:52:56 `1b3a6f71f709`) | 0 | 2 |

The last two classes are not in the plan's list: four AI Ark person lookups refused by a subject
lock, and two web searches that failed inside the database write (`DBAPIError`) during the 12-job
10-04 batch.

### 3.9 Rounds that produced nothing


**T3.7 — Wasted rounds (round = one model call + the tools it issued)**

| Day | Rounds | Productive | Read-only | Some tool errored | Every tool errored | finalize_turn only | Listing only |
|---|---|---|---|---|---|---|---|
| 2026-10-03 | 616 | 343 ($33.39, 757 min) | 191 ($15.64, 96 min) | 43 ($2.87, 36 min) | 30 ($3.91, 20 min) | 6 ($0.83, 2 min) | 3 ($0.24, 1 min) |
| 2026-10-04 | 736 | 399 ($30.90, 232 min) | 230 ($14.20, 27 min) | 60 ($3.50, 17 min) | 27 ($2.27, 5 min) | 18 ($2.11, 2 min) | 2 ($0.16, 0 min) |
| 2026-10-06 | 604 | 316 ($26.38, 193 min) | 190 ($13.03, 23 min) | 56 ($3.85, 11 min) | 26 ($2.63, 3 min) | 12 ($1.62, 1 min) | 4 ($0.37, 0 min) |
| all | 1956 | 1058 ($90.67, 1181 min) | 611 ($42.87, 146 min) | 159 ($10.23, 64 min) | 83 ($8.81, 29 min) | 36 ($4.56, 5 min) | 9 ($0.77, 1 min) |


Across the corpus: 83 rounds in which every tool errored ($8.81, 29 min), 159 with at least one
error ($10.23, 64 min), 36 finalize-only ($4.56), 9 listing-only ($0.77): **$24.4 of $157.9 (15%)
and ~100 min** of run time. Separately, **611 of 1,956 rounds (31%) issue nothing but `read_file`**
— paging through saved results, evidence and skills — and cost $42.87 (27%).

---

## 4. What the agent does


**T4.1 — Operation mix per run type (mean per run; all runs)**

| Kind | n | search_web | fetch_page | research_deep | lookup_person | enrich_contact | discover_people | lookup_company | read_people_result | discover_media | read_media | read_ats_board | refused | read_file | save_dossier_section | update_dossier_findings | search_evidence | ls/glob/grep | write_file/todos | nominate | validate | finish | finalize |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| account | 7 | 11.3 | 9.0 | 1.7 | 0.0 | 0.0 | 2.1 | 1.0 | 0.9 | 1.0 | 0.4 | 0.3 | 0.0 | 87.9 | 12.9 | 3.0 | 5.0 | 11.4 | 7.1 | 5.0 | 1.0 | 1.0 | 1.4 |
| person | 35 | 8.1 | 3.8 | 1.0 | 0.9 | 1.0 | 0.0 | 0.0 | 0.0 | 0.5 | 0.5 | 0.0 | 0.0 | 72.4 | 10.1 | 1.2 | 5.1 | 9.7 | 6.8 | 0.0 | 1.0 | 1.0 | 1.4 |


Per run an account issues ~28 evidence calls (11 searches, 9 fetches, 2 people discoveries, 1–2 deep
reports, 1 company lookup, 1 media discovery) and a person ~16 (8 searches, 4 fetches, 1 enrichment,
1 person lookup, 1 deep report, 0.5 media discover + 0.5 read); both then make 72–88 `read_file`
calls, 10–13 section saves, ~5 `search_evidence`, ~10 listings. The first evidence round of a run
issues a median of 5 calls (3–7).


**T4.2 — Evidence created vs read (runs with I/O)**

| Day | Runs | Source records available (validate_dossier) | Distinct /evidence files read | Read share | Referenced by findings | Referenced share |
|---|---|---|---|---|---|---|
| 2026-10-03 | 12 | 6088 | 289 | 5% | 254 | 4% |
| 2026-10-04 | 18 | 7504 | 384 | 5% | 390 | 5% |
| 2026-10-06 | 12 | 6447 | 288 | 4% | 281 | 4% |
| all | 42 | 20039 | 961 | 5% | 925 | 5% |

read_file by category over runs with I/O: saved result (/research/operations): 1185 calls ≈1626k tokens; evidence (/evidence): 1126 calls ≈1012k tokens; skill: 361 calls ≈623k tokens; context/dossier/reads/other: 343 calls ≈461k tokens; capabilities: 135 calls ≈185k tokens


20,039 source records were indexed for the 42 runs (median 327 per account run, 506 per person run);
the agent opened **961 distinct `/evidence/` files (4.8%)** and its findings referenced 925 (4.6%).
`validate_dossier` itself notes that "unreferenced does not mean unread or omitted facts"; the read
figure is the agent's own `read_file` calls, so ~95% of what was indexed was never opened.


**T4.3 — Deep-report consumption (read_file windows on the research_deep operation's result file)**

| Kind | Runs with a deep report | Deep calls per run | Windows read per run (min/med/max) | Chars read per run (min/med/max) | Runs reading 0 windows |
|---|---|---|---|---|---|
| account | 7 | 1 / 1 / 6 | 4 / 7 / 8 | 29727 / 43348 / 51679 | 0 |
| person | 35 | 1 / 1 / 1 | 3 / 7 / 11 | 22277 / 43506 / 76811 | 0 |


Every run reads its deep report through its `/research/operations/<op>/0.json` result file in
3–11 windows (median 7), 22–77k characters per run (median 43.5k) — the Exa deep report takes 39–53 s
of provider time and is the single most re-sent block of text in every run. The Mortenson account run
spent five refused `research_deep` calls (`invalid_acquisition_arguments`) before its one accepted one.


**T4.4 — Queries: volume, duplicates, follow-ups (runs with I/O)**

| Day | Runs | search_web | per run (med) | Exact repeats within a run | Same query in >1 run (cross-job) | fetch_page | Unique URLs | URLs fetched in >1 run | First-round queries | Later queries reusing an earlier query's term | Later queries with only new terms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-03 | 12 | 114 | 8 | 4 | 0 | 61 | 57 | 4 | 48 | 53 | 13 |
| 2026-10-04 | 18 | 146 | 8 | 8 | 0 | 74 | 70 | 3 | 82 | 53 | 11 |
| 2026-10-06 | 12 | 104 | 8 | 0 | 0 | 61 | 58 | 2 | 52 | 36 | 16 |
| all | 42 | 364 | 8 | 12 | 0 | 196 | 185 | 9 | 182 | 142 | 40 |


364 `search_web` queries (22 of them refused for invalid arguments), median 8 per run; 12 exact
repeats inside a run (4 on 10-03, 8 on 10-04, 0 on 10-06); **0 identical queries across runs**; 196
page fetches of 185 distinct URLs, 9 URLs fetched in more than one run of the same launch. Follow-up
heuristic (Lane L2 does the real chain mining from `sequences/`): 182 queries (50%) are issued in the
run's first evidence round; of the later 182, **142 (78%) reuse a distinctive term from an earlier
query of the same run** and 40 introduce only new terms. Every one of the 42 ordered operation
sequences is in `.artifacts/arv2-research-runs-20261007/sequences/<traceId>.json` (round, start,
tool, operation, argument summary, `purpose` where the agent supplied one — only `discover_media`
inputs carry one — providers, provider seconds, result path, receipt status, error code).

---

## 5. Quality signals visible in the logs


**T5.3 — Distribution of findings per run**

| Day | Kind | n | Findings min/med/max | Sections | Sources available | Referenced | Referenced share (med) |
|---|---|---|---|---|---|---|---|
| 2026-10-03 | account | 2 | 60 / 64 / 67 | 11 / 11 / 11 | 327 / 336 / 344 | 32 / 34 / 37 | 10% |
| 2026-10-03 | person | 10 | 23 / 34 / 54 | 5 / 8 / 9 | 495 / 538 / 601 | 9 / 18 / 26 | 3% |
| 2026-10-04 | account | 3 | 63 / 67 / 77 | 11 / 11 / 11 | 218 / 262 / 264 | 25 / 33 / 33 | 13% |
| 2026-10-04 | person | 15 | 14 / 35 / 59 | 6 / 8 / 10 | 375 / 462 / 514 | 15 / 19 / 35 | 4% |
| 2026-10-06 | account | 2 | 45 / 51 / 57 | 10 / 11 / 12 | 342 / 360 / 377 | 19 / 26 / 33 | 7% |
| 2026-10-06 | person | 10 | 35 / 44 / 56 | 6 / 8 / 10 | 497 / 580 / 647 | 15 / 22 / 32 | 4% |
| all | account | 7 | 45 / 63 / 77 | 10 / 11 / 12 | 218 / 327 / 377 | 19 / 33 / 37 | 10% |
| all | person | 35 | 14 / 36 / 59 | 5 / 8 / 10 | 375 / 506 / 647 | 9 / 19 / 35 | 4% |

**T5.1 — Quality signals per run (runs with I/O): findings, sections, sources, outcome**

| Day | Run | Findings (validate) | Sections | Sources available | Referenced | Finalize status | Failed saves | Nominations | Final message mentions gaps |
|---|---|---|---|---|---|---|---|---|---|
| 10-03 | mckeefoods.com (account) | 60 | 11 | 327 | 32 | refused only | 1 | 5 | no |
| 10-03 | mortenson.com (account) | 67 | 11 | 344 | 37 | completed | 1 | 5 | no |
| 10-03 | Robin Ritter, Chief Human Resources Officer — mortenson.com | 47 | 9 | 564 | 26 | completed | 3 | 0 | no |
| 10-03 | Patrick Locken, Chief Financial Officer, Mortenson Construction — mortenson.com | 32 | 7 | 601 | 9 | completed | 1 | 0 | no |
| 10-03 | John Bachhuber, Vice President Total Rewards — mortenson.com | 35 | 6 | 521 | 18 | completed | 3 | 0 | no |
| 10-03 | Jean McGrory, Director, Total Rewards — mortenson.com | 46 | 8 | 540 | 17 | refused only | 3 | 0 | no |
| 10-03 | Athena Burkholder, Senior Manager — mortenson.com | 27 | 8 | 535 | 18 | refused only | 2 | 0 | no |
| 10-03 | Chris McKee, President and COO — mckeefoods.com | 54 | 8 | 495 | 23 | refused only | 5 | 0 | no |
| 10-03 | Kyler Vann, Comp and Benefits Analyst — mckeefoods.com | 25 | 9 | 497 | 11 | refused only | 2 | 0 | no |
| 10-03 | Andy Lang, Chief Financial Officer — mckeefoods.com | 34 | 8 | 580 | 25 | refused only | 1 | 0 | no |
| 10-03 | Don Gladden, Vice President — mckeefoods.com | 38 | 8 | 506 | 19 | completed | 1 | 0 | no |
| 10-03 | Cindy Lyons, Corporate Health & Wellness Manager — mckeefoods.com | 23 | 5 | 578 | 19 | completed | 1 | 0 | no |
| 10-04 | nyc.gov (account) | 63 | 11 | 264 | 25 | completed | 2 | 5 | no |
| 10-04 | Renee Campion, Commissioner — nyc.gov | 43 | 9 | 462 | 19 | completed | 2 | 0 | no |
| 10-04 | Beth Kushner — nyc.gov | 27 | 6 | 488 | 16 | completed | 1 | 0 | no |
| 10-04 | Sang Hong, Director — nyc.gov | 14 | 6 | 514 | 16 | completed | 1 | 0 | no |
| 10-04 | Claire Levitt, Deputy Commissioner, Health Strategy — nyc.gov | 49 | 10 | 463 | 21 | completed | 1 | 0 | no |
| 10-04 | Octavia McCormick-Sharf, Associate Commissioner, Human Resources and Staff Development — nyc.gov | 20 | 7 | 480 | 19 | completed | 1 | 0 | no |
| 10-04 | firstfleetinc.com (account) | 77 | 11 | 218 | 33 | completed | 2 | 5 | no |
| 10-04 | jrayl.com (account) | 67 | 11 | 262 | 33 | completed | 3 | 5 | no |
| 10-04 | Robb Getts, Executive Vice President — firstfleetinc.com | 41 | 8 | 427 | 35 | completed | 1 | 0 | no |
| 10-04 | Bronson Laney, Director — firstfleetinc.com | 25 | 10 | 414 | 15 | completed | 1 | 0 | no |
| 10-04 | Austin Henderson — firstfleetinc.com | 59 | 9 | 375 | 24 | completed | 2 | 0 | no |
| 10-04 | Rebecca Wilson, Vice President Corporate Operations — firstfleetinc.com | 30 | 6 | 386 | 22 | completed | 1 | 0 | no |
| 10-04 | John Cole, Safety Director — firstfleetinc.com | 35 | 8 | 426 | 25 | completed | 1 | 0 | no |
| 10-04 | Ryan Richards, CEO — jrayl.com | 42 | 10 | 484 | 15 | completed | 1 | 0 | no |
| 10-04 | Matthew Parks, Vice President — jrayl.com | 35 | 8 | 430 | 16 | completed | 1 | 0 | no |
| 10-04 | Toni Roberts, Safety Director — jrayl.com | 36 | 7 | 474 | 17 | completed | 4 | 0 | no |
| 10-04 | Gene Shippy, Director — jrayl.com | 30 | 6 | 507 | 17 | completed | 3 | 0 | no |
| 10-04 | Justin Yoder, CPA, CFO — jrayl.com | 36 | 7 | 430 | 22 | completed | 3 | 0 | no |
| 10-06 | loopio.com (account) | 45 | 10 | 342 | 19 | completed | 2 | 5 | no |
| 10-06 | dialpad.com (account) | 57 | 12 | 377 | 33 | completed | 1 | 5 | no |
| 10-06 | Siobhan Mondesire, VP — loopio.com | 54 | 8 | 529 | 29 | completed | 2 | 0 | no |
| 10-06 | Michelle Oke, Vice President, Sales — loopio.com | 42 | 7 | 505 | 27 | completed | 3 | 0 | no |
| 10-06 | Alex Pace, Senior Revenue Operations Specialist (Sales Operations Focus) — loopio.com | 36 | 7 | 539 | 15 | completed | 1 | 0 | no |
| 10-06 | Vincent Lo, Senior Director, Product Marketing — loopio.com | 53 | 10 | 647 | 22 | completed | 3 | 0 | no |
| 10-06 | Alison Hayter, Senior Director, Marketing — loopio.com | 44 | 6 | 497 | 21 | completed | 2 | 0 | no |
| 10-06 | Jenny Coupe, Head — dialpad.com | 56 | 9 | 568 | 19 | completed | 1 | 0 | no |
| 10-06 | Andrew Flynn, SVP Marketing and Vertical Solutions — dialpad.com | 51 | 10 | 605 | 25 | completed | 1 | 0 | no |
| 10-06 | Sarah Rolfing, Sr. Director, Demand Generation — dialpad.com | 35 | 9 | 593 | 32 | completed | 1 | 0 | no |
| 10-06 | Meaghan Edelstein — dialpad.com | 45 | 7 | 621 | 21 | completed | 6 | 0 | no |
| 10-06 | Emily Wall, Field Programs & ABM Manager — dialpad.com | 36 | 8 | 624 | 18 | completed | 4 | 0 | no |

**T5.2 — Findings as saved (successful save_dossier_section calls, runs with I/O): review status and claim type**

Findings saved: 1701 over 362 saves (median 5 per save). Review status: supported 1402 (82%), insufficient_context 116 (7%), wrong_entity 99 (6%), potential_conflict 84 (5%). Claim type: reported_statement 868, observation 833.

Account sections (saves): People and organizational responsibilities 8; Business and operating model 7; Ownership, financing and resources 7; Workflows and operating demands 7; Hiring and organizational change 7; Contrary evidence and business risks 7; Unexpected findings 7; Public professional voice and working culture 6; Timing and meaningful developments 6; Strategy and active initiatives 6; Tools, vendors and execution 4; Tools, vendors and execution approaches 3; Strategy and initiatives 1; Public professional voice 1; Fit and committee discussion 1

Person sections: 150 distinct section names over 284 saves in 35 runs; 10 names recur in 5 or more runs. The ten most used: Education and background 18; Voice and working methods 18; Career history 17; Present responsibilities 11; Distinctive findings 10; Recent activity 10; Career and transitions 8; Identity and present role 7; Namesakes encountered 7; Interests and public personal life 6. (Account sections: 15 distinct names.)


Other signals: all 43 `validate_dossier` calls returned without issues; all accepted
`finalize_turn` calls used `status=completed` (36 runs; the 6 10-03 conflicts never got one); the
final message mentions gaps explicitly in 2 of 36; the finalize message's own finding count matched
`validate_dossier` wherever both were present (e.g. 32/32, 36/36, 57/57). **34 of the 41 runs with
saved sections include a namesake / identity / same-name section**; person dossiers use 150 distinct
section names across 35 runs (only 10 recur in five or more runs) against 15 for accounts.
`wrong_entity` is the recorded review status of 99 findings (6%) and `potential_conflict` of 84 (5%).

### 5.1 The September evaluation versus production

The 09-28 Zafran run on Grok 4.6 medium (`.artifacts/research-model-evaluation-20260928/grok46-model-calls.csv`,
isolated database, local workers with ffmpeg): account 61 calls, 19.6k → 199k context, $4.28,
13.4 s per call; the two people 80 calls / $4.69 (18k → 217k) and 44 calls / $3.13. Production 10-06:
accounts 56–59 calls, $3.90–5.00, final context 186–203k, 11.5 s per call; people 39–59 calls,
$3.21–4.80 — the same machine at the same cost. Failure modes (`FAILURES-ZAFRAN.md`): **Z15**
(missing `review` objects on saves) is exactly production's 82 schema refusals in 42/42 runs; **Z06**
(person completion files citing account-owned references) does not recur — production's finalize
refusals are all the unresolved-failure class; **Z16** — Grok reached an actual ISMG interview
transcript in September — did not recur in production, where 0 of 21 recording reads produced a
transcript (8 died on the missing `ffprobe`); **Z11/Z13** (narrative tool argument errors) did not
recur on v24 (15/15 `write_research_narrative` calls accepted) and are moot on v25. The evaluation's
quality verdicts (bundled claims, interpretation leaking into factual records, namesake notes stored
as findings, length) cannot be re-measured from Langfuse — they need the dossier bodies in the
database — but the 150 free-text person section names and 34/41 namesake sections are the same
shape in the logs.

---

## 6. The plan's 26 issues against the whole corpus

C = confirmed, E = extended (confirmed with a materially different or larger number), R = refuted or
not supported, N = not testable from Langfuse.

| # | Issue (plan §0) | Verdict | Corpus evidence |
|---|---|---|---|
| 1 | No forgetting; 17k → 200k; re-sending is 80% | **C** | 0 shrinks in 1,956 calls; start 16–19k, final 149–235k; cached share 73% / 79% / 80% by day, 77% overall (T2.4). |
| 2 | Dossier written inside the full context; 36% of calls, 46% of cost | **C** | 667/1,956 calls (34%), $73.85 (47%) from the first section save on. |
| 3 | Reading is two hops and inflated | **C/E** | 1,185 reads of saved results (≈1.63 M tokens, ≈$30.1, 19%) + 1,126 evidence reads (≈1.01 M, $18.7); 611 rounds (31%, $42.9) do nothing but `read_file`. Inflation ratio not re-measured (file bodies not kept). |
| 4 | Deep report read in 4–11 windows | **C** | 42/42 runs: 3–11 windows (median 7), 22–77k chars (median 43.5k); accounts 4–8. |
| 5 | Opening prompt sent twice (~4k) | **N** | Starting context 16–19k on every run is consistent; the duplication itself is a code fact not visible in Langfuse. |
| 6 | 27 failed saves; every run ≥1; `review` object | **E** | **82** failed saves in **42/42** runs (max 6 per run); 80 `findings[i].review` Field required + 2 value errors; $7.34 / 34 min in the failing rounds alone. |
| 7 | grep → search_evidence → finalize trap; 7/12 runs | **E** | 111 refused greps in 42/42 runs; 27 failed `search_evidence` (18 on `/research/operations`); 26 `retry_of` repairs; finalize refused in **17/42** runs (6/4/7), at median 188k context; on 10-03 all 6 then died on the snapshot bug. 71/188 successful searches returned 0 matches. |
| 8 | 60 refused listings and searches | **C** | `ls` 40, `glob` 11, unsafe-tree `grep` 4, `read_file` 9 (+111 trap greps) across the corpus; 10-06 alone: 22 listings + 38 greps. |
| 9 | ~$8 of $48 (17%) and ~25 min wasted | **C** | 10-06: all-error 26 ($2.63), some-error 56 ($3.85), finalize-only 12 ($1.62), listing-only 4 ($0.37) = $8.47 (18%); corpus: $24.4 (15%), ~100 min. |
| 10 | Zero transcripts; ffprobe missing; resolver gaps | **E** | 0 transcripts in 21 reads over 42 runs; 8 `ffprobe` FileNotFoundError (10-04 and 10-06), 11 `unavailable` with the exact gap codes, 2 bad arguments; 26 discoveries all `candidate_not_yet_attempted`. |
| 11 | Receipt says completed when the read failed | **C (precisely)** | Top-level `status: completed`; the refusal is in `reference_values.status: refused` + `error_code` on the receipt itself; the reason (`gaps`/`detail`) only in the result file. Never an ERROR-level observation. |
| 12 | Skills demand media anyway | **C** | 25 of 42 runs attempted `discover_media` (7/7 accounts, 18/35 people); every account skill set unchanged v24→v25. |
| 13 | ~58 s per evidence call, provider ~2 s | **E** | 10-06: 58 s mean (provider 4.2 s incl. deep reports); 10-04: 45 s; **10-03: 187 s**. Providers = 4.4% of evidence-tool time over the corpus. |
| 14 | One worker lock serialises jobs | **C/E** | 10-03 admission wait 67 s and 10.5 s per-round tool-start delay; after PR #91 admission 3 s and 0.6 s — but 42–46 s after-provider indexing remains on 10-04 and 10-06. |
| 15 | ~25 sources per search; ~90% never read | **E** | 20,039 records for 42 runs (median 327 per account, 506 per person, ≈ 30 per evidence call); **4.8% opened, 4.6% referenced**. |
| 16 | Four slots held through indexing; positions 5–6+ wait 43 / 76 s | **C (smaller)** | 10-06: positions 1–4 wait 17–21 s, 5 → 26 s, 6+ → 49 s (n=10); 10-04: 14–18 s then 26 s. |
| 17 | `recover_acquisitions` on every call | **N** | No span; only the after-provider wait (45 s) is visible. |
| 18 | People wait ~8 min for an import they barely use | **C** | Nomination → first person 6.7–9.4 min on v25 (17.5 / 29.1 on 10-03); first person starts ≤ 1 min after the import span; parent dossier opened 16 times across 35 people. |
| 19 | Committee chosen at minute 15 | **C** | First nomination at +8.7, +10.7, +11.7, +14.8, +15.0 min (v25) and +22.2, +23.3 (v24). |
| 20 | Each person is a full 40–60-round machine; ~80% of the bill | **C** | People: 30–68 rounds (median 44), $1.94–7.79 (median $3.21); 74–84% of each account's spend; 0 identical queries across runs, 9 URLs re-fetched. |
| 21 | Pages written three times; six rewrites back to back | **E** | 13 rewrites for 5 v25 accounts (3 / 4 / 6 per launch, one every ~2 min), 2 failed; plus 1 in-run writer failure (Dialpad) and 4 repair calls; v24 instead ran a 14-call $4.80 reconciliation agent and two failed attempts. |
| 22 | Launch chat turn took 4 min | **C (10-06 only)** | 4.0 min / $0.58 / 5 calls / 9 reads on 10-06; 2.0 min and 1.3 min on 10-04; 1.1 min on 10-03. |
| 23 | 12 slots fleet-wide | **C** | 10 people started within 103 s (10-04) and 48 s (10-06) alongside 2 accounts; on 10-03 two people waited 87–91 min after their task was claimed. |
| 24 | Coverage-first instructions → long, biographical dossiers | **C (shape)** | 150 free-text person section names; namesake/identity sections in 34/41 runs; findings 14–77 per run. Word-level filler share not measurable from logs. |
| 25 | Writer gets caveats, not conclusions | **N** | Writer inputs are not in Langfuse. |
| 26 | Miscellaneous dump; no person compliance pass | **N** | Page bodies and claim use-classes are in the database only. |

New since the 12-run audit: the 10-03 worker-wide queue (admission 67 s, +10.5 s per round, 2× model
latency) and its disappearance after PR #91; the unchanged 45 s indexing tail and the 10-06 ≈ 10-04
equality (PR #105 changed nothing visible); the Dialpad in-run page-writer failure and two failed
rewrites; `subject_lock_failed` and `DBAPIError` evidence refusals under the 12-job batch; the 6
10-03 jobs lost to the snapshot bug after a correct repair; 31% read-only rounds.

---

## 7. Open gaps that need the production database

Langfuse carries model spend, timings and tool I/O only. Someone with read access to the production
Postgres should run these (table and column names from `alembic/versions/65fb2128c904_…` and
`a3602967bb73_…`; `platform/projections/clue_projections/cost.py` and `clue_api/arv2/quality_meter.py`
use the same columns):

1. **Provider spend per run and per operation** (Exa, AI Ark, media) for the seven launches:
   `SELECT entity_research_job_id, provider, operation, count(*), sum(cost_usd), sum(credits),
   sum(media_seconds), count(*) FILTER (WHERE cost_usd IS NULL) AS unpriced, sum(latency_ms)/1000.0
   FROM provider_call_ledger WHERE phase='result' AND recorded_at BETWEEN '2026-10-03' AND '2026-10-07'
   GROUP BY 1,2,3 ORDER BY 1,5 DESC;` — joins to Langfuse through `entity_research_job_id` =
   the job id in the 10-03 trace attributes, and for 10-04/10-06 through `arv2_quality_execution`
   (`execution_id` = trace metadata `execution_id`).
2. **Job rows and outcomes:** `SELECT job_id, run_id, workspace_id, subject_type, status,
   failure_code, failure_message, attempt, started_at, finished_at, model_rounds, tool_calls, cost_usd,
   credits, media_seconds, profile_ref, input_refs->>'quality_recipe_version' FROM arv2_research_job
   WHERE created_at >= '2026-10-03' ORDER BY started_at;` — confirms the needs_review set in §3.6
   (the six 10-03 workspace conflicts, the Dialpad account after its writer failure, the W2
   account(s) behind the two failed rewrites) and the two 10-03 claim-without-capacity gaps
   (`started_at` vs the fleet task's claim).
3. **Which job each rewrite belongs to and whether a failed rewrite settled needs_review:** the
   `arv2_research_generation` / generation-settlement rows for the W2 project around 2026-10-05
   00:02–00:14 UTC and W3 around 2026-10-06 17:56–18:12, with `publish_page` rows (`display_block`
   revisions per page) to count the actual rewrites per account.
4. **Evidence volume and the 95%:** per job, `count(*)` of `arv2_evidence_manifest` / source rows
   versus the rows cited by imported claims, to confirm the `validate_dossier` figures (20,039 indexed,
   961 opened) and the storage cost of the unopened 95%.
5. **Model-call ledger cross-check:** `SELECT execution_id, count(*), sum(cost_usd), sum(input_tokens),
   sum(cache_read_input_tokens), sum(output_tokens), count(*) FILTER (WHERE status<>'completed')
   FROM agent_model_call WHERE started_at >= '2026-10-03' GROUP BY 1;` against `model-calls.csv`
   (1,956 calls, $157.91) — Langfuse recorded the model name on every call, but the memory notes say
   the first runs logged "unable to parse the LLM model", so the ledger's `answering_model` and
   `requested_model` should be checked for the model-fallback path (#96).
6. **Page bodies for the quality questions §6 cannot answer** (issues 24–26): `display_block`
   rows per account/contact page for the seven accounts (word counts, Miscellaneous item counts,
   caveat sentences, private-topic use-classes among imported claims), and the dossier artifacts
   (`finding` JSON) for filler/biography shares.
7. **Deepgram and ffmpeg on the worker image:** `provider_call_ledger WHERE provider LIKE 'deepgram%'`
   (expected 0 rows) and the worker container's `which ffprobe` — the 8 `FileNotFoundError` receipts
   say the binary is absent on the batch workers that ran 10-04 and 10-06.

---

Generated from `.artifacts/arv2-research-runs-20261007/` (`write_doc.py` over `tables.md`); the raw
Langfuse pull is reproducible with the puller scripts referenced in that folder's README.

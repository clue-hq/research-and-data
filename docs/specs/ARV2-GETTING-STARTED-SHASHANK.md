# Getting started — Shashank's setup, branch sync, and first week of work

**Companion to `ARV2-MASTER-PLAN.md` and `ARV2-WORK-SPLIT.md`. Version 1.0, 2026-09-04.** Follow
this top to bottom once; then §6 is the loop you repeat for every task. Commands are the repo's own
(`Makefile`, `DEV_STACK.md`, `scripts/dev_stack.sh`); if one disagrees with those files, the files win.

**Precondition (Aryan, step A1 of the work split):** the shared base is
**`origin/integration/design-improvement`** — it already carries R0, every ARV2 plan document and the
`.env.example` posture, and it absorbed the old `integration/design-improvement` line on 2026-09-07
(the two are identical at that point; the old name is retired as a base). Still to do before you
start: the empty `platform/api/clue_api/arv2/` skeleton is pushed; the Apollo and AI Ark keys are
rotated; the AI Ark paid tier is bought. Aryan keeps the base in sync and merges your task branches
into it. Aryan tells you when this is done. Nothing below works before it.

**Your coding agent's context comes from the branch itself:** once you have pulled, the agent reads
`docs/specs/ARV2-AGENT-BRIEFING.md` first (the repo's `CLAUDE.md` points every Claude Code session at
it), then the master plan and the work split, then your charter. You do not need to explain the
project to the agent; you paste the charter.

---

## 1. The repo and your branch (one-time)

Work in your Conductor workspace of the monorepo (the branch is `integration/design-improvement`).
In that workspace's terminal:

```bash
git status                       # must be clean; commit or stash anything pending first
git fetch origin
git checkout integration/design-improvement
git pull --ff-only origin integration/design-improvement
```

This gives you the shared base exactly as Aryan pushed it: the R0 foundations, the plan documents,
the agent briefing, the `arv2/` skeleton, and the `.env.example` with every flag. If `pull` refuses
because your local branch has commits Aryan's copy does not, run `git merge origin/integration/design-improvement`
instead; conflicts, if any, will be in `_memory/` or `.context/` files — keep **both** sides (they
are logs, not code) and commit. A conflict anywhere else: stop and send Aryan the file names.

Then confirm you have the plan:

```bash
ls docs/specs/ARV2-MASTER-PLAN.md docs/specs/ARV2-WORK-SPLIT.md docs/specs/ARV2-AGENT-BRIEFING.md docs/specs/ARV2-ROADMAP.md
ls platform/api/clue_api/arv2/
```

**Branch rules from here on:**
- `integration/design-improvement` is the shared base. **You never commit directly to it and never push to it** — Aryan merges into it.
- Every task runs on its own branch cut from the base: `task/<step>-<slug>` (e.g. `task/S5-ai-ark-client`).
- You push **task branches** (`git push -u origin task/<step>-<slug>`) and send Aryan the branch
  name; Aryan merges. (The "never push" rule in `CLAUDE.md` binds the coding agents, not you —
  agents commit; you push the task branch when its exit gate passes.)
- Every morning: `git fetch origin && git merge origin/integration/design-improvement` on your
  working branch, so you build on what Aryan merged yesterday.

## 2. The Python environment and the database

```bash
make install                     # creates .venv and installs everything (uv)
cp -n .env.example .env          # only if .env does not exist yet
```

Open `.env` and set the keys (never paste a key anywhere else — no charter, no artifact, no chat):
`CLUE_EXA_API_KEY`, `CLUE_AI_ARK_API_KEY`, `CLUE_GEMINI_API_KEY`, `CLUE_OPENROUTER_API_KEY`. Leave
every flag at the `.env.example` value — the example *is* the ruled posture (old lane off, memory
off, verification off, lenient writes on).

Database (needed for the db-gated tests; your leaf work rarely needs the full app):

```bash
make db-up                       # local Postgres (see Makefile / DEV_STACK.md for the DSN)
make migrate                     # alembic upgrade head
make db-smoke                    # up → down → up on a throwaway DB; must be green
```

Baseline check — run once so you know what "green" looks like on this base:

```bash
make check
```

Expect: format/lint/typecheck findings that are documented as pre-existing, and **11 known
pre-existing test failures** (listed in `_memory/2026-09-01-r0-step2-merge-complete.md`). Anything
beyond that list after one of your task branches is a regression your task introduced.

## 3. The two frontends

**The monorepo app (`apps/frontend`)** — only needed for D4 (the re-lift) and D5 (acceptance):
```bash
cd apps/frontend && npm ci && npm run design-system:build && cd ../..
./scripts/dev_stack.sh up        # the whole stack; open http://localhost:3020 (DEV_STACK.md has the login)
./scripts/dev_stack.sh status
./scripts/dev_stack.sh down
```
Read `DEV_STACK.md` once — it names the ports (3020 app, 8020 platform API, 8010 design API) and the
`.env` keys that break the stack when missing. Do not change ports.

**The dummy frontend (`clue-frontend`, your design truth)** — where S1 (D0-a) happens. Your
Conductor workspace `clue-frontend/live-backend-v1` on branch `integration/live-backend-v1` (truth
commit `84f8ee7`, 5 Sep) is it:
```bash
cd <your clue-frontend workspace> && git checkout integration/live-backend-v1 && git pull --ff-only
npm ci && npm run dev                            # fixture mode; open the printed localhost URL
npm run design-system:build && npm run lint && npm run build && npm test   # its gate (118 tests today)
```
The Zafran fixtures are parsed at import time from the vendored
`src/features/accounts/data/zafran/FRONTEND-SPEC-ZAFRAN.md`; the fidelity tests pin every
authored block to that markdown. Never edit the markdown to make a screen fit — change the
presentation, or raise a ruling.
It runs on fixtures with no backend. Later, setting `CLUE_API_BASE_URL` in its `.env` points its
repositories at the monorepo backend for a quick check — but the shipping path is always the re-lift
into `apps/frontend`, never the dummy talking to production.

## 4. Verify the setup (five checks, all must pass)

| # | Command | Expect |
|---|---|---|
| 1 | `git log --oneline -1 origin/integration/design-improvement` | a commit that mentions the ARV2 plan documents |
| 2 | `grep -c "CLUE_ARV2_ACCOUNT_RESEARCH_ENABLED=false" .env.example` | `1` |
| 3 | `make db-smoke` | green, single alembic head |
| 4 | `make check` | only the documented pre-existing findings |
| 5 | in `clue-frontend`: the gate command in §3 | green |

## 5. From your proof of concept to production — what becomes what

Your `.context` scripts are the reference every charter points at. The agents port their *laws*
into the production module shapes; nothing is copied as-is.

| Your PoC file(s) | Becomes | Who runs the charter |
|---|---|---|
| `z_lib.py` / `p_lib.py` (HTTP, ledger, save-raw, budget guard) | the shared base of every client in `platform/api/clue_api/arv2/` | you (S5) |
| `z1a`–`z1d` (AI Ark company, name-scoped people, email export + reparse) | `ai_ark_client.py` | you (S5) |
| `z2_free.py`, `z2b_ashby.py`, `z3_media_resolve.py` (RSS) | `ats_client.py`, `rss_client.py` | you (S5) |
| `z4a`–`z4e` (Gemini transcribe, loop detector, quote verify) | `gemini_client.py` (verify as annotation only) | you (S5) |
| `z5_exa_deep.py`, `p3_deep.py` (the charters + silent-fail guard) | `exa_client.py` + the dossier / contact-depth **skills** | you (S5, S7) |
| `z7_structure.py`, `p4_structure.py`, `p4b_unique.py` | `structuring_client.py` + the structuring prompts | you (S5) |
| `field_catalog.py` + the new keys from both runs | `catalog_seed.py` (data rows, every sub-field optional) | you (S3) |
| `p5b_redact.py`, `p5_tables.py` regexes | `compliance.py` (redact and mark, never drop) | you (S6) |
| `claims_zafran.json`, `claims_people.json` | the **claim loader** that writes them into the real store | Aryan (A3) |
| `frontend-page-content/README.md` §2–3 + the control test | the section recipes and Luna prompts | you (S4) |
| `FRONTEND-SPEC-ZAFRAN.md`, `ZAFRAN-PAGES.md`, `VARI-KAUR-CONTACT-PAGE.md` | the D5 acceptance answer key — the dummy already vendors the spec and parses it into fixtures (`data/zafran/spec-content.ts`); in production the backend's DisplayBlocks replace that parser | you (S9) |

## 6. The loop for every task

1. Pick the next step from `ARV2-WORK-SPLIT.md` §3. Write the charter using the template in its
   §6.0 (the first five are already written in §6.1–§6.5 — paste them).
2. Cut the branch: `git fetch origin && git checkout -b task/<step>-<slug> origin/integration/design-improvement`.
3. Start a Claude Code session in the workspace and paste the charter. The agent reads
   `docs/specs/ARV2-AGENT-BRIEFING.md` first (CLAUDE.md sends it there); the charter tells it which
   files it may touch and where to stop. Use Opus for implementation charters.
4. When the agent reports, **check the exit gate yourself** — run the command, open the screen, read
   the diff summary. Do not accept a report on its word.
5. If the agent stops with a QUESTION: answer it only if the answer is already in the master plan;
   otherwise add it to the weekly ruling list and pause that task.
6. Passed: `git push -u origin task/<step>-<slug>`, then send Aryan one message: the branch name,
   the agent's report, the exit-gate evidence. Failed: re-charter with the correction; never
   hand-patch.
7. Every run that spent money leaves its ledger and raw responses under `.context/<run>/` — commit
   those on the task branch too (they are evidence). Never a key.

## 7. Your first week, in order

| Day | Step | Needs from Aryan | Where |
|---|---|---|---|
| 1 | **S1 D0-a** — the remaining rulings applied to the dummy frontend (charter §6.1; the 5 Sep presentation stays) | nothing | `clue-frontend` |
| 1–2 | **S2 D0-b** — contract v1 into `apps/frontend/docs/api-contracts/accounts.md` (charter §6.2) | Aryan signs the doc | monorepo, task branch |
| 2 | **S3** — the catalog seed rows (every sub-field optional) | nothing | monorepo, task branch |
| 2–4 | **S5** — the six provider clients, one charter each (start with AI Ark, §6.3, then Exa, ATS, RSS/YouTube probe, Gemini, structuring) | the `arv2/` skeleton (in the base) + the keys | monorepo, one task branch per client |
| 4 | **S6** — the compliance pass (charter §6.4) | nothing | monorepo, task branch |
| 5 | **S7** — the research-agent content (dossier skill, contact-depth skill, audit skill, manual, prompts) | nothing | `platform/agents/catalog/entity-research/arv2-*/v1/` |
| when A4 lands | **S4** — recipes + section prompts into the display module (charter §6.5) | Aryan's D2 module | monorepo |
| when A4 + A5 land | **S8 D4** — the accounts re-lift into `apps/frontend` | D2 + D3 merged | monorepo |
| after S8 | **S9 D5** — the Zafran acceptance walk-through | — | `.context/d5-acceptance/` |

Everything on days 1–5 needs nothing from Aryan except reviews; you are never blocked in the first
week.

## 8. Do not

- Edit anything in `ARV2-WORK-SPLIT.md` §1.2 (migrations, `libs/`, wiring/composition files, the
  read layer, the claim store package) — hand it to Aryan as a one-line ask.
- Change an existing flag value in `.env.example`; only add a line for a flag your task introduces.
- Let an agent merge, push to the base, or "fix a bit more" outside its charter.
- Put a key, a customer's personal data, or a raw transcript into a commit message or a chat.
- Invent a UI component while wiring; if the design needs one, it is designed in the dummy first.

## 9. Where things are
Master plan: `docs/specs/ARV2-MASTER-PLAN.md` · Work split + charters: `docs/specs/ARV2-WORK-SPLIT.md` ·
Index: `docs/specs/ARV2-ROADMAP.md` · Dev stack: `DEV_STACK.md` · Answer keys: your `.context/` runs
(Probook, Zafran, the ten people, the three spec pages, the control test) · Contract doc:
`apps/frontend/docs/api-contracts/accounts.md` · Known test debt: `_memory/2026-09-01-r0-step2-merge-complete.md`.

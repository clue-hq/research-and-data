# 2026-06-19 — M2 + M3 integration (branch integration/m2-m3)

## Goal
Merge the two parallel worktrees — **M2 identity resolution** (`m2-identity-resolution`, bucharest
worktree) and **M3 ICP/packs/compiler** (`akeshri516/eng-109-…`, philadelphia, = M3.3+M3.1+M3.2
stacked) — onto one branch, before M4. Base = **origin/main (00a7392)** = the true common ancestor.
(Local `main` = d72e8ce "Initial commit" is an EMPTY UNRELATED root — do NOT use it.)

## Result: `integration/m2-m3`, merge commit 0adadfc (parents c79b56d M2 + 885dc6b M3)
Verified, committed locally (not pushed). M3.4 / M4 should branch off this.

## How it went (vs the analysis brief — all confirmed)
- **Git conflicts: NONE.** `git merge` auto-unioned the only two files both branches touched:
  `core/__init__.py` + `core/enums.py` (M2 adds ReuseScope/ContactEntity in different regions than
  M3's ICPStatus/ICPCreatedFrom/decode_jsonb). Every other file disjoint. M2 left ALL M3-owned files
  (registry.py, core/field.py, core/factories.py, core/handoff.py) byte-identical.
- **Only real blocker = alembic revision-id collision.** Renumbered M3's migrations:
  0005_pack_catalog→**0009**, 0006_icp_spec→**0010**, 0007_signal_class→**0011**; down_revisions
  chained onto M2's 0008. `git mv` + edited revision/down_revision + docstring headers + integration
  NOTE. **Single linear head 0011**: 0001..0004(M1) → 0005-0008(M2) → 0009-0011(M3).
- M2 deps came in (redis>=5, fakeredis, sortedcontainers); `uv sync`. M2 added a 6th import-linter
  contract ("claim store does not import identity/locks") + a `locks` package + redis docker service.

## Verification (fresh containers: pg `clue-integ` :5436, redis `clue-redis-integ` :6380)
- `alembic upgrade head` 0001→0011 clean; `make db-smoke` up→down→up clean (all downgrades reverse).
- `make check` GREEN: ruff, mypy --strict, **import-linter 6/6**, **364 passed + 13 skipped**; the
  13 skips were M2's redis lock tests — ran them with redis → **12 passed**. Total 376 tests, 0 fail.

## Cross-cutting findings (NOT blockers — follow-ups for M4+)
1. **Reuse-scope classification:** M2 added `reuse_scope`/`tenant_id` to the `claim` table (0008),
   defaulting `public_footprint`. **M3 writes NO claims** (packs author field_definition rows;
   icp_spec/field_plan are config; the compiler is pure), so nothing to fix now. BUT when M6/M8 write
   claims from ICP-derived/scoring/client-knowledge data, they MUST route through M2's
   `identity.classify_reuse_scope` (→ tenant_private) or those claims leak into the shared public base.
   The M3 `field_definition.signal_class`/namespace is a natural classifier input.
2. **Tenancy of M3 tables:** `icp_spec` is already client-scoped by its PK (client_id, icp_key,
   version); `source_profile_override` is per-client; `pack`/`source_profile` are shared platform
   config. Consistent with M2's "reuse boundary is a property of the data model." No change needed.
3. **Naming:** M2 uses `tenant_id` (claim table), M3 uses `client_id` (icp_spec) for the same concept
   — harmonize at leisure (cosmetic; not a blocker).

## M2 Redis caveats (backlog — also flagged in CLAUDE.md / AGENTS.md "Backlog / known caveats")
Surfaced from M2's review; recorded here at the user's request.
1. **Rate limiter requires Redis 7+ (version floor).** The token bucket reads the clock server-side
   via `redis.call('TIME')` to avoid cross-worker NTP skew. `TIME` is non-deterministic → a write
   after it is rejected on Redis ≤6 unless the Lua script calls `redis.replicate_commands()`. Redis 7
   (effects replication — what we compose/test) allows it, so tests pass. Correct for our stack but a
   hard floor. Fix ≈1 line (`redis.replicate_commands()` guard for 6-compat) or revert to client-time
   if we don't want to require 7. **Decision pending (user's call).**
2. **`multi_lock` can let an early lock expire while blocking on a later one.** Acquisition is
   deadlock-free (sorted order), but manually-acquired locks don't auto-renew (only `async with`
   does), so under heavy contention + short TTL, lock A can lapse while waiting on lock B. Mitigated
   today by deterministic order + a sane TTL; full fix = all-or-nothing acquire with retry. The one
   genuine soft spot in M2.

## Durable fix to avoid future collisions (recommended)
Stop the zero-padded sequential alembic ids. Use alembic default hash revision ids + `alembic merge`
for parallel branches, OR rebase-onto-head before merge. Removes the manual renumber.

## Throwaway containers still running (clean up when done): clue-integ (:5436), clue-redis-integ (:6380).
## Pre-existing per-branch containers: clue-postgres-m1 :5433, clue-postgres-m2 :5434,
## clue-postgres-eng104 :5435 (M3 work).

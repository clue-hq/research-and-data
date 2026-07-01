# 2026-06-29 — Source-profile serving consolidated into `icp` (single type)

## What changed
ICP-level source-profile serving no longer lives in `clue_research.sources`. **`ServedSourceProfile`
was removed entirely** — there is now one type, **`ResolvedSourceProfile`**, for both:

- **Pack-level** (`get_source_profile` / `get_pack_source_profile`): `packs=(pack_key,)`
- **ICP-level** (`serve_source_profile`): `packs=tuple(spec.enabled_packs)` after merge

Both return the same shape: `packs`, `default`, `by_field_class`, and `for_field_class()`.

Implementation:
- **`icp/source_profile.py`**: `ResolvedSourceProfile` now uses `packs: tuple[str, ...]` instead of
  `pack_key: str`. `ServedSourceProfile` deleted.
- **`icp/catalog.py`**: `serve_source_profile` + `_merge_slot` (next to `get_pack_source_profile`).
- **`sources/source_profile.py`**: only `resolve_allowed_set` + `AllowedSource` (registry ∩ profile).

## Why
The merge logic only needed `icp` + `core`; duplicating a second type (`ServedSourceProfile`) that
differed only in `pack_key` vs `packs` was the redundancy the user flagged. One type, two entry
functions.

## Verification
`ruff`, `mypy`, `lint-imports` (11/11), DB-backed `tests/sources`, `tests/icp`, `tests/stage0/test_icp_confirm.py`.

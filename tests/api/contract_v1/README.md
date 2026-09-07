# Contract v1 — the Zod oracle

`platform/api/clue_api/frontend_read/contract_v1.py` is the backend's wire contract for the five
accounts-screen payloads (ARV2 D3). The *oracle* it is checked against is the dummy frontend's own
Zod models, vendored here so the check is hermetic and reviewable in one diff.

## What is in this directory

| Path | What |
| --- | --- |
| `zod/*.ts` | the five model files copied verbatim from `clue-frontend` @ `84f8ee7` (`src/features/accounts/model/`), carrying **only** the D0/D3 contract amendments |
| `validate.ts` | the two-mode CLI: `--shapes` (print the field classification) and `<payload.json> <SchemaName>` (parse a payload) |
| `zod-fields.json` | the committed output of `validate.ts --shapes`; the test regenerates it and fails on drift |
| `test_contract_v1.py` | the three-part parity test: field sets, golden payloads, and the `accounts.md` field tables |

## The amendments

Every amended line carries a `// D0 ruling Rn/Sn` or `// D3 ruling` comment, so

```bash
diff -u /path/to/clue-frontend/src/features/accounts/model/<f>.ts tests/api/contract_v1/zod/<f>.ts
```

shows the amendments and nothing else. `account-workspace.ts` is byte-identical. The amendments are
listed with their rulings in the "D0 amendments (rulings)" table of
`apps/frontend/docs/api-contracts/accounts.md § Contract v1`.

## Running the Zod oracle by hand

`zod` (4.4.3) is **not** installed anywhere in this monorepo — `apps/frontend` has no `zod`
dependency — so the runner resolves it from the dummy frontend's `node_modules` through `NODE_PATH`
(tsx transpiles these modules to CJS, so `NODE_PATH` is honoured). Run from the **monorepo root**:

```bash
export CLUE_DUMMY_FRONTEND_ROOT=/Users/aryankeshri/conductor/workspaces/clue-frontend/live-backend-v1

# regenerate the committed shape file
NODE_PATH="$CLUE_DUMMY_FRONTEND_ROOT/node_modules" \
  npx --prefix "$CLUE_DUMMY_FRONTEND_ROOT" tsx "$PWD/tests/api/contract_v1/validate.ts" --shapes \
  > tests/api/contract_v1/zod-fields.json

# validate one payload
NODE_PATH="$CLUE_DUMMY_FRONTEND_ROOT/node_modules" \
  npx --prefix "$CLUE_DUMMY_FRONTEND_ROOT" tsx "$PWD/tests/api/contract_v1/validate.ts" \
  /tmp/payload.json AccountDetailSchema
```

`validate.ts` must be given an **absolute** path: `npx --prefix` changes how the `tsx` binary is
found, not the process working directory, and the relative import of `./zod/*` resolves from the
script's own location either way.

`test_contract_v1.py` runs exactly this, taking the dummy root from `CLUE_DUMMY_FRONTEND_ROOT`
(defaulting to the path above). The Node half of the test `skip`s — naming what is missing — when
`node` is not on `PATH` or `$CLUE_DUMMY_FRONTEND_ROOT/node_modules/zod` does not exist; the pydantic
half always runs.

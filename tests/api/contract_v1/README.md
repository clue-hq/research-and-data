# Contract v1 — the Zod oracle

`platform/api/clue_api/frontend_read/contract_v1.py` is the backend's wire contract for the five
accounts-screen payloads (ARV2 D3). The *oracle* it is checked against is the frontend's own Zod
models — since the D4 re-lift those live in this monorepo at
`apps/frontend/src/features/accounts/model/`, so there is exactly one copy of contract v1's
presentation truth and `validate.ts` imports it directly. (They were vendored here under `zod/`
while the frontend still lived in the dummy repo; that copy is gone.)

## What is in this directory

| Path | What |
| --- | --- |
| `validate.ts` | the two-mode CLI: `--shapes` (print the field classification) and `<payload.json> <SchemaName>` (parse a payload); imports the five models from `apps/frontend/src/features/accounts/model/` |
| `zod-fields.json` | the committed output of `validate.ts --shapes`; the test regenerates it and fails on drift |
| `oracle.py` | the toolchain probe + subprocess call, shared by this suite and the endpoint suites |
| `test_contract_v1.py` | the three-part parity test: field sets, golden payloads, and the `accounts.md` field tables |

## The amendments

The models carry the D0/D3 contract amendments against the dummy frontend @ `84f8ee7`, each marked
in place with a `// D0 ruling Rn/Sn` or `// D3 ruling` comment, so

```bash
diff -u /path/to/clue-frontend/src/features/accounts/model/<f>.ts \
        apps/frontend/src/features/accounts/model/<f>.ts
```

shows the amendments and nothing else. `account-workspace.ts` is byte-identical. The amendments are
listed with their rulings in the "D0 amendments (rulings)" table of
`apps/frontend/docs/api-contracts/accounts.md § Contract v1`.

## Running the Zod oracle by hand

`zod` (4.4.3) and `tsx` come from `apps/frontend/node_modules`; the runner puts them on `NODE_PATH`
(tsx transpiles these modules to CJS, so `NODE_PATH` is honoured). Run from the **monorepo root**:

```bash
NODE_ROOT="$PWD/apps/frontend"

# regenerate the committed shape file
NODE_PATH="$NODE_ROOT/node_modules" \
  npx --prefix "$NODE_ROOT" tsx "$PWD/tests/api/contract_v1/validate.ts" --shapes \
  > tests/api/contract_v1/zod-fields.json

# validate one payload
NODE_PATH="$NODE_ROOT/node_modules" \
  npx --prefix "$NODE_ROOT" tsx "$PWD/tests/api/contract_v1/validate.ts" \
  /tmp/payload.json AccountDetailSchema
```

`validate.ts` must be given an **absolute** path: `npx --prefix` changes how the `tsx` binary is
found, not the process working directory, and the relative import of the models resolves from the
script's own location either way.

`test_contract_v1.py` runs exactly this. The Node root defaults to `apps/frontend` and can be
overridden with `CLUE_DUMMY_FRONTEND_ROOT` (the name is kept so an operator can still point the
runner at another checkout). The Node half of the test `skip`s — naming what is missing — when
`node` is not on `PATH` or `<root>/node_modules/zod` does not exist; the pydantic half always runs.

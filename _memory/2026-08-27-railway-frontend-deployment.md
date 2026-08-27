# 2026-08-27 — Railway frontend deployment packaging

Founder authorized the code changes, local commit, and push needed to deploy
`apps/frontend` from `integration/frontend-design-part-iv-v4` on Railway.

## Deployment contract

- Railway source root stays at repository `/`; `/apps/frontend` is not an
  isolated app because its prebuild consumes design fonts and the browser
  engine from `subsystems/clue-design/`.
- `apps/frontend/Dockerfile.railway` selectively copies that contract, runs the
  existing design-system + Next build, and emits a Next standalone runtime.
- Railway must set
  `RAILWAY_DOCKERFILE_PATH=/apps/frontend/Dockerfile.railway`; custom Build and
  Start commands remain unset because the Dockerfile owns both.
- Root `.dockerignore` excludes all nested `.env*`, local databases/artifacts,
  dependency caches, Rust targets, and demo media. The first local Docker pass
  exposed that root-only `.env.*` was insufficient; the build was stopped and
  the pattern corrected to `**/.env.*` before the accepted image was built.
- The source-stamped wasm-pack outputs are now tracked release inputs. Stamp
  `4bf63781be19` matches the current helper; raw wasm is 2,654,410 bytes and
  817,767 bytes gzipped, below the 3 MiB budget.
- `apps/frontend/next.config.ts` enables standalone output. Runtime image size
  is 346,154,074 bytes instead of roughly 1.5 GB with the full npm tree.

## Verification

- `node subsystems/clue-design/scripts/preflight_editor_wasm.mjs` — up to date.
- `node subsystems/clue-design/scripts/verify_handshake.mjs` — HANDSHAKE OK.
- `bash subsystems/clue-design/scripts/build_wasm_core.sh --check` — within budget.
- Clean Docker build with no `.env.local` in context — green full Next route build.
- Docker build with the real Clerk publishable key passed only through its
  declared build arg — green.
- Standalone container honored injected `PORT=3199`, served `/` with HTTP 200
  in auth-off mode, and served the exact wasm + Inter font bytes.
- Auth-on container returned the expected signed-out Clerk redirects (`/` →
  `/sign-in?reason=session_expired` → `/onboarding/sign-in`) with no runtime error.
- `npm run lint` — zero errors; two pre-existing unused-function warnings in
  `canvasOperations.ts` only.

## Remaining account-side work

- Configure Railway source branch, root `/`, Dockerfile-path variable, frontend
  runtime/Clerk variables, and the two live ngrok API URLs.
- Add `app.cluehq.ai` after deploy and publish both Railway-provided DNS records.
- Add the origin to Clerk and append it to the local platform API authorized
  parties; keep platform API 8052, design API 8060, and both tunnels alive.

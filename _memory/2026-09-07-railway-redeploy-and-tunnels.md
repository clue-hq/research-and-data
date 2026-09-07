# 2026-09-07 — Railway frontend redeployed from `design/scene-ad`; tunnels back up for co-founder testing

Founder request: deploy the latest frontend (with the current wasm) to Railway and re-host the
platform API, design API and fleet worker via ngrok so the co-founder can test.

## What was done
- **Deploy = fast-forward push.** Railway builds `integration/frontend-design-part-iv-v4` (root `/`,
  `RAILWAY_DOCKERFILE_PATH=/apps/frontend/Dockerfile.railway`; env already points at the two static
  ngrok domains). HEAD `f67469e48` (already on GitHub as `design/scene-ad`) was pushed to v4 as a plain
  fast-forward (`3fa3f5669..f67469e48`, 281 commits). Founder authorized the push explicitly.
- **Pre-push gate:** `verify_handshake.mjs` HANDSHAKE OK at `32ce2d50a1ca`; the exact Railway
  Dockerfile built green locally (`docker build -f apps/frontend/Dockerfile.railway .`, image
  `colombo-frontend-railway-check`), wasm preflight inside the build passed, image wasm hash == tracked
  wasm hash (`67c61d3d…`).
- **Railway rebuild took ~3.5 min** after the push; verified by polling the served
  `/vendor/wasm/lumen_wasm_bg.wasm` hash until it flipped from the v4 build (`84471dda…`) to `67c61d3d…`.
- **ngrok:** `ngrok start --all` (config at `~/Library/Application Support/ngrok/ngrok.yml`, two named
  endpoints: `clue-platform-api.ngrok.app → 8052`, `clue-design-api.ngrok.app → 8060`), log
  `/private/tmp/colombo-ngrok.log`, inspector `localhost:4040`. The fleet worker is not an HTTP
  service — it needs no tunnel, just to be running against the same DB (it is, pid from the 22:04 restart).
- **End-to-end proof on the hosted app:** signed in as the Apollo test account on app.cluehq.ai →
  workspace select → projects list (platform tunnel; Railway egress IP 136.107.183.205 in the
  platform API log) → Apollo project gallery: 8 thumbnails rendered, served through the design tunnel
  (`GET /documents/…/thumbnail` 200 from the Railway IP in the design API log).

## Rules re-learned
- Railway watches v4 only (founder confirmation 2026-09-07). Deploying any branch = fast-forward v4 to
  it; never repoint the service without the founder.
- Always run the Railway Dockerfile locally before pushing a deploy — no Railway CLI/token on this
  machine, so a failed remote build would be invisible except as "wasm hash never flips".
- Tunnels die with reboots/sessions; check `pgrep -fl ngrok` and `localhost:4040/api/tunnels` first.

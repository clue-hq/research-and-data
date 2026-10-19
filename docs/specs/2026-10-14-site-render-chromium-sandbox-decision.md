# Decision: the site renderer's Chromium runs without its own sandbox in containers (option A)

**Date:** 2026-10-14. **Decided by:** the founder. **Review finding:** S7-1 (Wave 2 area review,
`docs/superpowers/verification/2026-10-14-wave2-area-review-findings.md`).
**Read this before** changing `LUMEN_SITE_RENDER_CHROMIUM_SANDBOX`, the backend image, the release
smoke check, or how agent-written site code is rendered on the server — and before any upgrade of
this decision (see "When to come back to this").

---

## 1. Background

Websites on Puck can carry **agent sections**: React code the site agent writes itself. On the
server that code runs only inside a **hardened headless Chromium** (decision D2, founder ruling
2026-10-11, `docs/superpowers/plans/2026-10-09-website-agent-on-puck-integration.md` §D2: "hardened
headless Chromium for every site, with no container … the locked container stays the documented
upgrade if agent sections become common"). It renders for the site agent's previews and screenshots,
when an agent section is recorded, on publish, and for thumbnails.

`subsystems/clue-design/apps/api/lumen_api/hardened_browser.py` gives that browser these protections,
each enough on its own against network access:

1. the render page's security policy (CSP);
2. no hostname resolves (`--host-resolver-rules`);
3. a dead-end proxy, loopback included;
4. WebRTC forced through that proxy;
5. Playwright: offline context, service workers blocked, every request and WebSocket refused;

plus a stripped environment (no API keys or database URLs in the browser process), a V8 heap cap, a
time limit, an output cap, the publish sanitizer — and **Chromium's own sandbox**, an operating-system
jail around Chromium's processes, so that page code exploiting a Chromium bug cannot reach the
machine. That last one is `LUMEN_SITE_RENDER_CHROMIUM_SANDBOX` (code default `1`, on).

## 2. The problem (S7-1)

On Linux, Chromium's sandbox needs to create **user namespaces**. Docker's default seccomp profile —
what CI's runner and the worker VM use — refuses that, and Ubuntu 24.04's AppArmor restricts it too.
Chromium then aborts: "No usable sandbox!". Macs sandbox Chromium differently, so every dev stack
worked and no lane saw it.

- The release smoke check (`docker/backend/smoke.sh`) launched Chromium with the sandbox hard-coded
  on, so it failed in CI: the `production` tags never moved and **no backend service could be
  released**, hotfixes included. Its advice ("set the variable to 0") could not help — it ignored the
  variable.
- Had the check been removed, production would have run the default (on) and **every site render
  would have failed**: no site built, previewed or published.

Proven by the S7 reviewer on a real backend image (sandbox on → "No usable sandbox"; off → renders).
Railway's runtime is untested, and almost certainly accepts no custom seccomp profile.

## 3. The options

| | What | Gains | Costs |
|---|---|---|---|
| **A** | Containers run the site renderer with the sandbox **off**; Macs keep it on | Unblocks releases now; same footing as every other Chromium in production; every other protection stays | One protection layer fewer, for this renderer |
| **B** | Give the containers a seccomp profile (and host AppArmor setting) that allows the sandbox | Keeps the sandbox on the VM | VM, host and CI ops work; probably impossible on Railway, so publish and thumbnails would move to the VM |
| **C** | The "locked container" D2 names: every render in a throwaway container with no network | Strongest isolation | Largest job; Railway cannot start containers, so every render moves to the VM; slower |

## 4. The decision: A

**Option A, now.** Why:

1. It unblocks every backend release today.
2. **Every other Chromium in production already runs without its own sandbox** — Playwright's
   default is off: brand ingestion visiting arbitrary websites (`lumen_ingestion/capture/rendered.py`),
   the web lane rendering agent-written pages (`lumen_agent/tools/web_substrate.py`), thumbnails,
   clone review, fragment isolation. The site renderer was the only one asking for it.
3. Every other protection in §1 stays, including all five network blocks and the stripped
   environment.
4. It fits the founder's standing direction for this layer: a simple fix now, hardened over time.

### What A is, concretely (every place that enforces it)

| Where | What |
|---|---|
| `docker/backend/Dockerfile` | `ENV LUMEN_SITE_RENDER_CHROMIUM_SANDBOX=0` |
| `deploy/check_prod_env.py` (`IMAGE_OWNED`) | refuses ANY env line for it, for every role: an env line overrides the image, and `.env.example`'s `1` is exactly the value that breaks containers |
| `docker/backend/smoke.sh` | `check "site renderer launches"` opens the real `hardened_page`, so it tests exactly what the services run (it reads the image's setting) |
| `.env.example`, `subsystems/clue-design/.env.example` | keep `1` (right on a Mac); the comment says the image sets 0 and production env files leave the line out |
| `docs/deploy/runbook.md` | lists it with the other image-owned settings |
| `hardened_browser.py` | unchanged: code default stays `1` (Macs) |
| tests | `tests/deploy/test_backend_image.py`, `tests/deploy/test_check_prod_env.py` pin all of the above |

## 5. What A costs (the honest residual risk)

With the sandbox off, a page that exploits a Chromium bug escapes straight into the browser process:
uid 1000 inside the worker container. From there:

- **the worker's secrets are readable**: the stripped environment protects only the browser
  process; the worker process runs as the same uid, and its environment is readable in `/proc`;
- **the Docker socket**: every worker pool built from `x-worker` in `deploy/vm/compose.yaml`
  (`chat`, `design`, `batch1`–`3`) mounts `/var/run/docker.sock` (the `run_python` sandbox needs it
  in `chat`), and that socket is effectively root on the VM. Only `ingestion` is built without it.

Reaching this needs a working Chromium exploit, delivered through code the agent was steered to write
(for example by a hostile page it read while researching). The same exposure already exists today for
the web lane's unsandboxed Chromium in those same workers, so A creates no new class of exposure — but
the exposure is real, and this is why A is the starting point, not the end state.

**Keep Chromium current**: Playwright (and so Chromium) is pinned in `uv.lock`; known Chromium bugs
are the realistic attack, so bump it regularly.

## 6. The hardening step that is NOT cheap (correction, 2026-10-14)

When A was proposed, step 2 was "move rendering of agent code away from the Docker socket — run site
renders in a pool without the socket, as ingestion already does", described as cheap. **It is not a
compose change.** The live walk on 2026-10-14 showed the site turn running inside an `agent_turn`
task (the design leg's inline lane, `clue_api/design_fleet.py`), i.e. in the `chat` pool, and `chat`
must keep the socket because `run_python` (Head of ABM) uses it. Real ways to do it, each its own
small design:

1. route the site turn's renders through the design API (on Railway, no socket) — a new internal
   render endpoint the turn calls;
2. a render-only fleet pool without the socket, which the turn hands each render to and waits on;
3. move `run_python` to its own pool, so `chat` and `design` drop the socket.

**Status: not built; owner unassigned; awaits a founder call.**

## 7. When to come back to this

Revisit (and move to B or C) when any of these happens:

- agent sections become common on customer sites (D2's own trigger for the locked container);
- a Chromium sandbox-escape or renderer bug is published that the pinned version carries;
- a customer security review asks how agent-written code is isolated on the server;
- the workers move to a runtime that can give Chromium its sandbox (then B is a setting change: set
  the image's value to 1, and the smoke check proves it on the next release).

Upgrading means: change the row(s) in §4's table, update this file's status, and keep the smoke check
launching the real renderer.

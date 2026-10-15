# syntax=docker/dockerfile:1
# The backend image (first deployment spec §9.1): platform API, design API, fleet workers,
# ingestion pool and migrations, started by `clue <command>` (docker/backend/entrypoint.sh).
# Smoke tests: docker/backend/smoke.sh (contents) and docker/backend/boot_smoke.sh (services boot).

# --- Rust design-engine helper -------------------------------------------------------------
FROM rust:1-bookworm AS helper
# rust-skia publishes no prebuilt Skia for our feature set (textlayout + svg + webp, no vulkan) on
# Linux, so skia-bindings compiles Skia from source: it needs clang, libclang (bindgen), ninja and
# the fontconfig headers (textlayout).
RUN apt-get update \
    && apt-get install -y --no-install-recommends clang libclang-dev ninja-build libfontconfig1-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY subsystems/clue-design/Cargo.toml subsystems/clue-design/Cargo.lock ./
COPY subsystems/clue-design/crates ./crates
# lumen-skia embeds the Inter faces from the design subsystem's fonts/ (include_bytes!).
COPY subsystems/clue-design/fonts ./fonts
# Skia's from-source build leaves several GB in target/ and the cargo registry: delete them in the
# same step so the layer (and CI's exported build cache) holds only the binary. Not a BuildKit cache
# mount: Railway's builder refuses cache mounts whose id is not prefixed with the service id.
RUN cargo build --release -p lumen-api-helper \
    && cp target/release/lumen-api-helper /usr/local/bin/lumen-api-helper \
    && rm -rf target /usr/local/cargo/registry

# --- Design editor's Tailwind toolchain (used at web export) ----------------------------------
FROM node:24-bookworm-slim AS editor
WORKDIR /src/subsystems/clue-design
COPY subsystems/clue-design/apps/editor/package.json subsystems/clue-design/apps/editor/package-lock.json ./apps/editor/
RUN cd apps/editor && npm ci --ignore-scripts
COPY subsystems/clue-design/scripts/vendor_tailwind_runtime.sh ./scripts/
RUN bash scripts/vendor_tailwind_runtime.sh \
    && test -f apps/editor/public/vendor/tailwind-browser.js

# --- Site kit bundles (Puck sites: the hardened-browser render bundle and the validator CLI) -----
FROM node:24-bookworm-slim AS sitekit
WORKDIR /src/apps/frontend
COPY apps/frontend/package.json apps/frontend/package-lock.json ./
COPY apps/frontend/packages/design-system/package.json ./packages/design-system/package.json
COPY apps/frontend/packages/site-kit ./packages/site-kit
RUN npm ci --ignore-scripts && npm run build -w @clue/site-kit \
    && test -f packages/site-kit/dist/render-browser.js \
    && test -f packages/site-kit/dist/validate-site.mjs \
    && test -f packages/site-kit/dist/build-catalog.mjs

# --- Runtime ------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
COPY --from=node:24-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv PATH=/app/.venv/bin:$PATH \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
# ffmpeg/ffprobe: research media prepares every recording for Deepgram with them (spec
# docs/superpowers/specs/2026-10-13-legitimate-media-sources-design.md §4); without them no
# transcript is ever produced. YouTube is never downloaded (no yt-dlp in this image).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates fontconfig libfontconfig1 libstdc++6 \
       libpq5 ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
# --group deploy: alembic (`clue migrate`) and the S3/R2 storage SDK, which no member depends on.
RUN uv sync --frozen --no-dev --group deploy --all-packages
RUN python -m playwright install --with-deps chromium && chmod -R a+rX /ms-playwright
COPY --from=helper /usr/local/bin/lumen-api-helper /app/subsystems/clue-design/target/release/lumen-api-helper
COPY --from=editor /src/subsystems/clue-design/apps/editor/node_modules /app/subsystems/clue-design/apps/editor/node_modules
COPY --from=editor /src/subsystems/clue-design/apps/editor/public/vendor /app/subsystems/clue-design/apps/editor/public/vendor
COPY --from=sitekit /src/apps/frontend/packages/site-kit/dist /app/apps/frontend/packages/site-kit/dist
# Lane B (Contract 4): the section compiler needs the frontend toolchain at run time (tsc with the
# react and zod types, esbuild, tsx); the site-kit sources come with `COPY . /app`.
COPY --from=sitekit /src/apps/frontend/node_modules /app/apps/frontend/node_modules
# CLUE_ARV2_RAW_ROOT: research's podcast downloads (deleted after transcription). The settings
# default, .artifacts/arv2, is relative and would land under the root-owned /app.
# LUMEN_SITE_RENDER_CHROMIUM_SANDBOX=0: the site renderer's Chromium runs WITHOUT its own sandbox in
# containers. Docker's default seccomp profile (CI, the VM; Railway is no better) refuses the user
# namespace the sandbox needs, so with it on no site renders and the release smoke fails. Option A
# of docs/specs/2026-10-14-site-render-chromium-sandbox-decision.md (founder, 2026-10-14): read it before changing this, and before any upgrade.
ENV LUMEN_CORE_HELPER=/app/subsystems/clue-design/target/release/lumen-api-helper \
    LUMEN_FONT_LIBRARY_MANIFEST_PATH=/app/subsystems/clue-design/apps/api/font-library/manifest.json \
    CLUE_ARV2_RAW_ROOT=/var/lib/clue/arv2-raw \
    LUMEN_SITE_RENDER_CHROMIUM_SANDBOX=0
COPY docker/backend/entrypoint.sh /usr/local/bin/clue
# The section compiler (Lane B, Contract 4) type-checks each agent section in a throwaway folder
# inside site-kit, where react and zod resolve; the runtime user must be able to create it.
RUN useradd --uid 1000 --create-home clue && chown -R clue:clue /app/subsystems/clue-design \
    && mkdir -p /var/lib/clue/arv2-raw && chown -R 1000:1000 /var/lib/clue/arv2-raw \
    && mkdir -p /app/apps/frontend/packages/site-kit/.section-check && chown 1000:1000 /app/apps/frontend/packages/site-kit/.section-check
USER 1000:1000
ENTRYPOINT ["clue"]

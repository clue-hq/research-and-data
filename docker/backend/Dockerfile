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
RUN cargo build --release -p lumen-api-helper

# --- Design editor's Tailwind toolchain (used at web export) ----------------------------------
FROM node:24-bookworm-slim AS editor
WORKDIR /src/subsystems/clue-design
COPY subsystems/clue-design/apps/editor/package.json subsystems/clue-design/apps/editor/package-lock.json ./apps/editor/
RUN cd apps/editor && npm ci --ignore-scripts
COPY subsystems/clue-design/scripts/vendor_tailwind_runtime.sh ./scripts/
RUN bash scripts/vendor_tailwind_runtime.sh \
    && test -f apps/editor/public/vendor/tailwind-browser.js

# --- Runtime ------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
COPY --from=node:24-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv PATH=/app/.venv/bin:$PATH \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates fontconfig libfontconfig1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
RUN uv sync --frozen --no-dev --all-packages
RUN python -m playwright install --with-deps chromium && chmod -R a+rX /ms-playwright
COPY --from=helper /src/target/release/lumen-api-helper /app/subsystems/clue-design/target/release/lumen-api-helper
COPY --from=editor /src/subsystems/clue-design/apps/editor/node_modules /app/subsystems/clue-design/apps/editor/node_modules
COPY --from=editor /src/subsystems/clue-design/apps/editor/public/vendor /app/subsystems/clue-design/apps/editor/public/vendor
# CLUE_ARV2_RAW_ROOT: research's podcast downloads (deleted after transcription). The settings
# default, .artifacts/arv2, is relative and would land under the root-owned /app.
ENV LUMEN_CORE_HELPER=/app/subsystems/clue-design/target/release/lumen-api-helper \
    LUMEN_FONT_LIBRARY_MANIFEST_PATH=/app/subsystems/clue-design/apps/api/font-library/manifest.json \
    CLUE_ARV2_RAW_ROOT=/var/lib/clue/arv2-raw
COPY docker/backend/entrypoint.sh /usr/local/bin/clue
RUN useradd --uid 1000 --create-home clue && chown -R clue:clue /app/subsystems/clue-design \
    && mkdir -p /var/lib/clue/arv2-raw && chown -R 1000:1000 /var/lib/clue/arv2-raw
USER 1000:1000
ENTRYPOINT ["clue"]

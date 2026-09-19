# Chat Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a person attach `.md`/`.txt` files and images to a project chat message (button or drag-and-drop), keep them on the platform, show them in the transcript, and put them in front of Head-of-ABM: text as readable project files, images as image parts the model sees on that turn and on later turns.

**Architecture:** One workspace-scoped upload endpoint stores bytes through the existing content-addressed artifact store and records the filename in a new `chat_upload` row. Submissions carry `attachment_refs` (already in the wire contract, refused today); the router validates them fail-closed, records them on the submission, turns text uploads into project documents at `attachments/<filename>`, and the fleet passes them to the turn as `AgentTurnRequest.attachment_refs` (already recorded as `agent_artifact_ref` rows with role `attachment`). The context assembler grows one optional field, `image_refs`, on `ContextCandidate`; the L7 layer attaches the sending turn's images and the L6 layer re-attaches prior turns' images, capped by a setting.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (platform API), Pydantic v2 contracts (`clue_agents`), LangChain `ChatOpenAI` over OpenRouter (Responses API), Next.js App Router + Zod + `node:test` (frontend), pytest with a throwaway Postgres for `*_db.py` suites.

**Spec:** `docs/superpowers/specs/2026-09-18-chat-attachments-design.md`

## Global Constraints

- Accepted media: `text/markdown`, `text/plain` (extensions `.md`, `.txt`), `image/png`, `image/jpeg`, `image/webp`, `image/gif`.
- Limits: `CLUE_CHAT_ATTACHMENT_MAX_FILES=10`, `CLUE_CHAT_ATTACHMENT_MAX_TOTAL_BYTES=157286400`, `CLUE_CHAT_ATTACHMENT_IMAGE_MAX_BYTES=10485760`, `CLUE_CHAT_ATTACHMENT_TEXT_MAX_BYTES=5242880`, `CLUE_CHAT_ATTACHMENT_HISTORY_IMAGES_MAX=20` (`0` = no cap). Every one of them lands in `.env.example` in the task that introduces it (repo rule: env parity).
- Alembic: random-hash revision ids via `uv run alembic revision -m "<slug>"`, `down_revision` = current head `fffa2a8ba17c`, reversible `downgrade()`, one head always (`uv run alembic heads`).
- Ruling 3: uploaded images never appear in the Gallery. Ruling 4: while an ad leg is open, images keep the existing design-reference route; text goes the new route. Ruling 5: drag-over shows a dashed outline on the composer only.
- The target-accounts gallery card is out of scope. Do not touch `gallery-card-target.ts`, `artifact-tabs.tsx`, or the gallery feed.
- Never run the broad pytest suite with real keys in `.env` (memory rule: live tests spend money). Run the named files below. DB suites need a throwaway database: `export CLUE_DATABASE_URL=postgresql+psycopg://…/clue_attachments_test` then `make migrate` once.
- Frontend gate after every frontend task: `cd apps/frontend && npm test && npm run lint`. Backend gate after every backend task: `uv run ruff check <changed files> && uv run mypy <changed files>` plus the named tests.
- No `Co-Authored-By` trailers, no AI attribution, no pushes. Commit at the end of each task.
- The vision probe (Task 1) gates Tasks 8 and 9. If it fails, stop after Task 1 and report; ruling 1 chose no fallback.

---

### Task 1: Vision probe — does Grok 4.6 accept an image through our model provider?

**Files:**
- Create: `scripts/probe_chat_image_input.py`
- Modify: `_memory/2026-09-18-chat-attachments-and-target-accounts-card-exploration.md` (append the outcome)

**Interfaces:**
- Consumes: `clue_gateway.OpenRouterAgentModelProvider(config, api_key).build(model_id=…, timeout_s=…, max_retries=…, max_output_tokens=…, temperature=…, role=…) -> BaseChatModel`; `clue_config.gateway.GatewayConfig()`; `clue_config.Secrets().openrouter_api_key`.
- Produces: a recorded yes/no. Nothing else in the repo imports this script.

- [ ] **Step 1: Write the probe script**

```python
#!/usr/bin/env python3
"""Probe: can the Head-of-ABM model see an image sent as an `image_url` content part?

Spends money (one small model call). Run with the lane's `.env` sourced:
    set -a; source .env; set +a; uv run python scripts/probe_chat_image_input.py [--model x-ai/grok-4.6]
Exit 0 = the model described the image correctly. Exit 1 = it did not (or refused).
"""

from __future__ import annotations

import argparse
import base64
import struct
import sys
import zlib

from langchain_core.messages import HumanMessage

from clue_config import Secrets
from clue_config.gateway import GatewayConfig
from clue_gateway import OpenRouterAgentModelProvider


def _png(width: int, height: int) -> bytes:
    """A PNG whose left half is pure red and right half pure blue; no Pillow needed."""

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        )

    rows = b""
    for _ in range(height):
        row = b"\x00"
        for x in range(width):
            row += b"\xff\x00\x00" if x < width // 2 else b"\x00\x00\xff"
        rows += row
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="x-ai/grok-4.6")
    args = parser.parse_args()

    api_key = Secrets().openrouter_api_key
    if api_key is None:
        print("CLUE_OPENROUTER_API_KEY is not set", file=sys.stderr)
        return 2
    provider = OpenRouterAgentModelProvider(GatewayConfig(), api_key)
    model = provider.build(
        model_id=args.model,
        timeout_s=60,
        max_retries=0,
        max_output_tokens=200,
        temperature=0,
        role="head_of_abm",
    )
    data_url = "data:image/png;base64," + base64.b64encode(_png(64, 64)).decode("ascii")
    message = HumanMessage(
        content=[
            {
                "type": "text",
                "text": "This image has two solid color halves. Name the left color and the "
                "right color, in that order, in one short sentence.",
            },
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
    )
    reply = model.invoke([message])
    text = reply.text() if callable(getattr(reply, "text", None)) else str(reply.content)
    print(f"model={args.model}\nreply={text!r}")
    lowered = text.lower()
    ok = "red" in lowered and "blue" in lowered and lowered.index("red") < lowered.index("blue")
    print("RESULT:", "IMAGE SEEN" if ok else "IMAGE NOT SEEN")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the probe**

Run: `set -a; source .env; set +a; uv run python scripts/probe_chat_image_input.py`
Expected: the reply names red then blue and the script prints `RESULT: IMAGE SEEN`, exit 0. Cost: well under one cent.

- [ ] **Step 3: Record the outcome**

Append to `_memory/2026-09-18-chat-attachments-and-target-accounts-card-exploration.md`:

```markdown
## Vision probe (Task 1)
- Date, model id, exact reply, RESULT line. Command: `uv run python scripts/probe_chat_image_input.py`.
```

If the result is `IMAGE NOT SEEN`: stop here, commit the script and the note, and report to the founder. Do not start Task 8 or 9.

- [ ] **Step 4: Commit**

```bash
git add scripts/probe_chat_image_input.py _memory/2026-09-18-chat-attachments-and-target-accounts-card-exploration.md
git commit -m "chore(probe): confirm the Head-of-ABM model accepts image parts over OpenRouter"
```

---

### Task 2: Settings and environment for attachment limits

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (next to `chat_turn_stream_batch_max_chars`, ~line 663)
- Modify: `.env.example` (after `CLUE_CHAT_STREAM_POLL_INTERVAL_S=0.25`, ~line 449)
- Modify: `.env` (same five lines, same values; the local file keeps key parity)
- Test: `tests/config/test_chat_attachment_settings.py`

**Interfaces:**
- Produces: `Settings.chat_attachment_max_files: int`, `Settings.chat_attachment_max_total_bytes: int`, `Settings.chat_attachment_image_max_bytes: int`, `Settings.chat_attachment_text_max_bytes: int`, `Settings.chat_attachment_history_images_max: int`. Env names are the field names upper-cased with the `CLUE_` prefix (the model's `env_prefix`).

- [ ] **Step 1: Write the failing test**

```python
# tests/config/test_chat_attachment_settings.py
from __future__ import annotations

from clue_config import Settings


def test_chat_attachment_defaults(monkeypatch) -> None:
    for name in (
        "CLUE_CHAT_ATTACHMENT_MAX_FILES",
        "CLUE_CHAT_ATTACHMENT_MAX_TOTAL_BYTES",
        "CLUE_CHAT_ATTACHMENT_IMAGE_MAX_BYTES",
        "CLUE_CHAT_ATTACHMENT_TEXT_MAX_BYTES",
        "CLUE_CHAT_ATTACHMENT_HISTORY_IMAGES_MAX",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings()
    assert settings.chat_attachment_max_files == 10
    assert settings.chat_attachment_max_total_bytes == 150 * 1024 * 1024
    assert settings.chat_attachment_image_max_bytes == 10 * 1024 * 1024
    assert settings.chat_attachment_text_max_bytes == 5 * 1024 * 1024
    assert settings.chat_attachment_history_images_max == 20


def test_chat_attachment_env_override(monkeypatch) -> None:
    monkeypatch.setenv("CLUE_CHAT_ATTACHMENT_HISTORY_IMAGES_MAX", "0")
    monkeypatch.setenv("CLUE_CHAT_ATTACHMENT_MAX_FILES", "3")
    settings = Settings()
    assert settings.chat_attachment_history_images_max == 0
    assert settings.chat_attachment_max_files == 3
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/config/test_chat_attachment_settings.py -v`
Expected: FAIL — `Settings` has no attribute `chat_attachment_max_files`.

- [ ] **Step 3: Add the fields**

In `libs/clue-config/clue_config/settings.py`, directly after `chat_turn_stop_poll_interval_s`:

```python
    # Chat attachments (spec 2026-09-18). Per-message ceilings the upload route and the
    # submission route both enforce, and the number of prior-turn images re-sent to the model
    # as image parts on every later turn of a thread (``0`` = no cap). Env:
    # ``CLUE_CHAT_ATTACHMENT_MAX_FILES`` / ``_MAX_TOTAL_BYTES`` / ``_IMAGE_MAX_BYTES`` /
    # ``_TEXT_MAX_BYTES`` / ``_HISTORY_IMAGES_MAX``.
    chat_attachment_max_files: int = Field(default=10, ge=1)
    chat_attachment_max_total_bytes: int = Field(default=150 * 1024 * 1024, ge=1)
    chat_attachment_image_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    chat_attachment_text_max_bytes: int = Field(default=5 * 1024 * 1024, ge=1)
    chat_attachment_history_images_max: int = Field(default=20, ge=0)
```

In `.env.example` after `CLUE_CHAT_STREAM_POLL_INTERVAL_S=0.25`:

```
# Chat attachments (spec 2026-09-18): per-message ceilings and the prior-turn image re-send cap.
CLUE_CHAT_ATTACHMENT_MAX_FILES=10
CLUE_CHAT_ATTACHMENT_MAX_TOTAL_BYTES=157286400
CLUE_CHAT_ATTACHMENT_IMAGE_MAX_BYTES=10485760
CLUE_CHAT_ATTACHMENT_TEXT_MAX_BYTES=5242880
CLUE_CHAT_ATTACHMENT_HISTORY_IMAGES_MAX=20
```

Add the same five lines to `.env` at the same place.

- [ ] **Step 4: Run the test and the env-parity check**

Run: `uv run pytest tests/config/test_chat_attachment_settings.py -v` → PASS.
Run: `uv run pytest tests -k "env_example or env_parity" -q --ignore-glob='*_live.py'` → PASS (the repo's parity guard sees the five new keys in both files).

- [ ] **Step 5: Commit**

```bash
git add libs/clue-config/clue_config/settings.py .env.example tests/config/test_chat_attachment_settings.py
git commit -m "feat(config): chat attachment limits and the history image cap"
```

(`.env` is git-ignored; do not add it.)

---

### Task 3: Migration — `chat_upload` and `agent_turn_submission_attachment`

**Files:**
- Create: `alembic/versions/<hash>_chat_uploads_and_submission_attachments.py` (generated by `uv run alembic revision -m "chat uploads and submission attachments"`)
- Test: `tests/db/test_chat_upload_tables_db.py`

**Interfaces:**
- Produces two tables.
  - `chat_upload(upload_id uuid PK, workspace_id text NOT NULL, uploaded_by_user_id text NOT NULL, filename text NOT NULL, media_type text NOT NULL, artifact_key text NOT NULL REFERENCES artifact(storage_key), sha256 text NOT NULL, byte_count bigint NOT NULL, created_at timestamptz NOT NULL DEFAULT now())` with CHECKs: `chat_upload_sha CHECK (sha256 ~ '^[0-9a-f]{64}$')`, `chat_upload_scope CHECK (artifact_key = workspace_id || '/' || sha256)`, `chat_upload_filename CHECK (length(btrim(filename)) > 0 AND position('/' in filename) = 0)`, `chat_upload_bytes CHECK (byte_count >= 0)`; index `chat_upload_workspace ON chat_upload (workspace_id, created_at DESC)`.
  - `agent_turn_submission_attachment(turn_id uuid NOT NULL, workspace_id text NOT NULL, ordinal integer NOT NULL, upload_id uuid NOT NULL REFERENCES chat_upload(upload_id), artifact_key text NOT NULL, sha256 text NOT NULL, media_type text NOT NULL, byte_count bigint NOT NULL, filename text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (turn_id, ordinal), FOREIGN KEY (turn_id, workspace_id) REFERENCES agent_turn_submission (turn_id, workspace_id), CHECK (ordinal >= 0), UNIQUE (turn_id, upload_id))`.

- [ ] **Step 1: Write the failing DB test**

```python
# tests/db/test_chat_upload_tables_db.py
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from clue_db import db_lifespan
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_chat_upload_scope_check_rejects_a_foreign_key_shape() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = "ws_test_upload_tables"
            sha = "a" * 64
            await conn.execute(
                text(
                    "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
                    "size_bytes) VALUES (:key, :ws, :sha, 'image/png', 3)"
                ),
                {"key": f"{ws}/{sha}", "ws": ws, "sha": sha},
            )
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO chat_upload (upload_id, workspace_id, uploaded_by_user_id, "
                        "filename, media_type, artifact_key, sha256, byte_count) VALUES "
                        "(gen_random_uuid(), 'other_ws', 'usr', 'a.png', 'image/png', :key, :sha, 3)"
                    ),
                    {"key": f"{ws}/{sha}", "sha": sha},
                )
            await txn.rollback()

    run_async(scenario())


def test_chat_upload_filename_has_no_slash() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = "ws_test_upload_names"
            sha = "b" * 64
            await conn.execute(
                text(
                    "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
                    "size_bytes) VALUES (:key, :ws, :sha, 'text/plain', 3)"
                ),
                {"key": f"{ws}/{sha}", "ws": ws, "sha": sha},
            )
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO chat_upload (upload_id, workspace_id, uploaded_by_user_id, "
                        "filename, media_type, artifact_key, sha256, byte_count) VALUES "
                        "(gen_random_uuid(), :ws, 'usr', '../x.txt', 'text/plain', :key, :sha, 3)"
                    ),
                    {"ws": ws, "key": f"{ws}/{sha}", "sha": sha},
                )
            await txn.rollback()

    run_async(scenario())
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/db/test_chat_upload_tables_db.py -v`
Expected: FAIL — relation `chat_upload` does not exist.

- [ ] **Step 3: Create the migration**

Run: `uv run alembic revision -m "chat uploads and submission attachments"`. Set `down_revision = "fffa2a8ba17c"`. Body:

```python
def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE chat_upload (
            upload_id            uuid PRIMARY KEY,
            workspace_id         text NOT NULL,
            uploaded_by_user_id  text NOT NULL,
            filename             text NOT NULL,
            media_type           text NOT NULL,
            artifact_key         text NOT NULL REFERENCES artifact (storage_key),
            sha256               text NOT NULL,
            byte_count           bigint NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT chat_upload_sha CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT chat_upload_scope CHECK (artifact_key = workspace_id || '/' || sha256),
            CONSTRAINT chat_upload_filename CHECK (
                length(btrim(filename)) > 0 AND position('/' in filename) = 0
            ),
            CONSTRAINT chat_upload_bytes CHECK (byte_count >= 0)
        )
        """
    )
    op.execute("CREATE INDEX chat_upload_workspace ON chat_upload (workspace_id, created_at DESC)")
    op.execute(
        "COMMENT ON TABLE chat_upload IS 'One file a human uploaded for a chat message: the "
        "filename beside the content-addressed artifact the bytes live under (spec 2026-09-18).'"
    )
    op.execute(
        """
        CREATE TABLE agent_turn_submission_attachment (
            turn_id        uuid NOT NULL,
            workspace_id   text NOT NULL,
            ordinal        integer NOT NULL,
            upload_id      uuid NOT NULL REFERENCES chat_upload (upload_id),
            artifact_key   text NOT NULL,
            sha256         text NOT NULL,
            media_type     text NOT NULL,
            byte_count     bigint NOT NULL,
            filename       text NOT NULL,
            created_at     timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (turn_id, ordinal),
            CONSTRAINT agent_turn_submission_attachment_submission_fk
                FOREIGN KEY (turn_id, workspace_id)
                REFERENCES agent_turn_submission (turn_id, workspace_id),
            CONSTRAINT agent_turn_submission_attachment_ordinal CHECK (ordinal >= 0),
            CONSTRAINT agent_turn_submission_attachment_once UNIQUE (turn_id, upload_id)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE agent_turn_submission_attachment IS 'Ordered, immutable uploads "
        "captured with one human chat submission (spec 2026-09-18).'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE agent_turn_submission_attachment")
    op.execute("DROP INDEX chat_upload_workspace")
    op.execute("DROP TABLE chat_upload")
```

- [ ] **Step 4: Migrate the throwaway DB and run the test**

Run: `uv run alembic heads` → exactly one head (the new id). `make migrate`. `uv run pytest tests/db/test_chat_upload_tables_db.py -v` → PASS. `make db-smoke` → clean up/down/up.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/*_chat_uploads_and_submission_attachments.py tests/db/test_chat_upload_tables_db.py
git commit -m "feat(db): chat_upload and agent_turn_submission_attachment tables"
```

---

### Task 4: Upload store module — validation and rows

**Files:**
- Create: `platform/api/clue_api/chat/uploads.py`
- Test: `tests/api/test_chat_uploads.py` (pure), `tests/api/test_chat_uploads_db.py` (DB)

**Interfaces:**
- Produces:
  - `ALLOWED_TEXT_MEDIA_TYPES = frozenset({"text/markdown", "text/plain"})`, `ALLOWED_IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})`.
  - `attachment_family(media_type: str) -> Literal["text", "image"] | None`.
  - `class UploadRefused(Exception)` with `.code: str` and `.message: str`.
  - `sanitize_filename(name: str) -> str` (keeps one path segment, strips leading dots and slashes, collapses whitespace, max 255 chars; raises `UploadRefused("UPLOAD_FILENAME_INVALID", …)` when nothing is left).
  - `resolve_media_type(*, declared: str | None, filename: str) -> str` (declared first, else by extension; raises `UploadRefused("UPLOAD_UNSUPPORTED_TYPE", …)`).
  - `validate_upload_bytes(*, data: bytes, media_type: str, settings: Settings) -> None` (size per family; text must be UTF-8; image magic bytes must match; raises `UploadRefused` with codes `UPLOAD_TOO_LARGE`, `UPLOAD_NOT_UTF8`, `UPLOAD_NOT_AN_IMAGE`).
  - `@dataclass(frozen=True) class ChatUploadRow: upload_id: UUID; workspace_id: str; uploaded_by_user_id: str; filename: str; media_type: str; artifact_key: str; sha256: str; byte_count: int; created_at: datetime`.
  - `async def record_chat_upload(conn, *, workspace_id, user_id, filename, media_type, ref: ArtifactRef) -> ChatUploadRow`.
  - `async def get_chat_uploads(conn, *, workspace_id: str, upload_ids: Sequence[UUID]) -> dict[UUID, ChatUploadRow]` (workspace-scoped; absent ids are simply missing from the dict).

- [ ] **Step 1: Write the pure tests**

```python
# tests/api/test_chat_uploads.py
from __future__ import annotations

import pytest

from clue_api.chat.uploads import (
    UploadRefused,
    attachment_family,
    resolve_media_type,
    sanitize_filename,
    validate_upload_bytes,
)
from clue_config import Settings

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 8
GIF = b"GIF89a" + b"\x00" * 16


def test_family_is_text_or_image_or_none() -> None:
    assert attachment_family("text/markdown") == "text"
    assert attachment_family("text/plain") == "text"
    assert attachment_family("image/png") == "image"
    assert attachment_family("application/pdf") is None


def test_sanitize_filename_keeps_one_segment() -> None:
    assert sanitize_filename("  notes.md ") == "notes.md"
    assert sanitize_filename("../../etc/passwd.txt") == "passwd.txt"
    assert sanitize_filename("a/b/c report v2.md") == "c report v2.md"
    with pytest.raises(UploadRefused) as caught:
        sanitize_filename("....")
    assert caught.value.code == "UPLOAD_FILENAME_INVALID"


def test_resolve_media_type_prefers_declared_then_extension() -> None:
    assert resolve_media_type(declared="image/png", filename="x.bin") == "image/png"
    assert resolve_media_type(declared=None, filename="x.md") == "text/markdown"
    assert resolve_media_type(declared="application/octet-stream", filename="x.txt") == "text/plain"
    assert resolve_media_type(declared=None, filename="x.jpg") == "image/jpeg"
    with pytest.raises(UploadRefused) as caught:
        resolve_media_type(declared="application/pdf", filename="x.pdf")
    assert caught.value.code == "UPLOAD_UNSUPPORTED_TYPE"


def test_validate_bytes_enforces_family_rules() -> None:
    settings = Settings(chat_attachment_image_max_bytes=32, chat_attachment_text_max_bytes=8)
    validate_upload_bytes(data=PNG, media_type="image/png", settings=settings)
    validate_upload_bytes(data=JPEG, media_type="image/jpeg", settings=settings)
    validate_upload_bytes(data=WEBP, media_type="image/webp", settings=settings)
    validate_upload_bytes(data=GIF, media_type="image/gif", settings=settings)
    validate_upload_bytes(data=b"# hi", media_type="text/markdown", settings=settings)
    with pytest.raises(UploadRefused) as too_big:
        validate_upload_bytes(data=b"x" * 9, media_type="text/plain", settings=settings)
    assert too_big.value.code == "UPLOAD_TOO_LARGE"
    with pytest.raises(UploadRefused) as not_utf8:
        validate_upload_bytes(data=b"\xff\xfe", media_type="text/plain", settings=settings)
    assert not_utf8.value.code == "UPLOAD_NOT_UTF8"
    with pytest.raises(UploadRefused) as not_image:
        validate_upload_bytes(data=b"not a png", media_type="image/png", settings=settings)
    assert not_image.value.code == "UPLOAD_NOT_AN_IMAGE"
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/api/test_chat_uploads.py -v` → FAIL, module not found.

- [ ] **Step 3: Write the module**

```python
# platform/api/clue_api/chat/uploads.py
"""Chat uploads: what a person may attach, and the row that remembers its filename.

The bytes live in the content-addressed artifact store like every turn artifact; this module owns
the two things that store cannot say — the filename the person gave the file and which family
(text or image) it belongs to — and the validation both the upload route and the submission route
apply. Spec: docs/superpowers/specs/2026-09-18-chat-attachments-design.md.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ArtifactRef
from clue_config import Settings

__all__ = [
    "ALLOWED_IMAGE_MEDIA_TYPES",
    "ALLOWED_TEXT_MEDIA_TYPES",
    "ChatUploadRow",
    "UploadRefused",
    "attachment_family",
    "get_chat_uploads",
    "record_chat_upload",
    "resolve_media_type",
    "sanitize_filename",
    "validate_upload_bytes",
]

ALLOWED_TEXT_MEDIA_TYPES = frozenset({"text/markdown", "text/plain"})
ALLOWED_IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
_EXTENSION_MEDIA_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
_MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}
_WHITESPACE = re.compile(r"\s+")


class UploadRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def attachment_family(media_type: str) -> Literal["text", "image"] | None:
    lowered = media_type.lower()
    if lowered in ALLOWED_TEXT_MEDIA_TYPES:
        return "text"
    if lowered in ALLOWED_IMAGE_MEDIA_TYPES:
        return "image"
    return None


def sanitize_filename(name: str) -> str:
    segment = name.replace("\\", "/").rsplit("/", 1)[-1]
    segment = _WHITESPACE.sub(" ", segment).strip().lstrip(".")
    if not segment or len(segment) > 255:
        raise UploadRefused("UPLOAD_FILENAME_INVALID", "the file needs a usable name")
    return segment


def resolve_media_type(*, declared: str | None, filename: str) -> str:
    candidate = (declared or "").split(";", 1)[0].strip().lower()
    if attachment_family(candidate) is not None:
        return candidate
    dot = filename.rfind(".")
    by_extension = _EXTENSION_MEDIA_TYPES.get(filename[dot:].lower()) if dot >= 0 else None
    if by_extension is None:
        raise UploadRefused(
            "UPLOAD_UNSUPPORTED_TYPE",
            "attach a .md or .txt file, or a PNG, JPEG, WebP or GIF image",
        )
    return by_extension


def validate_upload_bytes(*, data: bytes, media_type: str, settings: Settings) -> None:
    family = attachment_family(media_type)
    if family is None:
        raise UploadRefused("UPLOAD_UNSUPPORTED_TYPE", f"{media_type} is not an accepted attachment")
    limit = (
        settings.chat_attachment_text_max_bytes
        if family == "text"
        else settings.chat_attachment_image_max_bytes
    )
    if len(data) > limit:
        raise UploadRefused(
            "UPLOAD_TOO_LARGE", f"a {family} attachment may be at most {limit} bytes"
        )
    if family == "text":
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UploadRefused("UPLOAD_NOT_UTF8", "text attachments must be UTF-8") from exc
        return
    if media_type == "image/webp":
        if not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
            raise UploadRefused("UPLOAD_NOT_AN_IMAGE", "the file is not a WebP image")
        return
    if not data.startswith(_MAGIC[media_type]):
        raise UploadRefused("UPLOAD_NOT_AN_IMAGE", f"the file is not a {media_type} image")


@dataclass(frozen=True, slots=True)
class ChatUploadRow:
    upload_id: UUID
    workspace_id: str
    uploaded_by_user_id: str
    filename: str
    media_type: str
    artifact_key: str
    sha256: str
    byte_count: int
    created_at: datetime


_COLUMNS = (
    "upload_id, workspace_id, uploaded_by_user_id, filename, media_type, artifact_key, sha256, "
    "byte_count, created_at"
)


async def record_chat_upload(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    user_id: str,
    filename: str,
    media_type: str,
    ref: ArtifactRef,
) -> ChatUploadRow:
    upload_id = uuid4()
    row = (
        (
            await conn.execute(
                text(
                    "INSERT INTO chat_upload (upload_id, workspace_id, uploaded_by_user_id, "
                    "filename, media_type, artifact_key, sha256, byte_count) "
                    "VALUES (:id, :ws, :user, :name, :media, :key, :sha, :bytes) "
                    f"RETURNING {_COLUMNS}"
                ),
                {
                    "id": upload_id,
                    "ws": workspace_id,
                    "user": user_id,
                    "name": filename,
                    "media": media_type,
                    "key": ref.artifact_key,
                    "sha": ref.sha256,
                    "bytes": ref.byte_count,
                },
            )
        )
        .mappings()
        .one()
    )
    return ChatUploadRow(**dict(row))


async def get_chat_uploads(
    conn: AsyncConnection, *, workspace_id: str, upload_ids: Sequence[UUID]
) -> dict[UUID, ChatUploadRow]:
    if not upload_ids:
        return {}
    rows = (
        await conn.execute(
            text(
                f"SELECT {_COLUMNS} FROM chat_upload WHERE workspace_id = :ws "
                "AND upload_id = ANY(CAST(:ids AS uuid[]))"
            ),
            {"ws": workspace_id, "ids": [str(value) for value in upload_ids]},
        )
    ).mappings()
    return {row["upload_id"]: ChatUploadRow(**dict(row)) for row in rows}
```

- [ ] **Step 4: Write the DB test**

```python
# tests/api/test_chat_uploads_db.py
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_agents.contracts import ArtifactRef
from clue_api.chat.uploads import get_chat_uploads, record_chat_upload
from clue_db import db_lifespan
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_record_then_get_is_workspace_scoped() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = f"ws_upl_{uuid4().hex[:8]}"
            sha = "c" * 64
            key = f"{ws}/{sha}"
            await conn.execute(
                text(
                    "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
                    "size_bytes) VALUES (:key, :ws, :sha, 'text/markdown', 4)"
                ),
                {"key": key, "ws": ws, "sha": sha},
            )
            ref = ArtifactRef(
                workspace_id=ws, artifact_key=key, sha256=sha, media_type="text/markdown",
                byte_count=4,
            )
            row = await record_chat_upload(
                conn, workspace_id=ws, user_id="usr_a", filename="notes.md",
                media_type="text/markdown", ref=ref,
            )
            assert row.filename == "notes.md" and row.artifact_key == key
            found = await get_chat_uploads(conn, workspace_id=ws, upload_ids=[row.upload_id])
            assert found[row.upload_id] == row
            assert await get_chat_uploads(conn, workspace_id="ws_other", upload_ids=[row.upload_id]) == {}
            await txn.rollback()

    run_async(scenario())
```

- [ ] **Step 5: Run both suites and the gates**

Run: `uv run pytest tests/api/test_chat_uploads.py tests/api/test_chat_uploads_db.py -v` → PASS.
Run: `uv run ruff check platform/api/clue_api/chat/uploads.py && uv run mypy platform/api/clue_api/chat/uploads.py` → clean.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/chat/uploads.py tests/api/test_chat_uploads.py tests/api/test_chat_uploads_db.py
git commit -m "feat(chat): upload validation and the chat_upload row"
```

---

### Task 5: Upload and bytes routes on `/frontend/v1`

**Files:**
- Create: `platform/api/clue_api/frontend_read/uploads.py`
- Modify: `platform/api/clue_api/frontend_read/app.py:302` (register after the project-document routes)
- Test: `tests/api/test_frontend_read_uploads_db.py`

**Interfaces:**
- Consumes: `DurableAgentArtifactStore.persist_body(*, workspace_id, data, media_type) -> ArtifactRef` and `.read(ref) -> bytes` (`platform/api/clue_api/agent_turn_wiring.py:236`); `principal_from_request(request)` (`clue_api.auth_wiring`), `WorkspaceDep`; Task 4's module.
- Produces:
  - `POST /frontend/v1/uploads` multipart field `file` → `201 {"data": {"upload_id", "filename", "media_type", "byte_count", "artifact_key", "sha256"}}`; refusals `{"code","message"}` with 413 for `UPLOAD_TOO_LARGE`, 415 for `UPLOAD_UNSUPPORTED_TYPE`, 422 for the others, 503 when storage is absent.
  - `GET /frontend/v1/uploads/{upload_id}/bytes` → the bytes with the stored media type and `Content-Disposition: inline; filename="…"`; 404 when the row is not in this workspace.
  - `register_upload_routes(router, *, conn_factory, storage, settings, allow_local_mutations)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_frontend_read_uploads_db.py
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from clue_api.frontend_read.app import build_frontend_read_router
from clue_config import Secrets, Settings
from clue_db import transaction
from clue_storage.fs import FsStorage
from tests._workspace import seed_workspace
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _client(tmp_path: Path, ws: str) -> TestClient:
    settings = Settings(
        frontend_read_enabled=True, projections_auth_mode="local_header", auth_enabled=False
    )
    app = FastAPI()
    app.include_router(
        build_frontend_read_router(
            settings=settings,
            secrets=Secrets(),
            conn_factory=transaction,
            evidence_storage=FsStorage(tmp_path),
        )
    )
    client = TestClient(app)
    client.headers.update({"X-Clue-Workspace-Id": ws})
    return client


def test_upload_then_read_bytes(tmp_path: Path) -> None:
    ws = f"ws_upl_route_{uuid4().hex[:8]}"
    run_async(_seed(ws))
    client = _client(tmp_path, ws)
    response = client.post(
        "/frontend/v1/uploads", files={"file": ("shot.png", PNG, "image/png")}
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["filename"] == "shot.png" and data["media_type"] == "image/png"
    assert data["byte_count"] == len(PNG)
    served = client.get(f"/frontend/v1/uploads/{data['upload_id']}/bytes")
    assert served.status_code == 200 and served.content == PNG
    assert served.headers["content-type"].startswith("image/png")


def test_upload_refuses_a_pdf(tmp_path: Path) -> None:
    ws = f"ws_upl_route_{uuid4().hex[:8]}"
    run_async(_seed(ws))
    client = _client(tmp_path, ws)
    response = client.post(
        "/frontend/v1/uploads", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}
    )
    assert response.status_code == 415
    assert response.json()["code"] == "UPLOAD_UNSUPPORTED_TYPE"


def test_bytes_are_absent_for_another_workspace(tmp_path: Path) -> None:
    ws = f"ws_upl_route_{uuid4().hex[:8]}"
    other = f"ws_upl_route_{uuid4().hex[:8]}"
    run_async(_seed(ws))
    run_async(_seed(other))
    client = _client(tmp_path, ws)
    upload_id = client.post(
        "/frontend/v1/uploads", files={"file": ("n.md", b"# n", "text/markdown")}
    ).json()["data"]["upload_id"]
    foreign = _client(tmp_path, other)
    assert foreign.get(f"/frontend/v1/uploads/{upload_id}/bytes").status_code == 404


async def _seed(ws: str) -> None:
    async with transaction() as conn:
        await seed_workspace(conn, ws)
```

Check `build_frontend_read_router`'s real keyword names at `platform/api/clue_api/frontend_read/app.py` (the builder that contains line 254) and `seed_workspace` in `tests/_workspace.py` before running; adjust the test's call to match them exactly.

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/api/test_frontend_read_uploads_db.py -v` → FAIL, 404 on `/frontend/v1/uploads`.

- [ ] **Step 3: Write the routes**

```python
# platform/api/clue_api/frontend_read/uploads.py
"""``POST /frontend/v1/uploads`` and ``GET /frontend/v1/uploads/{id}/bytes`` (spec 2026-09-18)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict

from clue_agents.contracts import ArtifactRef
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.auth_wiring import principal_from_request
from clue_api.chat.uploads import (
    UploadRefused,
    get_chat_uploads,
    record_chat_upload,
    resolve_media_type,
    sanitize_filename,
    validate_upload_bytes,
)
from clue_api.frontend_read.app import WorkspaceDep
from clue_config import Settings
from clue_db import ConnFactory
from clue_storage import StorageBackend

__all__ = ["UploadResponseV1", "UploadV1", "register_upload_routes"]

_STATUS = {"UPLOAD_TOO_LARGE": 413, "UPLOAD_UNSUPPORTED_TYPE": 415}


class UploadV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    upload_id: str
    filename: str
    media_type: str
    byte_count: int
    artifact_key: str
    sha256: str


class UploadResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: UploadV1


def register_upload_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    storage: StorageBackend | None,
    settings: Settings,
    allow_local_mutations: bool = False,
) -> None:
    artifacts = (
        None if storage is None else DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)
    )

    def _user_id(request: Request) -> str:
        principal = principal_from_request(request)
        if principal is not None:
            principal.require("project.write")
            return principal.user_id
        if allow_local_mutations:
            return "local-development-user"
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "An authenticated session is required."},
        )

    @router.post("/uploads", response_model=UploadResponseV1, status_code=201)
    async def post_upload(
        request: Request, workspace_id: WorkspaceDep, file: UploadFile = File(...)
    ) -> UploadResponseV1:
        user_id = _user_id(request)
        if artifacts is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "STORAGE_UNAVAILABLE", "message": "no artifact storage"},
            )
        data = await file.read()
        try:
            filename = sanitize_filename(file.filename or "attachment")
            media_type = resolve_media_type(declared=file.content_type, filename=filename)
            validate_upload_bytes(data=data, media_type=media_type, settings=settings)
        except UploadRefused as refusal:
            raise HTTPException(
                status_code=_STATUS.get(refusal.code, 422),
                detail={"code": refusal.code, "message": refusal.message},
            ) from refusal
        ref = await artifacts.persist_body(workspace_id=workspace_id, data=data, media_type=media_type)
        async with conn_factory() as conn:
            row = await record_chat_upload(
                conn, workspace_id=workspace_id, user_id=user_id, filename=filename,
                media_type=media_type, ref=ref,
            )
        return UploadResponseV1(
            data=UploadV1(
                upload_id=str(row.upload_id), filename=row.filename, media_type=row.media_type,
                byte_count=row.byte_count, artifact_key=row.artifact_key, sha256=row.sha256,
            )
        )

    @router.get("/uploads/{upload_id}/bytes")
    async def get_upload_bytes(upload_id: UUID, workspace_id: WorkspaceDep) -> Response:
        if artifacts is None:
            raise HTTPException(status_code=503, detail={"code": "STORAGE_UNAVAILABLE", "message": ""})
        async with conn_factory() as conn:
            row = (await get_chat_uploads(conn, workspace_id=workspace_id, upload_ids=[upload_id])).get(
                upload_id
            )
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "no such upload"})
        data = await artifacts.read(
            ArtifactRef(
                workspace_id=workspace_id, artifact_key=row.artifact_key, sha256=row.sha256,
                media_type=row.media_type, byte_count=row.byte_count,
            )
        )
        safe_name = row.filename.replace('"', "")
        return Response(
            content=data,
            media_type=row.media_type,
            headers={
                "Content-Disposition": f'inline; filename="{safe_name}"',
                "Cache-Control": "private, max-age=3600",
            },
        )
```

Register in `frontend_read/app.py` right after `register_project_document_routes(...)`:

```python
    from clue_api.frontend_read.uploads import register_upload_routes
    # Chat attachments: the upload receipt and the bytes behind a transcript chip (spec 2026-09-18).
    register_upload_routes(
        router,
        conn_factory=conn_factory,
        storage=evidence_storage,
        settings=settings,
        allow_local_mutations=allow_local_mutations,
    )
```

(Put the import with the other local imports near line 254.)

- [ ] **Step 4: Run the tests and gates**

Run: `uv run pytest tests/api/test_frontend_read_uploads_db.py -v` → PASS. `uv run ruff check platform/api/clue_api/frontend_read/uploads.py platform/api/clue_api/frontend_read/app.py && uv run mypy platform/api/clue_api/frontend_read/uploads.py` → clean. Also `uv run pytest tests/api/test_frontend_read_project_documents_db.py -q` (or the nearest existing frontend-read DB suite) to prove the router still builds.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/frontend_read/uploads.py platform/api/clue_api/frontend_read/app.py tests/api/test_frontend_read_uploads_db.py
git commit -m "feat(api): chat upload and upload-bytes routes on /frontend/v1"
```

---

### Task 6: Submission accepts `attachment_refs` — validation, persistence, capability

**Files:**
- Modify: `platform/api/clue_api/chat/schemas.py:232-238` (`AttachmentRefRequest`), `:657` (`_composer_capabilities`)
- Create: `platform/api/clue_api/chat/attachments.py`
- Modify: `platform/api/clue_api/agent_turn_submission.py` (`insert_submission` gains `attachment_refs`; new `submission_attachment_refs`)
- Modify: `platform/api/clue_api/chat/router.py:836-841`, `:2231-2236` (replace the refusals), `:657` (capability), replay comparisons at `:2321-2333` and `:937-944`
- Test: `tests/api/test_chat_attachment_refs.py` (pure), `tests/api/test_chat_attachment_refs_db.py`

**Interfaces:**
- Consumes: Task 4's `get_chat_uploads`, `attachment_family`; `Settings` limits from Task 2.
- Produces:
  - `AttachmentRefRequest` fields: `upload_id: UUID`, `artifact_key: str`, `sha256: str`, `media_type: str`, `byte_count: int`, `filename: str (1..255)`.
  - `class AttachmentReferenceError(Exception)` with `.code` in `{"ATTACHMENT_NOT_FOUND", "ATTACHMENT_MISMATCH", "ATTACHMENT_LIMIT_EXCEEDED", "ATTACHMENT_DUPLICATE"}` and `.message`.
  - `@dataclass(frozen=True) class ValidatedAttachment: upload_id: UUID; ref: ArtifactRef; filename: str; family: Literal["text","image"]`.
  - `async def validated_attachment_refs(conn, *, workspace_id, refs: Sequence[AttachmentRefRequest], settings: Settings) -> tuple[ValidatedAttachment, ...]`.
  - `insert_submission(..., attachment_refs: Sequence[ValidatedAttachment] = ())` writes `agent_turn_submission_attachment` rows in order.
  - `@dataclass(frozen=True) class SubmissionAttachmentRow: turn_id: UUID; ordinal: int; upload_id: UUID; ref: ArtifactRef; filename: str`.
  - `async def submission_attachment_refs(conn, *, workspace_id, turn_id) -> tuple[SubmissionAttachmentRow, ...]`.
  - `_composer_capabilities(storage_available: bool)` → `attachments=storage_available`.

- [ ] **Step 1: Write the pure validation test**

```python
# tests/api/test_chat_attachment_refs.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from clue_api.chat import attachments as module
from clue_api.chat.attachments import AttachmentReferenceError, validated_attachment_refs
from clue_api.chat.schemas import AttachmentRefRequest
from clue_api.chat.uploads import ChatUploadRow
from clue_config import Settings

WS = "ws-attach"


def _row(upload_id, *, media="image/png", size=10, name="a.png") -> ChatUploadRow:
    sha = "d" * 64
    return ChatUploadRow(
        upload_id=upload_id, workspace_id=WS, uploaded_by_user_id="usr", filename=name,
        media_type=media, artifact_key=f"{WS}/{sha}", sha256=sha, byte_count=size,
        created_at=datetime.now(UTC),
    )


def _request(row: ChatUploadRow, **overrides) -> AttachmentRefRequest:
    payload = dict(
        upload_id=row.upload_id, artifact_key=row.artifact_key, sha256=row.sha256,
        media_type=row.media_type, byte_count=row.byte_count, filename=row.filename,
    )
    payload.update(overrides)
    return AttachmentRefRequest(**payload)


def _run(refs, rows, settings=Settings()):
    async def fake_get(conn, *, workspace_id, upload_ids):
        return {r.upload_id: r for r in rows if r.workspace_id == workspace_id}

    module.get_chat_uploads = fake_get  # type: ignore[assignment]
    return asyncio.run(
        validated_attachment_refs(object(), workspace_id=WS, refs=refs, settings=settings)
    )


def test_matching_ref_validates_and_classifies() -> None:
    row = _row(uuid4())
    (validated,) = _run([_request(row)], [row])
    assert validated.family == "image" and validated.filename == "a.png"
    assert validated.ref.artifact_key == row.artifact_key


def test_mismatch_and_absence_refuse_by_code() -> None:
    row = _row(uuid4())
    with pytest.raises(AttachmentReferenceError) as missing:
        _run([_request(row)], [])
    assert missing.value.code == "ATTACHMENT_NOT_FOUND"
    with pytest.raises(AttachmentReferenceError) as mismatch:
        _run([_request(row, byte_count=99)], [row])
    assert mismatch.value.code == "ATTACHMENT_MISMATCH"


def test_limits_and_duplicates() -> None:
    rows = [_row(uuid4(), size=60) for _ in range(3)]
    small = Settings(chat_attachment_max_files=2)
    with pytest.raises(AttachmentReferenceError) as too_many:
        _run([_request(r) for r in rows], rows, small)
    assert too_many.value.code == "ATTACHMENT_LIMIT_EXCEEDED"
    tight = Settings(chat_attachment_max_total_bytes=100)
    with pytest.raises(AttachmentReferenceError) as too_big:
        _run([_request(r) for r in rows[:2]], rows, tight)
    assert too_big.value.code == "ATTACHMENT_LIMIT_EXCEEDED"
    with pytest.raises(AttachmentReferenceError) as dup:
        _run([_request(rows[0]), _request(rows[0])], rows)
    assert dup.value.code == "ATTACHMENT_DUPLICATE"
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/api/test_chat_attachment_refs.py -v` → FAIL (module missing / `upload_id` unknown field).

- [ ] **Step 3: Extend the schema**

In `chat/schemas.py`, replace `AttachmentRefRequest`:

```python
class AttachmentRefRequest(_Request):
    """A durable upload receipt (spec 2026-09-18); browser-local URLs have no field here."""

    upload_id: UUID
    artifact_key: str = Field(min_length=1, max_length=1000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str = Field(min_length=1, max_length=255)
    byte_count: int = Field(ge=0)
    filename: str = Field(min_length=1, max_length=255)
```

(`UUID` is already imported in that module; confirm, else add `from uuid import UUID`.)

- [ ] **Step 4: Write the validation module**

```python
# platform/api/clue_api/chat/attachments.py
"""Validate a submission's ``attachment_refs`` against the upload rows, fail-closed."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ArtifactRef
from clue_api.chat.schemas import AttachmentRefRequest
from clue_api.chat.uploads import attachment_family, get_chat_uploads
from clue_config import Settings

__all__ = ["AttachmentReferenceError", "ValidatedAttachment", "validated_attachment_refs"]


class AttachmentReferenceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ValidatedAttachment:
    upload_id: UUID
    ref: ArtifactRef
    filename: str
    family: Literal["text", "image"]


async def validated_attachment_refs(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    refs: Sequence[AttachmentRefRequest],
    settings: Settings,
) -> tuple[ValidatedAttachment, ...]:
    if not refs:
        return ()
    if len(refs) > settings.chat_attachment_max_files:
        raise AttachmentReferenceError(
            "ATTACHMENT_LIMIT_EXCEEDED",
            f"a message may carry at most {settings.chat_attachment_max_files} attachments",
        )
    ids = [ref.upload_id for ref in refs]
    if len(set(ids)) != len(ids) or len({ref.artifact_key for ref in refs}) != len(refs):
        raise AttachmentReferenceError(
            "ATTACHMENT_DUPLICATE", "the same file may be attached only once per message"
        )
    total = sum(ref.byte_count for ref in refs)
    if total > settings.chat_attachment_max_total_bytes:
        raise AttachmentReferenceError(
            "ATTACHMENT_LIMIT_EXCEEDED",
            f"attachments may total at most {settings.chat_attachment_max_total_bytes} bytes",
        )
    rows = await get_chat_uploads(conn, workspace_id=workspace_id, upload_ids=ids)
    validated: list[ValidatedAttachment] = []
    for ref in refs:
        row = rows.get(ref.upload_id)
        if row is None:
            raise AttachmentReferenceError(
                "ATTACHMENT_NOT_FOUND", "an attachment is not available in this workspace"
            )
        if (
            row.artifact_key != ref.artifact_key
            or row.sha256 != ref.sha256
            or row.media_type != ref.media_type
            or row.byte_count != ref.byte_count
            or row.filename != ref.filename
        ):
            raise AttachmentReferenceError(
                "ATTACHMENT_MISMATCH", "an attachment receipt does not match its upload"
            )
        family = attachment_family(row.media_type)
        if family is None:
            raise AttachmentReferenceError(
                "ATTACHMENT_MISMATCH", "an attachment has an unsupported media type"
            )
        validated.append(
            ValidatedAttachment(
                upload_id=row.upload_id,
                ref=ArtifactRef(
                    workspace_id=workspace_id, artifact_key=row.artifact_key, sha256=row.sha256,
                    media_type=row.media_type, byte_count=row.byte_count,
                ),
                filename=row.filename,
                family=family,
            )
        )
    return tuple(validated)
```

- [ ] **Step 5: Run the pure test**

Run: `uv run pytest tests/api/test_chat_attachment_refs.py -v` → PASS.

- [ ] **Step 6: Persist attachments with the submission**

In `agent_turn_submission.py`:

```python
@dataclass(frozen=True, slots=True)
class SubmissionAttachmentRow:
    turn_id: UUID
    ordinal: int
    upload_id: UUID
    ref: ArtifactRef
    filename: str
```

Add `attachment_refs: Sequence[ValidatedAttachment] = ()` to `insert_submission` (import `ValidatedAttachment` under `TYPE_CHECKING` from `clue_api.chat.attachments` to avoid a cycle, and type the parameter as `Sequence["ValidatedAttachment"]`). Immediately after the existing loop that inserts `agent_turn_submission_context_ref` rows for a *created* submission, add:

```python
        for ordinal, item in enumerate(attachment_refs):
            await conn.execute(
                text(
                    "INSERT INTO agent_turn_submission_attachment "
                    "(turn_id, workspace_id, ordinal, upload_id, artifact_key, sha256, "
                    " media_type, byte_count, filename) "
                    "VALUES (:turn, :ws, :ordinal, :upload, :key, :sha, :media, :bytes, :name)"
                ),
                {
                    "turn": turn_id, "ws": workspace_id, "ordinal": ordinal,
                    "upload": item.upload_id, "key": item.ref.artifact_key,
                    "sha": item.ref.sha256, "media": item.ref.media_type,
                    "bytes": item.ref.byte_count, "name": item.filename,
                },
            )
```

And the reader, next to `submission_context_refs`:

```python
async def submission_attachment_refs(
    conn: AsyncConnection, *, workspace_id: str, turn_id: UUID
) -> tuple[SubmissionAttachmentRow, ...]:
    rows = (
        await conn.execute(
            text(
                "SELECT turn_id, ordinal, upload_id, artifact_key, sha256, media_type, "
                "byte_count, filename FROM agent_turn_submission_attachment "
                "WHERE workspace_id = :ws AND turn_id = :turn ORDER BY ordinal"
            ),
            {"ws": workspace_id, "turn": turn_id},
        )
    ).mappings()
    return tuple(
        SubmissionAttachmentRow(
            turn_id=row["turn_id"], ordinal=int(row["ordinal"]), upload_id=row["upload_id"],
            ref=ArtifactRef(
                workspace_id=workspace_id, artifact_key=row["artifact_key"], sha256=row["sha256"],
                media_type=row["media_type"], byte_count=int(row["byte_count"]),
            ),
            filename=row["filename"],
        )
        for row in rows
    )
```

- [ ] **Step 7: Wire the router**

In `chat/router.py`:

1. `_composer_capabilities()` becomes `_composer_capabilities(*, storage_available: bool)` returning `attachments=storage_available`; update its two callers to pass `storage is not None`.
2. Delete both `if body.attachment_refs: raise _refuse(... CAPABILITY_UNAVAILABLE ...)` blocks.
3. Add a helper beside `_validated_submission_context`:

```python
async def _validated_submission_attachments(
    conn: AsyncConnection, *, workspace_id: str, refs: Sequence[AttachmentRefRequest]
) -> tuple[ValidatedAttachment, ...]:
    if refs and storage is None:
        raise _refuse(status_code=503, code="CAPABILITY_UNAVAILABLE",
                      message="this deployment has no artifact storage for attachments")
    try:
        return await validated_attachment_refs(
            conn, workspace_id=workspace_id, refs=refs, settings=settings
        )
    except AttachmentReferenceError as exc:
        status_code = {"ATTACHMENT_NOT_FOUND": 404, "ATTACHMENT_LIMIT_EXCEEDED": 422,
                       "ATTACHMENT_DUPLICATE": 422}.get(exc.code, 409)
        raise _refuse(status_code=status_code, code=exc.code, message=exc.message) from exc
```

4. Thread turn path (`~2362`, right after `context_refs = await _validated_submission_context(...)`): `attachments = await _validated_submission_attachments(conn, workspace_id=who.workspace_id, refs=body.attachment_refs)` and pass `attachment_refs=attachments` to `insert_submission`. In the replay branch (`~2321`), also compare: `existing_attachments = await submission_attachment_refs(conn, workspace_id=who.workspace_id, turn_id=turn_id)` and add `or tuple(a.upload_id for a in existing_attachments) != tuple(r.upload_id for r in body.attachment_refs)` to the `IDEMPOTENCY_CONFLICT` condition.
5. Home path (`~882` after context refs; `~937` replay compare; `~975` insert): the same three edits.

- [ ] **Step 8: Write the DB test**

```python
# tests/api/test_chat_attachment_refs_db.py
from __future__ import annotations

from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text

from clue_agents.contracts import ArtifactRef
from clue_api.agent_turn_submission import insert_submission, submission_attachment_refs
from clue_api.chat.attachments import ValidatedAttachment
from clue_api.chat.uploads import record_chat_upload
from clue_db import db_lifespan
from clue_storage.fs import FsStorage
from tests.api.test_project_document_context_refs_db import _seed, _submission_kwargs
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_attachments_persist_with_the_submission(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed(conn, FsStorage(tmp_path))
            ws = seeds["ws"]
            sha = "e" * 64
            key = f"{ws}/{sha}"
            await conn.execute(
                text("INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
                     "size_bytes) VALUES (:key, :ws, :sha, 'image/png', 8)"),
                {"key": key, "ws": ws, "sha": sha},
            )
            ref = ArtifactRef(workspace_id=ws, artifact_key=key, sha256=sha, media_type="image/png", byte_count=8)
            upload = await record_chat_upload(conn, workspace_id=ws, user_id=seeds["user_id"],
                                              filename="shot.png", media_type="image/png", ref=ref)
            kwargs = _submission_kwargs(seeds, "attach")
            _row, created = await insert_submission(
                conn, attachment_refs=(ValidatedAttachment(upload_id=upload.upload_id, ref=ref,
                                                          filename="shot.png", family="image"),),
                **kwargs,
            )
            assert created
            (stored,) = await submission_attachment_refs(conn, workspace_id=ws, turn_id=kwargs["turn_id"])
            assert stored.upload_id == upload.upload_id and stored.filename == "shot.png"
            assert stored.ref == ref
            await txn.rollback()

    run_async(scenario())
```

- [ ] **Step 9: Run tests and gates**

Run: `uv run pytest tests/api/test_chat_attachment_refs.py tests/api/test_chat_attachment_refs_db.py tests/api/test_project_document_context_refs_db.py tests/api/test_chat_composer_context.py -v` → PASS. Run the existing router suites that cover the capability wire and the submission route: `uv run pytest tests/api/test_home_project_bootstrap_db.py tests/api -k "chat_router or thread_shell" -q --ignore-glob='*_live.py'` → PASS (adjust any test that asserted `attachments=False` to assert it follows storage availability). `uv run ruff check platform/api/clue_api/chat platform/api/clue_api/agent_turn_submission.py && uv run mypy platform/api/clue_api/chat/attachments.py platform/api/clue_api/chat/router.py platform/api/clue_api/agent_turn_submission.py` → clean.

- [ ] **Step 10: Commit**

```bash
git add platform/api/clue_api/chat/schemas.py platform/api/clue_api/chat/attachments.py platform/api/clue_api/chat/router.py platform/api/clue_api/agent_turn_submission.py tests/api/test_chat_attachment_refs.py tests/api/test_chat_attachment_refs_db.py
git commit -m "feat(chat): submissions accept validated attachment_refs and persist them"
```

---

### Task 7: Text uploads become project documents at submit time

**Files:**
- Modify: `platform/api/clue_api/chat/attachments.py` (add `materialize_text_attachments`)
- Modify: `platform/api/clue_api/chat/router.py` (call it in both paths after `insert_submission` for a *created* submission; refresh the library after commit)
- Test: `tests/api/test_chat_attachment_documents_db.py`

**Interfaces:**
- Consumes: `write_project_document(conn, storage, ProjectDocumentWrite(...), document_id=None) -> WrittenDocument`, `current_document_version(conn, *, workspace_id, project_id, path)` (check its exact keywords at `arv2/project_documents.py:333`), `ProjectDocumentRefused`; `DurableAgentArtifactStore.read(ref)`; `project_library.refresh(workspace_id=…, project_id=…)`.
- Produces: `async def materialize_text_attachments(conn, storage, artifacts, *, workspace_id, brand_id, project_id, turn_id, user_id, attachments: Sequence[ValidatedAttachment]) -> tuple[WrittenDocument, ...]`. Path per file: `"attachments/" + filename`. Front matter stamped by this function before the store stamps its own: `kind: attachment`, `title: <filename>`, `source: user_upload`, `upload_id: <uuid>`.

- [ ] **Step 1: Write the failing DB test**

```python
# tests/api/test_chat_attachment_documents_db.py
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from clue_agents.contracts import ArtifactRef
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.project_documents import list_project_documents, read_project_document
from clue_api.chat.attachments import ValidatedAttachment, materialize_text_attachments
from clue_api.chat.uploads import record_chat_upload
from clue_db import db_lifespan
from clue_storage.fs import FsStorage
from tests._workspace import seed_project
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_text_upload_becomes_a_versioned_project_document(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path)
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = f"ws_attdoc_{uuid4().hex[:8]}"
            project = await seed_project(conn, ws, name="Attachment docs")

            async def bound():
                yield conn

            from contextlib import asynccontextmanager
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=asynccontextmanager(bound))

            async def attach(body: bytes) -> ValidatedAttachment:
                ref = await artifacts.persist_body(workspace_id=ws, data=body, media_type="text/markdown")
                row = await record_chat_upload(conn, workspace_id=ws, user_id="usr", filename="brief.md",
                                               media_type="text/markdown", ref=ref)
                return ValidatedAttachment(upload_id=row.upload_id, ref=ref, filename="brief.md", family="text")

            first = await attach(b"# Brief\n\nFirst cut.\n")
            (written,) = await materialize_text_attachments(
                conn, storage, artifacts, workspace_id=ws, brand_id=str(project.brand_id),
                project_id=project.project_id, turn_id=uuid4(), user_id="usr", attachments=[first],
            )
            assert written.path == "attachments/brief.md" and written.version == 1
            assert written.workspace_path == "project/attachments/brief.md"
            found = await read_project_document(conn, storage, workspace_id=ws,
                                                project_id=project.project_id, document_id=written.document_id)
            assert found is not None
            row, front, body = found
            assert row.kind == "attachment" and front["source"] == "user_upload"
            assert "First cut." in body

            # Same bytes, same name: no new version.
            again = await attach(b"# Brief\n\nFirst cut.\n")
            (replayed,) = await materialize_text_attachments(
                conn, storage, artifacts, workspace_id=ws, brand_id=str(project.brand_id),
                project_id=project.project_id, turn_id=uuid4(), user_id="usr", attachments=[again],
            )
            assert replayed.version == 1

            # Changed bytes, same name: version 2.
            changed = await attach(b"# Brief\n\nSecond cut.\n")
            (second,) = await materialize_text_attachments(
                conn, storage, artifacts, workspace_id=ws, brand_id=str(project.brand_id),
                project_id=project.project_id, turn_id=uuid4(), user_id="usr", attachments=[changed],
            )
            assert second.version == 2
            listed = await list_project_documents(conn, workspace_id=ws, project_id=project.project_id)
            assert [d.path for d in listed] == ["attachments/brief.md"]
            await txn.rollback()

    run_async(scenario())
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/api/test_chat_attachment_documents_db.py -v` → FAIL, `materialize_text_attachments` missing.

- [ ] **Step 3: Implement**

Append to `chat/attachments.py`:

```python
from clue_api.arv2.project_documents import (  # at top of file with the other imports
    ProjectDocumentWrite,
    WrittenDocument,
    current_document_version,
    write_project_document,
)
from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_agents.ports import AgentArtifactReader
from clue_storage import StorageBackend
import yaml  # PyYAML is already a dependency of the knowledge front-matter module


def _with_upload_front_matter(text_body: str, *, filename: str, upload_id: UUID) -> str:
    try:
        front, body = parse_front_matter(text_body, preserve_body=True)
    except ValueError:
        front, body = {}, text_body
    stamped = dict(front)
    stamped.update(
        {"kind": "attachment", "title": filename, "source": "user_upload", "upload_id": str(upload_id)}
    )
    header = yaml.safe_dump(stamped, sort_keys=True, allow_unicode=True).strip()
    return f"---\n{header}\n---\n{body.lstrip()}"


async def materialize_text_attachments(
    conn: AsyncConnection,
    storage: StorageBackend,
    artifacts: AgentArtifactReader,
    *,
    workspace_id: str,
    brand_id: str,
    project_id: str,
    turn_id: UUID,
    user_id: str,
    attachments: Sequence[ValidatedAttachment],
) -> tuple[WrittenDocument, ...]:
    """Write each text attachment as the next version of ``attachments/<filename>``.

    Identical bytes at the path are a no-op: the store's replay key includes the text digest and
    the expected version, and a document whose current bytes equal the upload is returned as-is.
    """

    written: list[WrittenDocument] = []
    for item in attachments:
        if item.family != "text":
            continue
        path = f"attachments/{item.filename}"
        text_body = (await artifacts.read(item.ref)).decode("utf-8")
        document_text = _with_upload_front_matter(
            text_body, filename=item.filename, upload_id=item.upload_id
        )
        current = await current_document_version(
            conn, workspace_id=workspace_id, project_id=project_id, path=path
        )
        if current is not None:
            existing = await read_project_document(
                conn, storage, workspace_id=workspace_id, project_id=project_id,
                document_id=current.document_id,
            )
            if existing is not None and existing[2].strip() == text_body.strip():
                written.append(
                    WrittenDocument(
                        document_id=current.document_id, path=path, version=current.version,
                        workspace_path=f"project/{path}", replayed=True,
                    )
                )
                continue
        written.append(
            await write_project_document(
                conn,
                storage,
                ProjectDocumentWrite(
                    workspace_id=workspace_id, brand_id=brand_id, project_id=project_id,
                    turn_id=turn_id, user_id=user_id, path=path, document_text=document_text,
                    expected_version=None if current is None else current.version,
                ),
            )
        )
    return tuple(written)
```

Before running: open `arv2/project_documents.py:333` and confirm what `current_document_version` returns (a row with `document_id` and `version`, or a bare int). If it returns an int, replace the `current.document_id` read with `get_project_document`'s row lookup by path via `list_project_documents` filtered on `path`. Also import `read_project_document` from the same module.

- [ ] **Step 4: Call it from the router**

In both submit paths, immediately after a *created* `insert_submission` (not on replay):

```python
                    if attachments and any(a.family == "text" for a in attachments):
                        assert storage is not None and artifacts is not None
                        try:
                            await materialize_text_attachments(
                                conn, storage, artifacts,
                                workspace_id=who.workspace_id, brand_id=project.brand_id,
                                project_id=project_id, turn_id=turn_id, user_id=who.user_id,
                                attachments=attachments,
                            )
                        except ProjectDocumentRefused as refusal:
                            raise _refuse(status_code=422, code="ATTACHMENT_DOCUMENT_REFUSED",
                                          message=refusal.args[0]) from refusal
                        wrote_attachment_documents = True
```

Declare `wrote_attachment_documents = False` beside `pinned_project_icp = False` in the thread path (and at the top of the Home handler), and after the transaction commits, where the router already refreshes the library for a pinned ICP (`~2717`), extend the condition: `if project_library is not None and (pinned_project_icp or wrote_attachment_documents):`. For the Home path add the same post-commit refresh block after its `async with conn_factory()` exits.

- [ ] **Step 5: Run tests and gates**

Run: `uv run pytest tests/api/test_chat_attachment_documents_db.py tests/api/test_chat_attachment_refs_db.py -v` → PASS. `uv run ruff check platform/api/clue_api/chat && uv run mypy platform/api/clue_api/chat/attachments.py platform/api/clue_api/chat/router.py` → clean.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/chat/attachments.py platform/api/clue_api/chat/router.py tests/api/test_chat_attachment_documents_db.py
git commit -m "feat(chat): text attachments become versioned project documents at submit"
```

---

### Task 8: The fleet passes attachments to the turn; L7 describes them

**Files:**
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py:417-422` (read attachments beside the focus refs), `:861-880` (`attachment_refs=` on the request)
- Modify: `platform/agents/clue_agents/context.py:540-600` (`TurnLayerSource` gets an `attachments` describer)
- Create: `platform/api/clue_api/attachment_binding.py` (`DbAttachmentDescriber`)
- Modify: `platform/api/clue_api/agent_platform_wiring.py:483-525` (`build_agent_context_assembler` gains `attachment_describer`), `platform/api/clue_api/conversation_turns.py:580` (pass it)
- Test: `tests/agents/test_turn_layer_attachments.py` (pure), `tests/api/test_attachment_binding_db.py`

**Interfaces:**
- Produces in `clue_agents.context`:
  ```python
  class AttachmentDescription(Protocol):
      @property
      def filename(self) -> str: ...
      @property
      def workspace_path(self) -> str | None: ...   # project/attachments/<name> for text, None for images

  class AttachmentDescriber(Protocol):
      async def describe(self, request: AgentTurnRequest) -> Mapping[str, AttachmentDescription]: ...  # keyed by artifact_key
  ```
  `TurnLayerSource(artifacts, *, captured_turn=None, attachments: AttachmentDescriber | None = None)`.
- Produces in `clue_api.attachment_binding`: `DbAttachmentDescriber(conn_factory=transaction)` whose `describe` reads `agent_turn_submission_attachment` for `request.turn_id` and, for text rows, the highest servable `brand_knowledge_document` version at `attachments/<filename>` in `request.constitution.project_id` to fill `workspace_path`.
- Fleet: `attachment_refs=tuple(item.ref for item in await submission_attachment_refs(conn, workspace_id=workspace_id, turn_id=turn_id))`.

- [ ] **Step 1: Write the pure L7 test**

```python
# tests/agents/test_turn_layer_attachments.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from clue_agents.context import TurnLayerSource
from clue_agents.contracts import AgentTurnRequest, ArtifactRef
from tests.agents.conftest import constitution_for_tests  # the existing helper that builds a valid AgentConstitution

WS = "ws-l7"


class _Reader:
    def __init__(self, bodies): self._bodies = bodies
    async def read(self, ref): return self._bodies[ref.artifact_key]


class _Describer:
    def __init__(self, table): self._table = table
    async def describe(self, request): return self._table


class _Desc:
    def __init__(self, filename, workspace_path): self.filename = filename; self.workspace_path = workspace_path


def _ref(key: str, media: str, size: int) -> ArtifactRef:
    return ArtifactRef(workspace_id=WS, artifact_key=f"{WS}/{key * 64}", sha256=key * 64, media_type=media, byte_count=size)


def test_l7_names_text_and_image_attachments_in_plain_words() -> None:
    message = _ref("a", "text/plain", 5)
    doc = _ref("b", "text/markdown", 120)
    shot = _ref("c", "image/png", 4096)
    request = AgentTurnRequest(
        turn_id=uuid4(), thread_id="thr_l7", constitution=constitution_for_tests(WS),
        user_message_artifact_ref=message, attachment_refs=(doc, shot),
        requested_at=datetime.now(UTC),
    )
    source = TurnLayerSource(
        _Reader({message.artifact_key: b"hello", doc.artifact_key: b"# d", shot.artifact_key: b"png"}),
        attachments=_Describer({
            doc.artifact_key: _Desc("brief.md", "project/attachments/brief.md"),
            shot.artifact_key: _Desc("shot.png", None),
        }),
    )
    candidates = asyncio.run(source.load(request=request, profile=None, history=()))
    bodies = [c.body for c in candidates]
    assert any('Attachment "brief.md" (text/markdown, 120 bytes) is readable at project/attachments/brief.md' in b for b in bodies)
    assert any('Attachment "shot.png" (image/png, 4,096 bytes) is attached to this message as an image' in b for b in bodies)
    assert candidates[-1].body == "hello" and candidates[-1].role == "user"
```

If `tests/agents/conftest.py` has no constitution helper, look for how `AgentConstitution` is built in `tests/agents/test_context_assembly.py` (or the nearest context test) and reuse that builder by import.

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/agents/test_turn_layer_attachments.py -v` → FAIL (`attachments` kwarg unknown; old pointer text).

- [ ] **Step 3: Implement the L7 change**

In `clue_agents/context.py`, add after `CapturedTurnDescription`:

```python
class AttachmentDescription(Protocol):
    @property
    def filename(self) -> str: ...

    @property
    def workspace_path(self) -> str | None: ...


class AttachmentDescriber(Protocol):
    """Name each attachment by its filename and, for text, where it is readable in the workspace."""

    async def describe(self, request: AgentTurnRequest) -> Mapping[str, AttachmentDescription]: ...
```

`TurnLayerSource.__init__` gains `attachments: AttachmentDescriber | None = None` stored as `self._attachments`. In `load`, replace the attachment loop:

```python
        described = (
            await self._attachments.describe(request) if self._attachments is not None else {}
        )
        for index, ref in enumerate(request.attachment_refs):
            info = described.get(ref.artifact_key)
            size = f"{ref.byte_count:,} bytes"
            if info is None:
                body = (
                    "Attachment reference only: "
                    f"artifact_key={ref.artifact_key} sha256={ref.sha256} "
                    f"media_type={ref.media_type} byte_count={ref.byte_count}"
                )
            elif info.workspace_path is not None:
                body = (
                    f'Attachment "{info.filename}" ({ref.media_type}, {size}) is readable at '
                    f"{info.workspace_path}. Open it with read_file when the message needs it."
                )
            else:
                body = (
                    f'Attachment "{info.filename}" ({ref.media_type}, {size}) is attached to this '
                    "message as an image."
                )
            result.append(
                ContextCandidate(
                    stable_key=f"200-{index:06d}-attachment:{ref.artifact_key}",
                    ref=ref,
                    body=body,
                    role="system",
                )
            )
```

- [ ] **Step 4: Run the pure test**

Run: `uv run pytest tests/agents/test_turn_layer_attachments.py tests/agents -k "context" -q` → PASS (the older pointer-only assertion, if any test has one, still passes because a missing describer keeps the old text).

- [ ] **Step 5: The describer and the fleet**

```python
# platform/api/clue_api/attachment_binding.py
"""Name a turn's attachments for L7 from the submission rows (spec 2026-09-18 §3.4)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import text

from clue_agents.contracts import AgentTurnRequest
from clue_api.agent_turn_submission import submission_attachment_refs
from clue_api.chat.uploads import attachment_family
from clue_db import ConnFactory, transaction

__all__ = ["DbAttachmentDescriber", "DescribedAttachment"]


@dataclass(frozen=True, slots=True)
class DescribedAttachment:
    filename: str
    workspace_path: str | None


class DbAttachmentDescriber:
    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def describe(self, request: AgentTurnRequest) -> Mapping[str, DescribedAttachment]:
        workspace_id = request.constitution.workspace_id
        async with self._conn_factory() as conn:
            rows = await submission_attachment_refs(
                conn, workspace_id=workspace_id, turn_id=request.turn_id
            )
            result: dict[str, DescribedAttachment] = {}
            for row in rows:
                path = None
                if attachment_family(row.ref.media_type) == "text":
                    served = (
                        await conn.execute(
                            text(
                                "SELECT 1 FROM brand_knowledge_document WHERE workspace_id = :ws "
                                "AND project_id = :project AND path = :path "
                                "AND status IN ('ready', 'proposed', 'confirmed') "
                                "AND artifact_key IS NOT NULL LIMIT 1"
                            ),
                            {"ws": workspace_id, "project": request.constitution.project_id,
                             "path": f"attachments/{row.filename}"},
                        )
                    ).first()
                    path = f"project/attachments/{row.filename}" if served else None
                result[row.ref.artifact_key] = DescribedAttachment(row.filename, path)
        return result
```

Fleet (`agent_turn_fleet_wiring.py` ~418): after `submission_focus_refs = ...` add
`submission_attachments = await submission_attachment_refs(conn, workspace_id=workspace_id, turn_id=turn_id)`; at the `AgentTurnRequest(` construction add `attachment_refs=tuple(item.ref for item in submission_attachments),`.

`build_agent_context_assembler` gains `attachment_describer: AttachmentDescriber | None = None` and passes `attachments=attachment_describer` into `TurnLayerSource(...)`. `conversation_turns.py:580` passes `attachment_describer=DbAttachmentDescriber(conn_factory=conn_factory)`.

- [ ] **Step 6: DB test for the describer**

```python
# tests/api/test_attachment_binding_db.py
# Seed with tests.api.test_project_document_context_refs_db._seed, insert a submission with one text
# and one image attachment (as in test_chat_attachment_refs_db), materialize the text one with
# materialize_text_attachments, then build an AgentTurnRequest whose constitution names the seeded
# workspace/project and turn_id = the submission's turn_id, and assert:
#   described[text_key].workspace_path == "project/attachments/brief.md"
#   described[image_key].workspace_path is None and .filename == "shot.png"
```

Write it out fully following the two neighbouring DB tests' seeding; the assertions above are the contract.

- [ ] **Step 7: Run tests and gates**

Run: `uv run pytest tests/agents/test_turn_layer_attachments.py tests/api/test_attachment_binding_db.py tests/api -k "fleet_wiring and not live" -q` → PASS. `uv run ruff check platform/agents/clue_agents/context.py platform/api/clue_api/attachment_binding.py platform/api/clue_api/agent_turn_fleet_wiring.py platform/api/clue_api/agent_platform_wiring.py platform/api/clue_api/conversation_turns.py && uv run mypy` on the same files → clean.

- [ ] **Step 8: Commit**

```bash
git add platform/agents/clue_agents/context.py platform/api/clue_api/attachment_binding.py platform/api/clue_api/agent_turn_fleet_wiring.py platform/api/clue_api/agent_platform_wiring.py platform/api/clue_api/conversation_turns.py tests/agents/test_turn_layer_attachments.py tests/api/test_attachment_binding_db.py
git commit -m "feat(agents): turns carry attachments; L7 names each file and where it is readable"
```

---

### Task 9: Images reach the model — the sending turn (ruling 1)

**Files:**
- Modify: `platform/agents/clue_agents/context.py:118-141` (`ContextCandidate.image_refs`), `:645-655` (`_message`), `:540-640` (L7 builds the user message with `image_refs`), `:815-825` (final-message check), the `_retain` count
- Test: `tests/agents/test_context_image_parts.py`

**Interfaces:**
- Produces: `ContextCandidate.image_refs: tuple[ArtifactRef, ...] = ()`; `IMAGE_TOKEN_ALLOWANCE = 1_000`; `_message(candidate, images: Mapping[str, bytes]) -> BaseMessage` where a candidate with `image_refs` yields `HumanMessage(content=[{"type": "text", "text": body}, {"type": "image_url", "image_url": {"url": "data:<media>;base64,<b64>"}}, ...])`. The assembler reads each image's bytes once through its artifact reader and passes them in. The final-message check compares the text part when content is a list.

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_context_image_parts.py
from __future__ import annotations

import base64

from langchain_core.messages import HumanMessage

from clue_agents.context import IMAGE_TOKEN_ALLOWANCE, ContextCandidate, _message
from clue_agents.contracts import ArtifactRef

WS = "ws-img"


def _ref(key: str, media: str) -> ArtifactRef:
    return ArtifactRef(workspace_id=WS, artifact_key=f"{WS}/{key * 64}", sha256=key * 64, media_type=media, byte_count=3)


def test_user_candidate_with_images_becomes_multipart() -> None:
    shot = _ref("a", "image/png")
    candidate = ContextCandidate(
        stable_key="999-user-message", ref=_ref("b", "text/plain"), body="what is this?",
        role="user", origin="current_user_instruction", image_refs=(shot,),
    )
    message = _message(candidate, {shot.artifact_key: b"png"})
    assert isinstance(message, HumanMessage)
    assert message.content[0] == {"type": "text", "text": "what is this?"}
    assert message.content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64," + base64.b64encode(b"png").decode("ascii")},
    }


def test_candidate_without_images_is_unchanged() -> None:
    candidate = ContextCandidate(stable_key="k", ref=_ref("c", "text/plain"), body="plain", role="user")
    assert _message(candidate, {}).content == "plain"


def test_budget_text_counts_an_allowance_per_image() -> None:
    shot = _ref("a", "image/png")
    candidate = ContextCandidate(stable_key="k", ref=_ref("c", "text/plain"), body="x", role="user", image_refs=(shot, shot))
    assert candidate.image_token_allowance == 2 * IMAGE_TOKEN_ALLOWANCE
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/agents/test_context_image_parts.py -v` → FAIL.

- [ ] **Step 3: Implement**

In `ContextCandidate`:

```python
    #: Images the model sees beside this candidate's text (spec 2026-09-18, ruling 1 and 2).
    image_refs: tuple[ArtifactRef, ...] = ()

    @property
    def image_token_allowance(self) -> int:
        return IMAGE_TOKEN_ALLOWANCE * len(self.image_refs)
```

with `IMAGE_TOKEN_ALLOWANCE = 1_000` at module level (a reporting allowance; the budget never fails a turn).

`_message`:

```python
def _message(candidate: ContextCandidate, images: Mapping[str, bytes]) -> BaseMessage:
    if candidate.role == "user" and candidate.image_refs:
        parts: list[dict[str, Any]] = [{"type": "text", "text": candidate.body}]
        for ref in candidate.image_refs:
            encoded = base64.b64encode(images[ref.artifact_key]).decode("ascii")
            parts.append({"type": "image_url", "image_url": {"url": f"data:{ref.media_type};base64,{encoded}"}})
        return HumanMessage(content=parts)
    if candidate.role == "system": ...   # unchanged branches follow
```

Assembler: where candidates become messages, read bytes for every `image_refs` entry once (`images[ref.artifact_key] = await self._artifacts.read(ref)`; the assembler already holds the artifact reader through its sources — give `DeterministicAgentContextAssembler.__init__` an `artifacts: AgentArtifactReader | None = None` parameter, passed by `build_agent_context_assembler`, and raise `ValueError("image candidates need an artifact reader")` when a candidate has images and none was given). In `_retain`, count `self._counter.count(candidate.budget_text) + candidate.image_token_allowance`. The final check:

```python
        final = messages[-1]
        final_text = (
            final.content if isinstance(final.content, str)
            else next(p["text"] for p in final.content if p.get("type") == "text")
        )
        if not isinstance(final, HumanMessage) or final_text != current_instruction.body:
            raise ValueError("current user instruction must be the final opening-context message")
```

L7 (`TurnLayerSource.load`): the final user candidate gets
`image_refs=tuple(ref for ref in request.attachment_refs if ref.media_type.lower().startswith("image/"))`.

Receipts: the manifest's `source_refs` for L7 already lists the attachment refs (they are candidates of their own), so nothing else changes.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/agents/test_context_image_parts.py tests/agents/test_turn_layer_attachments.py tests/agents -k "context or assembler" -q` → PASS. `uv run ruff check platform/agents/clue_agents/context.py platform/api/clue_api/agent_platform_wiring.py && uv run mypy platform/agents/clue_agents/context.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add platform/agents/clue_agents/context.py platform/api/clue_api/agent_platform_wiring.py tests/agents/test_context_image_parts.py
git commit -m "feat(agents): the sending turn's images ride the user message as image parts"
```

---

### Task 10: Images stay in the conversation (ruling 2)

**Files:**
- Modify: `platform/agents/clue_agents/ports.py:77-83` (`HistoryMessageRef.attachment_refs`)
- Modify: `platform/agents/clue_agents/context.py:481-511` (`HistoryLayerSource(artifacts, *, images_max=20)`)
- Create: `platform/api/clue_api/turn_attachments.py` (`turn_image_refs`)
- Modify: `platform/api/clue_api/design_leg_wiring.py:365-420` (`load_head_of_abm_history`), `platform/api/clue_api/agent_turn_wiring.py:1385-1420` (`DbAgentHistoryStore.load`)
- Modify: `platform/api/clue_api/agent_platform_wiring.py` (`AgentPlatformComponents.history_images_max: int`; set from `settings.chat_attachment_history_images_max`; `build_agent_context_assembler(history_images_max=…)`), `platform/api/clue_api/conversation_turns.py:580` (pass `components.history_images_max`)
- Test: `tests/agents/test_history_image_parts.py`, `tests/api/test_turn_attachments_db.py`

**Interfaces:**
- `HistoryMessageRef.attachment_refs: tuple[ArtifactRef, ...] = ()`.
- `async def turn_image_refs(conn, *, workspace_id: str, turn_ids: Sequence[UUID]) -> dict[UUID, tuple[ArtifactRef, ...]]` reading `agent_artifact_ref r JOIN artifact a ON a.storage_key = r.artifact_key WHERE r.workspace_id=:ws AND r.owner_kind='turn' AND r.ref_role='attachment' AND r.turn_id = ANY(:ids) AND a.media_type LIKE 'image/%' AND a.erased_at IS NULL ORDER BY r.turn_id, r.ordinal`.
- `HistoryLayerSource.load` sets `image_refs` on each *user* candidate from `item.attachment_refs`, keeping only the most recent `images_max` images across the thread (`0` = all).

- [ ] **Step 1: Write the pure history test**

```python
# tests/agents/test_history_image_parts.py
from __future__ import annotations

import asyncio
from uuid import uuid4

from clue_agents.context import HistoryLayerSource
from clue_agents.contracts import ArtifactRef
from clue_agents.ports import HistoryMessageRef

WS = "ws-hist"


def _ref(key: str, media: str) -> ArtifactRef:
    return ArtifactRef(workspace_id=WS, artifact_key=f"{WS}/{key * 64}", sha256=key * 64, media_type=media, byte_count=1)


class _Reader:
    async def read(self, ref): return b"body"


def _user(seq: int, images: tuple[ArtifactRef, ...]) -> HistoryMessageRef:
    return HistoryMessageRef(message_id=uuid4(), turn_id=uuid4(), sequence=seq, role="user",
                             body_ref=_ref(str(seq), "text/plain"), attachment_refs=images)


def _load(history, images_max):
    from tests.agents.test_turn_layer_attachments import constitution_for_tests  # same helper as Task 8
    from clue_agents.contracts import AgentTurnRequest
    from datetime import UTC, datetime
    request = AgentTurnRequest(turn_id=uuid4(), thread_id="t", constitution=constitution_for_tests(WS),
                               user_message_artifact_ref=_ref("z", "text/plain"), requested_at=datetime.now(UTC))
    return asyncio.run(HistoryLayerSource(_Reader(), images_max=images_max).load(request=request, profile=None, history=history))


def test_prior_user_messages_keep_their_images() -> None:
    a, b = _ref("a", "image/png"), _ref("b", "image/jpeg")
    out = _load([_user(1, (a,)), _user(2, (b,))], images_max=0)
    assert out[0].image_refs == (a,) and out[1].image_refs == (b,)


def test_cap_keeps_the_most_recent_images() -> None:
    a, b, c = _ref("a", "image/png"), _ref("b", "image/png"), _ref("c", "image/png")
    out = _load([_user(1, (a, b)), _user(2, (c,))], images_max=2)
    assert out[0].image_refs == (b,) and out[1].image_refs == (c,)
```

- [ ] **Step 2: Run to see it fail** → FAIL (`attachment_refs` unknown on `HistoryMessageRef`).

- [ ] **Step 3: Implement**

`ports.py`: add `attachment_refs: tuple[ArtifactRef, ...] = ()` to `HistoryMessageRef`.

`context.py` `HistoryLayerSource`:

```python
    def __init__(self, artifacts: AgentArtifactReader, *, images_max: int = 20) -> None:
        self._artifacts = artifacts
        self._images_max = images_max

    async def load(self, *, request, profile, history):
        del profile
        ordered = sorted(history, key=lambda value: value.sequence)
        # Ruling 2 (2026-09-18): prior images ride history as image parts; the newest win the cap.
        budget = None if self._images_max == 0 else self._images_max
        kept: dict[int, tuple[ArtifactRef, ...]] = {}
        for item in reversed(ordered):
            images = tuple(r for r in item.attachment_refs if r.media_type.lower().startswith("image/"))
            if item.role != "user" or not images:
                continue
            if budget is None:
                kept[item.sequence] = images
            elif budget > 0:
                take = images[-budget:]
                kept[item.sequence] = take
                budget -= len(take)
        result = []
        for item in ordered:
            ...existing body read and workspace check...
            result.append(ContextCandidate(..., image_refs=kept.get(item.sequence, ())))
        return result
```

`turn_attachments.py`: the query above returning `dict[UUID, tuple[ArtifactRef, ...]]`. Both history loaders call it once for the page's turn ids and set `attachment_refs=images.get(row["turn_id"], ())` on each `HistoryMessageRef`.

Wiring: `AgentPlatformComponents` gains `history_images_max: int`; `build_agent_platform_components` sets it from `settings.chat_attachment_history_images_max`; `build_agent_context_assembler(..., history_images_max: int = 20)` passes it to `HistoryLayerSource`; `conversation_turns.py` passes `history_images_max=components.history_images_max`.

- [ ] **Step 4: DB test for `turn_image_refs`**

```python
# tests/api/test_turn_attachments_db.py
# Seed a submission with one image attachment (Task 6's DB test), then insert the turn's
# agent_artifact_ref rows the way agent_turn_wiring does (owner_kind='turn', ref_role='attachment',
# ordinal 0) — the simplest path is to insert the agent_turn row + the ref row by SQL — and assert
# turn_image_refs(conn, workspace_id=ws, turn_ids=[turn_id]) == {turn_id: (image_ref,)} and that a
# text/markdown ref on the same turn is NOT returned.
```

Write it in full following `tests/api/test_chat_attachment_refs_db.py`'s seeding; the two assertions are the contract.

- [ ] **Step 5: Run tests and gates**

Run: `uv run pytest tests/agents/test_history_image_parts.py tests/api/test_turn_attachments_db.py tests/agents -k "history or context" -q` → PASS. Ruff and mypy on every file touched → clean.

- [ ] **Step 6: Commit**

```bash
git add platform/agents/clue_agents/ports.py platform/agents/clue_agents/context.py platform/api/clue_api/turn_attachments.py platform/api/clue_api/design_leg_wiring.py platform/api/clue_api/agent_turn_wiring.py platform/api/clue_api/agent_platform_wiring.py platform/api/clue_api/conversation_turns.py tests/agents/test_history_image_parts.py tests/api/test_turn_attachments_db.py
git commit -m "feat(agents): prior turns' images stay in the conversation, capped by setting"
```

---

### Task 11: Transcript presentation — filenames and image bytes on attachment refs

**Files:**
- Modify: `platform/api/clue_api/chat/composer_context.py:619` (`PRESENTED_REF_TYPES` adds `"artifact"`), `:658-760` (`context_ref_presentations` attachment branch)
- Modify: `platform/api/clue_api/chat/stream.py:322-350` (pending-submission refs include attachments)
- Modify: `apps/frontend/src/features/projects/model/chat-message.ts:27-51` (`upload_id` → `uploadId`)
- Modify: `apps/frontend/src/features/projects/components/chat-transcript.tsx:100-153` (render `flavor === "attachment"` chips)
- Modify: `apps/frontend/src/features/projects/model/chat-message-presentation.ts` (add `chatUploadBytesUrl(uploadId)`)
- Test: `tests/api/test_chat_attachment_presentation_db.py`; `apps/frontend/src/features/projects/model/chat-message-presentation.test.ts`, `apps/frontend/src/features/projects/model/chat-message.test.ts` (extend or create)

**Interfaces:**
- Backend presentation for `("artifact", <artifact_key>)` whose key is a chat upload cited by the turn: `{"label": filename, "media_type": media_type, "upload_id": str(upload_id)}`. Source: `agent_turn_submission_attachment` rows for the page's turns (join by `artifact_key`; the ref's `object_id` is the artifact key).
- Wire: `refs[].upload_id: string | null`.
- Frontend: `chatUploadBytesUrl(uploadId: string) => "/api/clue/frontend/v1/uploads/" + uploadId + "/bytes"`.

- [ ] **Step 1: Backend test**

```python
# tests/api/test_chat_attachment_presentation_db.py
# Seed (Task 6 DB test), insert a submission with one image + one text attachment, then call
# context_ref_presentations(conn, workspace_id=ws, refs=(MessageObjectRef(flavor="attachment",
# workspace_id=ws, object_type="artifact", object_id=<image key>, version=None, ordinal=0), ...),
# storage=None) and assert result[("artifact", <image key>)] == {"label": "shot.png",
# "media_type": "image/png", "upload_id": str(upload.upload_id)} and the text one likewise.
```

Write it in full. `MessageObjectRef` is `clue_projections.thread_refs.MessageObjectRef`.

- [ ] **Step 2: Run to see it fail** → FAIL (no presentation for artifact refs).

- [ ] **Step 3: Implement backend**

In `context_ref_presentations`, add a branch:

```python
    artifact_keys = tuple(dict.fromkeys(str(ref.object_id) for ref in refs if ref.object_type == "artifact"))
    if artifact_keys:
        rows = (
            await conn.execute(
                text(
                    "SELECT DISTINCT ON (artifact_key) artifact_key, upload_id, filename, media_type "
                    "FROM agent_turn_submission_attachment WHERE workspace_id = :ws "
                    "AND artifact_key = ANY(:keys) ORDER BY artifact_key, created_at DESC"
                ),
                {"ws": workspace_id, "keys": list(artifact_keys)},
            )
        ).mappings()
        for row in rows:
            result[("artifact", str(row["artifact_key"]))] = {
                "label": str(row["filename"]), "media_type": str(row["media_type"]),
                "upload_id": str(row["upload_id"]),
            }
```

Add `"artifact"` to `PRESENTED_REF_TYPES`. In `stream.py`'s pending-submission shape, add the attachment refs after the context refs: read `submission_attachment_refs` for each pending turn and append `{"flavor": "attachment", "workspace_id": ws, "object_type": "artifact", "object_id": item.ref.artifact_key, "version": None, "ordinal": item.ordinal, "label": item.filename, "media_type": item.ref.media_type, "upload_id": str(item.upload_id)}`.

Also add `upload_id: str | None = None` wherever the ref wire model in `chat/schemas.py` enumerates presentation fields (search for `thumbnail_digest` in that file and mirror it).

- [ ] **Step 4: Frontend model + presentation helper**

`chat-message.ts`: add `upload_id: z.string().nullable().default(null)` to `MessageRefWireSchema`, `uploadId: string | null` to `ChatMessageRef`, and map it in the converter. `chat-message-presentation.ts`:

```ts
export function chatUploadBytesUrl(uploadId: string): string {
  return `/api/clue/frontend/v1/uploads/${encodeURIComponent(uploadId)}/bytes`;
}
```

Test (`chat-message-presentation.test.ts`, append):

```ts
test("chat upload bytes url is the BFF upload route", () => {
  assert.equal(chatUploadBytesUrl("11111111-2222-3333-4444-555555555555"),
    "/api/clue/frontend/v1/uploads/11111111-2222-3333-4444-555555555555/bytes");
});
```

- [ ] **Step 5: Transcript chips**

In `chat-transcript.tsx`, change the refs block to include both flavors: filter `ref.flavor === "context" || ref.flavor === "attachment"`. For `flavor === "attachment"` render:

```tsx
<span className={ref.mediaType?.startsWith("image/") ? styles.messageReferenceImage : undefined}
      key={`${ref.ordinal}:attachment:${ref.objectId}`} title={ref.label ?? "Attachment"}>
  {ref.mediaType?.startsWith("image/") && ref.uploadId ? (
    <Image alt="" className={styles.messageReferenceThumbnail} height={18} width={18} unoptimized
           src={chatUploadBytesUrl(ref.uploadId)} />
  ) : (
    <ProjectIcon name="file-text" size={12} />
  )}
  {ref.label ?? "Attachment"}
</span>
```

Keep the existing `context` branch byte-for-byte.

- [ ] **Step 6: Run tests and gates**

Backend: `uv run pytest tests/api/test_chat_attachment_presentation_db.py tests/api -k "stream and not live" -q` → PASS; ruff + mypy on the two backend files. Frontend: `cd apps/frontend && npm test && npm run lint` → PASS, 0 errors.

- [ ] **Step 7: Commit**

```bash
git add platform/api/clue_api/chat/composer_context.py platform/api/clue_api/chat/stream.py platform/api/clue_api/chat/schemas.py tests/api/test_chat_attachment_presentation_db.py apps/frontend/src/features/projects/model/chat-message.ts apps/frontend/src/features/projects/model/chat-message-presentation.ts apps/frontend/src/features/projects/model/chat-message-presentation.test.ts apps/frontend/src/features/projects/components/chat-transcript.tsx
git commit -m "feat(transcript): attachment refs carry filename, media type and an upload id; chips render"
```

---

### Task 12: Frontend attachments model, upload adapter, and hook

**Files:**
- Create: `apps/frontend/src/features/projects/model/chat-attachments.ts`
- Create: `apps/frontend/src/features/projects/data/uploads.repository.ts`
- Create: `apps/frontend/src/features/projects/hooks/use-chat-attachments.ts`
- Modify: `apps/frontend/src/features/projects/model/project-composer.ts:6-15` (`ProjectComposerAttachment` gains `uploadId?`, `artifactKey?`, `sha256?`, `byteCount?`)
- Modify: `apps/frontend/src/features/projects/model/chat-turn.ts:340-364` (`TurnSubmission` message gains `attachmentRefs?`; `turnRequestBody` maps them)
- Modify: `apps/frontend/src/features/projects/hooks/use-project-chat-controller.ts:229-235`, `:923-955` (`submitMessage` options gain `attachmentRefs`)
- Test: `apps/frontend/src/features/projects/model/chat-attachments.test.ts`, `apps/frontend/src/features/projects/model/chat-turn.test.ts` (extend `chat-schemas.test.ts` if that is where `turnRequestBody` is tested)

**Interfaces:**
- `chat-attachments.ts`:
  ```ts
  export const CHAT_ATTACHMENT_ACCEPT = ".md,.txt,.png,.jpg,.jpeg,.webp,.gif,text/markdown,text/plain,image/png,image/jpeg,image/webp,image/gif";
  export const CHAT_ATTACHMENT_LIMITS = { maxFiles: 10, maxTotalBytes: 157_286_400, imageMaxBytes: 10_485_760, textMaxBytes: 5_242_880 } as const;
  export type AttachmentFamily = "text" | "image";
  export function attachmentFamily(file: { name: string; type: string }): AttachmentFamily | null;
  export function attachmentLimitError(current: readonly ProjectComposerAttachment[], incoming: readonly File[]): string | null;
  export interface ChatAttachmentRef { uploadId: string; artifactKey: string; sha256: string; mediaType: string; byteCount: number; filename: string }
  export function chatAttachmentSnapshot(attachments: readonly ProjectComposerAttachment[]): readonly ChatAttachmentRef[] | null;  // null while any is not ready
  ```
- `uploads.repository.ts`: `export async function uploadChatFile(file: File, { fetchImpl }?): Promise<{ uploadId; filename; mediaType; byteCount; artifactKey; sha256 }>` posting `FormData` to `/api/clue/frontend/v1/uploads`; on a non-2xx response throws `Error(detail.message ?? "Upload failed.")`.
- `use-chat-attachments.ts`: `useChatAttachments({ enabled }): { attachments; error; onFiles(files: File[]); remove(id); clear(); snapshot(): readonly ChatAttachmentRef[] | null; submissionBlocked: boolean }` — the same shape as `useDesignReferenceAttachments`, with `uploadChatFile` and the chat limits.
- `turnRequestBody` emits `attachment_refs: [{ upload_id, artifact_key, sha256, media_type, byte_count, filename }]`.

- [ ] **Step 1: Model tests**

```ts
// apps/frontend/src/features/projects/model/chat-attachments.test.ts
import assert from "node:assert/strict";
import test from "node:test";
import type { ProjectComposerAttachment } from "./project-composer";
import { attachmentFamily, attachmentLimitError, chatAttachmentSnapshot, CHAT_ATTACHMENT_LIMITS } from "./chat-attachments";

function ready(i: number, extra: Partial<ProjectComposerAttachment> = {}): ProjectComposerAttachment {
  return { id: `a${i}`, filename: `f${i}.md`, mediaType: "text/markdown", status: "ready", type: "file", url: "",
    uploadId: `u${i}`, artifactKey: `ws/${"a".repeat(64)}`, sha256: "a".repeat(64), byteCount: 10, ...extra };
}

test("family by type then by extension", () => {
  assert.equal(attachmentFamily({ name: "x.md", type: "" }), "text");
  assert.equal(attachmentFamily({ name: "x.txt", type: "text/plain" }), "text");
  assert.equal(attachmentFamily({ name: "x.png", type: "image/png" }), "image");
  assert.equal(attachmentFamily({ name: "x.pdf", type: "application/pdf" }), null);
});

test("limits: count, per-file size, total size", () => {
  const big = { name: "b.png", type: "image/png", size: CHAT_ATTACHMENT_LIMITS.imageMaxBytes + 1 } as File;
  assert.match(attachmentLimitError([], [big]) ?? "", /10 MB/);
  const many = Array.from({ length: 11 }, (_, i) => ({ name: `f${i}.md`, type: "text/markdown", size: 1 }) as File);
  assert.match(attachmentLimitError([], many) ?? "", /ten files/);
  assert.equal(attachmentLimitError([], [{ name: "ok.md", type: "text/markdown", size: 1 } as File]), null);
});

test("snapshot is null until every attachment is ready", () => {
  assert.equal(chatAttachmentSnapshot([ready(1), { ...ready(2), status: "uploading" }]), null);
  const snap = chatAttachmentSnapshot([ready(1)]);
  assert.deepEqual(snap, [{ uploadId: "u1", artifactKey: `ws/${"a".repeat(64)}`, sha256: "a".repeat(64), mediaType: "text/markdown", byteCount: 10, filename: "f1.md" }]);
});
```

- [ ] **Step 2: Run to see it fail**: `cd apps/frontend && npm test` → the new file fails to import.

- [ ] **Step 3: Implement the model**

```ts
// apps/frontend/src/features/projects/model/chat-attachments.ts
import type { ProjectComposerAttachment } from "./project-composer";

export const CHAT_ATTACHMENT_ACCEPT =
  ".md,.txt,.png,.jpg,.jpeg,.webp,.gif,text/markdown,text/plain,image/png,image/jpeg,image/webp,image/gif";
export const CHAT_ATTACHMENT_LIMITS = {
  maxFiles: 10, maxTotalBytes: 157_286_400, imageMaxBytes: 10_485_760, textMaxBytes: 5_242_880,
} as const;
export type AttachmentFamily = "text" | "image";
const TEXT = new Set(["text/markdown", "text/plain"]);
const IMAGE = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);
const BY_EXT: Record<string, string> = { ".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain",
  ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif" };

export function attachmentMediaType(file: { name: string; type: string }): string | null {
  const declared = file.type.toLowerCase();
  if (TEXT.has(declared) || IMAGE.has(declared)) return declared;
  const dot = file.name.lastIndexOf(".");
  return dot >= 0 ? (BY_EXT[file.name.slice(dot).toLowerCase()] ?? null) : null;
}
export function attachmentFamily(file: { name: string; type: string }): AttachmentFamily | null {
  const media = attachmentMediaType(file);
  if (media === null) return null;
  return TEXT.has(media) ? "text" : "image";
}
export function attachmentLimitError(current: readonly ProjectComposerAttachment[], incoming: readonly File[]): string | null {
  if (current.length + incoming.length > CHAT_ATTACHMENT_LIMITS.maxFiles) return "A message can carry at most ten files.";
  for (const file of incoming) {
    const family = attachmentFamily(file);
    if (family === "image" && file.size > CHAT_ATTACHMENT_LIMITS.imageMaxBytes) return `${file.name} is over 10 MB.`;
    if (family === "text" && file.size > CHAT_ATTACHMENT_LIMITS.textMaxBytes) return `${file.name} is over 5 MB.`;
  }
  const total = current.reduce((n, a) => n + (a.byteCount ?? 0), 0) + incoming.reduce((n, f) => n + f.size, 0);
  if (total > CHAT_ATTACHMENT_LIMITS.maxTotalBytes) return "Attachments on one message may total at most 150 MB.";
  return null;
}
export interface ChatAttachmentRef { uploadId: string; artifactKey: string; sha256: string; mediaType: string; byteCount: number; filename: string }
export function chatAttachmentSnapshot(attachments: readonly ProjectComposerAttachment[]): readonly ChatAttachmentRef[] | null {
  const refs: ChatAttachmentRef[] = [];
  for (const a of attachments) {
    if (a.status !== "ready" || !a.uploadId || !a.artifactKey || !a.sha256 || a.byteCount === undefined) return null;
    refs.push({ uploadId: a.uploadId, artifactKey: a.artifactKey, sha256: a.sha256, mediaType: a.mediaType, byteCount: a.byteCount, filename: a.filename });
  }
  return refs;
}
```

Extend `ProjectComposerAttachment` with `uploadId?: string; artifactKey?: string; sha256?: string; byteCount?: number;`.

- [ ] **Step 4: Upload adapter and hook**

`uploads.repository.ts` mirrors `uploadWebAsset` (`design-editor/data/assets.ts:41-70`) but posts to `/api/clue/frontend/v1/uploads` and returns `{ uploadId: data.upload_id, filename: data.filename, mediaType: data.media_type, byteCount: data.byte_count, artifactKey: data.artifact_key, sha256: data.sha256 }` from the `{data}` envelope; on failure throw `new Error(payload?.message ?? payload?.detail?.message ?? \`Upload failed (${response.status}).\`)`.

`use-chat-attachments.ts` is `use-design-reference-attachments.ts` with these substitutions: `uploadChatFile` for `uploadWebAsset`; `attachmentLimitError(current, files)` replaces the count check and sets `error`; a file with `attachmentFamily(file) === null` is added as `status: "failed", error: "Use a .md, .txt, PNG, JPEG, WebP or GIF file."`; on success set `uploadId, artifactKey, sha256, byteCount, mediaType, filename` and `status: "ready"`; `snapshot()` returns `chatAttachmentSnapshot(attachmentsRef.current)`; ids are `chat-attachment-<uuid>`.

- [ ] **Step 5: Turn request body**

`chat-turn.ts`: add `attachmentRefs?: readonly ChatAttachmentRef[]` to the message variant of `TurnSubmission`; in `turnRequestBody` replace `attachment_refs: []` with
`attachment_refs: (submission.attachmentRefs ?? []).map((a) => ({ upload_id: a.uploadId, artifact_key: a.artifactKey, sha256: a.sha256, media_type: a.mediaType, byte_count: a.byteCount, filename: a.filename }))`. Extend the existing `turnRequestBody` test with one attachment ref and assert the snake_case shape.

`use-project-chat-controller.ts`: `submitMessage(text, options: { contextRefs?; agentProfileId?; attachmentRefs?: readonly ChatAttachmentRef[] })`; pass `attachmentRefs: options.attachmentRefs ?? []` into the `submission` object and into the `messageSubmissions.begin` fingerprint object; the not-submitted guard becomes `(!trimmed && !contextRefs.length && !attachmentRefs.length)`.

- [ ] **Step 6: Run the frontend gate**: `cd apps/frontend && npm test && npm run lint` → PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/features/projects/model/chat-attachments.ts apps/frontend/src/features/projects/model/chat-attachments.test.ts apps/frontend/src/features/projects/data/uploads.repository.ts apps/frontend/src/features/projects/hooks/use-chat-attachments.ts apps/frontend/src/features/projects/model/project-composer.ts apps/frontend/src/features/projects/model/chat-turn.ts apps/frontend/src/features/projects/model/chat-schemas.test.ts apps/frontend/src/features/projects/hooks/use-project-chat-controller.ts
git commit -m "feat(frontend): chat attachment model, upload adapter, hook, and turn request refs"
```

---

### Task 13: Wire the chat composer (ruling 4) and the Home composer

**Files:**
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx:406-412` (add the chat hook), `:680-700` (`submitTurn` snapshots), `:1000-1046` (composer props)
- Modify: `apps/frontend/src/features/projects/hooks/use-project-home-controller.ts:36-60`, `:120-140` (draft), `:submit` (attachmentRefs), the returned handlers
- Modify: `apps/frontend/src/features/projects/components/project-composer.tsx:198-201` (accept list default)
- Test: `apps/frontend/src/features/chat-shell/model/attachment-routing.test.ts` + a new pure module `apps/frontend/src/features/chat-shell/model/attachment-routing.ts`

**Interfaces:**
- `attachment-routing.ts`: `export function routeAttachmentFiles(files: readonly File[], designReferencesEnabled: boolean): { design: File[]; chat: File[] }` — when `designReferencesEnabled`, images go to `design`, everything else to `chat`; otherwise everything to `chat`.
- Chat surface: `const chatAttachments = useChatAttachments({ enabled: workspace.composerCapabilities.attachments })`. Composer props: `attachmentAccept` = `DESIGN_REFERENCE_ACCEPT + "," + CHAT_ATTACHMENT_ACCEPT` when design refs are enabled, else `CHAT_ATTACHMENT_ACCEPT`; `attachments` = design refs (when enabled) followed by chat attachments; `onAttachmentFiles` routes through `routeAttachmentFiles`; `onAttachmentRemove` removes from whichever hook owns the id; `attachmentError` = design error ?? chat error; `sendDisabled` also `|| chatAttachments.submissionBlocked`; `attachmentLabel` = "Attach files".
- `submitTurn`: `const attachmentSnapshot = chatAttachments.snapshot(); if (chatAttachments.attachments.length > 0 && attachmentSnapshot === null) return false;` then pass `attachmentRefs: attachmentSnapshot ?? []` to `chat.submitMessage(...)`; on acceptance call `chatAttachments.clear()`.
- Home: in HTTP mode the controller uses `useChatAttachments({ enabled: data.composerCapabilities.attachments })` and passes its `snapshot()` as `attachmentRefs` in `parseHomeBootstrapDraft`/`submit`; `addAttachments`/`removeAttachment`/`attachments` come from the hook (delete the fixture timer path and the `httpMode ? [] : attachments` gating; the fixture transport simply gets `enabled: false`).

- [ ] **Step 1: Routing test**

```ts
// apps/frontend/src/features/chat-shell/model/attachment-routing.test.ts
import assert from "node:assert/strict";
import test from "node:test";
import { routeAttachmentFiles } from "./attachment-routing";

const png = { name: "a.png", type: "image/png" } as File;
const md = { name: "b.md", type: "text/markdown" } as File;

test("with an ad leg open images go to design references, text to chat", () => {
  assert.deepEqual(routeAttachmentFiles([png, md], true), { design: [png], chat: [md] });
});

test("without an ad leg everything goes to chat", () => {
  assert.deepEqual(routeAttachmentFiles([png, md], false), { design: [], chat: [png, md] });
});
```

- [ ] **Step 2: Run to see it fail** → import error.

- [ ] **Step 3: Implement the router and the wiring**

```ts
// apps/frontend/src/features/chat-shell/model/attachment-routing.ts
import { attachmentFamily } from "@/features/projects/model/chat-attachments";

/** Ruling 4 (2026-09-18): while an ad leg is open, images keep the design-reference route. */
export function routeAttachmentFiles(files: readonly File[], designReferencesEnabled: boolean): { design: File[]; chat: File[] } {
  const design: File[] = []; const chat: File[] = [];
  for (const file of files) {
    if (designReferencesEnabled && attachmentFamily(file) === "image") design.push(file);
    else chat.push(file);
  }
  return { design, chat };
}
```

Then the chat-surface and Home edits described in Interfaces. In `project-composer.tsx`, the default `accept` list becomes `CHAT_ATTACHMENT_ACCEPT` (import it) so a caller that passes nothing gets the chat list.

- [ ] **Step 4: Gate**: `cd apps/frontend && npm test && npm run lint && npm run build` → PASS (build proves the surface still compiles under Next).

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/chat-shell/model/attachment-routing.ts apps/frontend/src/features/chat-shell/model/attachment-routing.test.ts apps/frontend/src/features/chat-shell/components/chat-surface.tsx apps/frontend/src/features/projects/hooks/use-project-home-controller.ts apps/frontend/src/features/projects/components/project-composer.tsx
git commit -m "feat(frontend): chat and Home composers upload attachments; ad-leg images keep the design route"
```

---

### Task 14: Drag-and-drop with the dashed outline (ruling 5)

**Files:**
- Create: `apps/frontend/src/features/chat-shell/hooks/use-file-drop.ts`
- Create: `apps/frontend/src/features/chat-shell/model/file-drag.ts` + `.test.ts`
- Modify: `apps/frontend/src/features/chat-shell/components/chat-surface.tsx:807` (the `chatPane` section gets the drop handlers), `:1000` (composer gets `dropActive`)
- Modify: `apps/frontend/src/features/projects/components/project-composer.tsx` (prop `dropActive?: boolean` → `data-drop-target`)
- Modify: `apps/frontend/src/features/projects/components/project-flow.module.css:69-91`

**Interfaces:**
- `file-drag.ts`: `export function dragCarriesFiles(types: readonly string[] | DOMStringList | undefined): boolean` (true when it includes `"Files"`).
- `use-file-drop.ts`: `useFileDrop({ enabled, onFiles }): { active: boolean; handlers: { onDragEnter; onDragOver; onDragLeave; onDrop } }` — counts nested enter/leave so `active` does not flicker across child elements; `onDrop` calls `event.preventDefault()`, resets, and calls `onFiles(Array.from(event.dataTransfer.files))`; every handler ignores drags that do not carry files.
- CSS: `.composer[data-drop-target="true"] { border: 1px dashed var(--clue-ds-color-border-neutral); }`.

- [ ] **Step 1: Test**

```ts
// apps/frontend/src/features/chat-shell/model/file-drag.test.ts
import assert from "node:assert/strict";
import test from "node:test";
import { dragCarriesFiles } from "./file-drag";

test("only a drag that carries files counts", () => {
  assert.equal(dragCarriesFiles(["Files"]), true);
  assert.equal(dragCarriesFiles(["text/plain"]), false);
  assert.equal(dragCarriesFiles(undefined), false);
});
```

- [ ] **Step 2: Run to see it fail** → import error.

- [ ] **Step 3: Implement**

```ts
// file-drag.ts
export function dragCarriesFiles(types: readonly string[] | DOMStringList | undefined): boolean {
  if (!types) return false;
  return Array.from(types as ArrayLike<string>).includes("Files");
}
```

```ts
// use-file-drop.ts
"use client";
import { useCallback, useRef, useState, type DragEvent } from "react";
import { dragCarriesFiles } from "../model/file-drag";

export function useFileDrop({ enabled, onFiles }: { enabled: boolean; onFiles: (files: File[]) => void }) {
  const depth = useRef(0);
  const [active, setActive] = useState(false);
  const reset = useCallback(() => { depth.current = 0; setActive(false); }, []);
  const onDragEnter = useCallback((event: DragEvent) => {
    if (!enabled || !dragCarriesFiles(event.dataTransfer?.types)) return;
    event.preventDefault(); depth.current += 1; setActive(true);
  }, [enabled]);
  const onDragOver = useCallback((event: DragEvent) => {
    if (!enabled || !dragCarriesFiles(event.dataTransfer?.types)) return;
    event.preventDefault(); event.dataTransfer.dropEffect = "copy";
  }, [enabled]);
  const onDragLeave = useCallback((event: DragEvent) => {
    if (!enabled || !dragCarriesFiles(event.dataTransfer?.types)) return;
    depth.current = Math.max(0, depth.current - 1); if (depth.current === 0) setActive(false);
  }, [enabled]);
  const onDrop = useCallback((event: DragEvent) => {
    if (!enabled || !dragCarriesFiles(event.dataTransfer?.types)) return;
    event.preventDefault(); const files = Array.from(event.dataTransfer.files); reset(); if (files.length) onFiles(files);
  }, [enabled, onFiles, reset]);
  return { active, handlers: { onDragEnter, onDragOver, onDragLeave, onDrop } };
}
```

Chat surface: `const drop = useFileDrop({ enabled: workspace.composerCapabilities.attachments, onFiles: (files) => handleAttachmentFiles(files) })` where `handleAttachmentFiles` is the same routed handler the `+` button uses; spread `{...drop.handlers}` on the `<section className={styles.chatPane}>` and pass `dropActive={drop.active}` to `ProjectComposer`. Composer: `dropActive?: boolean` → `data-drop-target={dropActive || undefined}` on the `<form>`. CSS as above.

- [ ] **Step 4: Gate**: `cd apps/frontend && npm test && npm run lint && npm run build` → PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/features/chat-shell/hooks/use-file-drop.ts apps/frontend/src/features/chat-shell/model/file-drag.ts apps/frontend/src/features/chat-shell/model/file-drag.test.ts apps/frontend/src/features/chat-shell/components/chat-surface.tsx apps/frontend/src/features/projects/components/project-composer.tsx apps/frontend/src/features/projects/components/project-flow.module.css
git commit -m "feat(frontend): drop files on the chat; dashed composer outline while dragging"
```

---

### Task 15: Contract notes, memory note, and the live walk

**Files:**
- Modify: `apps/frontend/docs/api-contracts/projects.md` (new section "Chat attachments")
- Modify: `_memory/2026-09-18-chat-attachments-and-target-accounts-card-exploration.md` (execution entry)
- Modify: `CLAUDE.md` (one backlog bullet only if the live walk finds a residual)

- [ ] **Step 1: Contract notes**

Add to `apps/frontend/docs/api-contracts/projects.md`:

```markdown
## Chat attachments (2026-09-18)

- `POST /frontend/v1/uploads` (multipart `file`) → `201 {data: {upload_id, filename, media_type, byte_count, artifact_key, sha256}}`. Refusals: 413 `UPLOAD_TOO_LARGE`, 415 `UPLOAD_UNSUPPORTED_TYPE`, 422 `UPLOAD_NOT_UTF8` / `UPLOAD_NOT_AN_IMAGE` / `UPLOAD_FILENAME_INVALID`, 503 `STORAGE_UNAVAILABLE`.
- `GET /frontend/v1/uploads/{upload_id}/bytes` → the bytes, workspace-scoped; 404 otherwise.
- Turn and Home submissions: `attachment_refs[] = {upload_id, artifact_key, sha256, media_type, byte_count, filename}`; at most 10, 150 MB total. Refusals: 404 `ATTACHMENT_NOT_FOUND`, 409 `ATTACHMENT_MISMATCH`, 422 `ATTACHMENT_LIMIT_EXCEEDED` / `ATTACHMENT_DUPLICATE` / `ATTACHMENT_DOCUMENT_REFUSED`.
- Transcript refs with `flavor: "attachment"` carry `label` (filename), `media_type`, `upload_id`.
- Text uploads become project documents at `attachments/<filename>` (kind `attachment`) and appear in the Gallery under Documents. Images do not appear in the Gallery (ruling 3).
- `composer_capabilities.attachments` is true whenever the deployment has artifact storage.
```

- [ ] **Step 2: Live walk (founder-triggered; do not run unattended)**

On the lane stack (`scripts/dev_stack*.sh` per `DEV_STACK.md`), in a project chat:
1. Attach `brief.md` via `+`, send "Summarise the attached brief in three bullets." Expect: chip in the transcript, `attachments/brief.md` under Gallery → Documents, the reply quotes the file.
2. Attach a screenshot, send "What is in this image?" Expect: image chip, an answer that describes the image.
3. Two messages later, ask "What colour was the button in the screenshot I sent earlier?" Expect: an answer from the image, not a request to re-send.
4. Drag a `.txt` onto the chat: dashed outline appears, chip appears on drop.
5. Upload `brief.md` again with one edited line: Gallery shows version 2.
6. Open an ad, attach one image: it lands as a design reference (existing chip style), not as a chat attachment.
Record each outcome and any defect in the memory note.

- [ ] **Step 3: Memory note and commit**

Append to the memory note: commits per task, gates run with counts, the live-walk outcomes (or "owed, founder-triggered"), and any deferred minors.

```bash
git add apps/frontend/docs/api-contracts/projects.md _memory/2026-09-18-chat-attachments-and-target-accounts-card-exploration.md
git commit -m "docs(chat): attachment contract notes and the execution record"
```

---

## Self-review

**Spec coverage.** §3.1 upload → Tasks 4–5. §3.2 submission → Task 6. §3.3 text documents → Task 7 (replay on identical bytes, new version on change, Home path). §3.4 agent: pointer lines → Task 8; sending-turn images → Task 9; history images and the cap → Task 10; the probe → Task 1. §3.5 ad-leg routing → Task 13. §3.6 hook, Home, drag-and-drop, transcript, contract notes → Tasks 11–15. §3.7 settings → Task 2. §3.8 erasure and tenancy: no new code; uploads are turn-cited workspace artifacts on the existing tombstone path, and every read in Tasks 4–5 and 11 is workspace-scoped. §4 testing: each task carries its tests; the live walk is Task 15.

**Placeholder scan.** Tasks 8 (DB test), 10 (DB test) and 11 (backend test) describe their DB tests as contracts plus a reference to the neighbouring test to copy the seeding from, because the seeding is forty lines of SQL that already exists in `tests/api/test_project_document_context_refs_db.py` and Task 6's test; the assertions are stated exactly. Task 7 flags one signature to confirm (`current_document_version`) before use, with both outcomes handled.

**Type consistency.** `ValidatedAttachment(upload_id, ref, filename, family)` is produced in Task 6 and consumed by Tasks 7 and 8. `SubmissionAttachmentRow(turn_id, ordinal, upload_id, ref, filename)` is produced in Task 6 and read in Tasks 8, 10 (via `turn_image_refs`, which reads the ledger instead) and 11 (stream). `ChatAttachmentRef` (camelCase) is produced in Task 12 and consumed in Task 13; `turnRequestBody` maps it to the snake_case wire that Task 6's `AttachmentRefRequest` parses. `HistoryMessageRef.attachment_refs` (Task 10) and `ContextCandidate.image_refs` (Task 9) are both `tuple[ArtifactRef, ...]`.

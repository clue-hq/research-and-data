# Agent Code Execution and Document Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a person attach PDF, DOCX, PPTX, XLSX, CSV and JSON files to a project chat, put the originals and a markdown reading of each in the agent's workspace, and give Head-of-ABM a governed `run_python@1` tool that runs a script in a Docker sandbox over that workspace.

**Architecture:** Documents are converted to markdown at upload (a second content-addressed artifact on the `chat_upload` row) and written as project documents at send; the fleet worker syncs every document upload of a project into `<ws>/projects/<project>/attachments/`, which each turn mounts read-only as `attachments/`. `run_python@1` is a normal governed tool that finds its turn's host paths in a per-execution registry the conversation engine fills while it holds the workspace lease, runs one `docker run --rm --network none …` off the event loop, and re-applies the workspace policy afterwards. A new skill, a manual chapter, a prompt line, profile v58 and recipe v29 teach the agent.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic; Pydantic v2 contracts; PyMuPDF, openpyxl, stdlib zip/XML/csv/json for conversion; Docker CLI via `subprocess` for the sandbox; `node:test` + Zod for the frontend; pytest with a throwaway Postgres for `*_db.py` suites.

**Spec:** `docs/superpowers/specs/2026-09-19-agent-code-execution-and-document-attachments-design.md`

## Global Constraints

- Document family media types: `application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document` (`.docx`), `application/vnd.openxmlformats-officedocument.presentationml.presentation` (`.pptx`), `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` (`.xlsx`), `text/csv`, `application/json`. No `.doc`/`.ppt`/`.xls`/`.xlsm`.
- Settings and defaults, every one added to `.env.example` AND the local `.env` in the task that introduces it: `CLUE_SANDBOX_ENABLED=false`, `CLUE_SANDBOX_IMAGE=clue-agent-sandbox:latest`, `CLUE_SANDBOX_TIMEOUT_S=60`, `CLUE_SANDBOX_CPUS=1`, `CLUE_SANDBOX_MEMORY_MB=1024`, `CLUE_SANDBOX_MAX_RUNS_PER_TURN=10`, `CLUE_SANDBOX_MAX_OUTPUT_BYTES=1048576`, `CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES=26214400`, `CLUE_CHAT_ATTACHMENT_SHEET_MAX_ROWS=2000`, `CLUE_CHAT_ATTACHMENT_MARKDOWN_MAX_BYTES=1048576`, `CLUE_CHAT_ATTACHMENT_OCR_ENABLED=false`.
- The markdown twin of a document lives at project-document path `attachments/<original filename>.md` (so `report.pdf` → `attachments/report.pdf.md`, read by the agent at `project/attachments/report.pdf.md`); the original lives in the workspace at `attachments/<original filename>`.
- Sandbox: `docker run --rm --network none --cpus … --memory …m --pids-limit 256 --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges --user 65534:65534 --workdir /workspace`; writable binds `scratch/ work/ outputs/`; read-only binds `inputs/ context/ reads/ brand/ project/ attachments/`; script on stdin to `python -I -`; no host environment variables.
- Files a script leaves under the writable prefixes must satisfy the profile's workspace policy plus the extra output extensions `.csv .xlsx .docx .pptx .pdf .png`; offending files are deleted and reported.
- Package boundary: `platform/agents/clue_agents` never imports `clue_api`; `make contracts` (import-linter) is the guard.
- Alembic: `uv run alembic revision -m "<slug>"`, `down_revision` = the output of `uv run alembic heads` (one head, currently `d659c2d2b537`), reversible `downgrade()`.
- DB suites run only on the throwaway DB: `set -a; source .env; set +a; export CLUE_DATABASE_URL="${CLUE_DATABASE_URL%/clue_damascus}/clue_damascus_test"`. Never run the broad pytest suite with real keys (`.env` holds them); run the named files.
- Gates: backend `uv run ruff check <files> && uv run mypy <files>` and `make contracts`; frontend `cd apps/frontend && npm test && npm run lint` (two pre-existing warnings in `canvasOperations.ts` are not ours) and `npm run build` in the frontend task.
- Profile bump mechanics are the v56/v57 ones: a skill's `sha256` is the SHA-256 of its `SKILL.md` bytes; a tool grant's schema digests are `_schema_sha256(input_model)` / `_schema_sha256(output_model)` from `clue_toolbelt.envelope`; every pin of the profile version moves together (`agent_registry_wiring.py` `C6_ACTIVE_PROFILE_VERSIONS`, `composer_context.PROJECT_CONVERSATION_AGENT_PROFILE_ID`, `manual/build.py` `PROFILE_VERSION`, `tool_notes.yaml` header, the tests that assert them).
- No `Co-Authored-By` trailers, no AI attribution, never push. Commit at the end of each task.

---

### Task 1: Settings for the sandbox and the document family

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (after `chat_attachment_history_images_max`, ~line 689)
- Modify: `.env.example` (after `CLUE_CHAT_ATTACHMENT_HISTORY_IMAGES_MAX=20`, line 465); `.env` (same block, not committed)
- Test: `tests/test_sandbox_settings.py`

**Interfaces:**
- Produces on `Settings`: `sandbox_enabled: bool`, `sandbox_image: str`, `sandbox_timeout_s: float`, `sandbox_cpus: float`, `sandbox_memory_mb: int`, `sandbox_max_runs_per_turn: int`, `sandbox_max_output_bytes: int`, `chat_attachment_document_max_bytes: int`, `chat_attachment_sheet_max_rows: int`, `chat_attachment_markdown_max_bytes: int`, `chat_attachment_ocr_enabled: bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sandbox_settings.py
from __future__ import annotations

from pathlib import Path

from clue_config import Settings

REPO = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO / ".env.example"

DEFAULTS: dict[str, object] = {
    "sandbox_enabled": False,
    "sandbox_image": "clue-agent-sandbox:latest",
    "sandbox_timeout_s": 60.0,
    "sandbox_cpus": 1.0,
    "sandbox_memory_mb": 1024,
    "sandbox_max_runs_per_turn": 10,
    "sandbox_max_output_bytes": 1_048_576,
    "chat_attachment_document_max_bytes": 25 * 1024 * 1024,
    "chat_attachment_sheet_max_rows": 2000,
    "chat_attachment_markdown_max_bytes": 1_048_576,
    "chat_attachment_ocr_enabled": False,
}
ENV_LINES = {
    "CLUE_SANDBOX_ENABLED=false",
    "CLUE_SANDBOX_IMAGE=clue-agent-sandbox:latest",
    "CLUE_SANDBOX_TIMEOUT_S=60",
    "CLUE_SANDBOX_CPUS=1",
    "CLUE_SANDBOX_MEMORY_MB=1024",
    "CLUE_SANDBOX_MAX_RUNS_PER_TURN=10",
    "CLUE_SANDBOX_MAX_OUTPUT_BYTES=1048576",
    "CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES=26214400",
    "CLUE_CHAT_ATTACHMENT_SHEET_MAX_ROWS=2000",
    "CLUE_CHAT_ATTACHMENT_MARKDOWN_MAX_BYTES=1048576",
    "CLUE_CHAT_ATTACHMENT_OCR_ENABLED=false",
}


def test_sandbox_and_document_defaults(monkeypatch) -> None:
    for line in ENV_LINES:
        monkeypatch.delenv(line.split("=", 1)[0], raising=False)
    settings = Settings(_env_file=None)
    for name, value in DEFAULTS.items():
        assert getattr(settings, name) == value, name


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("CLUE_SANDBOX_ENABLED", "true")
    monkeypatch.setenv("CLUE_SANDBOX_MAX_RUNS_PER_TURN", "3")
    settings = Settings(_env_file=None)
    assert settings.sandbox_enabled is True
    assert settings.sandbox_max_runs_per_turn == 3


def test_every_new_key_is_documented_with_its_default() -> None:
    body = ENV_EXAMPLE.read_text()
    missing = sorted(line for line in ENV_LINES if line not in body)
    assert not missing, f"absent from .env.example: {missing}"
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run pytest tests/test_sandbox_settings.py -q` → FAIL, `Settings` has no attribute `sandbox_enabled`.

- [ ] **Step 3: Add the fields and the env lines**

In `settings.py`, directly after `chat_attachment_history_images_max`:

```python
    # Document attachments (spec 2026-09-19 §3.1, §3.3): the per-file cap of the document family,
    # the rows one sheet contributes to the markdown twin, the twin's total size (the workspace's
    # per-file read bound, so read_file can always open it), and whether a PDF page with no text
    # is OCR'd (Tesseract is a machine dependency, so this ships off). Env:
    # ``CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES`` / ``_SHEET_MAX_ROWS`` / ``_MARKDOWN_MAX_BYTES``
    # / ``_OCR_ENABLED``.
    chat_attachment_document_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    chat_attachment_sheet_max_rows: int = Field(default=2000, ge=1)
    chat_attachment_markdown_max_bytes: int = Field(default=1_048_576, ge=1)
    chat_attachment_ocr_enabled: bool = False
    # The code sandbox (spec 2026-09-19 §3.4): off until an operator builds the image and turns it
    # on; then one container per run with these bounds. Env: ``CLUE_SANDBOX_ENABLED`` /
    # ``_IMAGE`` / ``_TIMEOUT_S`` / ``_CPUS`` / ``_MEMORY_MB`` / ``_MAX_RUNS_PER_TURN`` /
    # ``_MAX_OUTPUT_BYTES``.
    sandbox_enabled: bool = False
    sandbox_image: str = "clue-agent-sandbox:latest"
    sandbox_timeout_s: float = Field(default=60.0, gt=0)
    sandbox_cpus: float = Field(default=1.0, gt=0)
    sandbox_memory_mb: int = Field(default=1024, ge=64)
    sandbox_max_runs_per_turn: int = Field(default=10, ge=1)
    sandbox_max_output_bytes: int = Field(default=1_048_576, ge=1024)
```

In `.env.example` after line 465 (and the same block in `.env`):

```
# Document attachments (spec 2026-09-19): the document family's per-file cap, rows per sheet in
# the markdown twin, the twin's size (the workspace read bound), OCR of text-less PDF pages.
CLUE_CHAT_ATTACHMENT_DOCUMENT_MAX_BYTES=26214400
CLUE_CHAT_ATTACHMENT_SHEET_MAX_ROWS=2000
CLUE_CHAT_ATTACHMENT_MARKDOWN_MAX_BYTES=1048576
CLUE_CHAT_ATTACHMENT_OCR_ENABLED=false
# The agent code sandbox (spec 2026-09-19 §3.4). Off until `make sandbox-image` has built the
# image on this host; then one `docker run` per run_python call with these bounds.
CLUE_SANDBOX_ENABLED=false
CLUE_SANDBOX_IMAGE=clue-agent-sandbox:latest
CLUE_SANDBOX_TIMEOUT_S=60
CLUE_SANDBOX_CPUS=1
CLUE_SANDBOX_MEMORY_MB=1024
CLUE_SANDBOX_MAX_RUNS_PER_TURN=10
CLUE_SANDBOX_MAX_OUTPUT_BYTES=1048576
```

- [ ] **Step 4: Run the test and gates**

Run: `uv run pytest tests/test_sandbox_settings.py tests/test_chat_attachment_settings.py -q` → PASS. `uv run ruff check libs/clue-config/clue_config/settings.py tests/test_sandbox_settings.py && uv run mypy libs/clue-config/clue_config/settings.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add libs/clue-config/clue_config/settings.py .env.example tests/test_sandbox_settings.py
git commit -m "feat(config): sandbox and document-attachment settings"
```

---

### Task 2: Converter package — contract, caps, PDF, CSV, JSON

**Files:**
- Create: `platform/api/clue_api/chat/converters/__init__.py`, `platform/api/clue_api/chat/converters/pdf.py`, `platform/api/clue_api/chat/converters/tabular.py`
- Modify: `platform/api/pyproject.toml` (add `"pymupdf>=1.24"` and `"openpyxl>=3.1"` to `dependencies`; then `uv lock && uv sync`)
- Test: `tests/api/converters/__init__.py` (empty), `tests/api/converters/test_pdf_and_tabular.py`

**Interfaces:**
- Produces:
  ```python
  class ConversionFailed(Exception): code: str; message: str   # codes: "unreadable", "encrypted", "unsupported"
  @dataclass(frozen=True) class ConvertedDocument: markdown: str; units: int; unit_kind: str; note: str | None; truncated: bool
  @dataclass(frozen=True) class ConversionLimits: sheet_max_rows: int; markdown_max_bytes: int; ocr_enabled: bool
  def limits_from_settings(settings: Settings) -> ConversionLimits
  def convert_document(data: bytes, *, media_type: str, filename: str, limits: ConversionLimits) -> ConvertedDocument
  def render_twin(converted: ConvertedDocument, *, filename: str, media_type: str, upload_id: UUID) -> str   # front matter + body
  def apply_markdown_cap(body: str, *, max_bytes: int) -> tuple[str, bool]
  ```
  The `DOCUMENT_MEDIA_TYPES` frozenset (the six types) and `EXTENSION_MEDIA_TYPES` map (`.pdf .docx .pptx .xlsx .csv .json`) live here and Task 5 imports them.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/converters/test_pdf_and_tabular.py
from __future__ import annotations

import io
import json
from uuid import UUID

import fitz  # PyMuPDF
import pytest

from clue_api.chat.converters import (
    ConversionFailed,
    ConversionLimits,
    apply_markdown_cap,
    convert_document,
    render_twin,
)

LIMITS = ConversionLimits(sheet_max_rows=2000, markdown_max_bytes=1_048_576, ocr_enabled=False)


def _pdf(pages: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    return doc.tobytes()


def test_pdf_becomes_one_section_per_page() -> None:
    out = convert_document(_pdf(["Alpha page", "Beta page"]), media_type="application/pdf",
                           filename="r.pdf", limits=LIMITS)
    assert out.unit_kind == "page" and out.units == 2
    assert "## Page 1" in out.markdown and "Alpha page" in out.markdown
    assert "## Page 2" in out.markdown and "Beta page" in out.markdown
    assert out.truncated is False


def test_textless_pdf_page_is_marked_without_ocr() -> None:
    doc = fitz.open(); doc.new_page(); data = doc.tobytes()
    out = convert_document(data, media_type="application/pdf", filename="scan.pdf", limits=LIMITS)
    assert "no extractable text" in out.markdown
    assert out.note is not None and "OCR" in out.note


def test_encrypted_pdf_is_refused() -> None:
    doc = fitz.open(); doc.new_page().insert_text((72, 72), "secret")
    data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(ConversionFailed) as caught:
        convert_document(data, media_type="application/pdf", filename="e.pdf", limits=LIMITS)
    assert caught.value.code == "encrypted"


def test_corrupt_pdf_is_refused() -> None:
    with pytest.raises(ConversionFailed) as caught:
        convert_document(b"%PDF-1.4 garbage", media_type="application/pdf", filename="c.pdf", limits=LIMITS)
    assert caught.value.code == "unreadable"


def test_csv_becomes_a_table_with_row_cap() -> None:
    rows = "name,amount\n" + "\n".join(f"deal {i},{i}" for i in range(5))
    out = convert_document(rows.encode(), media_type="text/csv", filename="d.csv",
                           limits=ConversionLimits(sheet_max_rows=3, markdown_max_bytes=1_048_576, ocr_enabled=False))
    assert "| name | amount |" in out.markdown and "| deal 2 | 2 |" in out.markdown
    assert "deal 4" not in out.markdown and out.truncated is True
    assert out.note is not None and "3" in out.note


def test_json_is_pretty_printed_in_a_fence() -> None:
    out = convert_document(json.dumps({"b": 1, "a": [1, 2]}).encode(), media_type="application/json",
                           filename="x.json", limits=LIMITS)
    assert out.markdown.startswith("```json\n") and '"a": [' in out.markdown
    with pytest.raises(ConversionFailed):
        convert_document(b"{not json", media_type="application/json", filename="x.json", limits=LIMITS)


def test_markdown_cap_truncates_with_a_marker() -> None:
    body, truncated = apply_markdown_cap("x" * 100, max_bytes=40)
    assert truncated and len(body.encode()) <= 40 + 80 and body.endswith("[truncated: the reading was cut at the size limit]")
    assert apply_markdown_cap("short", max_bytes=40) == ("short", False)


def test_twin_front_matter_names_the_upload() -> None:
    out = convert_document(_pdf(["one"]), media_type="application/pdf", filename="r.pdf", limits=LIMITS)
    twin = render_twin(out, filename="r.pdf", media_type="application/pdf",
                       upload_id=UUID("11111111-2222-3333-4444-555555555555"))
    head = twin.split("---")[1]
    for line in ("kind: attachment", "title: r.pdf", "source: user_upload",
                 "upload_id: 11111111-2222-3333-4444-555555555555",
                 "original_media_type: application/pdf", "units: 1", "unit_kind: page"):
        assert line in head, line
    assert "## Contents" in twin and "## Page 1" in twin
```

- [ ] **Step 2: Run to see it fail**

Run: `uv run pytest tests/api/converters/test_pdf_and_tabular.py -q` → FAIL (module missing). If `import fitz` fails, add the dependency first (Step 3) and re-run.

- [ ] **Step 3: Implement**

`platform/api/clue_api/chat/converters/__init__.py`:

```python
"""Documents to markdown, once, at upload (spec 2026-09-19 §3.3).

One entry point, ``convert_document``, dispatches on media type to a family module and returns a
``ConvertedDocument``; ``render_twin`` wraps it as the project document the agent reads. The
converters are pure functions over bytes: no database, no storage, no model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

import yaml

from clue_config import Settings

__all__ = [
    "DOCUMENT_MEDIA_TYPES",
    "EXTENSION_MEDIA_TYPES",
    "ConversionFailed",
    "ConversionLimits",
    "ConvertedDocument",
    "apply_markdown_cap",
    "convert_document",
    "limits_from_settings",
    "render_twin",
]

PDF: Final = "application/pdf"
DOCX: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX: Final = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX: Final = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV: Final = "text/csv"
JSON: Final = "application/json"
DOCUMENT_MEDIA_TYPES = frozenset({PDF, DOCX, PPTX, XLSX, CSV, JSON})
EXTENSION_MEDIA_TYPES: dict[str, str] = {
    ".pdf": PDF, ".docx": DOCX, ".pptx": PPTX, ".xlsx": XLSX, ".csv": CSV, ".json": JSON,
}
TRUNCATION_MARKER: Final = "[truncated: the reading was cut at the size limit]"


class ConversionFailed(Exception):
    """The document cannot be read. ``code`` is one of unreadable / encrypted / unsupported."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ConversionLimits:
    sheet_max_rows: int
    markdown_max_bytes: int
    ocr_enabled: bool


@dataclass(frozen=True, slots=True)
class ConvertedDocument:
    markdown: str
    units: int
    unit_kind: str
    note: str | None
    truncated: bool


def limits_from_settings(settings: Settings) -> ConversionLimits:
    return ConversionLimits(
        sheet_max_rows=settings.chat_attachment_sheet_max_rows,
        markdown_max_bytes=settings.chat_attachment_markdown_max_bytes,
        ocr_enabled=settings.chat_attachment_ocr_enabled,
    )


def apply_markdown_cap(body: str, *, max_bytes: int) -> tuple[str, bool]:
    encoded = body.encode("utf-8")
    if len(encoded) <= max_bytes:
        return body, False
    cut = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return f"{cut}\n\n{TRUNCATION_MARKER}", True


def convert_document(
    data: bytes, *, media_type: str, filename: str, limits: ConversionLimits
) -> ConvertedDocument:
    from clue_api.chat.converters import pdf, tabular

    lowered = media_type.lower()
    if lowered == PDF:
        converted = pdf.convert(data, limits=limits)
    elif lowered == CSV:
        converted = tabular.convert_csv(data, limits=limits)
    elif lowered == JSON:
        converted = tabular.convert_json(data, limits=limits)
    elif lowered == DOCX:
        from clue_api.chat.converters import docx

        converted = docx.convert(data, limits=limits)
    elif lowered == PPTX:
        from clue_api.chat.converters import pptx

        converted = pptx.convert(data, limits=limits)
    elif lowered == XLSX:
        from clue_api.chat.converters import xlsx

        converted = xlsx.convert(data, limits=limits)
    else:
        raise ConversionFailed("unsupported", f"{media_type} has no reader")
    body, cut = apply_markdown_cap(converted.markdown, max_bytes=limits.markdown_max_bytes)
    if not cut:
        return converted
    note = "the reading was cut at the size limit; open the file itself with run_python"
    return ConvertedDocument(
        markdown=body, units=converted.units, unit_kind=converted.unit_kind,
        note=f"{converted.note}; {note}" if converted.note else note, truncated=True,
    )


def render_twin(
    converted: ConvertedDocument, *, filename: str, media_type: str, upload_id: UUID
) -> str:
    front = {
        "kind": "attachment",
        "title": filename,
        "source": "user_upload",
        "upload_id": str(upload_id),
        "original_media_type": media_type,
        "units": converted.units,
        "unit_kind": converted.unit_kind,
    }
    if converted.note:
        front["conversion_note"] = converted.note
    header = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{header}\n---\n{converted.markdown.lstrip()}"
```

`platform/api/clue_api/chat/converters/pdf.py`:

```python
"""PDF → markdown: one section per page, PyMuPDF text, optional Tesseract OCR for empty pages."""

from __future__ import annotations

from clue_api.chat.converters import ConversionFailed, ConversionLimits, ConvertedDocument


def _ocr(page: object) -> str:
    import pytesseract  # a machine dependency; only imported when OCR is on
    from PIL import Image

    pix = page.get_pixmap(dpi=200)  # type: ignore[attr-defined]
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return pytesseract.image_to_string(image)


def _table_markdown(rows: list[list[str | None]]) -> str:
    if not rows:
        return ""
    cells = [[(c or "").replace("|", "\\|").replace("\n", " ").strip() for c in row] for row in rows]
    width = max(len(row) for row in cells)
    cells = [row + [""] * (width - len(row)) for row in cells]
    head = "| " + " | ".join(cells[0]) + " |"
    sep = "|" + " --- |" * width
    body = "\n".join("| " + " | ".join(row) + " |" for row in cells[1:])
    return "\n".join(part for part in (head, sep, body) if part)


def convert(data: bytes, *, limits: ConversionLimits) -> ConvertedDocument:
    import fitz

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several classes for a broken file
        raise ConversionFailed("unreadable", "the PDF could not be opened") from exc
    if doc.needs_pass:
        raise ConversionFailed("encrypted", "the PDF is password-protected")
    sections: list[str] = []
    contents: list[str] = []
    empty_pages: list[int] = []
    for index, page in enumerate(doc, start=1):
        text = (page.get_text("text") or "").strip()
        tables: list[str] = []
        try:
            finder = page.find_tables()
            for table in finder.tables:
                rendered = _table_markdown(table.extract())
                if rendered:
                    tables.append(rendered)
        except Exception:  # table detection is best-effort
            tables = []
        if not text and limits.ocr_enabled:
            try:
                text = _ocr(page).strip()
            except Exception:
                text = ""
        if not text:
            empty_pages.append(index)
            text = "_(no extractable text on this page)_"
        block = text if not tables else text + "\n\n" + "\n\n".join(tables)
        sections.append(f"## Page {index}\n\n{block}")
        contents.append(f"- Page {index}" + (" (no text)" if index in empty_pages else ""))
    doc.close()
    note = None
    if empty_pages:
        note = (
            f"{len(empty_pages)} page(s) had no extractable text"
            + ("" if limits.ocr_enabled else "; OCR is off (CLUE_CHAT_ATTACHMENT_OCR_ENABLED)")
        )
    markdown = "## Contents\n\n" + "\n".join(contents) + "\n\n" + "\n\n".join(sections)
    return ConvertedDocument(markdown=markdown, units=len(sections), unit_kind="page", note=note, truncated=False)
```

`platform/api/clue_api/chat/converters/tabular.py`:

```python
"""CSV and JSON → markdown."""

from __future__ import annotations

import csv
import io
import json

from clue_api.chat.converters import ConversionFailed, ConversionLimits, ConvertedDocument


def rows_to_table(rows: list[list[str]]) -> str:
    if not rows:
        return "_(empty)_"
    width = max(len(row) for row in rows)
    clean = [[c.replace("|", "\\|").replace("\n", " ") for c in row] + [""] * (width - len(row)) for row in rows]
    head = "| " + " | ".join(clean[0]) + " |"
    sep = "|" + " --- |" * width
    body = "\n".join("| " + " | ".join(row) + " |" for row in clean[1:])
    return "\n".join(part for part in (head, sep, body) if part)


def convert_csv(data: bytes, *, limits: ConversionLimits) -> ConvertedDocument:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConversionFailed("unreadable", "the CSV is not UTF-8") from exc
    reader = csv.reader(io.StringIO(text))
    rows: list[list[str]] = []
    total = 0
    for row in reader:
        total += 1
        if len(rows) <= limits.sheet_max_rows:  # header + max rows
            rows.append(row)
    truncated = total > limits.sheet_max_rows + 1
    note = f"showing the first {limits.sheet_max_rows} of {total - 1} rows" if truncated else None
    return ConvertedDocument(
        markdown=f"## Rows\n\n{rows_to_table(rows)}", units=max(total - 1, 0), unit_kind="row",
        note=note, truncated=truncated,
    )


def convert_json(data: bytes, *, limits: ConversionLimits) -> ConvertedDocument:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConversionFailed("unreadable", "the file is not valid JSON") from exc
    pretty = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
    return ConvertedDocument(
        markdown=f"```json\n{pretty}\n```", units=1, unit_kind="document", note=None, truncated=False,
    )
```

- [ ] **Step 4: Run the tests and gates**

Run: `uv lock && uv sync` (after editing `platform/api/pyproject.toml`), then `uv run pytest tests/api/converters/test_pdf_and_tabular.py -q` → PASS. `uv run ruff check platform/api/clue_api/chat/converters tests/api/converters && uv run mypy platform/api/clue_api/chat/converters` → clean (add `pymupdf` and `pytesseract` to the mypy ignore-missing-imports list in `pyproject.toml` `[[tool.mypy.overrides]]` if mypy complains about missing stubs).

- [ ] **Step 5: Commit**

```bash
git add platform/api/pyproject.toml uv.lock platform/api/clue_api/chat/converters tests/api/converters pyproject.toml
git commit -m "feat(chat): document converters — contract, PDF, CSV and JSON to markdown"
```

---

### Task 3: DOCX and PPTX converters

**Files:**
- Create: `platform/api/clue_api/chat/converters/docx.py`, `platform/api/clue_api/chat/converters/pptx.py`
- Test: `tests/api/converters/test_office.py`

**Interfaces:**
- Consumes: `ConversionFailed`, `ConversionLimits`, `ConvertedDocument` from Task 2.
- Produces: `docx.convert(data, *, limits) -> ConvertedDocument` (unit_kind `"section"`, units = number of headings, or 1), `pptx.convert(data, *, limits) -> ConvertedDocument` (unit_kind `"slide"`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/converters/test_office.py
from __future__ import annotations

import io
import zipfile

import pytest

from clue_api.chat.converters import ConversionFailed, ConversionLimits, convert_document

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
LIMITS = ConversionLimits(sheet_max_rows=2000, markdown_max_bytes=1_048_576, ocr_enabled=False)
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
    return buf.getvalue()


def _docx() -> bytes:
    body = f"""<w:document {W}><w:body>
      <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Summary</w:t></w:r></w:p>
      <w:p><w:r><w:t>Pipeline grew </w:t></w:r><w:r><w:t>18%.</w:t></w:r></w:p>
      <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr><w:r><w:t>first point</w:t></w:r></w:p>
      <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Deal</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Amount</w:t></w:r></w:p></w:tc></w:tr>
             <w:tr><w:tc><w:p><w:r><w:t>Globex</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>420000</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Next</w:t></w:r></w:p>
    </w:body></w:document>"""
    return _zip({"[Content_Types].xml": "<Types/>", "word/document.xml": body})


def _pptx() -> bytes:
    slide = lambda title, body: f"""<p:sld {P} {A}><p:cSld><p:spTree>
      <p:sp><p:nvSpPr><p:cNvPr id="1" name="Title"/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>
        <p:txBody><a:p><a:r><a:t>{title}</a:t></a:r></a:p></p:txBody></p:sp>
      <p:sp><p:nvSpPr><p:cNvPr id="2" name="Body"/><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr>
        <p:txBody><a:p><a:r><a:t>{body}</a:t></a:r></a:p></p:txBody></p:sp>
    </p:spTree></p:cSld></p:sld>"""
    notes = f"""<p:notes {P} {A}><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Say it slowly</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:notes>"""
    return _zip({
        "[Content_Types].xml": "<Types/>",
        "ppt/slides/slide1.xml": slide("Agenda", "Three things"),
        "ppt/slides/slide2.xml": slide("Numbers", "Q3 up 18%"),
        "ppt/notesSlides/notesSlide1.xml": notes,
    })


def test_docx_headings_paragraphs_lists_and_tables() -> None:
    out = convert_document(_docx(), media_type=DOCX, filename="m.docx", limits=LIMITS)
    md = out.markdown
    assert "# Summary" in md and "## Next" in md
    assert "Pipeline grew 18%." in md
    assert "- first point" in md
    assert "| Deal | Amount |" in md and "| Globex | 420000 |" in md
    assert out.unit_kind == "section" and out.units == 2


def test_pptx_slides_with_titles_bodies_and_notes() -> None:
    out = convert_document(_pptx(), media_type=PPTX, filename="d.pptx", limits=LIMITS)
    md = out.markdown
    assert "## Slide 1 — Agenda" in md and "Three things" in md
    assert "## Slide 2 — Numbers" in md and "Q3 up 18%" in md
    assert "Speaker notes: Say it slowly" in md
    assert out.unit_kind == "slide" and out.units == 2


def test_corrupt_office_zip_is_refused() -> None:
    for media in (DOCX, PPTX):
        with pytest.raises(ConversionFailed) as caught:
            convert_document(b"PK\x03\x04 not a zip", media_type=media, filename="x", limits=LIMITS)
        assert caught.value.code == "unreadable"
```

- [ ] **Step 2: Run to see it fail** → FAIL (modules missing).

- [ ] **Step 3: Implement**

`docx.py`:

```python
"""DOCX → markdown over the raw OOXML: headings by style, paragraphs, list items, tables."""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

from clue_api.chat.converters import ConversionFailed, ConversionLimits, ConvertedDocument
from clue_api.chat.converters.tabular import rows_to_table

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_MAX_XML_BYTES = 50 * 1024 * 1024
_HEADING = re.compile(r"^(?:Heading|heading)\s*(\d)$")


def _text(node: ElementTree.Element) -> str:
    parts: list[str] = []
    for child in node.iter():
        if child.tag == f"{{{_W}}}t" and child.text:
            parts.append(child.text)
        elif child.tag == f"{{{_W}}}tab":
            parts.append("\t")
        elif child.tag == f"{{{_W}}}br":
            parts.append("\n")
    return "".join(parts).strip()


def _paragraph_markdown(p: ElementTree.Element) -> tuple[str, bool]:
    """(markdown line, is_heading)."""
    text = _text(p)
    if not text:
        return "", False
    ppr = p.find(f"{{{_W}}}pPr")
    if ppr is not None:
        style = ppr.find(f"{{{_W}}}pStyle")
        if style is not None:
            match = _HEADING.match(style.get(f"{{{_W}}}val", ""))
            if match:
                level = min(int(match.group(1)), 6)
                return f"{'#' * level} {text}", True
            if style.get(f"{{{_W}}}val", "") == "Title":
                return f"# {text}", True
        if ppr.find(f"{{{_W}}}numPr") is not None:
            return f"- {text}", False
    return text, False


def _read_part(data: bytes, name: str) -> ElementTree.Element | None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if name not in archive.namelist():
                return None
            if archive.getinfo(name).file_size > _MAX_XML_BYTES:
                raise ConversionFailed("unreadable", f"{name} is too large to read")
            return ElementTree.fromstring(archive.read(name))
    except ConversionFailed:
        raise
    except (zipfile.BadZipFile, OSError, ElementTree.ParseError, KeyError) as exc:
        raise ConversionFailed("unreadable", "the document is not a readable OOXML package") from exc


def convert(data: bytes, *, limits: ConversionLimits) -> ConvertedDocument:
    root = _read_part(data, "word/document.xml")
    if root is None:
        raise ConversionFailed("unreadable", "the document has no word/document.xml")
    body = root.find(f"{{{_W}}}body")
    if body is None:
        raise ConversionFailed("unreadable", "the document has no body")
    lines: list[str] = []
    headings = 0
    for child in body:
        if child.tag == f"{{{_W}}}p":
            line, is_heading = _paragraph_markdown(child)
            if line:
                lines.append(line)
                headings += int(is_heading)
        elif child.tag == f"{{{_W}}}tbl":
            rows = [[_text(tc) for tc in tr.findall(f"{{{_W}}}tc")] for tr in child.findall(f"{{{_W}}}tr")]
            lines.append(rows_to_table(rows))
    for part in ("word/header1.xml", "word/footer1.xml"):
        extra = _read_part(data, part)
        if extra is not None:
            text = _text(extra)
            if text:
                lines.append(f"_({part.split('/')[-1].split('1')[0].capitalize()}: {text})_")
    markdown = "\n\n".join(lines) if lines else "_(the document has no text)_"
    return ConvertedDocument(markdown=markdown, units=max(headings, 1), unit_kind="section", note=None, truncated=False)
```

`pptx.py`:

```python
"""PPTX → markdown: one section per slide with its title, body text and speaker notes."""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

from clue_api.chat.converters import ConversionFailed, ConversionLimits, ConvertedDocument

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_SLIDE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_NOTES = re.compile(r"^ppt/notesSlides/notesSlide(\d+)\.xml$")


def _paragraphs(node: ElementTree.Element) -> list[str]:
    out: list[str] = []
    for p in node.iter(f"{{{_A}}}p"):
        text = "".join(t.text or "" for t in p.iter(f"{{{_A}}}t")).strip()
        if text:
            out.append(text)
    return out


def _shapes(root: ElementTree.Element) -> tuple[str | None, list[str]]:
    title: str | None = None
    body: list[str] = []
    for sp in root.iter(f"{{{_P}}}sp"):
        ph = sp.find(f".//{{{_P}}}ph")
        paragraphs = _paragraphs(sp)
        if not paragraphs:
            continue
        if title is None and ph is not None and ph.get("type") in ("title", "ctrTitle"):
            title = " ".join(paragraphs)
        else:
            body.extend(paragraphs)
    return title, body


def convert(data: bytes, *, limits: ConversionLimits) -> ConvertedDocument:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            slides = sorted(
                ((int(m.group(1)), n) for n in names if (m := _SLIDE.match(n))), key=lambda t: t[0]
            )
            notes = {int(m.group(1)): n for n in names if (m := _NOTES.match(n))}
            sections: list[str] = []
            contents: list[str] = []
            for number, name in slides:
                root = ElementTree.fromstring(archive.read(name))
                title, body = _shapes(root)
                heading = f"## Slide {number}" + (f" — {title}" if title else "")
                block = "\n".join(body) if body else "_(no text)_"
                if number in notes:
                    note_text = " ".join(_paragraphs(ElementTree.fromstring(archive.read(notes[number]))))
                    if note_text:
                        block += f"\n\nSpeaker notes: {note_text}"
                sections.append(f"{heading}\n\n{block}")
                contents.append(f"- Slide {number}" + (f": {title}" if title else ""))
    except (zipfile.BadZipFile, OSError, ElementTree.ParseError, KeyError) as exc:
        raise ConversionFailed("unreadable", "the deck is not a readable OOXML package") from exc
    if not sections:
        raise ConversionFailed("unreadable", "the deck has no slides")
    markdown = "## Contents\n\n" + "\n".join(contents) + "\n\n" + "\n\n".join(sections)
    return ConvertedDocument(markdown=markdown, units=len(sections), unit_kind="slide", note=None, truncated=False)
```

- [ ] **Step 4: Run tests and gates**

Run: `uv run pytest tests/api/converters -q` → PASS. `uv run ruff check platform/api/clue_api/chat/converters tests/api/converters && uv run mypy platform/api/clue_api/chat/converters` → clean.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/chat/converters/docx.py platform/api/clue_api/chat/converters/pptx.py tests/api/converters/test_office.py
git commit -m "feat(chat): DOCX and PPTX converters"
```

---

### Task 4: XLSX converter (two-pass read: values and formulas)

**Files:**
- Create: `platform/api/clue_api/chat/converters/xlsx.py`
- Test: `tests/api/converters/test_xlsx.py`

**Interfaces:**
- Produces: `xlsx.convert(data, *, limits) -> ConvertedDocument` (unit_kind `"sheet"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/converters/test_xlsx.py
from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from clue_api.chat.converters import ConversionFailed, ConversionLimits, convert_document

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
LIMITS = ConversionLimits(sheet_max_rows=2000, markdown_max_bytes=1_048_576, ocr_enabled=False)


def _book() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Pipeline"
    ws.append(["Deal", "Amount"])
    ws.append(["Globex", 420000])
    ws.append(["Initech", 180000])
    ws["B4"] = "=SUM(B2:B3)"
    other = wb.create_sheet("Notes")
    other["A1"] = "hello"
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_sheets_values_and_formulas() -> None:
    out = convert_document(_book(), media_type=XLSX, filename="p.xlsx", limits=LIMITS)
    md = out.markdown
    assert "## Sheet: Pipeline" in md and "## Sheet: Notes" in md
    assert "| Globex | 420000 |" in md
    # openpyxl writes no cached value for a formula, so the cell shows its formula text …
    assert "=SUM(B2:B3)" in md
    # … and the sheet's formula list names it by cell.
    assert "B4: =SUM(B2:B3)" in md
    assert out.unit_kind == "sheet" and out.units == 2


def test_row_cap_per_sheet() -> None:
    wb = Workbook(); ws = wb.active; ws.title = "Big"
    for i in range(10):
        ws.append([i, i * 2])
    buf = io.BytesIO(); wb.save(buf)
    out = convert_document(buf.getvalue(), media_type=XLSX, filename="b.xlsx",
                           limits=ConversionLimits(sheet_max_rows=3, markdown_max_bytes=1_048_576, ocr_enabled=False))
    assert "| 2 | 4 |" in out.markdown and "| 5 | 10 |" not in out.markdown
    assert out.truncated and out.note is not None and "Big" in out.note


def test_corrupt_workbook_is_refused() -> None:
    with pytest.raises(ConversionFailed) as caught:
        convert_document(b"PK\x03\x04junk", media_type=XLSX, filename="x.xlsx", limits=LIMITS)
    assert caught.value.code == "unreadable"
```

- [ ] **Step 2: Run to see it fail** → FAIL.

- [ ] **Step 3: Implement**

```python
# platform/api/clue_api/chat/converters/xlsx.py
"""XLSX → markdown: every sheet as a table of cached values, formulas shown where no value is
cached, and a per-sheet formula list — the two-pass read the founder's reference skill
prescribes, folded into one document."""

from __future__ import annotations

import io

from clue_api.chat.converters import ConversionFailed, ConversionLimits, ConvertedDocument
from clue_api.chat.converters.tabular import rows_to_table


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def convert(data: bytes, *, limits: ConversionLimits) -> ConvertedDocument:
    from openpyxl import load_workbook

    try:
        values = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        formulas = load_workbook(io.BytesIO(data), data_only=False, read_only=True)
    except Exception as exc:
        raise ConversionFailed("unreadable", "the workbook could not be opened") from exc
    sections: list[str] = []
    contents: list[str] = []
    capped: list[str] = []
    for name in formulas.sheetnames:
        ws_f = formulas[name]
        ws_v = values[name]
        rows: list[list[str]] = []
        formula_cells: list[str] = []
        total = 0
        for row_f, row_v in zip(ws_f.iter_rows(), ws_v.iter_rows(), strict=False):
            total += 1
            if total > limits.sheet_max_rows:
                continue
            rendered: list[str] = []
            for cell_f, cell_v in zip(row_f, row_v, strict=False):
                raw = cell_f.value
                if isinstance(raw, str) and raw.startswith("="):
                    formula_cells.append(f"{cell_f.coordinate}: {raw}")
                    rendered.append(_cell_text(cell_v.value) if cell_v.value is not None else raw)
                else:
                    rendered.append(_cell_text(raw))
            if any(rendered):
                rows.append(rendered)
        if total > limits.sheet_max_rows:
            capped.append(f"{name} (showing {limits.sheet_max_rows} of {total} rows)")
        block = f"## Sheet: {name}\n\n{rows_to_table(rows)}"
        if formula_cells:
            block += "\n\nFormulas:\n" + "\n".join(f"- {item}" for item in formula_cells[:500])
        sections.append(block)
        contents.append(f"- {name}: {min(total, limits.sheet_max_rows)} rows" + (", formulas" if formula_cells else ""))
    values.close()
    formulas.close()
    note = ("row cap reached on " + "; ".join(capped)) if capped else None
    markdown = "## Contents\n\n" + "\n".join(contents) + "\n\n" + "\n\n".join(sections)
    return ConvertedDocument(markdown=markdown, units=len(sections), unit_kind="sheet", note=note, truncated=bool(capped))
```

- [ ] **Step 4: Run tests and gates**: `uv run pytest tests/api/converters -q` → PASS; ruff + mypy on the package → clean.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/chat/converters/xlsx.py tests/api/converters/test_xlsx.py
git commit -m "feat(chat): XLSX converter with cached values and formula list"
```

---

### Task 5: The `document` family in upload validation

**Files:**
- Modify: `platform/api/clue_api/chat/uploads.py:37-56` (allow-lists, extensions, magic) and `:64-70` (`attachment_family`), `:81-125` (`resolve_media_type`, `validate_upload_bytes`)
- Test: `tests/api/test_chat_uploads.py` (extend)

**Interfaces:**
- Produces: `attachment_family(media_type) -> Literal["text", "image", "document"] | None`; `ALLOWED_DOCUMENT_MEDIA_TYPES = DOCUMENT_MEDIA_TYPES` (imported from the converters package); `validate_upload_bytes` enforces `settings.chat_attachment_document_max_bytes` and the magic bytes (`%PDF-` for PDF, `PK\x03\x04` for the three OOXML types, UTF-8 for CSV, `json.loads` for JSON). `resolve_media_type`'s refusal text becomes "attach a .md, .txt, .pdf, .docx, .pptx, .xlsx, .csv or .json file, or a PNG, JPEG, WebP or GIF image".
- Every downstream `family == "text"` check keeps its meaning; `"document"` is a third value that Task 6/7/9/10 handle.

- [ ] **Step 1: Extend the pure tests**

Append to `tests/api/test_chat_uploads.py`:

```python
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_document_family_and_extensions() -> None:
    assert attachment_family("application/pdf") == "document"
    assert attachment_family(DOCX) == "document"
    assert attachment_family("text/csv") == "document"
    assert attachment_family("application/json") == "document"
    assert resolve_media_type(declared=None, filename="a.PDF") == "application/pdf"
    assert resolve_media_type(declared="application/octet-stream", filename="a.xlsx").endswith("spreadsheetml.sheet")
    assert resolve_media_type(declared=None, filename="a.csv") == "text/csv"


def test_document_bytes_rules() -> None:
    settings = Settings(_env_file=None, chat_attachment_document_max_bytes=64)
    validate_upload_bytes(data=b"%PDF-1.7\n" + b"\x00" * 10, media_type="application/pdf", settings=settings)
    validate_upload_bytes(data=b"PK\x03\x04" + b"\x00" * 10, media_type=DOCX, settings=settings)
    validate_upload_bytes(data=b'{"a": 1}', media_type="application/json", settings=settings)
    validate_upload_bytes(data=b"a,b\n1,2\n", media_type="text/csv", settings=settings)
    with pytest.raises(UploadRefused) as too_big:
        validate_upload_bytes(data=b"%PDF-" + b"x" * 100, media_type="application/pdf", settings=settings)
    assert too_big.value.code == "UPLOAD_TOO_LARGE"
    with pytest.raises(UploadRefused) as not_pdf:
        validate_upload_bytes(data=b"hello", media_type="application/pdf", settings=settings)
    assert not_pdf.value.code == "UPLOAD_UNREADABLE"
    with pytest.raises(UploadRefused) as not_json:
        validate_upload_bytes(data=b"{oops", media_type="application/json", settings=settings)
    assert not_json.value.code == "UPLOAD_UNREADABLE"
```

- [ ] **Step 2: Run to see it fail**: `uv run pytest tests/api/test_chat_uploads.py -q` → FAIL.

- [ ] **Step 3: Implement**

In `uploads.py`: import `DOCUMENT_MEDIA_TYPES, EXTENSION_MEDIA_TYPES as DOCUMENT_EXTENSIONS` from `clue_api.chat.converters`; add `ALLOWED_DOCUMENT_MEDIA_TYPES = DOCUMENT_MEDIA_TYPES`; merge `DOCUMENT_EXTENSIONS` into `_EXTENSION_MEDIA_TYPES`; `attachment_family` returns `"document"` for the new set (return type `Literal["text", "image", "document"] | None`); in `validate_upload_bytes` add:

```python
    if family == "document":
        limit = settings.chat_attachment_document_max_bytes
        if len(data) > limit:
            raise UploadRefused("UPLOAD_TOO_LARGE", f"a document attachment may be at most {limit} bytes")
        if media_type == "application/pdf" and not data.startswith(b"%PDF-"):
            raise UploadRefused("UPLOAD_UNREADABLE", "the file is not a PDF")
        if media_type in _OOXML_TYPES and not data.startswith(b"PK\x03\x04"):
            raise UploadRefused("UPLOAD_UNREADABLE", "the file is not an Office document")
        if media_type in ("text/csv", "application/json"):
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise UploadRefused("UPLOAD_UNREADABLE", "the file is not UTF-8") from exc
            if media_type == "application/json":
                try:
                    json.loads(text)
                except json.JSONDecodeError as exc:
                    raise UploadRefused("UPLOAD_UNREADABLE", "the file is not valid JSON") from exc
        return
```

with `_OOXML_TYPES = frozenset({DOCX, PPTX, XLSX})` (the three constants imported from the converters package) and `import json`. Place the block before the existing text branch and move the `limit` selection so `text`/`image` keep their limits.

- [ ] **Step 4: Run tests and gates**: `uv run pytest tests/api/test_chat_uploads.py tests/api/test_chat_uploads_db.py -q` (DB one on the throwaway DB) → PASS; ruff + mypy on `uploads.py` → clean. Also `uv run pytest tests/api/test_chat_attachment_refs.py -q` still passes (families unchanged for text/image).

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/chat/uploads.py tests/api/test_chat_uploads.py
git commit -m "feat(chat): document family (pdf, docx, pptx, xlsx, csv, json) in upload validation"
```

---

### Task 6: Convert at upload — migration, twin artifact on the upload row, `UPLOAD_UNREADABLE`

**Files:**
- Create: `alembic/versions/<hash>_chat_upload_text_twin.py`
- Modify: `platform/api/clue_api/chat/uploads.py` (`ChatUploadRow` gains `text_artifact_key: str | None`, `conversion_note: str | None`; `record_chat_upload(..., text_ref: ArtifactRef | None = None, conversion_note: str | None = None)`; `_COLUMNS` and both SQL statements)
- Modify: `platform/api/clue_api/frontend_read/uploads.py:106-143` (`post_upload`)
- Test: `tests/db/test_chat_upload_tables_db.py` (column assertions), `tests/api/test_frontend_read_uploads_db.py` (extend)

**Interfaces:**
- Migration adds `text_artifact_key text NULL REFERENCES artifact(storage_key)` and `conversion_note text NULL` to `chat_upload`.
- `post_upload`: for `family == "document"`, after `validate_upload_bytes`, call `convert_document(data, media_type=…, filename=…, limits=limits_from_settings(settings))`; on `ConversionFailed` raise 422 `{"code": "UPLOAD_UNREADABLE", "message": f"{filename}: {exc.message}"}`; persist `render_twin(...)` bytes via `store.persist_body(workspace_id=…, data=twin.encode(), media_type="text/markdown")` and pass its ref as `text_ref`. The response gains `"conversion_note": row.conversion_note` (nullable) on `UploadV1`.
- Order of the `render_twin` call: it needs the `upload_id`, which is minted inside `record_chat_upload`; so mint the id first: `record_chat_upload` gains `upload_id: UUID | None = None` and the route generates `uuid4()` before converting.

- [ ] **Step 1: Write the failing tests**

Append to `tests/db/test_chat_upload_tables_db.py`:

```python
def test_chat_upload_carries_the_twin_columns() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'chat_upload' "
                "AND column_name IN ('text_artifact_key', 'conversion_note')"))).scalars().all()
            assert sorted(rows) == ["conversion_note", "text_artifact_key"]
    run_async(scenario())
```

Append to `tests/api/test_frontend_read_uploads_db.py` (mirroring `_upload_then_read_bytes`):

```python
import fitz  # noqa: E402


def _pdf_bytes(text_: str) -> bytes:
    doc = fitz.open(); doc.new_page().insert_text((72, 72), text_); return doc.tobytes()


async def _upload_pdf_records_a_twin(tmp_path: Path) -> None:
    async with rollback_conn() as conn:
        ws = await seed_workspace(conn, f"ws_upl_pdf_{uuid4().hex[:8]}")
        async with _client(conn, tmp_path, ws) as client:
            response = await client.post("/frontend/v1/uploads", files={"file": ("r.pdf", _pdf_bytes("Alpha page"), "application/pdf")})
            assert response.status_code == 201, response.text
            data = response.json()["data"]
            row = (await conn.execute(text("SELECT text_artifact_key, conversion_note FROM chat_upload WHERE upload_id = :id"), {"id": data["upload_id"]})).mappings().one()
            assert row["text_artifact_key"] is not None and row["text_artifact_key"].startswith(f"{ws}/")
            assert data["conversion_note"] is None
            twin = FsStorage(tmp_path).get(row["text_artifact_key"])  # use the storage backend's read; adapt to its real method name
            assert b"## Page 1" in twin and b"Alpha page" in twin


async def _corrupt_pdf_is_refused_at_upload(tmp_path: Path) -> None:
    async with rollback_conn() as conn:
        ws = await seed_workspace(conn, f"ws_upl_bad_{uuid4().hex[:8]}")
        async with _client(conn, tmp_path, ws) as client:
            response = await client.post("/frontend/v1/uploads", files={"file": ("c.pdf", b"%PDF-1.4 garbage", "application/pdf")})
            assert response.status_code == 422, response.text
            assert response.json()["detail"]["code"] == "UPLOAD_UNREADABLE"
            assert (await conn.execute(text("SELECT count(*) FROM chat_upload WHERE workspace_id = :ws"), {"ws": ws})).scalar_one() == 0


def test_upload_pdf_records_a_twin(tmp_path: Path) -> None:
    run_async(_upload_pdf_records_a_twin(tmp_path))


def test_corrupt_pdf_is_refused_at_upload(tmp_path: Path) -> None:
    run_async(_corrupt_pdf_is_refused_at_upload(tmp_path))
```

Check `clue_storage.fs.FsStorage`'s read method name (`get`/`read`/`open`) before running and use it.

- [ ] **Step 2: Run to see it fail** (test DB exported) → FAIL (no columns; 500 or 201 without twin).

- [ ] **Step 3: Migration**

`uv run alembic revision -m "chat upload text twin"`; set `down_revision` to `uv run alembic heads`' output:

```python
def upgrade() -> None:
    op.execute(
        "ALTER TABLE chat_upload "
        "ADD COLUMN text_artifact_key text NULL, "
        "ADD COLUMN conversion_note text NULL"
    )
    op.execute(
        "ALTER TABLE chat_upload ADD CONSTRAINT chat_upload_text_artifact_fk "
        "FOREIGN KEY (text_artifact_key) REFERENCES artifact (storage_key)"
    )
    op.execute(
        "COMMENT ON COLUMN chat_upload.text_artifact_key IS 'The markdown reading of a document "
        "upload, converted at upload time (spec 2026-09-19 §3.1); NULL for text and image uploads.'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE chat_upload DROP CONSTRAINT chat_upload_text_artifact_fk")
    op.execute("ALTER TABLE chat_upload DROP COLUMN conversion_note, DROP COLUMN text_artifact_key")
```

Upgrade the test DB; `uv run alembic heads` → one head.

- [ ] **Step 4: Store and route**

`uploads.py`: extend `ChatUploadRow`, `_COLUMNS` (`…, byte_count, created_at, text_artifact_key, conversion_note`), the INSERT (`text_artifact_key = :text_key, conversion_note = :note`), and `record_chat_upload(conn, *, workspace_id, user_id, filename, media_type, ref, upload_id=None, text_ref=None, conversion_note=None)` (`upload_id = upload_id or uuid4()`).

`frontend_read/uploads.py::post_upload`, after `validate_upload_bytes`:

```python
        upload_id = uuid4()
        text_ref: ArtifactRef | None = None
        conversion_note: str | None = None
        if attachment_family(media_type) == "document":
            try:
                converted = convert_document(
                    data, media_type=media_type, filename=filename, limits=limits_from_settings(settings)
                )
            except ConversionFailed as failure:
                raise HTTPException(
                    status_code=422,
                    detail={"code": "UPLOAD_UNREADABLE", "message": f"{filename}: {failure.message}"},
                ) from failure
            twin = render_twin(converted, filename=filename, media_type=media_type, upload_id=upload_id)
            text_ref = await store.persist_body(workspace_id=workspace_id, data=twin.encode("utf-8"), media_type="text/markdown")
            conversion_note = converted.note
        ref = await store.persist_body(workspace_id=workspace_id, data=data, media_type=media_type)
        async with conn_factory() as conn:
            row = await record_chat_upload(
                conn, workspace_id=workspace_id, user_id=user_id, filename=filename,
                media_type=media_type, ref=ref, upload_id=upload_id, text_ref=text_ref,
                conversion_note=conversion_note,
            )
```

`UploadV1` gains `conversion_note: str | None = None`; fill it from `row.conversion_note`. Run the conversion in `asyncio.to_thread(...)` so a large PDF does not block the event loop (the same reason the design leg uses it).

- [ ] **Step 5: Run tests and gates**

Run (test DB): `uv run pytest tests/db/test_chat_upload_tables_db.py tests/api/test_frontend_read_uploads_db.py tests/api/test_chat_uploads_db.py tests/api/test_chat_attachment_refs_db.py -q` → PASS; `uv run alembic downgrade -1 && uv run alembic upgrade head` clean; ruff + mypy on the two source files and the migration → clean.

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/*_chat_upload_text_twin.py platform/api/clue_api/chat/uploads.py platform/api/clue_api/frontend_read/uploads.py tests/db/test_chat_upload_tables_db.py tests/api/test_frontend_read_uploads_db.py
git commit -m "feat(chat): documents are converted at upload; the twin rides the chat_upload row"
```

---

### Task 7: The twin becomes a project document at send

**Files:**
- Modify: `platform/api/clue_api/chat/attachments.py` (`ValidatedAttachment.family` Literal gains `"document"`; `validated_attachment_refs` carries `text_ref`; `materialize_text_attachments` handles both families)
- Modify: `platform/api/clue_api/chat/router.py` (the `_wrote_attachment_documents` helper's `any(item.family == "text" …)` becomes `in ("text", "document")`)
- Test: `tests/api/test_chat_attachment_documents_db.py` (extend), `tests/api/test_chat_attachment_refs.py` (family assertion)

**Interfaces:**
- `ValidatedAttachment` gains `text_ref: ArtifactRef | None = None` (the twin artifact for documents; `None` otherwise), built in `validated_attachment_refs` from `row.text_artifact_key` (an `ArtifactRef` needs sha256/media_type/byte_count: read them with one `SELECT content_sha256, media_type, size_bytes FROM artifact WHERE storage_key = :key` per document ref, or extend `get_chat_uploads` to join them — do the join: `ChatUploadRow` keeps `text_artifact_key`, and `validated_attachment_refs` queries the `artifact` rows for the document uploads in one `ANY(:keys)` statement).
- `materialize_text_attachments`: a document item's `document_text` is the twin bytes read from `artifacts.read(item.text_ref)` (already rendered with front matter, so `_attachment_document` is skipped for it); path `attachments/<filename>.md`; identical-bytes replay compares the full twin text. A document with `text_ref is None` is refused `ProjectDocumentRefused("attachment_twin_missing", …)`.

- [ ] **Step 1: Write the failing DB test**

Append to `tests/api/test_chat_attachment_documents_db.py` a scenario that seeds a document upload (persist a fake twin `b"---\nkind: attachment\n---\n## Page 1\n\nAlpha"` as `text/markdown` through the bound `DurableAgentArtifactStore`, persist `b"%PDF-1.4 x"` as the original, `record_chat_upload(..., text_ref=twin_ref)`), builds `ValidatedAttachment(upload_id=…, ref=original_ref, filename="r.pdf", family="document", text_ref=twin_ref)`, calls `materialize_text_attachments`, and asserts `written[0].path == "attachments/r.pdf.md"`, `workspace_path == "project/attachments/r.pdf.md"`, and that `read_project_document` returns a body containing `## Page 1`; then re-materialises the same twin and asserts `replayed is True`.

- [ ] **Step 2: Run to see it fail** → FAIL (family literal / text_ref unknown).

- [ ] **Step 3: Implement** the interface above. In `materialize_text_attachments`:

```python
    for item in attachments:
        if item.family == "text":
            path = f"{ATTACHMENT_FOLDER}/{item.filename}"
            upload_text = (await artifacts.read(item.ref)).decode("utf-8")
            document_text, body = _attachment_document(upload_text, filename=item.filename, upload_id=item.upload_id)
        elif item.family == "document":
            if item.text_ref is None:
                raise ProjectDocumentRefused("attachment_twin_missing", f"{item.filename} has no readable twin")
            path = f"{ATTACHMENT_FOLDER}/{item.filename}.md"
            document_text = (await artifacts.read(item.text_ref)).decode("utf-8")
            _front, body = parse_front_matter(document_text, preserve_body=True)
        else:
            continue
        ...  # the existing current-version / replay / write logic, unchanged
```

- [ ] **Step 4: Run tests and gates**: `uv run pytest tests/api/test_chat_attachment_documents_db.py tests/api/test_chat_attachment_refs.py tests/api/test_chat_attachment_refs_db.py tests/api/test_lane_d2_turn_submission_db.py -q` → PASS; ruff + mypy on `chat/attachments.py`, `chat/router.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/chat/attachments.py platform/api/clue_api/chat/router.py tests/api/test_chat_attachment_documents_db.py tests/api/test_chat_attachment_refs.py
git commit -m "feat(chat): a document attachment's twin becomes a project document at send"
```

---

### Task 8: The `attachments` mount in the workspace

**Files:**
- Modify: `platform/agents/clue_agents/workspace.py` (`MountRequest.attachments: bool = False`; `_open_mounts` opens `<ws>/projects/<project>/attachments` read-only as mount `attachments` when present; `AgentWorkspaceFactory` keeps `self._root_path = prepared_root.path` and exposes `root_path` and `thread_host_path(workspace_id, project_id, thread_id) -> Path`, `project_host_path(workspace_id, project_id) -> Path`; `AgentWorkspaceLease` exposes `workspace_segment`, `project_segment`, `thread_segment` properties)
- Add constant `ATTACHMENTS_DIR: Final = "attachments"` beside `LIBRARY_DIR`.
- Test: `tests/agents/test_workspace_attachments_mount.py`

**Interfaces:**
- `MountRequest(attachments=True)` mounts the directory if it exists; a missing directory is not an error (the mount is simply absent), so a project with no uploads mounts nothing.
- `AgentWorkspaceLease.workspace_segment/project_segment/thread_segment: str` (read-only properties over the private fields).
- `AgentWorkspaceFactory.root_path: Path`; `project_host_path(ws, project) -> Path` = `root_path / <validated ws segment> / "projects" / <validated project segment>`; `thread_host_path(ws, project, thread)` = `project_host_path(...) / "threads" / <validated thread segment>`. Use the same segment validation the factory uses to build fds (`validate_workspace_segment`).

- [ ] **Step 1: Write the failing test**

Model it on the existing workspace tests (find the factory fixture in `tests/agents/test_workspace*.py` and reuse its `PreparedWorkspaceRoot`/policy builders):

```python
def test_attachments_mount_is_read_only_and_optional(factory, identity_kwargs, policy) -> None:
    # 1. no directory → acquire with attachments=True succeeds and `ls("attachments")` refuses/lists nothing
    lease = factory.acquire(**identity_kwargs, policy=policy, mounts=MountRequest(attachments=True))
    try:
        assert "attachments" not in {m.name for m in lease.backend.mounts}  # adapt to the backend's mount accessor
    finally:
        lease.release()
    # 2. create the directory with one file → it is listed, readable as bytes, refused for writes
    project_dir = factory.project_host_path(identity_kwargs["workspace_id"], identity_kwargs["project_id"])
    (project_dir / "attachments").mkdir(mode=0o700)
    (project_dir / "attachments" / "r.pdf").write_bytes(b"%PDF-1.4")
    lease = factory.acquire(**identity_kwargs, policy=policy_with_readable("attachments"), mounts=MountRequest(attachments=True))
    try:
        names = [e.path for e in run(lease.backend.list_entries("attachments"))]
        assert "attachments/r.pdf" in names
        with pytest.raises(WorkspaceSecurityError):
            run(lease.backend.write_text("attachments/x.md", "no"))
        assert factory.thread_host_path(identity_kwargs["workspace_id"], identity_kwargs["project_id"], identity_kwargs["thread_id"]).is_dir()
    finally:
        lease.release()
```

Write it in full against the real fixtures in `tests/agents/` (read `tests/agents/test_workspace_mounts*.py` or the nearest file that exercises `MountRequest(brand=…)` and copy its setup).

- [ ] **Step 2: Run to see it fail** → FAIL (`attachments` kwarg unknown).

- [ ] **Step 3: Implement** in `workspace.py`:

```python
ATTACHMENTS_DIR: Final = "attachments"
# MountRequest:
    #: ``<ws>/projects/<project>/attachments`` → the ``attachments`` mount, read-only, when the
    #: directory exists (spec 2026-09-19 §3.2). The fleet's sync creates it before the acquire.
    attachments: bool = False
# _open_mounts, after the project_library block:
            if request.attachments:
                try:
                    directory_fd = self._open_library(
                        (workspace_segment, PROJECTS_DIR, project_segment, ATTACHMENTS_DIR),
                        name="attachments",
                    )
                except WorkspaceConfigurationError:
                    directory_fd = -1
                if directory_fd >= 0:
                    opened.append(WorkspaceMount(name="attachments", directory_fd=directory_fd, mode="read_only"))
```

Factory: store `self._root_path = prepared_root.path` in `__init__`; add

```python
    @property
    def root_path(self) -> Path:
        return self._root_path

    def project_host_path(self, workspace_id: str, project_id: str) -> Path:
        return (
            self._root_path
            / validate_workspace_segment(workspace_id, label="workspace_id")
            / PROJECTS_DIR
            / validate_workspace_segment(project_id, label="project_id")
        )

    def thread_host_path(self, workspace_id: str, project_id: str, thread_id: str) -> Path:
        return self.project_host_path(workspace_id, project_id) / THREADS_DIR / validate_workspace_segment(thread_id, label="thread_id")
```

(`THREADS_DIR` exists or is the literal the factory already uses for `threads`; use the same constant.) Lease: three `@property` accessors.

- [ ] **Step 4: Run tests and gates**: `uv run pytest tests/agents/test_workspace_attachments_mount.py tests/agents -k "workspace" -q` → PASS; ruff + mypy on `workspace.py` → clean; `make contracts` → 28 kept.

- [ ] **Step 5: Commit**

```bash
git add platform/agents/clue_agents/workspace.py tests/agents/test_workspace_attachments_mount.py
git commit -m "feat(agents): read-only attachments mount and host-path accessors"
```

---

### Task 9: Sync the project's attachments tree on the worker, mount it every turn

**Files:**
- Create: `platform/api/clue_api/project_attachments.py`
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py` (~line 600–640: after `mounts = MountRequest(...)` is decided and before `self._engine.components.workspaces.acquire(...)` at ~812, call the sync and set `attachments=True` on the request)
- Test: `tests/api/test_project_attachments_sync_db.py`

**Interfaces:**
- ```python
  @dataclass(frozen=True) class ProjectAttachmentEntry: filename: str; media_type: str; byte_count: int; sha256: str; uploaded_at: str; turn_id: str; twin_path: str | None
  async def project_attachment_entries(conn, *, workspace_id: str, project_id: str) -> tuple[ProjectAttachmentEntry, ...]
      # SELECT DISTINCT ON (a.filename) … FROM agent_turn_submission_attachment a
      # JOIN agent_turn_submission s ON s.turn_id = a.turn_id AND s.workspace_id = a.workspace_id
      # JOIN chat_upload u ON u.upload_id = a.upload_id
      # JOIN artifact art ON art.storage_key = a.artifact_key
      # WHERE s.workspace_id = :ws AND s.project_id = :project AND a.media_type NOT LIKE 'image/%'
      #   AND art.erased_at IS NULL AND art.purged_at IS NULL
      # ORDER BY a.filename, a.created_at DESC        -- newest upload of a name wins
  async def sync_project_attachments(workspaces: AgentWorkspaceFactory, artifacts: AgentArtifactReader, conn, *, workspace_id, project_id) -> int
      # ensures <project>/attachments exists (0o700), writes each entry whose file is missing or whose
      # bytes differ (compare sha256 of the file on disk), removes files not in the entry set,
      # rewrites attachments/index.json, returns the number of files written.
  ```
- The twin path in the index: `project/attachments/<filename>` for a text upload, `project/attachments/<filename>.md` for a document.
- File writes go through the factory's fd (`project_parent_fd` → `ensure_child_directory(parent, ATTACHMENTS_DIR)` → `os.open(name, O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW, 0o600, dir_fd=…)`), never through a path string, matching the brand-library writer's discipline.

- [ ] **Step 1: Write the failing DB test**

Seed as in `tests/api/test_chat_attachment_refs_db.py` (one document upload + one text upload inserted on a submission), build a real `AgentWorkspaceFactory` over a `tmp_path` root the way `tests/agents` fixtures do, then:

```python
            written = await sync_project_attachments(factory, artifacts, conn, workspace_id=ws, project_id=project_id)
            assert written == 2
            root = factory.project_host_path(ws, project_id) / "attachments"
            assert (root / "r.pdf").read_bytes() == b"%PDF-1.4 x"
            index = json.loads((root / "index.json").read_text())
            names = {e["filename"]: e for e in index["files"]}
            assert names["r.pdf"]["twin_path"] == "project/attachments/r.pdf.md"
            assert names["brief.md"]["twin_path"] == "project/attachments/brief.md"
            # idempotent: nothing rewritten the second time
            assert await sync_project_attachments(factory, artifacts, conn, workspace_id=ws, project_id=project_id) == 0
            # erasure: mark the pdf's artifact erased → the file is removed on the next sync
            await conn.execute(text("UPDATE artifact SET erased_at = now() WHERE storage_key = :k"), {"k": pdf_key})
            await sync_project_attachments(factory, artifacts, conn, workspace_id=ws, project_id=project_id)
            assert not (root / "r.pdf").exists()
```

- [ ] **Step 2: Run to see it fail** → FAIL (module missing).

- [ ] **Step 3: Implement** the module per the interface, then in the fleet wiring, just before `acquire(...)`:

```python
        # Spec 2026-09-19 §3.2: the project's uploaded documents, byte for byte, beside the
        # threads. Synced here — on the worker that owns the workspace root — never by the API.
        async with self._conn_factory() as conn:
            await sync_project_attachments(
                self._engine.components.workspaces,
                self._engine.components.artifacts,
                conn,
                workspace_id=workspace_id,
                project_id=scope.project_id,
            )
        mounts = replace(mounts, attachments=True)
```

(`from dataclasses import replace`; `MountRequest` is a frozen dataclass — confirm, else construct it with the field set.)

- [ ] **Step 4: Run tests and gates**: `uv run pytest tests/api/test_project_attachments_sync_db.py tests/api -k "fleet_wiring and not live" -q` → PASS; ruff + mypy on the two files → clean; `make contracts` → 28 kept.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/project_attachments.py platform/api/clue_api/agent_turn_fleet_wiring.py tests/api/test_project_attachments_sync_db.py
git commit -m "feat(fleet): sync the project's attachments tree on the worker and mount it every turn"
```

---

### Task 10: L7 names both paths; the profile-independent describer

**Files:**
- Modify: `platform/agents/clue_agents/context.py` (`AttachmentDescription` gains `original_path: str | None`; `TurnLayerSource.load` wording)
- Modify: `platform/api/clue_api/attachment_binding.py` (`DescribedAttachment(filename, workspace_path, original_path)`; `original_path = f"attachments/{filename}"` for text and document uploads, `None` for images; `workspace_path` for a document is `project/attachments/<filename>.md` when the twin document is servable)
- Test: `tests/agents/test_turn_layer_attachments.py` (update strings), `tests/api/test_attachment_binding_db.py` (document case)

**Interfaces:**
- L7 lines:
  - text: `Attachment "brief.md" (text/markdown, 120 bytes) was attached to this message. The file is at attachments/brief.md and is readable at project/attachments/brief.md.`
  - document: `Attachment "q3.xlsx" (…, 412,010 bytes) was attached to this message. The file is at attachments/q3.xlsx; a markdown reading of it is at project/attachments/q3.xlsx.md. Use run_python to open the file itself when the reading is not enough.`
  - image: unchanged (`… is attached to this message as an image.`).
  - undescribed: unchanged pointer line.

- [ ] **Step 1: Update the tests** (RED): change the two assertions in `tests/agents/test_turn_layer_attachments.py` to the new sentences and add a document case with `_Desc("q3.xlsx", "project/attachments/q3.xlsx.md", "attachments/q3.xlsx")`; in the DB test add a document upload and assert both paths.

- [ ] **Step 2: Run to see it fail** → FAIL.

- [ ] **Step 3: Implement** the wording in `context.py` and the describer fields; the describer decides `workspace_path` for a document by looking up `attachments/<filename>.md` with the same servable query it uses for text.

- [ ] **Step 4: Run tests and gates**: `uv run pytest tests/agents/test_turn_layer_attachments.py tests/api/test_attachment_binding_db.py tests/agents -k context -q` → PASS; ruff + mypy; `make contracts`.

- [ ] **Step 5: Commit**

```bash
git add platform/agents/clue_agents/context.py platform/api/clue_api/attachment_binding.py tests/agents/test_turn_layer_attachments.py tests/api/test_attachment_binding_db.py
git commit -m "feat(agents): L7 names the attachment file and its markdown reading"
```

---

### Task 11: `SandboxWorkspaces` — the per-execution registry

**Files:**
- Create: `platform/api/clue_api/sandbox/__init__.py` (empty docstring), `platform/api/clue_api/sandbox/workspaces.py`
- Test: `tests/api/sandbox/__init__.py`, `tests/api/sandbox/test_workspaces.py`

**Interfaces:**
```python
@dataclass(frozen=True)
class SandboxMounts:
    thread_root: Path                      # <root>/<ws>/projects/<p>/threads/<t>
    read_only: Mapping[str, Path]          # name → host dir: inputs, context, reads, brand?, project?, attachments?
    read_write: Mapping[str, Path]         # scratch, work, outputs (created if missing)
    policy: WorkspacePolicy                # the profile's contract (max_file_bytes, max_total_bytes, allowed_extensions, …)

class SandboxWorkspaces:
    def __init__(self, *, max_runs_per_turn: int) -> None
    def register(self, execution_id: ExecutionId, mounts: SandboxMounts) -> None      # ValueError if already registered
    def release(self, execution_id: ExecutionId) -> None                              # idempotent
    def mounts_for(self, execution_id: ExecutionId) -> SandboxMounts | None
    def take_run(self, execution_id: ExecutionId) -> int                              # decrements; returns runs remaining; raises RunBudgetExhausted
    def runs_remaining(self, execution_id: ExecutionId) -> int
def sandbox_mounts_for_lease(lease: AgentWorkspaceLease, workspaces: AgentWorkspaceFactory, *, brand: tuple[str, str] | None, project_library: bool, attachments: bool) -> SandboxMounts
```
- `sandbox_mounts_for_lease` derives paths with the Task 8 accessors: thread root from `thread_host_path`; `brand` → `root_path/<ws>/library/brand/<brand>/<version>`; `project` → `project_host_path/library`; `attachments` → `project_host_path/attachments` (only when the directory exists). The policy is `lease.backend.policy` (confirm the backend exposes its policy; if it is `_policy`, add a read-only `policy` property in this task).
- Thread-safe (a `threading.Lock`): registration happens on the worker loop, `take_run` from the tool's thread.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/sandbox/test_workspaces.py
from pathlib import Path
import pytest
from clue_api.sandbox.workspaces import RunBudgetExhausted, SandboxMounts, SandboxWorkspaces
from clue_agents.contracts import WorkspacePolicy  # adapt to where WorkspacePolicy (the contract) lives

def _mounts(tmp_path: Path) -> SandboxMounts:
    policy = WorkspacePolicy(virtual_mode=True, max_total_bytes=20_971_520, max_file_bytes=1_048_576, max_file_count=400,
                             allowed_extensions=(".md",), readable_prefixes=("scratch",), writable_prefixes=("scratch",), retention_class="agent-ephemeral-v1")
    return SandboxMounts(thread_root=tmp_path, read_only={"inputs": tmp_path / "inputs"}, read_write={"scratch": tmp_path / "scratch"}, policy=policy)

def test_register_take_release(tmp_path: Path) -> None:
    reg = SandboxWorkspaces(max_runs_per_turn=2)
    ex = "exec-1"
    assert reg.mounts_for(ex) is None
    reg.register(ex, _mounts(tmp_path))
    with pytest.raises(ValueError):
        reg.register(ex, _mounts(tmp_path))
    assert reg.runs_remaining(ex) == 2
    assert reg.take_run(ex) == 1 and reg.take_run(ex) == 0
    with pytest.raises(RunBudgetExhausted):
        reg.take_run(ex)
    reg.release(ex); reg.release(ex)
    assert reg.mounts_for(ex) is None
```

(`ExecutionId` is a `str` NewType in `clue_core`; pass strings.)

- [ ] **Step 2: Run to see it fail** → FAIL. **Step 3: Implement** per the interface. **Step 4:** `uv run pytest tests/api/sandbox -q` → PASS; ruff + mypy.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/sandbox tests/api/sandbox
git commit -m "feat(sandbox): per-execution workspace registry and run budget"
```

---

### Task 12: The Docker runner — command builder, execution, output capture

**Files:**
- Create: `platform/api/clue_api/sandbox/docker_runner.py`
- Test: `tests/api/sandbox/test_docker_runner.py`

**Interfaces:**
```python
@dataclass(frozen=True) class SandboxLimits: image: str; timeout_s: float; cpus: float; memory_mb: int; max_output_bytes: int
@dataclass(frozen=True) class SandboxRun: exit_code: int | None; timed_out: bool; duration_ms: int; stdout: bytes; stderr: bytes; stdout_truncated: bool; stderr_truncated: bool
def build_command(mounts: SandboxMounts, limits: SandboxLimits) -> list[str]
def docker_available(image: str) -> tuple[bool, str]     # (ok, reason) — `docker image inspect <image>` exit 0
def run_script(code: str, *, mounts: SandboxMounts, limits: SandboxLimits, timeout_s: float) -> SandboxRun   # BLOCKING; call in a thread
```
- `build_command` returns exactly:
  `["docker", "run", "--rm", "-i", "--network", "none", "--cpus", str(cpus), "--memory", f"{memory_mb}m", "--pids-limit", "256", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534", "--workdir", "/workspace", "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "MPLCONFIGDIR=/tmp", *mount_flags, image, "python", "-I", "-"]` where `mount_flags` is `-v <host>:/workspace/<name>:ro` for each read-only mount (sorted by name) and `-v <host>:/workspace/<name>:rw` for each read-write one, and `--label clue.execution=<sanitised execution id>` is added when `run_script` is given one (optional kwarg).
- `run_script` creates the read-write dirs if missing (mode 0o700), runs `subprocess.run(cmd, input=code.encode(), capture_output=True, timeout=timeout_s, env={"PATH": "/usr/bin:/bin"})`; on `subprocess.TimeoutExpired` it runs `docker kill` by label when a label was set and returns `timed_out=True, exit_code=None`; stdout/stderr are cut at `max_output_bytes` with the truncated flags.

- [ ] **Step 1: Tests**

```python
# tests/api/sandbox/test_docker_runner.py
import shutil, subprocess
from pathlib import Path
import pytest
from clue_api.sandbox.docker_runner import SandboxLimits, build_command, docker_available, run_script
from tests.api.sandbox.test_workspaces import _mounts

LIMITS = SandboxLimits(image="clue-agent-sandbox:latest", timeout_s=60, cpus=1.0, memory_mb=1024, max_output_bytes=4096)

def test_command_is_locked_down(tmp_path: Path) -> None:
    cmd = build_command(_mounts(tmp_path), LIMITS)
    for flag in ("--network", "none", "--read-only", "--cap-drop", "ALL", "--pids-limit", "256", "--user", "65534:65534"):
        assert flag in cmd
    assert cmd[-3:] == ["python", "-I", "-"]
    assert f"{tmp_path / 'inputs'}:/workspace/inputs:ro" in cmd
    assert f"{tmp_path / 'scratch'}:/workspace/scratch:rw" in cmd
    assert "--env" in cmd and not any(part.startswith("CLUE_") or part.startswith("OPENROUTER") for part in cmd)

def test_output_truncation_flags(monkeypatch, tmp_path: Path) -> None:
    class Done:  # stands in for subprocess.CompletedProcess
        returncode = 0; stdout = b"x" * 10_000; stderr = b""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    run = run_script("print('hi')", mounts=_mounts(tmp_path), limits=LIMITS, timeout_s=5)
    assert run.exit_code == 0 and run.stdout_truncated and len(run.stdout) == 4096

def test_timeout_is_reported(monkeypatch, tmp_path: Path) -> None:
    def boom(*a, **k): raise subprocess.TimeoutExpired(cmd="docker", timeout=1)
    monkeypatch.setattr(subprocess, "run", boom)
    run = run_script("while True: pass", mounts=_mounts(tmp_path), limits=LIMITS, timeout_s=1)
    assert run.timed_out and run.exit_code is None

@pytest.mark.skipif(shutil.which("docker") is None or not docker_available("clue-agent-sandbox:latest")[0],
                    reason="Docker or the clue-agent-sandbox image is not available on this host")
def test_real_container_runs_and_writes_scratch(tmp_path: Path) -> None:
    mounts = _mounts(tmp_path)
    run = run_script("import pathlib; pathlib.Path('scratch/hello.md').write_text('hi'); print('ok')", mounts=mounts, limits=LIMITS, timeout_s=60)
    assert run.exit_code == 0 and run.stdout.strip() == b"ok"
    assert (tmp_path / "scratch" / "hello.md").read_text() == "hi"
```

- [ ] **Step 2: Run to see it fail** → FAIL. **Step 3: Implement.** **Step 4:** `uv run pytest tests/api/sandbox -q` → PASS (the real-container test skips until Task 16's image exists); ruff + mypy.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/sandbox/docker_runner.py tests/api/sandbox/test_docker_runner.py
git commit -m "feat(sandbox): locked-down docker runner with output capture and timeout"
```

---

### Task 13: Post-run policy sweep

**Files:**
- Create: `platform/api/clue_api/sandbox/policy_sweep.py`
- Test: `tests/api/sandbox/test_policy_sweep.py`

**Interfaces:**
```python
SANDBOX_OUTPUT_EXTENSIONS: Final = (".csv", ".xlsx", ".docx", ".pptx", ".pdf", ".png")
@dataclass(frozen=True) class SweepResult: kept: tuple[tuple[str, int], ...]; removed: tuple[tuple[str, str], ...]   # (path, bytes) / (path, reason)
def snapshot(mounts: SandboxMounts) -> dict[str, tuple[int, float]]       # path → (size, mtime) over the read-write dirs
def sweep(mounts: SandboxMounts, *, before: Mapping[str, tuple[int, float]]) -> SweepResult
```
- `sweep` walks the read-write dirs (never following symlinks; a symlink or non-regular file is removed with reason `not_a_regular_file`), removes files whose suffix is not in `policy.allowed_extensions + SANDBOX_OUTPUT_EXTENSIONS` (`extension_not_allowed`), files over `policy.max_file_bytes` (`file_too_large`), and, if the total over the writable dirs exceeds `policy.max_total_bytes` or the count exceeds `policy.max_file_count`, removes the newest-written files (by comparison with `before`) until within quota (`quota_exceeded`). `kept` lists files new or changed since `before`, with sizes.

- [ ] **Step 1: Tests** covering each reason and the "unchanged files are not listed as written" rule. **Step 2:** RED. **Step 3:** implement. **Step 4:** PASS + gates.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/sandbox/policy_sweep.py tests/api/sandbox/test_policy_sweep.py
git commit -m "feat(sandbox): post-run workspace policy sweep"
```

---

### Task 14: `run_python@1` — the governed tool

**Files:**
- Create: `platform/api/clue_api/run_python_tool.py`
- Modify: `platform/api/clue_api/toolbelt_wiring.py` (`build_toolbelt` gains `sandbox_workspaces: SandboxWorkspaces | None = None`; registers `build_run_python_tools(...)` after the artifact reads at ~2849, `make_default=True`)
- Modify: `platform/api/clue_api/agent_registry_wiring.py` (grants dict: `"run_python": (),` — registered ungranted; Task 18 grants it)
- Test: `tests/api/test_run_python_tool.py`

**Interfaces:**
```python
class RunPythonInput(ToolInput): code: str = Field(min_length=1, max_length=65_536); timeout_s: float | None = Field(default=None, gt=0); note: str | None = Field(default=None, max_length=200)
class RunPythonOutput(ToolOutput): exit_code: int | None; timed_out: bool; duration_ms: int; stdout: str; stdout_spilled_to: str | None; stdout_truncated: bool; stderr: str; stderr_spilled_to: str | None; stderr_truncated: bool; files_written: tuple[dict[str, object], ...]; files_removed: tuple[dict[str, str], ...]; runs_remaining: int
class RunPythonTool(Tool):
    name = "run_python"; version = "1"; effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(policy=ReplayPolicy.OPERATION_IDEMPOTENT, durable_identity="this operation's journaled receipt", external_boundary=ExternalReplayBoundary.NONE)
    parameter_policy = JournalParameterPolicy(safe_display_fields=("code", "note", "timeout_s"))
    pin_requirements = ("project",)
    def __init__(self, *, settings: Settings, workspaces: SandboxWorkspaces | None, conn_factory: ConnFactory = transaction)
def build_run_python_tools(*, settings: Settings, workspaces: SandboxWorkspaces | None, conn_factory=transaction) -> tuple[Tool, ...]
```
- `invoke`: refuse `PreconditionFailed([PreconditionFailure("sandbox_unavailable", reason)])` when `not settings.sandbox_enabled`, when `workspaces is None`, or when `docker_available(settings.sandbox_image)` is false (reason names the fix: `make sandbox-image`); `workspace_unavailable` when `ctx.execution_id` is `None` or unregistered; `run_budget_exhausted` from `take_run`; clamp `timeout_s` to `settings.sandbox_timeout_s`. Then `before = snapshot(mounts)`, `run = await asyncio.to_thread(run_script, …)`, `swept = sweep(mounts, before=before)`. Stdout/stderr over 16 KB are written by the tool to `<thread_root>/reads/<operation_id>.stdout.txt` (and `.stderr.txt`) with mode 0o600 and referenced as `reads/<operation_id>.stdout.txt`; the inline field then holds the first 16 KB. `model_description` states: the container's paths, that `attachments/` holds the originals, the run budget, and "Manual: .deepagent/skills/manual-tools/v5/SKILL.md#run_python".

- [ ] **Step 1: Tests** (pure, with `SandboxWorkspaces` and `monkeypatch`ed `run_script`/`docker_available`): refusal codes for each precondition; a happy run returning `exit_code 0`, `files_written` from the sweep, `runs_remaining` decrement; spill when stdout > 16 KB; the tool appears in `build_toolbelt(...)` with address `run_python@1` and is granted to nobody (`authority` dict).

- [ ] **Step 2:** RED. **Step 3:** implement. **Step 4:** `uv run pytest tests/api/test_run_python_tool.py tests/api/test_toolbelt_wiring.py -q` → PASS after updating the two registry counts in `test_toolbelt_wiring.py` (`names 136 → 137`, `addresses 156 → 157`, at both assertion sites, with a one-line comment in the file's existing style); ruff + mypy; `make contracts`.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/run_python_tool.py platform/api/clue_api/toolbelt_wiring.py platform/api/clue_api/agent_registry_wiring.py tests/api/test_run_python_tool.py tests/api/test_toolbelt_wiring.py
git commit -m "feat(toolbelt): run_python@1 — sandboxed script execution, registered ungranted"
```

---

### Task 15: Wire the registry through the worker and the conversation engine

**Files:**
- Modify: `platform/api/clue_api/agent_platform_wiring.py` (`AgentPlatformComponents.sandbox_workspaces: SandboxWorkspaces | None = None`; `build_agent_platform_components` builds `SandboxWorkspaces(max_runs_per_turn=settings.sandbox_max_runs_per_turn)` when `settings.sandbox_enabled`)
- Modify: `platform/api/clue_api/fleet_main.py` (~1006: pass `sandbox_workspaces=` to `build_toolbelt`; the same instance must be the one on the components — build it once before both calls)
- Modify: `platform/api/clue_api/conversation_turns.py` (~410–440): register before `build_head_of_abm_stage0_execution`, release in a `finally`
- Modify: `platform/api/clue_api/agent_turn_fleet_wiring.py`: the engine needs the mount facts (`brand`, `project_library`, `attachments`) to derive host paths — pass the `MountRequest` used at `acquire` into `engine.run(...)` (add a `mounts: MountRequest | None = None` kwarg on the engine's run method and thread it)
- Test: `tests/api/test_sandbox_registration_db.py` (or extend `tests/api/test_o6_conversation_composition_db.py`)

**Interfaces:**
- In `conversation_turns.py`:
```python
            sandbox = self.components.sandbox_workspaces
            if sandbox is not None:
                sandbox.register(
                    request.constitution.execution_id,
                    sandbox_mounts_for_lease(lease, self.components.workspaces, brand=…, project_library=…, attachments=…),
                )
            try:
                execution = build_head_of_abm_stage0_execution(...)
                outcome = await self._runtime.run(...)
            finally:
                if sandbox is not None:
                    sandbox.release(request.constitution.execution_id)
```

- [ ] **Step 1: Test**: compose the engine with a `SandboxWorkspaces` and a fake runtime whose `run` asserts `sandbox.mounts_for(execution_id)` is set during the turn and `None` after; assert the thread root equals `workspaces.thread_host_path(...)`.

- [ ] **Step 2:** RED. **Step 3:** implement. **Step 4:** `uv run pytest tests/api/test_o6_conversation_composition_db.py tests/api/test_sandbox_registration_db.py tests/api -k "fleet_wiring and not live" -q` → PASS; ruff + mypy on the four files; `make contracts`.

- [ ] **Step 5: Commit**

```bash
git add platform/api/clue_api/agent_platform_wiring.py platform/api/clue_api/fleet_main.py platform/api/clue_api/conversation_turns.py platform/api/clue_api/agent_turn_fleet_wiring.py tests/api/test_sandbox_registration_db.py
git commit -m "feat(fleet): the conversation engine registers the turn's sandbox mounts while it holds the lease"
```

---

### Task 16: The sandbox image and `make sandbox-image`

**Files:**
- Create: `docker/agent-sandbox/Dockerfile`, `docker/agent-sandbox/README.md`
- Modify: `Makefile` (target after `langfuse-check`)
- Test: `tests/api/sandbox/test_docker_runner.py::test_real_container_runs_and_writes_scratch` now runs (not skipped) on a host with Docker

- [ ] **Step 1: Dockerfile**

```dockerfile
# The Head-of-ABM code sandbox (spec 2026-09-19 §3.4). One container per run_python call:
# no network, no secrets, read-only root, an unprivileged user. Rebuild with `make sandbox-image`.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    pymupdf==1.24.* pypdf==5.* pdfplumber==0.11.* python-docx==1.1.* python-pptx==1.0.* \
    openpyxl==3.1.* pandas==2.2.* matplotlib==3.9.* pillow==11.* pytesseract==0.3.*
RUN mkdir -p /workspace && chown 65534:65534 /workspace
USER 65534:65534
WORKDIR /workspace
ENV PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp
```

Makefile:

```make
# --- agent code sandbox (spec 2026-09-19) ------------------------------------
sandbox-image: ## Build the Head-of-ABM code sandbox image named by CLUE_SANDBOX_IMAGE (default clue-agent-sandbox:latest)
	docker build -t $${CLUE_SANDBOX_IMAGE:-clue-agent-sandbox:latest} docker/agent-sandbox
```

README: what is in the image, how to rebuild, that `CLUE_SANDBOX_ENABLED=true` is the switch, and that the tool refuses `sandbox_unavailable` naming `make sandbox-image` when the image is absent.

- [ ] **Step 2:** `make sandbox-image` on this host, then `uv run pytest tests/api/sandbox/test_docker_runner.py -q -rs` → the real-container test PASSES (not skipped). Record the image size in the README.

- [ ] **Step 3: Commit**

```bash
git add docker/agent-sandbox Makefile
git commit -m "feat(sandbox): the clue-agent-sandbox image and make sandbox-image"
```

---

### Task 17: What the agent is taught — skill, manual chapter, Stage-0 pointer, prompt v11

**Files:**
- Create: `platform/agents/catalog/skills/code-execution/v1/SKILL.md`
- Create: `platform/agents/catalog/skills/manual-workspace/v5/SKILL.md` (copy of v4 with the `attachments/` mount row, a new "## `attachments/` the project's uploads" section, and `run_python`'s read/write rules in the writes paragraph)
- Create: `platform/agents/catalog/skills/stage0-interview/v34/SKILL.md` (copy of v33; §1 gains "When a message names an attachment, read `.deepagent/skills/code-execution/v1/SKILL.md` first"; §7c gains one bullet "**What an attached file says:** its markdown reading under `project/attachments/`, read whole, in pages; the file itself through `run_python` when the reading is cut or the question needs computation"; the frontmatter `tools:` list is unchanged)
- Create: `platform/agents/catalog/prompts/head-of-abm/v11/SYSTEM.md` (copy of v10; the sentence "There is no shell, code execution, host filesystem, arbitrary network, secret, or provider SDK access." becomes "There is no shell, host filesystem, arbitrary network, secret, or provider SDK access. Code runs only through `run_python`, inside the sandbox its manual entry describes.")
- Modify: `platform/agents/catalog/manual/tool_notes.yaml` (a `run_python:` entry with `afterwards`, `skill_section`, `see_also: [workspace, limits]`, `refusals` for `sandbox_unavailable`, `workspace_unavailable`, `run_budget_exhausted`, `code_too_large`, `project_not_found`)
- Test: `tests/agents/test_catalog.py` (lexical lists gain `skill:code-execution@v1`, `skill:manual-workspace@v5`, `skill:stage0-interview@v34`, `prompt:head-of-abm@v11`), `tests/agents/test_manual_drift.py` (the rule-sentence audit runs over the new skill; every rule line carries `(enforced)` or `(asked of you)`)

**The `code-execution` skill** (frontmatter `schema_version: "1"`, `kind: skill`, `name: code-execution`, `version: v1`, `summary: "Run a short Python script in the sandbox over your workspace to read an attached PDF, Word, PowerPoint, spreadsheet, CSV or JSON file properly, compute over it, or produce a derived file; and when the markdown reading is enough instead."`, `roles: [head_of_abm]`, `tools:` listing `run_python` `"1"` with its two schema digests computed by `python -c "from clue_toolbelt.envelope import _schema_sha256; from clue_api.run_python_tool import RunPythonInput, RunPythonOutput; print(_schema_sha256(RunPythonInput)); print(_schema_sha256(RunPythonOutput))"`). Body sections, plain language, adapted from `attachments/XLSX/skill.md`, `attachments/DOCX/skill.md`, `attachments/PDF/skill.md`:

1. **When to run code, when not to** — the twin under `project/attachments/` answers most questions; run code when the twin says it was cut, when you need a number computed rather than read, when you need a table joined or filtered, or when you must produce a file. The budget is `N` runs per turn (`(enforced)`); a run is not a launch and spends nothing outside the container.
2. **Where things are inside the container** — `/workspace` is your workspace: `attachments/<name>` are the originals (read only), `project/`, `brand/`, `inputs/`, `context/`, `reads/` read only; `scratch/`, `work/`, `outputs/` writable; only files with the allowed extensions survive a run (`(enforced)`); nothing on the network, no secrets (`(enforced)`).
3. **Reading recipes** — XLSX two passes (`load_workbook(path, data_only=False)` for formulas, `data_only=True` for cached values; `None` for a never-recalculated formula; `pandas.read_excel(path, sheet_name=None)` for bulk); PDF (`fitz.open(path)`, `page.get_text("text")`, `page.find_tables()`, `pdfplumber` for tables; a page with no text → render with `page.get_pixmap(dpi=200)` and `pytesseract.image_to_string`); DOCX (`docx.Document(path)`, paragraphs with `p.style.name`, `doc.tables`); PPTX (`pptx.Presentation(path)`, slide shapes' `text_frame`, `slide.notes_slide`); CSV/JSON with pandas / `json`. Print what you found; keep output under the cap; write big results to `work/` and read them back with `read_file`.
4. **Reporting** — every number you state comes from output you saw, with its page, sheet or row (`(asked of you)`); when a run fails, read stderr, fix, and try again within the budget; when the sandbox is unavailable, say so and use the twin.
5. **Producing files** — write under `outputs/` with an allowed extension; say what you wrote and where; nothing you write is shown to the human yet.

- [ ] **Step 1:** Write the four resources and the notes entry. **Step 2:** `uv run pytest tests/agents/test_catalog.py tests/agents/test_manual_drift.py -q` → FAIL on the lexical lists → add the four addresses (keep the lists sorted the way the file sorts them) → PASS. If `test_manual_drift`'s `SKILLS_BLOCK_MAX_BYTES` (4608) trips because the disclosed skills block grew, raise it with a dated comment in the file's existing style stating the new measured size.

- [ ] **Step 3: Commit**

```bash
git add platform/agents/catalog/skills/code-execution platform/agents/catalog/skills/manual-workspace/v5 platform/agents/catalog/skills/stage0-interview/v34 platform/agents/catalog/prompts/head-of-abm/v11 platform/agents/catalog/manual/tool_notes.yaml tests/agents/test_catalog.py tests/agents/test_manual_drift.py
git commit -m "feat(head-of-abm): code-execution skill, workspace chapter v5, stage0 v34, prompt v11"
```

---

### Task 18: Profile v58, recipe v29, the pins, the generated manual

**Files:**
- Create: `platform/agents/catalog/profiles/head-of-abm/v58/profile.yaml` (copy v57; `version: v58`; header comment; `prompt.version: v11` + its sha256; skills: `stage0-interview v34`, `manual-workspace v5`, every `manual-*` chapter at `v5`, plus `code-execution v1`, each with the SHA-256 of its `SKILL.md`; tools: add `run_python "1"` with the two schema digests; `workspace.allowed_extensions` unchanged (the sandbox's extra output extensions are enforced by the sweep, not by `write_file`); `workspace.readable_prefixes` gains `"attachments"`)
- Create: `platform/execution/recipes/recipe0-stage0-v29.json` (copy v28; `"version": 29`; `run_python@1` appended to `graph.tool_allowlist`, `nodes[1].dynamic_tool_allowlist`, `nodes[1].requirements` (`{"kind": "tool", "key": "run_python", "version": "1"}`) and `compatibility.nodes.stage0_interactions`)
- Modify: `platform/api/clue_api/recipe_wiring.py` (add `"recipe0-stage0-v29.json"` with a comment), `platform/api/clue_api/recipe_contracts.py` (RECIPE_0 addresses gain `"run_python@1"`), `platform/api/clue_api/stage0_recipe.py` (the tool name list gains `"run_python"`), `platform/api/clue_api/conversation_turns.py` (`CONVERSATION_RECIPE_VERSION = 29`), `platform/api/clue_api/agent_registry_wiring.py` (`AgentRole.HEAD_OF_ABM: "v58"`; grants `"run_python": (AgentRole.HEAD_OF_ABM,)`), `platform/api/clue_api/chat/composer_context.py` (`PROJECT_CONVERSATION_AGENT_PROFILE_ID = "head-of-abm@v58"`), `platform/agents/clue_agents/manual/build.py` (`MANUAL_VERSION = "v5"`, `PROFILE_VERSION = "v58"`), `platform/agents/catalog/manual/tool_notes.yaml` header
- Generated: `make manual` writes `manual-tools/v5`, `manual-fields/v5`, `manual-errors/v5`, `manual-limits/v5`; copy the other hand-written chapters (`index`, `turn`, `claims`, `accounts-research`, `discovery`, `documents-decisions`, `gates-authority`, `humans-screens`, `siblings`, `glossary`) to `v5` unchanged except their `version:` line and cross-reference paths (`make manual-link`), because the profile pins one manual version for every chapter
- Tests to update: `tests/agents/test_catalog.py` (`profile:head-of-abm@v58`, every `skill:manual-*@v5`), `tests/api/test_comprehensive_research_contract.py:469-470`, `tests/api/test_agent_registry_wiring.py:545`, `tests/api/test_client_knowledge_privacy_s4e.py:161`, `tests/api/test_toolbelt_wiring.py` (the authority dict now grants `run_python` to `HEAD_OF_ABM`), `tests/agents/test_tool_authority_audit.py` (if it enumerates grants)

- [ ] **Step 1:** Make every edit above; compute digests with `shasum -a 256 <SKILL.md>` and the schema snippet from Task 17. **Step 2:** `make manual && make manual-check` clean. **Step 3:** Run `uv run pytest tests/agents tests/api/test_toolbelt_wiring.py tests/api/test_agent_registry_wiring.py tests/api/test_comprehensive_research_contract.py tests/api/test_client_knowledge_privacy_s4e.py tests/api/test_o6_conversation_composition_db.py -q --ignore-glob='*_live.py'` (DB ones on the test DB) → PASS; `make lint typecheck contracts` clean.

- [ ] **Step 4: Commit**

```bash
git add platform/agents/catalog platform/execution/recipes/recipe0-stage0-v29.json platform/api/clue_api/recipe_wiring.py platform/api/clue_api/recipe_contracts.py platform/api/clue_api/stage0_recipe.py platform/api/clue_api/conversation_turns.py platform/api/clue_api/agent_registry_wiring.py platform/api/clue_api/chat/composer_context.py platform/agents/clue_agents/manual/build.py tests
git commit -m "feat(head-of-abm): v58 grants run_python@1 and pins the attachments-aware skills; recipe 29; manual v5"
```

---

### Task 19: Frontend — document types in the composer

**Files:**
- Modify: `apps/frontend/src/features/projects/model/chat-attachments.ts` (`CHAT_ATTACHMENT_ACCEPT` gains `.pdf,.docx,.pptx,.xlsx,.csv,.json,application/pdf,text/csv,application/json` and the three OOXML types; `CHAT_ATTACHMENT_LIMITS.documentMaxBytes: 26_214_400`; `AttachmentFamily` gains `"document"`; `DOCUMENT` set and `BY_EXT` entries; `attachmentLimitError` message `"${file.name} is over 25 MB."`)
- Modify: `apps/frontend/src/features/projects/hooks/use-chat-attachments.ts` (`UNSUPPORTED` message: "Use a .md, .txt, .pdf, .docx, .pptx, .xlsx, .csv or .json file, or a PNG, JPEG, WebP or GIF image.")
- Modify: `apps/frontend/src/features/projects/data/uploads.repository.ts` (`UploadResponseSchema` gains `conversion_note: z.string().nullable().default(null)`; returned as `conversionNote`)
- Modify: `apps/frontend/src/features/projects/model/project-composer.ts` (`ProjectComposerAttachment.conversionNote?: string`), `project-composer-attachment.tsx` (show `conversionNote` under the media type in the hover card when present)
- Modify: `apps/frontend/src/features/chat-shell/model/attachment-routing.ts` — unchanged behaviour (documents are not images, so they go the chat route); add a test line for a `.pdf`
- Test: `chat-attachments.test.ts` (family, accept list, document limit), `attachment-routing.test.ts`

- [ ] **Step 1:** Tests RED. **Step 2:** implement. **Step 3:** `cd apps/frontend && npm test && npm run lint && npm run build` → PASS, 0 errors.

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/features/projects/model/chat-attachments.ts apps/frontend/src/features/projects/model/chat-attachments.test.ts apps/frontend/src/features/projects/hooks/use-chat-attachments.ts apps/frontend/src/features/projects/data/uploads.repository.ts apps/frontend/src/features/projects/model/project-composer.ts apps/frontend/src/features/projects/components/project-composer-attachment.tsx apps/frontend/src/features/chat-shell/model/attachment-routing.test.ts
git commit -m "feat(frontend): document attachments (pdf, docx, pptx, xlsx, csv, json) in the composers"
```

---

### Task 20: Contract notes, memory, backlog, and the owed live walk

**Files:**
- Modify: `apps/frontend/docs/api-contracts/projects.md` ("Chat attachments" section: the document family, the 25 MB cap, `UPLOAD_UNREADABLE`, `conversion_note` on the upload receipt, the twin path rule)
- Modify: `_memory/2026-09-18-chat-attachments-and-target-accounts-card-exploration.md` (execution record: per-task commits, gates with counts, rulings, deferred minors, the image build, the owed walk)
- Modify: `CLAUDE.md` (one backlog bullet: `[chat×sandbox]` — what shipped, `CLUE_SANDBOX_ENABLED` off by default, `make sandbox-image` per host, residuals: outputs not rendered to the human, no OCR by default, the sandbox is Head-of-ABM only)

- [ ] **Step 1:** Write the three documents. **Step 2:** Live walk (founder-triggered; do not run unattended): build the image, set `CLUE_SANDBOX_ENABLED=true` in the lane `.env`, restart the workers, then in a project chat: attach a spreadsheet and ask for a column total (expect a `run_python` receipt in the inspector and a number with the sheet named); attach a PDF and ask for a figure on page 3; attach a scanned PDF with `CLUE_CHAT_ATTACHMENT_OCR_ENABLED=true`; ask for a CSV derived from the spreadsheet (expect `outputs/<name>.csv` in `files_written`); upload a corrupt file (expect the chip to fail with the reason). Record outcomes in the memory note.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/docs/api-contracts/projects.md _memory/2026-09-18-chat-attachments-and-target-accounts-card-exploration.md CLAUDE.md
git commit -m "docs(chat): document attachments and the code sandbox — contract notes, execution record, backlog"
```

---

## Self-review

**Spec coverage.** §3.1 (family, caps, magic, convert at upload, `UPLOAD_UNREADABLE`, the two columns) → Tasks 1, 5, 6. §3.2 (worker-side sync, `attachments/` mount, index, replace-on-reupload, erasure) → Tasks 8, 9. §3.3 (twin per family, front matter, caps, OCR flag) → Tasks 2–4, 7. §3.4 (contract, refusals, execution flags, sweep, registry, image, settings, off by default) → Tasks 1, 11–16. §3.5 (skill, manual v5, stage0 v34, prompt v11, profile v58, recipe 29, pins) → Tasks 17, 18. §3.6 security → Tasks 12 (flags), 13 (sweep), 14 (journaled code, refusals). §3.7 frontend → Task 19. §4 testing → each task; live walk in Task 20. §5 out of scope respected (no rendering, no network, no LibreOffice formats).

**Placeholder scan.** Tasks 8, 9, 13, 15, 17 describe tests by contract where the fixture setup is forty lines already present in a named neighbouring file; the assertions are stated exactly. Task 6's test names the one storage read method to confirm. No TBDs.

**Type consistency.** `ConvertedDocument`/`ConversionLimits`/`ConversionFailed` (Task 2) are consumed unchanged by Tasks 3–6. `attachment_family` returns the three-valued literal from Task 5 onward; Tasks 7, 9, 10 branch on `"document"`. `SandboxMounts`/`SandboxWorkspaces` (Task 11) are consumed by Tasks 12–15 with the same field names. `AgentWorkspaceFactory.thread_host_path/project_host_path/root_path` and the lease segment properties (Task 8) are what Task 11's `sandbox_mounts_for_lease` uses. `RunPythonInput`/`RunPythonOutput` (Task 14) are what Task 17's digest snippet and Task 18's profile pin name.

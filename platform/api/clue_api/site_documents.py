"""The empty Puck site document a website leg births when its workspace is on the site engine.

Pure (no engine round-trip): the stored shape is the site-kit's own JSON, top-level id/title/
theme so the design DAL's creation contract (`clue_design.documents.create_document`) treats it
like a web document and stamps the approved brand kit at birth.
"""

from __future__ import annotations

from typing import Any


def mint_empty_site_document(
    *, document_id: str, title: str, brand_kit_ref: dict[str, Any] | None
) -> dict[str, Any]:
    theme: dict[str, Any] = {} if brand_kit_ref is None else {"brand_kit": brand_kit_ref}
    return {
        "id": document_id,
        "title": title,
        "theme": theme,
        "pages": {"/": {"root": {"props": {"title": title}}, "content": []}},
        "shell": None,
        "agent_sections": {},
    }

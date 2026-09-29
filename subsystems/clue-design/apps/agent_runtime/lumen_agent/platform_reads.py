"""The platform's reads, as the design agent sees them (design note 2026-09-19).

Three tools — the same three head-of-abm has for the target account — and the seller's pinned
knowledge written into ``workspace/seller/`` once per pin. Web legs also receive the original
project instruction/decision snapshot in ``workspace/project-context/``. The runtime never learns
where any of this comes from: ``reads`` is an object the platform injected (config.platform_reads),
and this module only calls it. Every tool answers a JSON string; a failure answers
``{"error": "<code>"}`` and is recorded, never raised — a read the agent could not make is a fact
to design around, not a reason to kill the turn.

A GOVERNED REFUSAL IS NOT A CRASH. The platform's read error carries one machine-readable code,
and a refusal spells it ``refused:<reason>[,<reason>...]``. That shape is unfolded here into
``{"error": "refused", "reasons": [...]}`` so the model reads the reasons as reasons — "this
account's overview is not written yet, read its claims instead" — rather than as an opaque
string it has to parse. The trace keeps the code verbatim either way.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from py_lumen_obs import get_logger

logger = get_logger("lumen_agent.platform_reads")

SELLER_DIR = "seller"
PROJECT_CONTEXT_DIR = "project-context"
_PIN_FILE = ".pin"
_REFUSED_PREFIX = "refused:"


def _error_payload(code: str) -> dict[str, Any]:
    """A refusal keeps its reasons; every other code answers as itself."""
    if code.startswith(_REFUSED_PREFIX):
        reasons = [reason for reason in code[len(_REFUSED_PREFIX) :].split(",") if reason]
        return {"error": "refused", "reasons": reasons}
    return {"error": code}


def _call(tools: Any, reads: Any, name: str, **kwargs: Any) -> str:
    try:
        payload = getattr(reads, name)(**kwargs)
    except Exception as error:  # noqa: BLE001 - a refused read is a tool result, never a crash
        code = str(error) or error.__class__.__name__
        tools.record(
            "orchestrator",
            "platform_read",
            payload={"tool": name, "ok": False, "code": code, "args": kwargs},
        )
        logger.info("platform_read_failed", tool=name, code=code)
        return json.dumps(_error_payload(code), ensure_ascii=False)
    tools.record(
        "orchestrator", "platform_read", payload={"tool": name, "ok": True, "args": kwargs}
    )
    return json.dumps(payload, ensure_ascii=False)


def make_platform_read_tools(tools: Any, reads: Any) -> list:
    from langchain_core.tools import tool

    @tool
    def read_project_accounts(query: str | None = None, offset: int = 0) -> str:
        """List the accounts of this project. query narrows by name or domain fragment
        (case-insensitive); the answer's total is the whole filtered membership and its
        accounts list is one page — read again with offset when total is larger. Use this to
        find the account the brief names before reading its research."""
        return _call(tools, reads, "read_project_accounts", query=query, offset=offset)

    @tool
    def read_account_research(
        account_entity_id: str,
        section: str = "overview",
        field_prefix: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> str:
        """Read account context or gated claims. Both sections page: follow next_offset until
        null; limit caps overview chunks or claims. Overview entries carry section_key,
        display_block_id, section_json, section_sha256, chunk_index and chunk_count. A single
        chunk is complete JSON with body_json, cited_claim_ids and generated_at. For multiple
        chunks, concatenate section_json by chunk_index for the same block/hash, verify SHA-256,
        then parse; restart at offset=0 if the block changes. Preserve source/status labels:
        stored overview prose (including imported unverified notes) is context, not verified
        evidence. overview_not_written means read section="claims". Claims retain the
        verification/use gate; field_prefix narrows a family named in prefixes."""
        return _call(
            tools,
            reads,
            "read_account_research",
            account_entity_id=account_entity_id,
            section=section,
            field_prefix=field_prefix,
            offset=offset,
            **({"limit": limit} if limit is not None else {}),
        )

    @tool
    def read_claims(
        entity_id: str,
        field_prefix: str | None = None,
        tier: int | None = None,
        verification_status: str | None = None,
        since: str | None = None,
        offset: int = 0,
    ) -> str:
        """A specific question about one account's or one contact's claims: one family
        (field_prefix), one source tier (1 deterministic API .. 4 LLM synthesis), only verified,
        or only since a date. Paged like read_account_research. Quote a fact only with a claim
        behind it; bind it to the claim id the answer gives you."""
        return _call(
            tools,
            reads,
            "read_claims",
            entity_id=entity_id,
            field_prefix=field_prefix,
            tier=tier,
            verification_status=verification_status,
            since=since,
            offset=offset,
        )

    return [read_project_accounts, read_account_research, read_claims]


def _render_index(seller: Any, documents: list[Any]) -> str:
    lines = [
        "# Seller knowledge",
        "",
        "The brand's own knowledge documents, as pinned for this design session. Paths are",
        "relative to seller/. Read a document when you need what it holds.",
        "",
    ]
    if seller.product_set:
        lines.append(
            "Confirmed products for this project (selection version "
            f"{seller.product_set['selection_version']}): "
            + ", ".join(seller.product_set["product_ids"])
        )
        lines.append("")
    if seller.confirmed_icp_path:
        lines.append(f"The project's confirmed ICP: {seller.confirmed_icp_path}")
        lines.append("")
    for doc in documents:
        lines.append(f"- {doc.path} — {doc.kind} (v{doc.version}, {doc.status})")
    return "\n".join(lines) + "\n"


def _is_contained(document_path: str) -> bool:
    """A document path names a FILE under seller/ — never absolute, never a climb, never the
    directory itself (``""``/``"."`` resolve to the root and would write over it)."""
    candidate = Path(document_path)
    return bool(candidate.name) and not candidate.is_absolute() and ".." not in candidate.parts


def write_seller_knowledge(workspace: Path, reads: Any, *, record: Callable[..., Any]) -> bool:
    """Write ``seller/`` once per pin. Returns True when it wrote, False when current or empty."""

    try:
        seller = reads.seller_knowledge()
    except Exception as error:  # noqa: BLE001 - an unavailable pin is a fact, never a crash
        code = str(error) or error.__class__.__name__
        record("orchestrator", "seller_knowledge_unavailable", payload={"code": code})
        logger.info("seller_knowledge_unavailable", code=code)
        return False
    if not seller.documents or not seller.documents_sha256:
        return False
    root = workspace / SELLER_DIR
    pin = root / _PIN_FILE
    if pin.is_file() and pin.read_text(encoding="utf-8") == seller.documents_sha256:
        return False
    # A new pin replaces the old tree wholesale: a document the brand retired must not survive
    # as a file the agent can still read and design against.
    if root.exists():
        shutil.rmtree(root)
    written = []
    for doc in seller.documents:
        if not _is_contained(doc.path):
            logger.warning("seller_document_path_refused", path=doc.path)
            continue
        target = root / doc.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc.body_text, encoding="utf-8")
        written.append(doc)
    # The index names exactly the files that exist: a path this refused is not offered as a
    # document the agent can open.
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.md").write_text(_render_index(seller, written), encoding="utf-8")
    pin.write_text(seller.documents_sha256, encoding="utf-8")
    record(
        "orchestrator",
        "seller_knowledge_written",
        payload={
            "documents": len(written),
            "refused": len(seller.documents) - len(written),
            "pin": seller.documents_sha256[:12],
        },
    )
    return True


def write_project_design_context(
    workspace: Path, reads: Any, *, record: Callable[..., Any]
) -> None:
    """Materialize original project sources, replacing stale bytes even on a failed read.

    The adapter owns scope and artifact integrity. This fixed-path derived copy is read-only
    to the agent; unavailable context is explicit, never an earlier turn's silent fallback.
    """
    try:
        payload = reads.project_design_context()
    except Exception:  # noqa: BLE001 - unavailable context must clear the previous snapshot
        # Do not propagate arbitrary adapter exception text into agent context or traces.
        payload = {"status": "unavailable", "is_live_project_view": False, "files": []}
    root = workspace / PROJECT_CONTEXT_DIR
    root.mkdir(parents=True, exist_ok=True)
    (root / "snapshot.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    record(
        "orchestrator",
        "project_design_context_written",
        payload={
            "status": payload["status"],
            "source_turn_id": payload.get("source_turn_id"),
            "source_pin_sha256": payload.get("source_pin_sha256"),
            "files": [file["path"] for file in payload["files"]],
        },
    )


__all__ = [
    "PROJECT_CONTEXT_DIR",
    "SELLER_DIR",
    "make_platform_read_tools",
    "write_project_design_context",
    "write_seller_knowledge",
]

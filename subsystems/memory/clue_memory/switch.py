"""The workspace kill-switch (Doc M §17 / PB-B3 ruling 2): per-workspace DB toggle + audit,
under the ``CLUE_MEMORY_ENABLED`` deploy master default.

Enforced at the two seams and nowhere else — there is no third path. Off ≠ erasure: the store
freezes intact (toggling back on restores exactly what was there); DSAR verbs
(``compliance.py``) operate regardless — obligations attach to *holding* data, not using it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import Settings
from clue_memory import _store


async def is_memory_enabled(conn: AsyncConnection, workspace_id: str, settings: Settings) -> bool:
    """Effective state = deploy master default ∧ workspace toggle (missing row = on)."""
    if not settings.memory_enabled:
        return False
    toggle = await _store.get_switch(conn, workspace_id)
    return True if toggle is None else toggle


async def set_memory_enabled(
    conn: AsyncConnection, workspace_id: str, enabled: bool, *, actor: str
) -> None:
    """Instant-effect user action (no propose→promote ceremony), audit-logged (who/when) —
    the audit entry is what makes journal claims of "memory was off" verifiable."""
    await _store.set_switch(conn, workspace_id, enabled, actor)


async def switch_audit(conn: AsyncConnection, workspace_id: str) -> list[dict[str, Any]]:
    """The audit trail, oldest first."""
    return await _store.list_switch_audit(conn, workspace_id)

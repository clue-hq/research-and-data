"""Static form of Lane B acceptance gate 1: provider values are lookup attributes only."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from sqlalchemy import text

from .conftest import rollback_conn, run_async

REPO = Path(__file__).resolve().parents[2]

_KEY_CLAUSE = re.compile(
    r"\b(?:PRIMARY\s+KEY|FOREIGN\s+KEY)\s*\(([^)]*)\)"
    r"|\bREFERENCES\s+[a-z_][a-z0-9_]*\s*\(([^)]*)\)",
    re.IGNORECASE,
)
_BANNED_KEY = re.compile(
    r"\b(?:provider_subject|provider_session_subject|clerk(?:_[a-z0-9]+)*|"
    r"auth_provider_org(?:anization)?_id|identity_provider_org(?:anization)?_id|"
    r"email(?:_address)?|invited_address|session_token)\b",
    re.IGNORECASE,
)
_BANNED_SCHEMA_ID = re.compile(
    r"\b(?:clerk|auth_provider|identity_provider|provider_session|email)_?[a-z0-9_]*_id\b",
    re.IGNORECASE,
)


def _sql_strings(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tuple(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def test_no_provider_or_email_value_is_a_schema_key() -> None:
    offenders: list[str] = []
    for path in sorted((REPO / "alembic" / "versions").glob("*.py")):
        for sql in _sql_strings(path):
            for match in _KEY_CLAUSE.finditer(sql):
                columns = next(group for group in match.groups() if group is not None)
                if _BANNED_KEY.search(columns):
                    offenders.append(f"{path.name}: {match.group(0).strip()}")
            if ("CREATE TABLE" in sql.upper() or "ALTER TABLE" in sql.upper()) and (
                match := _BANNED_SCHEMA_ID.search(sql)
            ):
                offenders.append(f"{path.name}: provider-authored schema id {match.group(0)!r}")
    assert not offenders, f"provider-authored values entered schema keys: {offenders}"


def test_provider_subject_ddl_is_confined_to_auth_identity() -> None:
    offenders: list[str] = []
    for path in sorted((REPO / "alembic" / "versions").glob("*.py")):
        for sql in _sql_strings(path):
            normalized = " ".join(sql.lower().split())
            if (
                "provider_subject" in normalized
                and ("create table" in normalized or "alter table" in normalized)
                and "auth_identity" not in normalized
            ):
                offenders.append(path.name)
    assert not offenders, f"provider_subject escaped auth_identity DDL: {offenders}"


def test_b1_migration_uses_only_internal_foreign_key_targets() -> None:
    migration = REPO / "alembic" / "versions" / "9398ae4467e3_lane_b_internal_identity_substrate.py"
    sql = "\n".join(_sql_strings(migration)).lower()
    assert "references auth_identity (provider_subject)" not in sql
    assert "references platform_user (user_id)" in sql
    assert "references workspace (workspace_id)" in sql
    assert "references workspace_membership (membership_id, workspace_id)" in sql


def test_provider_jwt_interpretation_is_confined_to_authenticator_adapter() -> None:
    adapter = REPO / "platform" / "auth" / "clue_auth" / "providers" / "clerk.py"
    offenders: list[str] = []
    for root in (REPO / "platform", REPO / "subsystems", REPO / "libs"):
        for path in root.rglob("*.py"):
            if path == adapter or "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(
                    alias.name == "jwt" for alias in node.names
                ):
                    offenders.append(str(path.relative_to(REPO)))
                if isinstance(node, ast.ImportFrom) and node.module == "jwt":
                    offenders.append(str(path.relative_to(REPO)))
    assert not offenders, f"provider JWT interpretation escaped the authenticator: {offenders}"


@pytest.mark.usefixtures("require_auth_db")
def test_live_schema_has_no_provider_or_email_primary_foreign_key() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        SELECT tc.table_name, kcu.column_name, tc.constraint_type
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                          ON kcu.constraint_schema = tc.constraint_schema
                         AND kcu.constraint_name = tc.constraint_name
                         AND kcu.table_name = tc.table_name
                        WHERE tc.table_schema = 'public'
                          AND tc.constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY')
                        ORDER BY tc.table_name, kcu.column_name
                        """
                    )
                )
            ).all()
            offenders = [
                f"{table}.{column} ({constraint_type})"
                for table, column, constraint_type in rows
                if _BANNED_KEY.search(str(column)) or _BANNED_SCHEMA_ID.search(str(column))
            ]
            assert not offenders, f"provider-authored live schema keys: {offenders}"

    run_async(scenario())

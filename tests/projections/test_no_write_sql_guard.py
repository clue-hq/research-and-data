"""Review F10 — the static half of the D7 read-only guarantee.

The runtime half (``test_projection_reads_issue_no_writes``) diffs ``pg_stat_xact_user_tables``
on the ONE test connection every reader is bound to — sound for the current wiring, but blind to
a future reader that opens its own connection. This static guard closes that hole from the other
side: no write-SQL token may appear anywhere in ``clue_projections`` source. Together the two
make "projections never write" enforced, not trusted.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PKG = REPO / "platform" / "projections" / "clue_projections"

# Word-boundary write-SQL tokens. UPDATE/DELETE also appear in prose ("updated_at", "delete the
# row"), so match them only in UPPERCASE SQL form followed by whitespace — the form SQLAlchemy
# text() queries use in this repo.
_WRITE_SQL = re.compile(
    r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|CREATE\s+TABLE|ALTER\s+TABLE|TRUNCATE)\b"
)


def test_projections_package_contains_no_write_sql() -> None:
    offenders: list[str] = []
    files = list(PKG.rglob("*.py"))
    assert len(files) >= 5, f"scan scope broken — only {len(files)} files under {PKG}"
    for path in files:
        for match in _WRITE_SQL.finditer(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(REPO)}: {match.group(0)!r}")
    assert not offenders, f"write SQL in the read-only projections package (D7): {offenders}"

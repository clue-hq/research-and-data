"""Static guard: product verdict reads have one owner; judge cache and DSAR remain explicit."""

from __future__ import annotations

import re
from pathlib import Path


def test_faithfulness_verdict_sql_ownership_is_closed() -> None:
    root = Path(__file__).resolve().parents[2]
    operation = re.compile(
        r"\b(FROM|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+faithfulness_verdict\b",
        re.IGNORECASE,
    )
    found: dict[str, set[str]] = {}
    for top in (root / "subsystems", root / "platform"):
        for path in top.rglob("*.py"):
            matches = {
                " ".join(match.group(1).upper().split())
                for match in operation.finditer(path.read_text())
            }
            if matches:
                found[str(path.relative_to(root))] = matches

    assert found == {
        "subsystems/research/clue_research/claimstore/faithfulness_attribution.py": {"FROM"},
        "subsystems/research/clue_research/compliance/dsar.py": {"UPDATE"},
        "subsystems/research/clue_research/verification/faithfulness.py": {
            "FROM",
            "INSERT INTO",
        },
    }

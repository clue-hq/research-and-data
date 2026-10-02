"""First deployment: the S3/R2 storage settings the code reads are documented in .env.example
(the repo's env parity rule), with their shipped defaults."""

from __future__ import annotations

import re
from pathlib import Path

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"

#: Every storage env name the code reads, and the value .env.example must ship.
DOCUMENTED = {
    "CLUE_STORAGE_BACKEND": "fs",
    "CLUE_STORAGE_S3_BUCKET": "",
    "CLUE_STORAGE_S3_ENDPOINT_URL": "",
    "CLUE_STORAGE_S3_REGION": "",
    "CLUE_STORAGE_S3_ACCESS_KEY_ID": "",
    "CLUE_STORAGE_S3_SECRET_ACCESS_KEY": "",
}


def test_every_storage_env_name_is_documented_with_its_default() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for name, default in DOCUMENTED.items():
        match = re.search(rf"^{name}=(.*)$", text, re.MULTILINE)
        assert match is not None, f"absent from .env.example: {name}"
        assert match.group(1).strip() == default, name

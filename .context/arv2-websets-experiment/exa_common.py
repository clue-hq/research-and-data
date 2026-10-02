"""Shared bits for the Websets-vs-search discovery experiment: HTTP, raw saving, the ledger."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
LEDGER = HERE / "ledger.json"
EXA_KEY = os.environ["CLUE_EXA_API_KEY"]

#: The v3 proof of concept's ICP, verbatim from its BRIEF (founder ruling 1).
ICP_TEXT = (
    "US B2B vertical SaaS or AI startup that raised a Series A or Series A extension within the "
    "last 24 months (not seed, not Series B or later), selling software to independent small "
    "businesses in a fragmented vertical (dental practices, veterinary clinics, HVAC and plumbing "
    "contractors, auto repair shops, law firms, pharmacies, restaurants, trucking), actively "
    "hiring go-to-market roles now, and showing buying-intent signals for outbound or "
    "account-based prospecting."
)


def request(method: str, url: str, body: dict | None = None, *, timeout: int = 120) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"x-api-key": EXA_KEY, "Content-Type": "application/json"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, text = resp.status, resp.read().decode()
    except urllib.error.HTTPError as err:
        status, text = err.code, err.read().decode()
    elapsed = round(time.monotonic() - started, 2)
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        out = {"_unparsed": text[:4000]}
    if isinstance(out, dict):
        out["_http_status"] = status
        out["_elapsed_s"] = elapsed
    return status, out


def save_raw(label: str, obj: object) -> Path:
    RAW.mkdir(exist_ok=True)
    path = RAW / f"{label}.json"
    path.write_text(json.dumps(obj, indent=2))
    return path


def ledger_append(row: dict) -> None:
    rows = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
    rows.append({"at": datetime.now(UTC).isoformat(), **row})
    LEDGER.write_text(json.dumps(rows, indent=2))

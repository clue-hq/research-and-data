"""Readable names over immutable source metadata; no copied files or alternate identity store."""

import re
import unicodedata
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

SOURCE_PATH = re.compile(r"/evidence/([0-9]{4,10})-([a-z0-9]+(?:-[a-z0-9]+)*)\.json\Z")
INDEX_PATH = "/evidence/index.json"


def source_path(source: Mapping[str, Any]) -> str:
    """Account manifest revision is assigned once and never changes on grant refresh.

    Titles are optional provider metadata, never instructions. Bound/sanitize them and use
    the already-unique account revision to distinguish same-title captures and people.
    """
    metadata = source.get("metadata") or {}
    title = metadata.get("title")
    if not isinstance(title, str) or not title.strip():
        url = urlsplit(source.get("source_url") or "")
        path_parts = [
            p for p in url.path.split("/") if p and not re.fullmatch(r"[0-9a-f-]{24,}", p)
        ]
        title = " ".join([url.hostname or "", *path_parts]) or str(source["kind"])
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:80].rstrip("-")
    return f"/evidence/{int(source['revision']):04d}-{slug or 'source'}.json"

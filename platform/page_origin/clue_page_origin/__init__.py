"""The public page origin (custom-domain publishing S1, spec §5).

One small FastAPI service on Railway. Every request arrives through the Cloudflare Worker
``pages-edge`` carrying ``X-Clue-Public-Host`` (the hostname the visitor typed) and
``X-Clue-Edge-Auth`` (a shared secret); the origin resolves the hostname through the
``workspace_hostname`` registry, the path through ``design_web_publish``, and serves the immutable
publish package. It imports the spine, the design DAL and storage — never ``lumen_api`` or
``clue_api``.
"""

from clue_page_origin.app import create_page_origin_app
from clue_page_origin.edge import EdgeGate
from clue_page_origin.reads import DbPageReads, PageReads, ServedPage, ServedPublish

__all__ = [
    "create_page_origin_app",
    "EdgeGate",
    "DbPageReads",
    "PageReads",
    "ServedPage",
    "ServedPublish",
]

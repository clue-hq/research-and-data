"""Phase C3 raw-material ingestion."""

from clue_research.ingestion.adapters import (
    DocumentAdapterRegistry,
    RegisteredDocumentAdapter,
    default_document_adapters,
    paid_ocr_manifest,
)
from clue_research.ingestion.engine import IngestionEngine
from clue_research.ingestion.errors import IngestionError
from clue_research.ingestion.models import (
    DeclaredMaterialContext,
    IngestionFailureCode,
    IngestionJob,
    IngestionResultRefs,
    IngestionSegment,
    IngestionTarget,
    MaterialContext,
)
from clue_research.ingestion.store import (
    declared_context_hash,
    get_job,
    list_segments,
    mark_erased,
)

__all__ = [
    "DeclaredMaterialContext",
    "DocumentAdapterRegistry",
    "IngestionError",
    "IngestionFailureCode",
    "IngestionEngine",
    "IngestionJob",
    "IngestionResultRefs",
    "IngestionSegment",
    "IngestionTarget",
    "MaterialContext",
    "RegisteredDocumentAdapter",
    "declared_context_hash",
    "default_document_adapters",
    "get_job",
    "list_segments",
    "mark_erased",
    "paid_ocr_manifest",
]

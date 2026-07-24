from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_config.ingestion import IngestionPolicy
from clue_core.ingestion import IngestionJobRef, IngestionStatus, new_ingestion_job_id
from clue_research.ingestion import DeclaredMaterialContext, MaterialContext


def test_ingestion_policy_rejects_zero_limits() -> None:
    with pytest.raises(ValidationError):
        IngestionPolicy(max_bytes=0)
    with pytest.raises(ValidationError):
        IngestionPolicy(max_segments=0)
    with pytest.raises(ValidationError):
        IngestionPolicy(max_retries=-1)


def test_context_requires_project_and_product_coordinates() -> None:
    with pytest.raises(ValidationError, match="project_id"):
        DeclaredMaterialContext(
            brand_id="brd", document_context=MaterialContext.PROJECT_INSTRUCTION
        )
    with pytest.raises(ValidationError, match="product_id"):
        DeclaredMaterialContext(
            brand_id="brd", document_context=MaterialContext.CLIENT_ABOUT_PRODUCT
        )


def test_reference_is_frozen_and_reference_only() -> None:
    ref = IngestionJobRef(
        ingestion_job_id=new_ingestion_job_id(),
        artifact_key="ws/hash",
        status=IngestionStatus.QUEUED,
    )
    assert set(ref.model_dump()) == {"ingestion_job_id", "artifact_key", "status"}
    with pytest.raises(ValidationError):
        IngestionJobRef.model_validate({**ref.model_dump(), "text": "secret"})

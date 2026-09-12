"""One answer to "which versions of a document are servable", restated in six modules.

``clue_api.arv2`` may not import ``clue_api`` modules outside the lane (Global Constraint 7), so
the tuple that decides whether a document still owns its path is written out in each module that
asks the question rather than imported from one home. That is structurally forced, and it is a
drift risk: add a status to one copy and ``status.md``'s document list, the project's documents
tab, the ICP gate and the brand's knowledge surface start disagreeing about what a workspace owns
— silently, because each copy is internally consistent.

This guard is the repo's usual answer to a forced restatement (the ``conflict_tier_threshold``
pattern): no database, no imports beyond the modules themselves, and a loud failure the moment two
copies stop naming the same set.
"""

from __future__ import annotations

from clue_api.arv2.icp_authoring import _SERVABLE_STATUSES as ICP_AUTHORING
from clue_api.arv2.icp_confirmation import _SERVABLE_STATUSES as ICP_CONFIRMATION
from clue_api.arv2.onboarding_store import _SERVED_STATUSES as ONBOARDING_STORE
from clue_api.arv2.project_documents import _SERVABLE_STATUSES as PROJECT_DOCUMENTS
from clue_api.brand_knowledge_context import SERVABLE_STATUSES as BRAND_KNOWLEDGE_CONTEXT
from clue_api.frontend_read.brand_knowledge import SERVABLE_STATUSES as FRONTEND_READ

#: Every copy, named by where it lives, so a failure names the file to fix.
_COPIES: dict[str, tuple[str, ...]] = {
    "arv2/project_documents.py::_SERVABLE_STATUSES": PROJECT_DOCUMENTS,
    "arv2/icp_authoring.py::_SERVABLE_STATUSES": ICP_AUTHORING,
    "arv2/icp_confirmation.py::_SERVABLE_STATUSES": ICP_CONFIRMATION,
    "arv2/onboarding_store.py::_SERVED_STATUSES": ONBOARDING_STORE,
    "brand_knowledge_context.py::SERVABLE_STATUSES": BRAND_KNOWLEDGE_CONTEXT,
    "frontend_read/brand_knowledge.py::SERVABLE_STATUSES": FRONTEND_READ,
}


def test_every_servable_status_tuple_names_the_same_set() -> None:
    """All six copies are one set. Order is each module's own business; membership is not."""

    disagreeing = {
        where: sorted(statuses)
        for where, statuses in _COPIES.items()
        if set(statuses) != set(PROJECT_DOCUMENTS)
    }
    assert disagreeing == {}, (
        "the servable-status tuples have drifted; they must name the same set: "
        f"{sorted(PROJECT_DOCUMENTS)}"
    )


def test_the_set_is_the_three_statuses_a_document_owns_its_path_in() -> None:
    """Pinned by name too, so *adding* a status is a deliberate edit of this test as well —
    a document is servable while it has bytes and has not been superseded."""

    assert set(PROJECT_DOCUMENTS) == {"ready", "proposed", "confirmed"}

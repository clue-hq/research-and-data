from __future__ import annotations

import pytest

from clue_api.arv2.knowledge_frontmatter import document_identity, parse_front_matter
from clue_api.arv2.onboarding_documents import KnowledgeDocument, render_markdown


def test_parse_is_the_inverse_of_render() -> None:
    doc = KnowledgeDocument(
        kind="icp-definition",
        folder="audience",
        path="audience/icp-x.md",
        front_matter={
            "kind": "icp-definition",
            "icp_key": "x",
            "product_ids": ["prd_1"],
            "persona_map": {"user": {"titles": ["Nurse"]}},
        },
        body="# X\n\nBody.\n",
        cost=None,
    )
    front, body = parse_front_matter(render_markdown(doc))
    assert front == doc.front_matter and body == doc.body
    assert document_identity(front) == ("icp-definition", "x")


def test_a_document_without_fences_or_with_a_non_mapping_is_refused() -> None:
    with pytest.raises(ValueError):
        parse_front_matter("# no front matter\n")
    with pytest.raises(ValueError):
        parse_front_matter("---\n- a\n- b\n---\n\nbody\n")
    assert document_identity({"kind": "audience-persona"}) == ("audience-persona", None)


@pytest.mark.parametrize("body", ["", "\n\n# Heading\n\n", "# Café\r\n\r\nBody\r\n"])
def test_editable_markdown_preserves_body_whitespace(body: str) -> None:
    doc = KnowledgeDocument(
        kind="company-overview",
        folder="company",
        path="company/overview.md",
        front_matter={"kind": "company-overview"},
        body=body,
        cost=None,
    )
    assert parse_front_matter(render_markdown(doc), preserve_body=True)[1] == body

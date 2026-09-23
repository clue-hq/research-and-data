from clue_api.arv2.quality_brief import document_excerpt


def test_document_preview_keeps_structured_criteria_and_marks_prose_continuation():
    raw = (
        "---\nkind: icp-definition\nqualifier_fields:\n"
        "- field_key: account.workflow\n  description: Investigate referral delays.\n"
        "  display: section:why-fit\nclosed_won_patterns:\n- Centralised intake team\n"
        "as_of: '2026-09-23'\n---\n" + "Original narrative.\n" * 500
    )
    preview, continues = document_excerpt(raw)
    assert continues
    assert "Investigate referral delays." in preview
    assert "Centralised intake team" in preview
    assert "2026-09-23" in preview
    assert "section:why-fit" not in preview
    assert "Original narrative." in preview


def test_plain_prose_and_short_originals_are_preserved_without_inference():
    body = "The seller describes its work here.\nPricing is not stated."
    assert document_excerpt(body) == (body, False)

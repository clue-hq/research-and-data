from clue_design.asset_context import AssetAnalysis


def analysis(title: str = "Product panel", occurrences: list[dict] | None = None) -> dict:
    return AssetAnalysis(
        creative_type="product_screenshot", usage_roles=["card_image"],
        classification_reason="A product interface is visible", title=title,
        description="A product interface with a navigation sidebar.",
        usage="Use in a feature card where interface details are readable.",
        avoid_when="Avoid as a text background", placement="Preserve interface labels",
        tags=["interface"], observed={
            "subjects": ["interface"], "composition": "sidebar and content",
            "colors": ["white"], "readable_text": [], "typography": "sans serif",
            "logo_placement": "unknown", "negative_space": "little", "transparency": "unknown",
        }, source_interpretations=[{
            "occurrence_id": item["occurrence_id"], "observed_usage": "supplied placement",
            "logo_relationship": "unknown", "relationship_evidence": "",
            "messaging_angle": "", "tone": "", "cta": "", "visual_hierarchy": "",
            "copy_density": "", "product_or_use_case_hypothesis": "",
            "audience_hypothesis": "", "design_patterns": [], "uncertainties": [],
        } for item in occurrences or []], uncertainties=["Small text is illegible"],
        reuse_boundary="Reference only until rights are confirmed",
    ).model_dump()

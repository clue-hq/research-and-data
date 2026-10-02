"""The shared ARV2 presentation policy, separate from factual applicability."""

from clue_core import EntityType, UseClass
from clue_research.compliance.use_gate import WorkspacePolicy


def research_display_allowed(
    *,
    entity_type: EntityType | str,
    use_class: UseClass | str | None,
    outreach_safe: bool,
    policy: WorkspacePolicy,
    restricted: bool = False,
) -> bool:
    """Restricted research can retain uncertainty, but never bypass display-class controls.

    Account facts have no personal-data subject. None on a contact's non-facet field means
    professional-public, matching the established ARV2 reader contract.
    """
    if entity_type == EntityType.ACCOUNT:
        return True
    if use_class == UseClass.SENSITIVE:
        return policy.display_sensitive
    if not outreach_safe and not restricted:
        return False
    if use_class == UseClass.PERSONAL_PUBLIC_NON_SENSITIVE:
        return policy.display_personal_public_non_sensitive
    return policy.display_professional_public

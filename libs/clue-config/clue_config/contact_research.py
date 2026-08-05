"""Conservative, layered contact-research policy defaults (M8C C0)."""

from __future__ import annotations

from clue_core import ContactResearchPolicyPin


class ContactResearchPolicy(ContactResearchPolicyPin):
    """Policy-as-data for bounded contact research and separately metered reveals.

    The C0 default admits snapshot-backed professional facts and Exa contact research as source
    families, but authorizes no email/phone provider and reserves zero reveal budget.  A later C5
    revision must replace this complete sub-tree before a reveal is executable.
    """

    def pin(self) -> ContactResearchPolicyPin:
        """Freeze the effective layered config into the content-addressed core receipt shape."""

        return ContactResearchPolicyPin.model_validate(self.model_dump(mode="python"))


DEFAULT_CONTACT_RESEARCH_POLICY = ContactResearchPolicy()


__all__ = ["ContactResearchPolicy", "DEFAULT_CONTACT_RESEARCH_POLICY"]

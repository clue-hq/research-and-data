---
name: web-contact-personalization
description: Use when a website targets a named professional or buying-committee member, or a person-level page only changes the name, title or salutation of an account page.
---

# Design for this person's professional decision

Use `web-account-personalization` for exact identity, evidence status and allowed
use. Read [worked contact brief](references/worked-contact.md).

1. **Resolve the person.** Establish their exact employer and supplied contact
   entity ID. When exposed, use `read_claims(entity_id=<resolved contact ID>, ...)`
   for relevant professional statements, responsibilities or initiatives. Follow
   returned pagination as needed. Account overview alone is not a contact read.
   If the ID/tool/evidence is absent, use eligible supplied excerpts with their
   attribution or name the gap; never guess an ID or launch discovery in design.
2. **Find the decision.** Prefer the person's own eligible, sourced professional
   criterion; next use a documented responsibility. A title alone supports
   role-relevant framing, not their private priorities, feelings or buying authority.
   Keep the evidence level explicit in the internal brief.
3. **Write the professional brief.** Record: person/employer; supporting excerpt
   and status; responsibility/criterion; question they need to resolve; seller
   mechanism; demonstration; actual next action. Keep it in the existing plan.
4. **Change the material.** Use `web-decision-material` to select a scenario,
   product state, proof or worksheet that answers that person's question. Compared
   with the account page, something substantive must change: explanation, priority,
   depth or evidence. A greeting plus the same feature tour is not person-level work.
5. **Choose respectful presentation.** Their name need not be the headline or a
   navbar label. A discreet eyebrow can identify the intended reader; the headline
   explains the professional value. Use authentic portraits only when available,
   appropriate and requested or clearly useful; do not synthesize a named person.

Public professional evidence may shape relevant work content. Personal facets also
require the existing strong identity and allowed-use gates. Do not use private or
sensitive interests, inferred emotional pressure, assumed budget authority or an
unrelated hobby to manufacture depth. An eligible hobby still needs a clear,
respectful connection to the requested experience; it is not a default hook.

Before composition, compare account and contact briefs side by side. Can you name
the professional evidence that changed the page? If not, report a role-relevant
draft rather than pretending it is deeply person-specific. `campaign-landing-page`
chooses the CTA from the actual task and offer. `review-website` verifies the result.

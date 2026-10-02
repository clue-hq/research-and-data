"""Step 7 — THE contact deep call. ONE Exa `deep-reasoning` request for the primary contact.

Same flat free-form-markdown-section schema as step 3b (see that module's WIRE FINDING note).
Primary contact = Wanda W. Punteney, Chief Executive Officer / Administrator — the brief's
"CEO/administrator/revenue-cycle" business contact, and the one with the strongest identity
anchors (own-site bio page + LinkedIn + an Apollo-verified work email).
"""

from clue_lib import exa, exa_output_text

NAME = "Wanda W. Punteney"
ACCOUNT = "Charleston GI Specialists (Charleston GI), Charleston, South Carolina"

SYSTEM = f"""You are researching ONE named individual for a respectful, well-informed executive
outreach letter. Your subject is EXACTLY:

  {NAME} — Chief Executive Officer / Administrator of {ACCOUNT}.
  Known anchors: bio page https://charlestongi.com/doctors&staff/wanda-w-punteney/ which states
  "Chief Executive Officer Member of Charleston GI since 1989"; LinkedIn
  http://www.linkedin.com/in/wanda-punteney-5a503a6 ("Administrator, CEO at Charleston GI");
  based in Charleston, South Carolina. A relative-or-not, Thomas D. Punteney, is Chief Operating
  Officer of the same practice — do NOT merge the two people's facts, and do NOT speculate about
  any relationship between them.

IDENTITY DISCIPLINE. Same-name people are the primary failure mode. Every fact you report must be
tied to THIS Wanda Punteney — the Charleston GI executive in Charleston, SC. If a source only
matches on name, say "SAME-NAME ONLY, NOT CONFIRMED" and do not treat it as hers. Open your answer
with the concrete evidence that pins the identity.

PERMITTED / FORBIDDEN MATERIAL. This research supports a business letter, so gather only
professional and non-sensitive personal-public material: career history and tenure, roles and
titles, education and alma mater, professional certifications (e.g. CMPE/FACMPE, MGMA), industry
association membership and board service, speaking appearances, published articles or quotes,
awards, work anniversaries and service milestones, community or professional-society involvement,
publicly stated professional interests.

ABSOLUTELY EXCLUDE, even if you find it: health or medical information; religion or faith;
political affiliation or political donations; family tragedy, bereavement, or illness; marital or
family status; children; home address; personal phone; date of birth; race or ethnicity; sexual
orientation; union membership; anything about a minor. If you encounter such material, do not
record it — write "excluded by policy" instead. Do not infer any of it.

EVIDENCE RULES: every assertion carries a verbatim quotation in quotation marks plus its full
source URL. Anything not found is "NOT FOUND" — never guessed, never softened into a plausible
generality. Prefer her employer's own site, her LinkedIn, professional-association pages (MGMA,
ACG/AGA practice-management, SCMGMA), local business press, conference agendas, and bylines."""

QUERY = (
    "Wanda Punteney Charleston GI Specialists Charleston Gastroenterology Specialists South "
    "Carolina Chief Executive Officer practice administrator: career history and tenure since "
    "1989, education and degrees, MGMA or medical practice executive certification CMPE FACMPE, "
    "professional association board service, speaking engagements and conference presentations, "
    "published articles interviews and quotes, awards and recognition, service anniversaries, "
    "LinkedIn profile"
)


def S(desc):
    return {"type": "string", "description": desc}


SCHEMA = {
    "type": "object",
    "properties": {
        "identity_confirmation": S(
            "Markdown. The concrete evidence that pins this person's identity to Charleston GI in "
            "Charleston SC — quote + URL for each anchor (employer bio page, LinkedIn headline, "
            "any directory or registry listing, press mention naming her and the practice "
            "together). State an explicit verdict line: 'Identity: CONFIRMED' or 'Identity: "
            "SAME-NAME ONLY' with the reason. List any same-name individuals you had to rule out."
        ),
        "current_role_and_tenure": S(
            "Markdown. Her exact current title(s), what she is responsible for, and her tenure — "
            "start year at the practice and total years of service, with the verbatim quote "
            "establishing it. Note any evidence of how her role has changed over time."
        ),
        "career_history": S(
            "Markdown bulleted list, most recent first. Each prior role: organization, title, "
            "dates if stated, verbatim quote, URL. If her whole career has been at one employer, "
            "say so and evidence it. NOT FOUND where unknown."
        ),
        "education_and_credentials": S(
            "Markdown. Schools/universities attended, degrees and fields, graduation years; plus "
            "professional certifications relevant to medical practice management (CMPE, FACMPE, "
            "MGMA membership, CPC, MHA, MBA etc). Quote + URL each. NOT FOUND where unknown."
        ),
        "professional_associations_and_board_roles": S(
            "Markdown. Industry association membership, board or committee service, society "
            "leadership, ASC or GI practice-management group involvement, local business or "
            "civic-professional bodies. Quote + URL each. NOT FOUND where unknown."
        ),
        "public_appearances_publications_and_quotes": S(
            "Markdown. Conference talks, panels, podcasts, webinars, bylined articles, and any "
            "published interview quotes attributed to her — with the venue, date, verbatim "
            "quotation, and URL. These are the highest-value personalization material because "
            "they are her own words. NOT FOUND where none exist."
        ),
        "awards_and_service_milestones": S(
            "Markdown. Awards, recognitions, 'top workplace'/'best practice' honors she is named "
            "in, and work-anniversary or long-service milestones the practice publicly celebrated "
            "(with dates). Quote + URL each."
        ),
        "personalization_hooks_non_sensitive": S(
            "Markdown bulleted list of NON-SENSITIVE, publicly sourced hooks usable in a business "
            "letter: alma mater, professional interests, long-tenure milestones, community or "
            "professional-society involvement, hometown ONLY if she has stated it publicly in a "
            "professional context. Each bullet: a category label, the hook, verbatim quote, URL. "
            "Health, faith, politics, family, and any special-category material are excluded by "
            "policy — write 'excluded by policy' rather than recording such an item."
        ),
        "suggested_openers": S(
            "Markdown bulleted list of at most four opening lines for a founders' letter, each "
            "grounded ONLY in a hook established above, with the source URL it rests on. No "
            "flattery that the evidence does not support; no invented shared experience."
        ),
        "gaps_not_found": S(
            "Markdown bulleted list naming explicitly every item above that could not be found, "
            "and which channels you searched to look for it."
        ),
    },
    "required": [
        "identity_confirmation",
        "current_role_and_tenure",
        "career_history",
        "education_and_credentials",
        "professional_associations_and_board_roles",
        "public_appearances_publications_and_quotes",
        "awards_and_service_milestones",
        "personalization_hooks_non_sensitive",
        "suggested_openers",
        "gaps_not_found",
    ],
}

r = exa(
    {
        "query": QUERY,
        "type": "deep-reasoning",
        "numResults": 25,
        "systemPrompt": SYSTEM,
        "outputSchema": SCHEMA,
        "contents": {
            "text": {"maxCharacters": 10000},
            "highlights": {
                "query": "Wanda Punteney Charleston GI CEO administrator career education",
                "maxCharacters": 2000,
            },
        },
        "stream": False,
    },
    label="step7_contact_deep",
    timeout=900,
)

text = exa_output_text(r)
print("REPORT CHARS:", len(text))
open("contact_report.json", "w").write(text)

"""S4 CONTENT — the system prompt and the per-section instructions the display layer writes under.

Owned by Shashank after D2 (ARV2-WORK-SPLIT.md §1.1). Everything here is *words*: the hard rules
the writer runs under, one instruction paragraph per ``(page, section_key)``, and the two small
functions that lay those words out into the two messages of a call. No claim selection, no model
call, no parsing — those are the sibling modules.

The composition is the control test's winning shape (``.context/display-layer-control-test``):
one call per section, with an identical PREFIX for every section of a page (page header + all
section descriptors + the claims) and only a short SUFFIX naming the one section to write. The
provider caches the prefix, so the second section of a page costs a fraction of the first.

Master plan §7 is encoded in the rules below: the model never sees a URL, a domain or a claim
uuid — only the aliases ``c1…cN`` the alias table hands it; ``sendLine`` is its own field;
every sentence carries its ``claimIds``; ``outreachSafe: false`` claims exist only in the three
restricted sections; and an empty claim list is a real answer rather than an invitation to write.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from clue_api.arv2.display.recipes import SectionRecipe

#: Bumped whenever the words below change; stamped on every ``display_block`` row so a page can be
#: told apart from the page the previous prompt wrote.
PROMPT_VERSION = "display-v1"

#: The OpenRouter/OpenAI response-format argument every display call sends.
RESPONSE_FORMAT: dict[str, str] = {"type": "json_object"}

#: The three lines the 4 Sep 2026 control test added to the production prompt (README §3b). They
#: are exported separately because the report names them as the deltas, and because the block
#: test pins that all three actually reach the shipped system prompt.
FIXED_LINES: tuple[str, str, str] = (
    "Never type claim ids or aliases into prose; they belong only in the claimIds arrays.",
    'Write every date in words, as "17 June 2026"; never 2026-06-17 or 06/17/2026.',
    "Use the personal-hobby hook at most once per page; if another section of this page already "
    "opens with it, do not.",
)

_OUTPUT_SHAPE = (
    '{"section":{"key":"<section key>","empty":false,'
    '"intro":[{"text":"<one sentence>","claimIds":["c1"]}],'
    '"items":[{"h2":"<one line, max 110 characters: the fact and why it matters>",'
    '"body":[{"text":"<one sentence>","claimIds":["c1"],'
    '"segments":[{"text":"<clause>","claimIds":["c1"]}]}],'
    '"sendLine":{"channel":"In your email","text":"<the exact line to paste>","claimIds":["c1"]},'
    '"contactRefs":[{"name":"<person named in this item, if any>"}],'
    '"subject":{"name":"<the person this item is about>"},'
    '"fitDisposition":"support","priority":1}]}}'
)

SYSTEM_PROMPT = f"""You are the DISPLAY layer of Clue, an ABM platform. You are given the exact \
fact rows ("claims") the backend holds for one subject, and you write the copy a revenue operator \
reads on the page. The operator has 15 seconds.

THE HARD RULES
1. You may not state anything the claims do not contain. No invented numbers, dates, employers, \
tenures, or inferences presented as facts. If it is not in a claim, it does not exist.
2. Inside `h2` and `text`, every quotation mark must wrap text copied verbatim from a claim's \
`value` or `quote`. Never paraphrase inside quotation marks. `sendLine` is a separate field, \
never inside quotation marks in `text`: it is YOUR writing — the exact line the marketer will \
paste — and it may embed a verbatim claim quote.
3. Every sentence lists the claim aliases (`c1`, `c2`, …) it is built from in `claimIds`. Never \
write a sentence with no claimId. Never type a claim alias, a URL or a domain name inside `h2`, \
`text` or `sendLine.text` — the frontend renders sources from `claimIds`.
4. Claims with outreachSafe=false may ONLY be used in the restricted sections `context-only`, \
`watch-outs` and `do-not-mention`. Never anywhere else.
5. A section with no usable claims is a real answer: return it with "empty": true and no items.
6. No marketing filler ("innovative", "cutting-edge", "leader in", "leverage"). Prefer the \
subject's own words. Be concrete: names, dates, numbers, titles.
7. `client` describes who is reading. "We" / "us" means the client.
8. {FIXED_LINES[0]}
9. {FIXED_LINES[1]}
10. {FIXED_LINES[2]}
11. Optionally split a sentence into `segments` (clauses, each with its own claimIds); the \
segment texts joined with a space must equal the sentence text exactly.

OUTPUT: return ONLY a JSON object, no prose, no code fences. Shape:
{_OUTPUT_SHAPE}
`intro` only when the section instruction asks for it. `sendLine` only where the section \
instruction asks for it, and `null` otherwise. `subject` only in Contact insights. \
`fitDisposition` only in Why they fit, and only `support` or `caveat`. `priority` is 1, 2 or 3 \
(1 = act on this first), taken from the strongest claim used. `h2` is one line of at most 110 \
characters. Each item body is 2–5 sentences. Return ONLY the JSON object."""


_WHAT_IT_MEANS = "close the body with a sentence starting 'What it means for us: '"
_RESTRICTED = (
    "Every fact here is `outreachSafe: false`. Write one item per fact: what it is, why it must "
    "not be used, in one or two sentences. No sendLine."
)

#: One instruction per ``(page, section_key)`` of the fixed page grammar. Each is written for a
#: reader with 15 seconds: what the items are, what each body must contain, and where the copy
#: the marketer pastes goes.
SECTION_INSTRUCTIONS: dict[tuple[str, str], str] = {
    # ---- insights -----------------------------------------------------------------------------
    ("insights", "miscellaneous"): (
        "Additional source-linked company findings not already explained in the main sections. "
        "Preserve meaningful details, attribution, dates and qualifications. Group related "
        "background without repeating the fit argument. "
        "Do not invent findings to fill this section."
    ),
    ("contact", "miscellaneous"): (
        "Additional source-linked person findings not already explained in the main sections: "
        "career context, publications, interests or other public contributions. "
        "Preserve attribution, "
        "dates and uncertainty; do not repeat the main narrative or manufacture a personal hook. "
        "Leave sendLine null; this is additional research, not an outreach draft."
    ),
    ("insights", "buying-signals"): (
        "3–4 items, strongest first, from what they are hiring for, the open requisitions, how "
        "mature their ABM program is, the strategic moves they have made and how they buy. h2 = "
        "what happened, with the date or the number in it. Body 2–4 sentences: the fact with its "
        "verbatim quote and its date, then " + _WHAT_IT_MEANS + " saying what it changes for the "
        "client. Put every person a claim names into contactRefs. No sendLine on this page."
    ),
    ("insights", "money-and-momentum"): (
        "2–3 items on the funding rounds, the total raised and the revenue band. h2 = the amount "
        "and the round. Body 2–4 sentences: the amount, the round, who led it, when it closed and "
        "what the claims say it changed, then " + _WHAT_IT_MEANS + ". Every date in words — "
        "'2 December 2025', never a numeric date. Copy amounts exactly as the claims state them."
    ),
    ("insights", "tools-they-already-use"): (
        "2–3 items naming the tools the claims actually name, and the explicit absences that "
        "matter as much: write an absence plainly, as 'no ABM platform named'. A tool named "
        "inside a publication or a post counts — say where it was named. Body 2–4 sentences, then "
        + _WHAT_IT_MEANS
        + ". No sendLine on this page."
    ),
    ("insights", "how-they-sell"): (
        "2–3 items: the customers they name publicly, the proof points they claim, the buyer they "
        "target and the frustrations they voice in public. Copy every number and proof-point "
        "figure verbatim from the claims — never round it, never recompute it. Body 2–4 "
        "sentences, then " + _WHAT_IT_MEANS + ". contactRefs for anyone a claim names."
    ),
    ("insights", "context-only"): _RESTRICTED,
    # ---- overview -----------------------------------------------------------------------------
    ("overview", "what-they-do"): (
        "Write `intro` as two paragraphs of prose (each paragraph one `intro` entry, 2–4 "
        "sentences, every sentence cited): what they sell and to whom, then founding, HQ, size, "
        "funding and named customers. `items` must be `[]`."
    ),
    ("overview", "why-they-fit"): (
        "Write `intro` as one sentence naming the overall picture, then one item per fit "
        "criterion; set `fitDisposition` to `support` for a satisfied criterion and `caveat` for "
        "an honest negative — a page with no caveat is a page nobody trusts. h2 states the "
        "criterion; the body is 2–3 sentences of the evidence behind it."
    ),
    ("overview", "why-now"): (
        "At most three items: the three strongest time-bound reasons to act this quarter, ordered "
        "by urgency. Each body says what changed and when, with the dates in words. Leave out "
        "anything that would be as true a year from now."
    ),
    ("overview", "buying-committee"): (
        "One item per person, with `contactRefs` set to that person. h2 = their name, title and "
        "persona in words ('Champion', 'Economic buyer'). Body = why they matter for this "
        "purchase: what they own, what they decide, and who they answer to."
    ),
    ("overview", "how-to-approach"): (
        "Items, in this order and only the ones the claims support: 'Lead with whom' — the person "
        "to open with and why; 'The message' — the one sentence to lead with; 'The proof to show' "
        "— the evidence to put in front of them; 'Tier and channels' — the tier and the channels "
        "to run; 'Timing' — when, and what makes it now."
    ),
    ("overview", "watch-outs"): _RESTRICTED,
    # ---- contact ------------------------------------------------------------------------------
    ("contact", "why-this-person"): (
        "2–3 items: the role this person owns in the deal, the category experience they bring, "
        "and how they think about buying. h2 = the one thing that matters about them. Body 2–4 "
        "sentences from this person's own claims, with their own words where the claims give "
        "them. Every item ends with a use line carried in `sendLine`: channel `In your email` for "
        "a line the marketer sends, or `In the platform` when it is advice to the operator rather "
        "than copy."
    ),
    ("contact", "problem-right-now"): (
        "3–4 items: the account's pain as it is felt from this seat — their problem, never their "
        "product's pitch. h2 = the problem in one line, with its number or date. Body 2–4 "
        "sentences of the evidence. Every item ends with `sendLine`, channel `In your email`: the "
        "exact sentence the marketer can paste, in their language, not ours."
    ),
    ("contact", "openers"): (
        "Each item is one opener; h2 names it; the body explains why it is safe and why it is "
        "strong; `sendLine` is the exact line to paste, with channel `In your email`. Strongest "
        "opener first, and the strongest ones use the most specific safe fact there is — "
        "something they published, a line they wrote, a seat they cannot fill — never their job "
        "title. The hobby opener, if any, appears once, as the first line only, never in the "
        "subject; say so in its body."
    ),
    ("contact", "angles"): (
        "2–4 items, each one channel angle: direct mail (`sendLine` channel `In the direct-mail "
        "brief`), landing page (`On the landing page`, or `Brief the design agent with` when the "
        "line is a brief for the design agent), content (`In your email`), and event (`For the "
        "event`). Name the channel in the h2, say why this person in the body, and let `sendLine` "
        "carry the brief itself."
    ),
    ("contact", "do-not-mention"): (
        "Every fact here is `outreachSafe: false` for this person or their account. One item per "
        "fact: what it is and why it must not be used, in one or two sentences. No sendLine, and "
        "no closing summary item — every item cites the claims it is built from."
    ),
}


def section_descriptor(recipe: SectionRecipe) -> dict[str, object]:
    """The one section, as the model sees it: its key, its H1, its instruction, its field keys.

    A restricted section's field keys are not a list the writer should filter on — it receives
    exactly the unsafe claims — so it is told that instead of a recipe it cannot apply.
    """
    return {
        "key": recipe.section_key,
        "h1": recipe.h1,
        "instruction": SECTION_INSTRUCTIONS[(recipe.page, recipe.section_key)],
        "allowedFieldKeys": (
            ["every claim with outreachSafe=false"]
            if recipe.restricted
            else list(recipe.allowed_field_keys)
        ),
    }


_SUFFIX_MARKER = "\n\n# WRITE ONLY THIS SECTION NOW"


def build_messages(
    *,
    page: str,
    subject: Mapping[str, object],
    client: Mapping[str, object],
    recipes: Sequence[SectionRecipe],
    target: SectionRecipe,
    claim_rows: Sequence[Mapping[str, object]],
    forbidden_aliases: Sequence[str] = (),
) -> list[dict[str, str]]:
    """The two messages of one section call: the system prompt, then PREFIX + SUFFIX.

    The prefix depends only on the page, so every section of a page sends byte-identical leading
    content and the provider's prompt cache hits from the second section onward. ``claim_rows``
    are alias rows (:func:`clue_api.arv2.display.render.alias_table`), which is why no url or
    claim uuid can reach the model. ``forbidden_aliases`` names the claims a previous draft cited
    that must not appear this time — the regenerate path.
    """
    header = json.dumps(
        {"page": page, "subject": dict(subject), "client": dict(client)}, ensure_ascii=False
    )
    descriptors = json.dumps(
        [section_descriptor(recipe) for recipe in recipes], ensure_ascii=False, indent=1
    )
    claims = json.dumps([dict(row) for row in claim_rows], ensure_ascii=False, indent=1)
    prefix = (
        "# PAGE\n"
        + header
        + "\n\n# ALL SECTIONS OF THIS PAGE (context only — you will be told which one to write)\n"
        + descriptors
        + "\n\n# CLAIMS (this is everything you know)\n"
        + claims
    )
    regenerate = ""
    if forbidden_aliases:
        regenerate = (
            "\nYour previous draft cited "
            + ", ".join(forbidden_aliases)
            + " which must not appear in this section. Rewrite without them."
        )
    suffix = (
        _SUFFIX_MARKER
        + ": "
        + target.section_key
        + "\n"
        + json.dumps(section_descriptor(target), ensure_ascii=False)
        + regenerate
        + '\nReturn {"section": <this one section>}.'
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prefix + suffix},
    ]


def prefix_of(messages: Sequence[Mapping[str, str]]) -> str:
    """The cacheable head of the user message — everything before the section suffix."""
    return messages[1]["content"].split(_SUFFIX_MARKER)[0]

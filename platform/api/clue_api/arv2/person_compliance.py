"""The coded compliance pass for person claims (substance §5; prompt rules 4–6).

The prompt tells the agent the floor, but the prompt is advice and this module is the decision: no
person claim reaches the store without passing through :func:`apply_person_floor` first. It is
deliberately a *pure* function — drafts in, surviving drafts and a log out — with no settings
import, no database and no clock, so the founder can read exactly what happens to a sentence and a
test can prove it without a connection.

Two laws hold everywhere here:

* **Nothing disappears silently.** Every drop, redaction and marking is one row in the returned log,
  and the log rides the job receipt so the display can say *something was removed and why* without
  showing what it was.
* **The pass never raises.** A value shape it cannot read is logged (``unreadable_value``) and the
  draft is passed through untouched: a compliance pass that crashed the write path would cost a job
  every claim it had, which is a worse failure than a value it could not inspect.

Redaction is by **sentence**, never by word: half a sentence with a hole in it is both unreadable
and still capable of implying what was removed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from clue_api.arv2.claim_writer import ClaimDraft
from clue_core import ExtractionMethod

#: The one field where an email address is the point: the professional email the export produces.
#: An email address on any other field is a personal contact detail and the draft goes.
WORK_EMAIL_FIELD = "core.work_email"

#: The agent's reading of claims it already wrote. It cites nothing *by design* — the hooks are a
#: judgement about evidence that is already in the store, not a new fact off a page — so rule 6
#: has nothing to say about it. Named here rather than imported, the way ``WORK_EMAIL_FIELD`` is,
#: so this module stays a pure function of drafts with no claim-mapper import behind it.
HOOKS_FIELD = "contact.facet.hooks"

#: The two fields the display turns into outreach. Rule 7 holds them to a higher bar than the rest:
#: a fact that is biography-only may be *recorded* but may never be the thing an opener rests on.
HOOK_FIELD_LEAVES = frozenset({"hooks", "openers"})

# -- the keyword lists ----------------------------------------------------------------------------
#
# Plain lower-case lists, one per category, meant to be read and edited by a human. Matching is
# whole-word and case-insensitive, so ``son`` does not fire on "Jackson" and ``ill`` is not here at
# all. Keep entries specific: a word that is also ordinary business vocabulary (campaign, party,
# engaged, anniversary) costs real claims and belongs nowhere in this file.

KEYWORDS: dict[str, list[str]] = {
    # health — medical conditions, treatment, diagnosis, disability, mental health.
    "health": [
        "cancer",
        "chemotherapy",
        "diagnosed",
        "diagnosis",
        "surgery",
        "hospitalised",
        "hospitalized",
        "disability",
        "disabled",
        "depression",
        "mental health",
        "adhd",
        "autism",
        "diabetes",
        "had a stroke",
        "suffered a stroke",
        "heart attack",
        "medication",
        "chronic illness",
        "terminal illness",
        "addiction",
        "rehab",
        "in remission",
    ],
    # faith — religion, observance, places of worship, religious festivals and clergy.
    "faith": [
        "church",
        "mosque",
        "synagogue",
        "christian",
        "catholic",
        "protestant",
        "muslim",
        "islam",
        "islamic",
        "jewish",
        "judaism",
        "hindu",
        "buddhist",
        "sikh",
        "atheist",
        "religion",
        "religious",
        "faith community",
        "prayer",
        "baptised",
        "baptized",
        "ramadan",
        "diwali",
        "hanukkah",
        "bible",
        "quran",
        "torah",
        "pastor",
        "rabbi",
        "imam",
    ],
    # politics — party affiliation, voting, activism, campaigning for a cause or candidate.
    "politics": [
        "election",
        "republican",
        "democrat",
        "labour party",
        "conservative party",
        "green party",
        "socialist",
        "communist",
        "maga",
        "brexit",
        "voted for",
        "campaigned for",
        "political",
        "politics",
        "political activist",
        "activism",
        "protest",
        "protester",
        "lobbying",
        "party member",
    ],
    # sexuality — sexual orientation and gender identity.
    "sexuality": [
        "lgbtq",
        "lgbt",
        "gay",
        "lesbian",
        "bisexual",
        "queer",
        "transgender",
        "same-sex",
        "sexuality",
        "sexual orientation",
        "coming out",
        "non-binary",
        "nonbinary",
    ],
    # family_tragedy — bereavement, illness in the family, divorce, loss.
    "family_tragedy": [
        "bereavement",
        "bereaved",
        "passed away",
        "funeral",
        "grieving",
        "mourning",
        "divorce",
        "divorced",
        "widow",
        "widowed",
        "miscarriage",
        "in memory of",
        "lost my",
        "loss of my",
    ],
    # union — trade-union membership and industrial action.
    "union": [
        "trade union",
        "labor union",
        "labour union",
        "union member",
        "union rep",
        "unionised",
        "unionized",
        "shop steward",
        "collective bargaining",
        "strike action",
        "picket line",
    ],
    # criminal — arrests, charges, convictions, courts and prison.
    "criminal": [
        "arrested",
        "under arrest",
        "convicted",
        "conviction",
        "indicted",
        "prosecuted",
        "felony",
        "misdemeanor",
        "prison",
        "jail",
        "probation officer",
        "parole",
        "lawsuit",
        "court case",
        "criminal record",
    ],
    # minors — any reference to children, redacted even when the person published it themselves.
    "minors": [
        "child",
        "children",
        "kid",
        "kids",
        "son",
        "sons",
        "daughter",
        "daughters",
        "baby",
        "babies",
        "newborn",
        "toddler",
        "infant",
        "grandchild",
        "grandchildren",
        "stepson",
        "stepdaughter",
        "school run",
        "kindergarten",
        "nursery",
        "preschool",
        "playgroup",
    ],
    # origin — nationality, migration and origin stories: biography only, never an outreach hook.
    "origin": [
        "immigrant",
        "immigrated",
        "emigrated",
        "migrated",
        "refugee",
        "asylum",
        "born in",
        "grew up in",
        "naturalised",
        "naturalized",
        "citizenship",
        "green card",
        "work visa",
        "visa sponsorship",
        "ancestry",
        "homeland",
        "native of",
        "first-generation",
        "second-generation",
        "nationality",
        "diaspora",
        "mother tongue",
    ],
    # milestone_wedding — a self-announced wedding: recorded, never a hook (founder, 2026-09-09).
    "milestone_wedding": [
        "wedding",
        "married",
        "got engaged",
        "engaged to",
        "my wife",
        "my husband",
        "my fiancé",
        "my fiancée",
        "honeymoon",
        "tied the knot",
        "bride",
        "groom",
    ],
    # milestone_baby — a self-announced birth: recorded, never a hook (founder, 2026-09-09).
    "milestone_baby": [
        "new baby",
        "newborn",
        "gave birth",
        "expecting a baby",
        "pregnant",
        "pregnancy",
        "maternity leave",
        "paternity leave",
        "parental leave",
        "welcomed our",
        "welcomed a baby",
        "birth of our",
        "baby shower",
    ],
}

#: The floor of rule 3, in the order it is applied. ``minors`` (rule 2) runs before these and the
#: two ``milestone_*`` lists and ``origin`` are markings, not redactions — so none of them is here.
SENSITIVITY_CATEGORIES: tuple[str, ...] = (
    "health",
    "faith",
    "politics",
    "sexuality",
    "family_tragedy",
    "union",
    "criminal",
)

# -- personal contact details (rule 1) ------------------------------------------------------------

#: Stripped before the phone and address scans: a numeric id inside a media URL is not a phone
#: number, and dropping a voice quote over its episode id would be a silly, invisible loss.
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)

#: A run of digits and phone punctuation. The *pattern* is deliberately loose and the digit count
#: below is what decides, so "2021-2024" (eight digits) is a tenure and not a phone number.
_PHONE = re.compile(r"\+?\d[\d\s().\-]{6,}\d")
_PHONE_DIGITS = range(9, 16)

#: Any token carrying a letter is not a phone number and is taken out of the text before the scan:
#: the digits inside a uuid (``contact.reports_to``'s required ``contact_id``) or a media id read
#: exactly like a phone number otherwise, and dropping a whole claim over one would be silent and
#: baffling. A phone number written with a label ("tel:+1…") survives because ``:`` splits first.
_LETTER_TOKEN = re.compile(r"\S*[A-Za-z]\S*")

#: What a removed word leaves behind. It must be a character ``_PHONE``'s class does **not**
#: contain: whitespace *is* in that class, so substituting a space let the digits of unrelated
#: numbers run together into one match — "grew the team from 12 to 250 people between 2019 and
#: 2024" scanned as a fifteen-digit run and the whole claim was dropped as a phone number. A pipe
#: fences each number off from the next, so only digits actually written together are counted. One
#: fence character is written **per character of the removed word**, so the fenced text is the same
#: length as the text it came from and a match's offsets still point at the original words — which
#: is what lets :data:`_PHONE_WORDS` be read in the candidate's own neighbourhood.
_TOKEN_FENCE = "|"

#: What makes a run of digits a *phone number* rather than a set of years, dates or counts. One of
#: these must hold, on the candidate itself: an international prefix, a parenthesised area code, a
#: dash- or dot-separated subscriber tail, one of the grouped national forms (the UK five-plus-six
#: "07700 900123", the North American three-three-four "415 555 0134", and its two mirrors), or a
#: contiguous ten-or-eleven-digit token ("4155550134") — URLs are stripped and every token carrying
#: a letter is fenced out before the scan, so a bare run that long is not an id or a date.
#:
#: The grouped forms are boundary-fenced (``(?<!\d)``/``(?!\d)``) because a phone number's grouping
#: must be the *whole* run, not a slice of a longer one: without the fences "2019 2021 2024" (a talk
#: list's three appearances) reads as the two-four-four grouping and a real claim is dropped.
_PHONE_SIGNALS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\+\d"),
    re.compile(r"\(\d{3}\)"),
    re.compile(r"\d{3}[-.]\d{4}"),
    re.compile(r"(?<!\d)\d{5}\s\d{6}(?!\d)"),
    re.compile(r"(?<!\d)\d{3}\s\d{3}\s\d{4}(?!\d)"),
    re.compile(r"(?<!\d)\d{4}\s\d{3}\s\d{3}(?!\d)"),
    re.compile(r"(?<!\d)\d{2}\s\d{4}\s\d{4}(?!\d)"),
    re.compile(r"(?<!\d)\d{10,11}(?!\d)"),
)

#: The words that make a number a phone number whatever it is punctuated like. Read on the text
#: around the candidate, before the letters are fenced out of it.
_PHONE_WORDS = re.compile(r"\b(?:tel|phone|mobile|cell|whatsapp)\b|\bcall me\b", re.IGNORECASE)

#: How near a phone word has to be to be about *this* number. A leaf is not a sentence — a talk
#: list, a publication list and a career history rarely carry terminal punctuation — so reading the
#: word anywhere in "the sentence" meant reading it anywhere in the whole value: one row titled
#: "Mobile threat landscape" made every year in the list a phone number. Thirty characters is close
#: enough to be a label on the number and far enough to survive "my mobile is 020 7946 0958".
_PHONE_WORD_WINDOW = 30

_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")

#: A house number, a capitalised street name and a thoroughfare word. The capitals are load-bearing:
#: without them "5 people found a way" and "3 steps on the road" are addresses, and a claim would
#: vanish over an idiom. Two more fences, because a match here **drops the whole claim**:
#:
#: * the house number may not be a year — "Joined in 2019 Acme Corp St. Louis office" is a date and
#:   a place name, not number 2019 of some street;
#: * ``way``, ``place``, ``court`` and ``square`` are ordinary English nouns as well as
#:   thoroughfares, so those four (and their abbreviations) count only when the address ends the
#:   clause — a comma or the end of the value behind them. "He led 3 Product Lines Way beyond
#:   target" is a sentence; "12 Elm Court, Springfield" is an address. The unambiguous
#:   thoroughfares still match mid-sentence ("he works from 221 Baker Street most days").
#:
#: A street written in lower case is still missed, which is the right way to be wrong here.
_STREET = re.compile(
    r"\b(?!(?:19|20)\d{2}\b)\d{1,5}\s+(?:[A-Z][\w.'\-]*\s+){1,3}"
    r"(?:"
    r"(?i:street|avenue|boulevard|road|lane|drive|terrace|crescent|st|ave|blvd|rd|ln|dr)\b\.?"
    r"|(?i:way|place|court|square|pl|ct|sq)\b\.?(?=\s*(?:,|$))"
    r")"
)

#: Rule 1's three shapes, by the name the log reports.
PERSONAL_CONTACT_PATTERNS: dict[str, re.Pattern[str]] = {
    "phone": _PHONE,
    "personal_email": _EMAIL,
    "street_address": _STREET,
}

# -- text mechanics -------------------------------------------------------------------------------

#: A sentence ends at ``.``/``!``/``?`` followed by whitespace. Redaction removes whole sentences.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

#: Below this, a sentence is too generic to prove that two drafts rest on the same fact (rule 7).
_SHARED_SENTENCE_MIN_WORDS = 4


class _UnreadableValue(Exception):
    """A value shape outside JSON: the draft is passed through and the pass says so."""


def _keyword_pattern(words: Iterable[str]) -> re.Pattern[str]:
    """One whole-word, case-insensitive alternation; longest first so phrases win over words."""
    ordered = sorted(words, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(word) for word in ordered) + r")\b", re.I)


_PATTERNS: dict[str, re.Pattern[str]] = {
    category: _keyword_pattern(words) for category, words in KEYWORDS.items()
}
_MILESTONE = _keyword_pattern(KEYWORDS["milestone_wedding"] + KEYWORDS["milestone_baby"])


def _text_leaves(value: Any) -> list[str]:
    """Every string inside a JSON value, in order. Raises on a shape that is not JSON."""
    if value is None or isinstance(value, bool | int | float):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _text_leaves(item)]
    if isinstance(value, dict):
        leaves: list[str] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise _UnreadableValue(f"object key of type {type(key).__name__}")
            leaves.extend(_text_leaves(item))
        return leaves
    raise _UnreadableValue(f"value of type {type(value).__name__}")


def _redact_text(text: str, pattern: re.Pattern[str]) -> str:
    """Drop every sentence the pattern hits; keep the rest exactly as written."""
    sentences = _SENTENCE.split(text)
    kept = [sentence for sentence in sentences if not pattern.search(sentence)]
    if len(kept) == len(sentences):
        return text
    return " ".join(sentence for sentence in kept if sentence.strip()).strip()


def _redact_value(value: Any, pattern: re.Pattern[str]) -> tuple[Any, bool]:
    """Redact every string leaf. The flag is *survived*: false means the node lost its content.

    A list keeps only the items that survived and dies when it empties; an object dies when any of
    its leaves does, because a ``voice_quote`` with no text or a career row with no role is not a
    smaller fact, it is a broken one.
    """
    if isinstance(value, str):
        redacted = _redact_text(value, pattern)
        return redacted, bool(redacted.strip()) or not value.strip()
    if isinstance(value, list):
        kept: list[Any] = []
        for item in value:
            new_item, survived = _redact_value(item, pattern)
            if survived:
                kept.append(new_item)
        return kept, bool(kept) or not value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        survived_all = True
        for key, item in value.items():
            out[key], survived = _redact_value(item, pattern)
            survived_all = survived_all and survived
        return out, survived_all
    return value, True


def _sentences(texts: Iterable[str]) -> frozenset[str]:
    """The draft's sentences, normalized, long enough to identify a shared fact (rule 7)."""
    found: set[str] = set()
    for text in texts:
        for sentence in _SENTENCE.split(text):
            normalized = " ".join(sentence.lower().split())
            if len(normalized.split()) >= _SHARED_SENTENCE_MIN_WORDS:
                found.add(normalized)
    return frozenset(found)


def _evidenced_by_shape(draft: ClaimDraft) -> bool:
    """Is this a draft rule 6 has nothing to say about, whatever its span and URL are?

    A provider record and the hooks claim are the two: neither *can* carry a page quote, so marking
    them ``unevidenced`` would be a complaint about their shape, and purging them would delete the
    deterministic spine the person page is built from.
    """
    return draft.extraction_method is ExtractionMethod.API or draft.field_key == HOOKS_FIELD


def _phone_in(texts: Iterable[str]) -> str | None:
    """A phone number in any one of these texts, or ``None``. A digit count is never enough.

    The texts are the value's string leaves and the evidence span, **each scanned on its own** and
    never joined: a joined value is one long line with no terminal punctuation, so a "sentence" was
    frequently the whole claim and one leaf's word decided every other leaf's numbers. A phone
    number and the word that labels it are written together, in the same leaf.

    Within a leaf the scan runs one sentence at a time, and a candidate is a phone number only when
    something *says so*: one of :data:`_PHONE_SIGNALS` on the candidate itself, or one of
    :data:`_PHONE_WORDS` within :data:`_PHONE_WORD_WINDOW` characters of it.

    Two fences failed before this rule existed. Every removed word leaves :data:`_TOKEN_FENCE`
    characters rather than spaces, so two numbers standing near each other ("from 12 to 250 people
    between 2019 and 2024") stay two numbers — but the fence only splits at *letter* tokens, and a
    talk list or a career history is years and dates separated by nothing but whitespace and
    punctuation. "2019-06 2021 2024" is fourteen digits in one run, and four conference-talk rows
    and a career history were dropped whole as phone numbers. A run of plain numbers carrying none
    of the signals above is a set of years, dates or counts, and it is never a phone number.
    """
    for text in texts:
        # ``:`` and ``,`` become spaces one-for-one, so the offsets below still point at the
        # original characters — "tel:+1…" must split into a word and a number, not read as one.
        normalized = text.replace(":", " ").replace(",", " ")
        for sentence in _SENTENCE.split(normalized):
            fenced = _LETTER_TOKEN.sub(lambda hit: _TOKEN_FENCE * len(hit.group()), sentence)
            for match in _PHONE.finditer(fenced):
                candidate = match.group().strip()
                if sum(character.isdigit() for character in candidate) not in _PHONE_DIGITS:
                    continue
                if any(signal.search(candidate) for signal in _PHONE_SIGNALS):
                    return candidate
                start = max(0, match.start() - _PHONE_WORD_WINDOW)
                if _PHONE_WORDS.search(sentence[start : match.end() + _PHONE_WORD_WINDOW]):
                    return candidate
    return None


# -- the pass -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Processed:
    """One draft after rules 1–6, with what rule 7 needs to judge the hooks beside it."""

    draft: ClaimDraft
    sentences: frozenset[str]
    #: Marked origin-biography or self-announced-milestone: nothing may rest on this fact.
    unsafe: bool
    #: This draft met the floor itself (redacted, origin or milestone) — a hook may not survive it.
    floor_hit: bool


def _row(action: str, draft: ClaimDraft, rule: str, detail: str) -> dict[str, str]:
    return {"action": action, "field_key": draft.field_key, "rule": rule, "detail": detail}


def apply_person_floor(
    drafts: Sequence[ClaimDraft], *, purge_unevidenced: bool
) -> tuple[list[ClaimDraft], list[dict[str, str]]]:
    """Run the person floor over one batch of drafts, in the order the rules are written.

    Returns the drafts that survive and the log of everything the pass did. The log's rows are all
    strings so they can ride the job receipt as they are.
    """
    log: list[dict[str, str]] = []
    processed: list[_Processed] = []

    for draft in drafts:
        try:
            outcome = _apply_rules_one_to_six(draft, purge_unevidenced=purge_unevidenced, log=log)
        except Exception as error:  # noqa: BLE001 — the pass never raises into the write path
            detail = (
                str(error)
                if isinstance(error, _UnreadableValue)
                else f"{type(error).__name__}: {error}"
            )
            log.append(_row("skipped", draft, "unreadable_value", detail[:200]))
            processed.append(
                _Processed(draft=draft, sentences=frozenset(), unsafe=False, floor_hit=False)
            )
            continue
        if outcome is not None:
            processed.append(outcome)

    return _apply_rule_seven(processed, log=log), log


def _apply_rules_one_to_six(
    draft: ClaimDraft, *, purge_unevidenced: bool, log: list[dict[str, str]]
) -> _Processed | None:
    """The six per-draft rules. ``None`` means the draft is dropped; the log already says why."""
    original = _text_leaves(draft.value_json)
    if draft.evidence_span:
        original.append(draft.evidence_span)
    blob = " ".join(original)

    # Rule 1 — personal contact details. A phone, a private email or a home address is never
    # written in research prose; the professional email export and source-bound phone field are
    # explicit channel exceptions.
    # URLs come out first: a numeric id in a media link is not a phone number.
    scrubbed = _URL.sub(" ", blob)
    # The phone scan reads the leaves apart; the other two read the value as one text, because an
    # address or an email is a single span and cannot be split across leaves the way a number and
    # its label can.
    scrubbed_leaves = [_URL.sub(" ", leaf) for leaf in original]
    for name, pattern in PERSONAL_CONTACT_PATTERNS.items():
        if name == "personal_email":
            if draft.field_key == WORK_EMAIL_FIELD:
                continue
            found = pattern.search(blob) is not None
        elif name == "phone":
            if (
                draft.field_key == "core.direct_phone"
                and draft.extraction_method == ExtractionMethod.API
                and draft.source_key == "ai_ark:phone"
                and draft.artifact_key
                and draft.markers.get("provider_subject_id")
                and draft.markers.get("operation_id")
            ):
                continue
            found = _phone_in(scrubbed_leaves) is not None
        else:
            found = pattern.search(scrubbed) is not None
        if found:
            log.append(_row("dropped", draft, "personal_contact_detail", f"{name} in the value"))
            return None

    markers: dict[str, Any] = dict(draft.markers)
    value: Any = draft.value_json
    span = draft.evidence_span
    redacted: list[str] = []

    # Rules 2 and 3 — minors first, then the sensitivity floor, one category at a time so the log
    # and the marker name exactly which one fired.
    for category in ("minors", *SENSITIVITY_CATEGORIES):
        pattern = _PATTERNS[category]
        new_value, survived = _redact_value(value, pattern)
        new_span = _redact_text(span, pattern) if span else span
        if new_value == value and new_span == span:
            continue
        if not survived:
            log.append(_row("dropped", draft, category, "the whole value matched the floor"))
            return None
        value, span = new_value, (new_span or None)
        redacted.append(category)
        log.append(_row("redacted", draft, category, "the matching sentence was removed"))

    if redacted:
        markers["redacted"] = redacted[0] if len(redacted) == 1 else redacted

    outreach_safe = draft.outreach_safe

    # Rule 4 — origin, nationality and migration are biography. Read against the *original* text:
    # a sentence rule 2 or 3 already removed still tells us what this claim was about.
    if _PATTERNS["origin"].search(blob):
        markers["origin_biography"] = True
        outreach_safe = False
        log.append(_row("unsafe", draft, "origin_biography", "recorded as biography only"))

    # Rule 5 — a self-announced wedding or baby is recorded and is never an outreach hook.
    if _MILESTONE.search(blob):
        markers["self_announced_milestone"] = True
        outreach_safe = False
        log.append(
            _row("unsafe", draft, "self_announced_milestone", "a wedding or a birth is biography")
        )

    # Rule 6 — a row with no quote **or** no URL is marked; it is only purged when the flag says
    # so. Two shapes are exempt, because for them "no quote and no URL" is the correct output and
    # not a gap: a provider record (``ExtractionMethod.API``) is evidenced by the record itself,
    # which is not a page a human can open, and the hooks claim carries neither by design. Without
    # the exemption, turning the purge on would delete the lane's whole deterministic spine.
    if (not span or not draft.source_url) and not _evidenced_by_shape(draft):
        missing = "no evidence span" if not span else "no source url"
        markers["unevidenced"] = True
        if purge_unevidenced:
            log.append(_row("dropped", draft, "unevidenced", f"{missing}; purge enabled"))
            return None
        log.append(_row("marked", draft, "unevidenced", missing))

    kept = replace(
        draft,
        value_json=value,
        evidence_span=span,
        outreach_safe=outreach_safe,
        markers=markers,
    )
    unsafe = bool(markers.get("origin_biography")) or bool(markers.get("self_announced_milestone"))
    return _Processed(
        draft=kept,
        sentences=_sentences(original),
        unsafe=unsafe,
        floor_hit=unsafe or bool(redacted),
    )


def _apply_rule_seven(
    processed: Sequence[_Processed], *, log: list[dict[str, str]]
) -> list[ClaimDraft]:
    """Rule 7 — an opener or a hook may not rest on a fact the floor made biography-only."""
    unsafe_sentences: set[str] = set()
    for item in processed:
        if item.unsafe:
            unsafe_sentences |= item.sentences

    kept: list[ClaimDraft] = []
    for item in processed:
        leaf = item.draft.field_key.rsplit(".", 1)[-1]
        if leaf not in HOOK_FIELD_LEAVES:
            kept.append(item.draft)
            continue
        if item.floor_hit:
            log.append(
                _row("dropped", item.draft, "unsafe_hook", "the hook itself meets the floor")
            )
            continue
        if item.sentences & unsafe_sentences:
            log.append(
                _row("dropped", item.draft, "unsafe_hook", "it rests on a biography-only fact")
            )
            continue
        kept.append(item.draft)
    return kept

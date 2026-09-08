"""A4 MACHINERY — one section, one model call, and the reply turned into the page's wire shape.

The runner is the only place in the display module that spends money. It does exactly what the
4 Sep 2026 control test proved works: **one call per section**, at the model's own reasoning
effort (no ``reasoning`` block, no ``temperature`` — a display section is writing, not
extraction), with the page's cacheable prefix in front of the one-section suffix.

What comes back is a model's opinion, and it is treated as one. :func:`materialise` is where the
opinion becomes data:

* every cited alias is resolved back to a claim uuid — an alias the table never issued is dropped
  and named, and a uuid whose claim is not in this section's input is dropped and named;
* ``segments`` survive only when they rejoin their sentence exactly, so a segment can never
  re-attribute text the sentence did not contain;
* ``priority`` is the strongest *claim* cited, not the number the model liked;
* a ``contactRef`` is a person the page already knows, resolved by name, or it is not a ref;
* ``sendLine``, ``subject``, ``fitDisposition`` and ``intro`` survive only where the page grammar
  has a slot for them.

A reply the model got wrong is not an exception: an unparseable or ill-shaped answer is retried
**once** with the identical messages, and a second failure yields an honest empty draft with
``checks["reply_invalid"]``. A provider that refuses to sell (:class:`ProviderHalted`) or a
network that never answered (:class:`ProviderTransportError`) still propagate — those are not
this layer's to swallow.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from clue_api.arv2.calls import CallCost, CallResult, CallSpec, ProviderCaller, SpendEstimate
from clue_api.arv2.display.gather import ClientContext, SectionInput, SubjectRef
from clue_api.arv2.display.personas import persona_display
from clue_api.arv2.display.prompts import PROMPT_VERSION, RESPONSE_FORMAT, build_messages
from clue_api.arv2.display.recipes import SectionRecipe
from clue_api.arv2.display.render import DisplayClaim, alias_table
from clue_api.arv2.errors import RawParseError
from clue_api.arv2.openrouter import (
    openrouter_chat_request,
    openrouter_cost_reader,
    openrouter_halt_rule,
    openrouter_message_text,
)
from clue_api.arv2.sinks import SpendTotals
from clue_api.arv2.structuring_client import parse_reply_text

#: A section is a page's worth of prose, not a document, but the model must never be truncated
#: mid-JSON — an unfinished object is an invalid reply and costs a whole second call.
DISPLAY_MAX_TOKENS = 16_000

#: The pre-spend reservation for one section call (law 2). The real cost is read back from the
#: provider's own metering; this only has to be the right order of magnitude.
DISPLAY_ESTIMATE_USD = Decimal("0.02")

#: The section key whose items may carry a ``subject`` (one item per committee member).
SUBJECT_SECTION_KEY = "contact-insights"

#: The section key whose items may carry a ``fitDisposition``.
FIT_SECTION_KEY = "why-they-fit"

#: The lowest (weakest) priority a display item can carry.
WEAKEST_PRIORITY = 3


# -- the reply the model is allowed to send ------------------------------------------------------


class _ReplyModel(BaseModel):
    """Unknown keys are ignored, never an error: a model that invents a field is not a failure."""

    model_config = ConfigDict(extra="ignore")


class ReplySegment(_ReplyModel):
    """One clause of a sentence, with its own citations."""

    text: str
    claimIds: list[str] = Field(default_factory=list)  # noqa: N815 — the wire shape is camelCase


class ReplySentence(_ReplyModel):
    """One sentence of prose, cited, optionally split into clauses."""

    text: str
    claimIds: list[str] = Field(default_factory=list)  # noqa: N815
    segments: list[ReplySegment] | None = None


class ReplySendLine(_ReplyModel):
    """The line the marketer pastes, and where they paste it."""

    channel: str
    text: str
    claimIds: list[str] = Field(default_factory=list)  # noqa: N815


class ReplyRef(_ReplyModel):
    """A person named by name — the model never sees an id, so a name is all it can send."""

    name: str


class ReplyItem(_ReplyModel):
    """One card of a section."""

    h2: str
    body: list[ReplySentence] = Field(default_factory=list)
    sendLine: ReplySendLine | None = None  # noqa: N815
    contactRefs: list[ReplyRef] = Field(default_factory=list)  # noqa: N815
    subject: ReplyRef | None = None
    fitDisposition: Literal["support", "caveat"] | None = None  # noqa: N815
    priority: int | None = None


class ReplySection(_ReplyModel):
    """The one section the call asked for."""

    key: str | None = None
    empty: bool = False
    intro: list[ReplySentence] = Field(default_factory=list)
    items: list[ReplyItem] = Field(default_factory=list)


class Reply(_ReplyModel):
    """``{"section": {…}}`` — or the control test's ``{"sections": [{…}]}``, first one wins."""

    section: ReplySection

    @model_validator(mode="before")
    @classmethod
    def _accept_a_sections_list(cls, data: Any) -> Any:
        if isinstance(data, Mapping) and "section" not in data:
            sections = data.get("sections")
            if isinstance(sections, list) and sections:
                return {**data, "section": sections[0]}
        return data


# -- what one written section is ------------------------------------------------------------------


@dataclass(frozen=True)
class SectionDraft:
    """One written section, in the shape the page layer stores and the frontend renders.

    ``items`` and ``intro`` are already the wire shape — uuids, not aliases — so nothing
    downstream has to know an alias existed. ``aliases`` is kept because the regenerate path
    needs it: the aliases a floor violation maps back to are the aliases the rewrite must forbid,
    and only the table that wrote this draft can name them.
    """

    section_key: str
    intro: list[dict[str, object]]
    items: list[dict[str, object]]
    cited_claim_ids: list[str]
    checks: dict[str, object]
    aliases: Mapping[str, str]
    cost: CallCost | None
    model: str
    raw_refs: tuple[str, ...]


# -- materialisation ------------------------------------------------------------------------------


class _Resolver:
    """Alias → claim uuid, keeping the two honest tallies of what it refused."""

    def __init__(self, aliases: Mapping[str, str], claims: Mapping[str, DisplayClaim]) -> None:
        self._aliases = aliases
        self._claims = claims
        self.unknown: set[str] = set()
        self.off_recipe: set[str] = set()

    def __call__(self, cited: Sequence[str]) -> list[str]:
        resolved: list[str] = []
        for token in cited:
            claim_id = self._aliases.get(token)
            if claim_id is None:
                self.unknown.add(token)
                continue
            if claim_id not in self._claims:
                self.off_recipe.add(claim_id)
                continue
            if claim_id not in resolved:
                resolved.append(claim_id)
        return resolved


def _people_by_name(people: Sequence[SubjectRef], subject: SubjectRef) -> dict[str, SubjectRef]:
    """``{lower-cased full name: person}`` over the page's people.

    The subject joins the table only when it *is* a person: on an account page the subject is the
    account, and "Zafran Security" is not a contact reference however the model wrote it.
    """
    table: dict[str, SubjectRef] = {}
    candidates = list(people)
    if subject.kind == "contact":
        candidates.append(subject)
    for person in candidates:
        key = person.name.strip().lower()
        if key and key not in table:
            table[key] = person
    return table


def _ref_payload(person: SubjectRef) -> dict[str, object]:
    """One contact chip as the frontend receives it.

    ``persona`` is written as **display text** (``"Economic buyer"``), not as the vocabulary value:
    this payload goes straight into ``display_block.body_json`` at generation time and is served
    from there verbatim, so a raw ``economic_buyer`` stored here is a raw ``economic_buyer`` on the
    screen forever (D4-b decision 5). Blocks written before that ruling are corrected by
    ``scripts/rewrite_display_persona_labels.py``.
    """
    payload: dict[str, object] = {
        "accountId": person.account_id,
        "contactId": person.id,
        "name": person.name,
    }
    if person.title is not None:
        payload["title"] = person.title
    label = persona_display(person.persona)
    if label is not None:
        payload["persona"] = label
    return payload


def _sentence_payload(
    sentence: ReplySentence, resolve: _Resolver, counters: dict[str, int]
) -> dict[str, object] | None:
    """One sentence as the frontend receives it, or ``None`` when it says nothing."""
    text = sentence.text.strip()
    if not text:
        return None
    payload: dict[str, object] = {"text": text, "claimIds": resolve(sentence.claimIds)}
    if not payload["claimIds"]:
        counters["uncited_sentences"] += 1
    segments = sentence.segments or []
    if segments:
        rejoined = " ".join(segment.text for segment in segments).strip()
        if rejoined == text:
            payload["segments"] = [
                {"text": segment.text, "claimIds": resolve(segment.claimIds)}
                for segment in segments
            ]
        else:
            counters["segments_dropped"] += 1
    return payload


def _priority(
    model_value: int | None, cited: Sequence[str], claims: Mapping[str, DisplayClaim]
) -> int:
    """The strongest claim the item is built from; failing that, the model's own clipped number."""
    priorities = [claims[claim_id].priority for claim_id in cited if claim_id in claims]
    if priorities:
        return min(priorities)
    if model_value is None:
        return WEAKEST_PRIORITY
    return max(1, min(WEAKEST_PRIORITY, model_value))


def materialise(
    reply: Reply,
    *,
    section: SectionInput,
    aliases: Mapping[str, str],
    people: Sequence[SubjectRef],
    subject: SubjectRef,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str], dict[str, object]]:
    """A validated reply as ``(intro, items, cited_claim_ids, checks)`` in the page's wire shape.

    Pure: no provider, no database, no clock. Everything the model was not entitled to say is
    removed here and counted in ``checks`` — the counts are what makes a thin section legible
    afterwards ("it cited three aliases that do not exist") rather than mysterious.
    """
    recipe: SectionRecipe = section.recipe
    claims = {claim.claim_id: claim for claim in section.claims}
    resolve = _Resolver(aliases, claims)
    counters = {"segments_dropped": 0, "unresolved_refs": 0, "uncited_sentences": 0}
    by_name = _people_by_name(people, subject)

    def _resolve_ref(ref: ReplyRef | None) -> dict[str, object] | None:
        if ref is None:
            return None
        person = by_name.get(ref.name.strip().lower())
        if person is None:
            counters["unresolved_refs"] += 1
            return None
        return _ref_payload(person)

    intro: list[dict[str, object]] = []
    if recipe.narrative:
        for sentence in reply.section.intro:
            payload = _sentence_payload(sentence, resolve, counters)
            if payload is not None:
                intro.append(payload)

    items: list[dict[str, object]] = []
    for index, raw_item in enumerate(reply.section.items, start=1):
        body: list[dict[str, object]] = []
        for sentence in raw_item.body:
            payload = _sentence_payload(sentence, resolve, counters)
            if payload is not None:
                body.append(payload)

        send_line: dict[str, object] | None = None
        if recipe.page == "contact" and raw_item.sendLine is not None:
            channel = raw_item.sendLine.channel.strip()
            line = raw_item.sendLine.text.strip()
            if channel and line:
                send_line = {
                    "channel": channel,
                    "text": line,
                    "claimIds": resolve(raw_item.sendLine.claimIds),
                }

        cited_here: list[str] = []
        for sentence_payload in body:
            cited_here.extend(claim_ids_of(sentence_payload))
        if send_line is not None:
            cited_here.extend(claim_ids_of(send_line))

        item: dict[str, object] = {
            "id": f"{recipe.section_key}-{index}",
            "h2": raw_item.h2.strip(),
            "body": body,
            "sendLine": send_line,
            "contactRefs": [
                payload
                for payload in (_resolve_ref(ref) for ref in raw_item.contactRefs)
                if payload is not None
            ],
            "priority": _priority(raw_item.priority, cited_here, claims),
            "newSinceLastVisit": False,
        }
        if recipe.section_key == SUBJECT_SECTION_KEY:
            item_subject = _resolve_ref(raw_item.subject)
            if item_subject is not None:
                item["subject"] = item_subject
        if recipe.section_key == FIT_SECTION_KEY and raw_item.fitDisposition is not None:
            item["fitDisposition"] = raw_item.fitDisposition
        items.append(item)

    said_empty = reply.section.empty or (not items and not intro)
    if said_empty:
        intro, items = [], []

    cited_claim_ids: list[str] = []
    for sentence_payload in intro:
        cited_claim_ids.extend(claim_ids_of(sentence_payload))
    for item in items:
        for cited_payload in cited_payloads(item):
            cited_claim_ids.extend(claim_ids_of(cited_payload))
    cited_claim_ids = list(dict.fromkeys(cited_claim_ids))

    checks: dict[str, object] = {
        "aliases": len(aliases),
        "prompt_version": PROMPT_VERSION,
        "unknown_aliases": sorted(resolve.unknown),
        "off_recipe": sorted(resolve.off_recipe),
        "segments_dropped": counters["segments_dropped"],
        "unresolved_refs": counters["unresolved_refs"],
        "uncited_sentences": counters["uncited_sentences"],
        "model_said_empty": said_empty,
    }
    return intro, items, cited_claim_ids, checks


def claim_ids_of(payload: Mapping[str, object]) -> list[str]:
    """The ``claimIds`` of one sentence/segment/sendLine payload, tolerant of a missing key."""
    raw = payload.get("claimIds")
    return [str(value) for value in raw] if isinstance(raw, list) else []


def cited_payloads(item: Mapping[str, object]) -> list[Mapping[str, object]]:
    """Every payload of an item that can carry citations: body, its segments, and the sendLine.

    One traversal, shared with :mod:`clue_api.arv2.display.floor`: the floor must look exactly
    where the runner counted, or a citation could be recorded on the page and missed by the check.
    """
    found: list[Mapping[str, object]] = []
    body = item.get("body")
    if isinstance(body, list):
        for sentence in body:
            if not isinstance(sentence, Mapping):
                continue
            found.append(sentence)
            segments = sentence.get("segments")
            if isinstance(segments, list):
                found.extend(segment for segment in segments if isinstance(segment, Mapping))
    send_line = item.get("sendLine")
    if isinstance(send_line, Mapping):
        found.append(send_line)
    return found


# -- the runner -----------------------------------------------------------------------------------


class LunaSectionRunner:
    """Writes one section per call, through the lane's shared provider wrapper."""

    def __init__(
        self,
        caller: ProviderCaller,
        *,
        api_key: SecretStr,
        base_url: str,
        model: str,
        timeout_s: float,
    ) -> None:
        self._caller = caller
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._timeout_s = timeout_s

    def totals(self) -> SpendTotals:
        """What this runner's caller has metered so far — the page's spend, summed per runner.

        A draft's ``cost`` is one call's reading; a section that was retried or regenerated made
        more than one. The caller's running total is the only number that counts them all.
        """
        return self._caller.totals()

    def write_section(
        self,
        *,
        page: str,
        subject: SubjectRef,
        client: ClientContext,
        recipes: Sequence[SectionRecipe],
        section: SectionInput,
        people: Sequence[SubjectRef],
        forbidden_aliases: Sequence[str] = (),
    ) -> SectionDraft:
        """Write ``section`` of ``page`` for ``subject``: one call, retried once if it is unusable.

        ``forbidden_aliases`` is the regenerate path — the caller passes the *same* section input
        it drafted from, so the alias table is byte-identical and the aliases it names still mean
        what they meant.
        """
        claim_rows, aliases = alias_table(section.claims)
        messages = build_messages(
            page=page,
            subject=subject.to_prompt(),
            client=client.to_prompt(),
            recipes=recipes,
            target=section.recipe,
            claim_rows=claim_rows,
            forbidden_aliases=forbidden_aliases,
        )
        request = openrouter_chat_request(
            base_url=self._base_url,
            api_key=self._api_key,
            model=self._model,
            messages=messages,
            response_format=RESPONSE_FORMAT,
            max_tokens=DISPLAY_MAX_TOKENS,
            timeout_s=self._timeout_s,
        )
        spec = CallSpec(
            provider="openrouter",
            operation="chat/completions",
            label=f"display-{page}-{section.recipe.section_key}",
            request=request,
            estimate=SpendEstimate(usd=DISPLAY_ESTIMATE_USD),
            cost_reader=openrouter_cost_reader,
            halt_rule=openrouter_halt_rule,
            extras={
                "page": page,
                "section_key": section.recipe.section_key,
                "subject_kind": subject.kind,
                "subject_id": subject.id,
            },
        )

        raw_refs: list[str] = []
        cost: CallCost | None = None
        reply: Reply | None = None
        retried = False
        for attempt in (1, 2):
            result = self._caller.call(spec)
            raw_refs.extend(result.raw_refs)
            cost = result.call_cost
            reply = _read_reply(result)
            if reply is not None:
                break
            if attempt == 1:
                retried = True

        if reply is None:
            intro: list[dict[str, object]] = []
            items: list[dict[str, object]] = []
            cited: list[str] = []
            checks: dict[str, object] = {
                "aliases": len(aliases),
                "prompt_version": PROMPT_VERSION,
                "unknown_aliases": [],
                "off_recipe": [],
                "segments_dropped": 0,
                "unresolved_refs": 0,
                "uncited_sentences": 0,
                "model_said_empty": False,
            }
        else:
            intro, items, cited, checks = materialise(
                reply, section=section, aliases=aliases, people=people, subject=subject
            )
        checks["reply_retried"] = retried
        checks["reply_invalid"] = reply is None

        return SectionDraft(
            section_key=section.recipe.section_key,
            intro=intro,
            items=items,
            cited_claim_ids=cited,
            checks=checks,
            aliases=aliases,
            cost=cost,
            model=self._model,
            raw_refs=tuple(raw_refs),
        )


def _read_reply(result: CallResult) -> Reply | None:
    """The call's reply, or ``None`` when the model did not answer in the shape it was asked for.

    Both failure modes are the same event to the caller — the answer is unusable — and law 1 has
    already put the body on disk under ``result.raw_ref``, so nothing is lost by not raising.
    """
    try:
        parsed = parse_reply_text(openrouter_message_text(result.json()), raw_ref=result.raw_ref)
        return Reply.model_validate(dict(parsed))
    except (RawParseError, ValidationError):
        return None

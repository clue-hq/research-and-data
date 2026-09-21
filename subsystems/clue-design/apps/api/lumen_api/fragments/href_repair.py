"""Derive a captured payload by changing only exact anchor targets and its CSS namespace."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import tinycss2
from selectolax.lexbor import LexborHTMLParser
from tinycss2.serializer import serialize_string_value

from .artifact import FragmentArtifact, canonical_bytes
from .cssscope import _ANIMATION_PROPERTIES, _GLOBAL_BLOCK_AT_RULES, _KEYFRAMES_AT_RULES
from .refs import FragmentRefused, fragment_wrapper_class, link_scheme_allowed
from .slots import SLOT_MARKER_ATTR

MAX_HREF_REPLACEMENTS = 8
MAX_HREF_CHARS = 2048


@dataclass(frozen=True)
class HrefRepair:
    artifact: FragmentArtifact
    match_counts: dict[str, int]


def validate_href_replacements(replacements: Any) -> dict[str, str]:
    if not isinstance(replacements, Mapping) or not 1 <= len(replacements) <= MAX_HREF_REPLACEMENTS:
        raise FragmentRefused(
            "repair.bad_href_map", "href replacements must contain 1 to 8 entries"
        )
    for old, new in replacements.items():
        if any(
            not isinstance(url, str) or not url or len(url) > MAX_HREF_CHARS for url in (old, new)
        ):
            raise FragmentRefused(
                "repair.bad_href_map", "hrefs must be nonempty strings <=2048 chars"
            )
        if old == new or not link_scheme_allowed(new) or any(ord(c) < 32 for c in new):
            raise FragmentRefused(
                "repair.bad_href_map", "replacement href must be safe and different"
            )
    return dict(replacements)


def build_href_repair(source: Mapping[str, Any], replacements: Any) -> HrefRepair:
    """Accept only a stored, sanitized payload; no arbitrary markup/CSS input or re-sanitization.

    The source's identity plus the exact resulting HTML/manifest define this derivative's id.
    Its CSS has already passed custody/scoping: only its parsed wrapper/keyframe names move.
    """
    mapping = validate_href_replacements(replacements)
    tree = LexborHTMLParser(source["html"])
    body = tree.body
    if body is None or _inner_html(body) != source["html"]:
        raise FragmentRefused(
            "repair.source_not_canonical", "stored HTML cannot round-trip unchanged"
        )
    counts = dict.fromkeys(mapping, 0)
    changed_slots = set()
    for anchor in body.css("a[href]"):
        old = anchor.attributes.get("href")
        if old in mapping:
            anchor.attrs["href"] = mapping[old]
            counts[old] += 1
            changed_slots.add(anchor.attributes.get(SLOT_MARKER_ATTR))
    if not all(counts.values()):
        raise FragmentRefused("repair.href_unmatched", "every old href must match an anchor")
    payload = copy.deepcopy(dict(source))
    payload["html"] = _inner_html(body)
    for key, spec in payload["slot_manifest"].items():
        if key in changed_slots and spec.get("kind") == "href" and spec.get("fallback") in mapping:
            spec["fallback"] = mapping[spec["fallback"]]
    identity = {
        "href_derivative_version": 1,
        "source_payload_digest": hashlib.sha256(canonical_bytes(source)).hexdigest(),
        "html": payload["html"],
        "slot_manifest": payload["slot_manifest"],
    }
    fragment_id = "frag_" + hashlib.sha256(canonical_bytes(identity)).hexdigest()[:16]
    payload["css"] = _rebase_css(source["css"], source["fragment_id"], fragment_id)
    payload["fragment_id"] = fragment_id
    payload["preview_digest"] = None
    encoded = canonical_bytes(payload)
    return HrefRepair(
        FragmentArtifact(fragment_id, payload, encoded, hashlib.sha256(encoded).hexdigest(), ()),
        counts,
    )


def _inner_html(body: Any) -> str:
    return "".join(child.html or "" for child in body.iter(include_text=True))


def _rebase_css(css: str, old_id: str, new_id: str) -> str:
    old, new = fragment_wrapper_class(old_id), fragment_wrapper_class(new_id)
    rules = tinycss2.parse_stylesheet(css, skip_comments=False, skip_whitespace=False)
    renames: dict[str, str] = {}

    def nested(rule: Any) -> list:
        return tinycss2.parse_rule_list(rule.content, skip_comments=False, skip_whitespace=False)

    def collect(items: list) -> None:
        for rule in items:
            if rule.type == "error":
                raise FragmentRefused("repair.css_unreadable", "stored CSS could not be parsed")
            if rule.type != "at-rule" or rule.content is None:
                continue
            if rule.lower_at_keyword in _KEYFRAMES_AT_RULES:
                for token in rule.prelude:
                    if token.type in {"ident", "string"} and token.value.endswith("--" + old):
                        renames[token.value] = token.value[: -len(old)] + new
            elif rule.lower_at_keyword not in _GLOBAL_BLOCK_AT_RULES:
                collect(nested(rule))

    def rename(token: Any, value: str) -> None:
        token.value = value
        if token.type == "string":
            token.representation = '"' + serialize_string_value(value) + '"'
        else:
            token.lower_value = value.lower()

    def selectors(tokens: list) -> None:
        for index, token in enumerate(tokens):
            if (
                token.type == "ident"
                and token.value == old
                and index > 0
                and tokens[index - 1].type == "literal"
                and tokens[index - 1].value == "."
            ):
                rename(token, new)
            if token.type == "function":
                selectors(token.arguments)
            elif token.type == "() block":
                selectors(token.content)

    def animation(tokens: list) -> None:
        for token in tokens:
            if token.type in {"ident", "string"} and token.value in renames:
                rename(token, renames[token.value])
            elif token.type == "function":
                animation(token.arguments)

    def rewrite(items: list) -> None:
        for rule in items:
            if rule.type == "qualified-rule":
                selectors(rule.prelude)
                for declaration in tinycss2.parse_declaration_list(rule.content):
                    if (
                        declaration.type == "declaration"
                        and declaration.lower_name in _ANIMATION_PROPERTIES
                    ):
                        animation(declaration.value)
            elif rule.type == "at-rule" and rule.content is not None:
                if rule.lower_at_keyword in _KEYFRAMES_AT_RULES:
                    animation(rule.prelude)
                    rewrite(nested(rule))
                elif rule.lower_at_keyword not in _GLOBAL_BLOCK_AT_RULES:
                    if rule.lower_at_keyword == "scope":
                        selectors(rule.prelude)
                    rewrite(nested(rule))

    collect(rules)
    rewrite(rules)
    return tinycss2.serialize(rules)

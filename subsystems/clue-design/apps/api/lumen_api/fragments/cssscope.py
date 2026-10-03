"""Scoping one cloned section's CSS so it cannot reach the rest of the page (F1.2).

A captured section ships the stylesheet rules it was written against — ``.btn``, ``h1``,
``:root``. Dropped into a document verbatim those rules would style everything else on the page
too, so every selector is re-anchored under the fragment's own wrapper class
(:func:`~lumen_api.fragments.refs.fragment_wrapper_class`), which the F1.3 render arm emits
around the markup.

The rulings this file implements, and why:

* **Media queries (and ``@supports``/``@container``) are preserved, and the selectors
  INSIDE them are scoped.** A responsive section that lost its breakpoints would be a different
  section.
* **``@layer`` structure is FLATTENED into plain rule order** (2026-08-29 ruling; the scope
  walk still descends into layer blocks, then :func:`~lumen_api.fragments.cssflatten.
  flatten_css_layers` removes the structure from the final text). Stored css that carried its
  own cascade layers was demoted to nested sub-layers inside the render's ``@layer base``
  wrapper, where Tailwind's preflight reset — direct in that layer — outranked every clone rule
  regardless of specificity. See cssflatten's module docstring for the full mechanism.
* **``@import`` is stripped, loudly.** It is a live fetch of arbitrary CSS from a third party at
  render time — the one construct that could reintroduce everything the sanitizer just removed.
  It leaves a note rather than vanishing, because "your section's imported stylesheet is gone" is
  something a human has to be told.
* **``@font-face`` passes through UNSCOPED.** A font family is a global name by construction:
  ``.lumen-frag-x @font-face`` is not a thing, and a scoped one would simply never define the
  family the rules below it ask for. Faces are already rehosted (their ``url()`` still goes
  through the reference gate here) and are subject to the D-F2 licence posture at publish, so
  passing them through is a scoping decision, not a licensing one.
* **``@keyframes`` names are NAMESPACED** to ``<name>--<wrapper class>``, and every
  ``animation``/``animation-name`` declaration in this same stylesheet that names one is rewritten
  to match. Keyframe names live in a single global namespace, so two cloned sections that both
  animate ``fade`` would otherwise silently overwrite each other's timeline — the last stylesheet
  parsed wins, which is a bug that only appears once a second fragment lands on the page. A name
  that no local ``@keyframes`` declares is left alone: it belongs to the host document.
* **``:root``/``html``/``body`` selectors BECOME the wrapper** instead of being prefixed. Prefixing
  produces ``.lumen-frag-x :root``, which matches nothing, and a modern section keeps its custom
  properties on ``:root`` — so prefixing would silently strip the section's entire colour scheme.
  Rewriting to the wrapper puts those declarations on the element that actually contains the
  section. A note records it either way.

Every byte-loading reference — at any nesting depth — goes through the same fail-closed gate the
HTML sanitizer uses (:func:`~lumen_api.fragments.refs.resolve_asset_reference`), so a section
whose background image was never rehosted refuses rather than rendering a hole. That means
``url()`` in both its token forms, AND the bare string candidates of ``image-set()`` /
``-webkit-image-set()``, which load bytes through a plain string rather than through ``url()``
and would otherwise be the one reference shape that walked past a fail-closed gate.

**Stored CSS may not contain ``</``** (:func:`_refuse_markup_breakout`). This is a *markup*
concern living in a *CSS* module on purpose. The render arm and the export packager write this
stylesheet RAW into a ``<style>`` element, whose content is raw text to the HTML tokenizer —
so a CSS string reading ``content: "</style><script>alert(1)</script>"`` ends the style element
and turns the rest into live markup, on a published page whose CSP permits inline script.
Sanitize-once means stored bytes are trusted absolutely downstream, so the door is here, at the
one moment anything about this stylesheet is still checkable. It is the same posture the engine
takes on its own write door (``theme.rs``'s value gate) rather than at its serializers.

Two layers, so fidelity survives the safety:

* ``<`` inside a string or url token is ESCAPED to the CSS escape ``\\3c ``, which means exactly
  what it did — a section whose breadcrumb separator is ``content: "<"`` is not refused.
* whatever ``</`` remains after that is outside any string, which is not meaningful CSS, so the
  fragment is REFUSED and names the snippet. The check is on ``</`` rather than on ``<`` because
  the media range syntax (``@media (400px <= width <= 700px)``) is legitimate and common, and
  because ``</`` is the actual raw-text end condition.

A reference tinycss2 cannot even tokenize (``url(var(--x))`` → a ``bad-url`` parse error;
an unterminated string → ``bad-string``) is REFUSED rather than serialized: serializing it stores
the literal text ``url([bad url]))`` in an immutable artifact, which is neither the author's CSS
nor anything a browser can use.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import tinycss2
from tinycss2 import ast
from tinycss2.serializer import serialize_string_value

from .cssflatten import flatten_css_layers
from .reference_identity import indexed_references
from .refs import (
    FragmentRefused,
    asset_reference_url,
    fragment_wrapper_class,
    resolve_asset_reference,
)

#: At-rules whose block holds declarations, not nested rules, and which are NOT scoped.
_GLOBAL_BLOCK_AT_RULES = frozenset({"font-face", "page", "counter-style", "property"})

#: Statement at-rules refused outright: a live third-party fetch, and two document-level
#: declarations that mean nothing inside a section subtree.
_REFUSED_AT_RULES = frozenset({"import", "charset", "namespace"})

_KEYFRAMES_AT_RULES = frozenset({"keyframes", "-webkit-keyframes", "-moz-keyframes"})

_ANIMATION_PROPERTIES = frozenset(
    {"animation", "animation-name", "-webkit-animation", "-webkit-animation-name"}
)

#: Selectors that address the document rather than anything inside the section.
_DOCUMENT_SELECTORS = frozenset({":root", "html", "body", "html body", ":host"})

#: Functions whose bare STRING arguments are URLs by their own grammar, not by ``url()``.
_IMAGE_SET_FUNCTIONS = frozenset({"image-set", "-webkit-image-set"})

#: The raw-text end condition for a ``<style>`` element. See the module docstring.
_MARKUP_BREAKOUT = "</"

#: ``<`` as a CSS escape. The trailing space terminates the hex escape and is consumed, so
#: ``\3c `` + any following character is always correct — including when that character is
#: itself a space or a hex digit, which is exactly when an unterminated escape would misread.
_ESCAPED_LT = "\\3c "

#: Refuse the whole fragment for a READABLE url in an at-rule prelude. The F1 default: a
#: hand-authored caller wants to be told, and an immutable artifact is worth being strict about.
PRELUDE_REFERENCE_REFUSE = "refuse"

#: Strip the offending AT-RULE whole, with a loud note (F2.2 ruling; the ``@import`` precedent).
#:
#: The minting path harvests CSS it did not write, from real pages, and round 2 recorded its own
#: false positive: ``@supports (background-image: url(x.png))`` is a legitimate feature probe —
#: it asks whether the browser understands ``url()`` values at all, and nothing ever fetches the
#: url. Refusing it costs a whole real section over syntax that loads no bytes. Stripping the
#: at-rule is the treatment ``@import`` already gets for the same reason: the construct means
#: nothing inside a fragment, removing it is honest, and the note tells a human what went.
#:
#: What did NOT change: an unreadable token (``bad-url``/``bad-string``) still refuses in both
#: modes — that is a token we cannot even read, not a probe we can recognize — and a url in a
#: SELECTOR still refuses in both modes, because "strip the rule whole" there would silently
#: delete styling the section actually uses.
PRELUDE_REFERENCE_STRIP = "strip"

PRELUDE_REFERENCE_MODES = (PRELUDE_REFERENCE_REFUSE, PRELUDE_REFERENCE_STRIP)


@dataclass(frozen=True)
class ScopedCss:
    """One fragment's stylesheet, re-anchored and reference-checked."""

    css: str
    asset_digests: tuple[str, ...]
    notes: tuple[str, ...]


def scope_fragment_css(
    css: str,
    *,
    fragment_id: str,
    rehosted: Mapping[str, str],
    prelude_reference: str = PRELUDE_REFERENCE_REFUSE,
    source_fragment_id: str | None = None,
) -> ScopedCss:
    """Scope one fragment's source CSS under its wrapper class. Refuses on a bad reference.

    ``prelude_reference`` decides what a READABLE url in an at-rule prelude costs — see
    :data:`PRELUDE_REFERENCE_MODES`. The default refuses, which is what every hand-authored
    caller wants; F2's minting path passes ``"strip"``.

    Repairs may name their resolved ``source_fragment_id`` so inspected wrapper selectors and
    keyframes move to the new scope exactly once. Unscoped additions still get the normal
    prefix, and every declaration/reference still passes this parser's ordinary gates.
    """
    if prelude_reference not in PRELUDE_REFERENCE_MODES:
        raise FragmentRefused(
            "fragment.prelude_mode_invalid",
            f"prelude_reference must be one of {', '.join(PRELUDE_REFERENCE_MODES)}: "
            f"{prelude_reference!r}",
        )
    rehosted = indexed_references(rehosted)
    wrapper = fragment_wrapper_class(fragment_id)
    source_wrapper = fragment_wrapper_class(source_fragment_id) if source_fragment_id else None
    notes: list[str] = []
    digests: set[str] = set()
    rules = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
    keyframe_names = _declared_keyframe_names(rules)
    renames = {
        name: f"{name.removesuffix('--' + source_wrapper) if source_wrapper else name}--{wrapper}"
        for name in keyframe_names
    }
    body = _scope_rules(rules, wrapper=wrapper, renames=renames, rehosted=rehosted,
                        digests=digests, notes=notes, prelude_reference=prelude_reference,
                        source_wrapper=source_wrapper)
    # AFTER scoping, so the flattener reorders exactly the rules that will be stored — and
    # BEFORE the breakout gate, which must run on the final text (2026-08-29 ruling; see
    # cssflatten's module docstring for why stored css may not carry cascade layers).
    body = flatten_css_layers(body, notes=notes)
    _refuse_markup_breakout(body)
    return ScopedCss(css=body, asset_digests=tuple(sorted(digests)), notes=tuple(notes))


def _refuse_markup_breakout(css: str) -> None:
    """The last gate: stored CSS may not carry the sequence that ends a ``<style>`` element.

    Runs on the FINAL text rather than per-token, so it covers everything a token walk can miss —
    comments, at-rule preludes, attribute selectors, escaped idents, and any serializer behaviour
    that changes under us later. A whole-output assertion is the only form of this check that
    cannot be outflanked by a construct nobody thought of.
    """
    index = css.find(_MARKUP_BREAKOUT)
    if index == -1:
        return
    snippet = css[max(0, index - 20) : index + 40]
    raise FragmentRefused(
        "fragment.css_markup_breakout",
        "fragment css contains '</', which would end the <style> element it is written into: "
        f"...{snippet}...",
        reference=snippet,
    )


def rewrite_declaration_urls(
    declarations: str, rehosted: Mapping[str, str]
) -> tuple[str, tuple[str, ...]]:
    """Reference-gate the ``url()`` tokens of a bare declaration list (a ``style=`` attribute).

    Shared with the HTML sanitizer so an inline ``background-image`` is exactly as gated as the
    same declaration in a stylesheet — an ungated inline style would be the obvious hole in an
    otherwise fail-closed rule.
    """
    rehosted = indexed_references(rehosted)
    digests: set[str] = set()
    tokens = tinycss2.parse_component_value_list(declarations)
    _rewrite_urls(tokens, rehosted=rehosted, digests=digests)
    return tinycss2.serialize(tokens), tuple(sorted(digests))


# --------------------------------------------------------------------------- #
# rule walking
# --------------------------------------------------------------------------- #


def _scope_rules(
    rules: Sequence[object],
    *,
    wrapper: str,
    renames: Mapping[str, str],
    rehosted: Mapping[str, str],
    digests: set[str],
    notes: list[str],
    prelude_reference: str,
    source_wrapper: str | None = None,
) -> str:
    out: list[str] = []
    for rule in rules:
        rendered = _scope_rule(
            rule, wrapper=wrapper, renames=renames, rehosted=rehosted, digests=digests,
            notes=notes, prelude_reference=prelude_reference,
            source_wrapper=source_wrapper,
        )
        if rendered:
            out.append(rendered)
    return "\n".join(out)


def _scope_rule(
    rule: object,
    *,
    wrapper: str,
    renames: Mapping[str, str],
    rehosted: Mapping[str, str],
    digests: set[str],
    notes: list[str],
    prelude_reference: str,
    source_wrapper: str | None = None,
) -> str:
    if isinstance(rule, ast.QualifiedRule):
        selector = _scope_selector(
            rule.prelude, wrapper=wrapper, notes=notes, source_wrapper=source_wrapper,
        )
        if not selector:
            return ""
        content = _declaration_block(
            rule.content, renames=renames, rehosted=rehosted, digests=digests
        )
        return f"{selector} {{{content}}}"

    if isinstance(rule, ast.AtRule):
        return _scope_at_rule(
            rule, wrapper=wrapper, renames=renames, rehosted=rehosted, digests=digests,
            notes=notes, prelude_reference=prelude_reference,
            source_wrapper=source_wrapper,
        )

    if isinstance(rule, ast.ParseError):
        notes.append(f"dropped unparseable css: {rule.message}")
        return ""
    return ""


def _scope_at_rule(
    rule: ast.AtRule,
    *,
    wrapper: str,
    renames: Mapping[str, str],
    rehosted: Mapping[str, str],
    digests: set[str],
    notes: list[str],
    prelude_reference: str,
    source_wrapper: str | None = None,
) -> str:
    keyword = rule.lower_at_keyword

    if keyword in _REFUSED_AT_RULES:
        # Checked BEFORE the prelude gate below, deliberately: `@import`'s and `@namespace`'s
        # preludes ARE urls by definition, and they are handled by removal (with a loud note),
        # not by refusing the whole fragment for containing one.
        notes.append(f"stripped @{keyword} — a fragment may not pull in document-level css")
        return ""

    if not _gate_prelude(
        rule.prelude,
        where=f"the @{keyword} prelude",
        prelude_reference=prelude_reference,
        notes=notes,
    ):
        return ""
    if keyword == "scope" and source_wrapper is not None:
        _retarget_scope_prelude(rule.prelude, source_wrapper=source_wrapper, wrapper=wrapper)
    prelude = tinycss2.serialize(rule.prelude).strip()

    if rule.content is None:
        # A statement at-rule we have no opinion about (`@layer a, b;`): pass it through.
        return f"@{keyword} {prelude};".replace("  ", " ")

    if keyword in _GLOBAL_BLOCK_AT_RULES:
        # Global by nature — declarations only, no selectors to scope. References still gated.
        if keyword == "font-face":
            content = _font_face_block(
                rule.content, renames=renames, rehosted=rehosted, digests=digests, notes=notes
            )
            if content is None:
                return ""
        else:
            content = _declaration_block(
                rule.content, renames=renames, rehosted=rehosted, digests=digests
            )
        head = f"@{keyword} {prelude}".rstrip()
        return f"{head} {{{content}}}"

    if keyword in _KEYFRAMES_AT_RULES:
        name = _keyframes_name(rule.prelude)
        renamed = renames.get(name, name)
        inner = tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
        for frame in inner:
            if isinstance(frame, ast.QualifiedRule):
                # `from`/`to`/`50%` — no url belongs here either, and the gate is free. A frame
                # prelude is part of THIS at-rule, so on the minting path the strip takes the
                # whole `@keyframes` block rather than half a timeline.
                if not _gate_prelude(
                    frame.prelude,
                    where=f"an @{keyword} selector",
                    prelude_reference=prelude_reference,
                    notes=notes,
                ):
                    return ""
        frames = [
            f"{tinycss2.serialize(frame.prelude).strip()} "
            f"{{{_declaration_block(frame.content, renames=renames, rehosted=rehosted, digests=digests)}}}"
            for frame in inner
            if isinstance(frame, ast.QualifiedRule)
        ]
        return f"@{keyword} {renamed} {{ {' '.join(frames)} }}"

    # Everything else with a block (@media, @supports, @container, @layer {…}) nests RULES:
    # preserve the condition and scope what is inside it, at any depth.
    inner = tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
    body = _scope_rules(
        inner, wrapper=wrapper, renames=renames, rehosted=rehosted, digests=digests, notes=notes,
        prelude_reference=prelude_reference,
        source_wrapper=source_wrapper,
    )
    head = f"@{keyword} {prelude}".rstrip()
    return f"{head} {{ {body} }}"


def _gate_prelude(
    tokens: Sequence[object], *, where: str, prelude_reference: str, notes: list[str]
) -> bool:
    """Run the prelude gate; ``False`` means "strip this at-rule whole and say so".

    The mode only ever softens :data:`fragment.reference_in_prelude` — a url we can READ, in a
    place nothing fetches from. Everything else the gate raises (an unreadable token) propagates
    in both modes, because a token we cannot read is not a construct we can claim to recognize.
    """
    try:
        _refuse_references_in_prelude(tokens, where=where)
    except FragmentRefused as refusal:
        if (
            prelude_reference != PRELUDE_REFERENCE_STRIP
            or refusal.code != "fragment.reference_in_prelude"
        ):
            raise
        notes.append(
            f"stripped the at-rule carrying {where} — it names {refusal.reference!r} in a place "
            "nothing fetches from, so the rule could be neither rehosted nor honestly kept"
        )
        return False
    return True


def _font_face_block(
    tokens: Sequence[object],
    *,
    renames: Mapping[str, str],
    rehosted: Mapping[str, str],
    digests: set[str],
    notes: list[str],
) -> str | None:
    """An ``@font-face`` body, with an unrehostable ``src`` DROPPED rather than refused.

    RULED (F2 wave W2), and narrow on purpose. Everywhere else in this module an unrehosted
    reference refuses the whole fragment, and that stays: an ``<img>`` we cannot serve is a hole
    in the section, and a hole is the failure a clone can least afford.

    A font is not a hole. A face whose file we do not hold falls back to the next family in the
    stack — the section still renders, still lays out, still reads. And the cost of the hard
    refusal here was measured on the F2 acceptance walk: ONE ``@media``-wrapped ``@font-face`` in
    a site's global stylesheet, whose file the capture layer never fetched, refused **every
    section of that site**. A hundred per cent loss to protect against a fallback typeface is not
    a trade anyone would choose.

    So: a ``src`` descriptor that cannot be resolved is dropped with a loud note, and if that
    leaves the face with no ``src`` at all the whole rule goes (a face that declares no source
    defines nothing). This mirrors ``PRELUDE_REFERENCE_STRIP`` exactly — construct-scoped
    degradation with a note, never a silent one — and it is the only reference in a fragment that
    degrades. ``None`` means "drop this rule".
    """
    segments = _split_declarations(list(tokens))
    kept: list[str] = []
    sources = 0
    dropped: list[str] = []
    for segment in segments:
        property_name = _declaration_property(segment)
        # Collected per DESCRIPTOR, merged only if the descriptor survives. A `src` listing two
        # rungs resolves the first and then refuses on the second; if the shared set were written
        # straight through, the dropped descriptor would leave the first rung's digest behind and
        # the artifact would claim to display bytes its stored CSS no longer names — a delivery
        # build would then ship a font file nothing references.
        found: set[str] = set()
        try:
            rendered = _declaration_block(
                segment, renames=renames, rehosted=rehosted, digests=found
            )
        except FragmentRefused as refusal:
            if property_name != "src" or refusal.code != "fragment.unrehosted_reference":
                raise
            dropped.append(refusal.reference or "an unrehosted font file")
            continue
        digests.update(found)
        if property_name == "src":
            sources += 1
        if rendered.strip():
            kept.append(rendered)
    if dropped:
        notes.append(
            "dropped an @font-face src naming "
            + ", ".join(sorted(set(dropped))[:3])
            + " — the file was never rehosted, so the face is defined by whatever source "
            "survives and otherwise falls back to the next family in the stack"
        )
    if not sources:
        if dropped:
            notes.append(
                "dropped the whole @font-face rule: none of its sources were rehosted, so it "
                "would have defined a family with no file behind it"
            )
        return None if dropped else ";".join(kept)
    return ";".join(kept)


def _refuse_references_in_prelude(tokens: Sequence[object], *, where: str) -> None:
    """No at-rule prelude or selector may carry a URL, readable or not.

    Preludes and selectors were the one place the reference machinery never reached: they are
    serialized straight to text, so both halves of the round-1 gate — the rehost check and the
    bad-url refusal — skipped them entirely. Two consequences, and the second is the worse one:

    * an unreadable reference (``@supports (background: url(var(--x)))``) serialized to the
      literal ``url([bad url]))``, whose unbalanced ``)`` swallows every rule the at-rule wraps.
      Stored immutably, discovered only at render, and silent — the exact shape this phase's
      loud-never-silent rule exists to prevent;
    * a readable one (``@supports (background: url(hero.png))``) passed through un-rehosted.

    Both REFUSE rather than being rewritten, because a URL in a prelude or a selector is never a
    URL we can rehost: nothing fetches it (a feature query is a syntax probe; an attribute
    selector is a string comparison), so pointing it at our blob store would change what the
    stylesheet MEANS while pretending to preserve it.

    Known false positive, recorded so a future relaxation is a decision rather than a
    rediscovery: ``@supports (background-image: url(x.png))`` is legitimate CSS testing whether
    the browser understands ``url()`` values at all. It is refused here. It is also vanishingly
    rare, and fail-closed is the right default for a gate whose output is immutable.
    """
    for token in tokens:
        if isinstance(token, ast.ParseError):
            if token.kind in ("bad-url", "bad-string"):
                raise FragmentRefused(
                    "fragment.unreadable_reference",
                    f"fragment css has an unreadable token ({token.kind}) in {where}: "
                    f"{token.message}",
                    reference=where,
                )
            continue
        if isinstance(token, ast.URLToken):
            raise FragmentRefused(
                "fragment.reference_in_prelude",
                f"fragment css references {token.value!r} from {where}, where a url can be "
                "neither fetched nor rehosted",
                reference=token.value,
            )
        if isinstance(token, ast.FunctionBlock):
            if token.lower_name == "url" or token.lower_name in _IMAGE_SET_FUNCTIONS:
                raise FragmentRefused(
                    "fragment.reference_in_prelude",
                    f"fragment css calls {token.lower_name}() from {where}, where a url can be "
                    "neither fetched nor rehosted",
                    reference=token.lower_name,
                )
            _refuse_references_in_prelude(token.arguments, where=where)
        elif isinstance(
            token, (ast.ParenthesesBlock, ast.SquareBracketsBlock, ast.CurlyBracketsBlock)
        ):
            _refuse_references_in_prelude(token.content, where=where)


def _scope_selector(
    prelude: Sequence[object], *, wrapper: str, notes: list[str],
    source_wrapper: str | None = None,
) -> str:
    _refuse_references_in_prelude(prelude, where="a selector")
    parts: list[str] = []
    for group in _split_on_commas(prelude):
        text = tinycss2.serialize(group).strip()
        if not text:
            continue
        leading, remainder = _split_root_prefix(text)
        # Inspected source CSS already has a scope. Retarget that exact leading class rather
        # than inventing an impossible `.new .old` nesting. The remainder still goes through
        # the ordinary reference/declaration gates; this is not the trusted href-derivative
        # shortcut. A sibling of the wrapper is outside custody and cannot be retargeted.
        retargeted = _retarget_source_selector(
            remainder if leading and remainder else text,
            source_wrapper=source_wrapper, wrapper=wrapper,
        )
        if retargeted is not None:
            parts.append(f"{leading} {retargeted}" if leading and remainder else retargeted)
            continue
        if text.lower() in _DOCUMENT_SELECTORS:
            notes.append(
                f"rewrote document-level selector {text!r} to the fragment wrapper "
                "(its declarations, including custom properties, now apply to the section)"
            )
            parts.append(f".{wrapper}")
            continue
        if leading and remainder:
            # `html.dark .btn` is a THEME rule: the leading compound qualifies the document, the
            # rest addresses the section. Prefixing the whole thing produces
            # `.lumen-frag-x html.dark .btn` — an `<html>` inside the wrapper, which can never
            # match — so the qualifier keeps its place at the front and the wrapper goes where
            # the section actually begins. The F2 walk found Webflow's whole interaction layer
            # (`html.w-mod-js:not(.w-mod-ix) [data-w-id]`) dead this way; they were `opacity: 0`
            # pre-animation states, so the page stayed readable and the rules were pure weight.
            notes.append(
                f"kept the document qualifier {leading!r} in front of the fragment wrapper "
                "(a root-qualified rule addresses the page's state, not the section)"
            )
            parts.append(f"{leading} .{wrapper} {remainder}")
        else:
            parts.append(f".{wrapper} {text}")
    return ", ".join(parts)


def _retarget_source_selector(
    selector: str, *, source_wrapper: str | None, wrapper: str,
) -> str | None:
    if source_wrapper is None:
        return None
    tokens = tinycss2.parse_component_value_list(selector, skip_comments=True)
    if not (
        len(tokens) >= 2 and tokens[0].type == "literal" and tokens[0].value == "."
        and tokens[1].type == "ident" and tokens[1].value == source_wrapper
    ):
        return None
    # The first relationship after the wrapper compound must stay inside that wrapper.
    # Pseudo functions are single parsed tokens; commas inside them are not selector groups.
    for index, token in enumerate(tokens[2:], start=2):
        if token.type == "whitespace" or (
            token.type == "literal" and token.value in {">", "+", "~", "|", "||"}
        ):
            following = next((item for item in tokens[index:] if item.type != "whitespace"), None)
            if (
                following is not None and following.type == "literal"
                and following.value in {"+", "~", "|", "||"}
            ):
                raise FragmentRefused(
                    "fragment.css_scope_escape", "a source wrapper cannot target its siblings",
                    reference=selector,
                )
            break
    tokens[1].value = wrapper
    tokens[1].lower_value = wrapper.lower()
    return tinycss2.serialize(tokens)


def _retarget_scope_prelude(
    tokens: Sequence[object], *, source_wrapper: str, wrapper: str,
) -> None:
    """Retarget only class tokens in @scope's selector groups after its reference gate."""
    for index, token in enumerate(tokens):
        if (
            token.type == "ident" and token.value == source_wrapper and index > 0
            and tokens[index - 1].type == "literal" and tokens[index - 1].value == "."
        ):
            token.value = wrapper
            token.lower_value = wrapper.lower()
        if token.type == "() block":
            _retarget_scope_prelude(token.content, source_wrapper=source_wrapper, wrapper=wrapper)
        elif token.type == "function":
            _retarget_scope_prelude(token.arguments, source_wrapper=source_wrapper, wrapper=wrapper)


#: The element part of a compound that names the document root.
_ROOT_COMPOUND_HEADS = ("html", "body", ":root", ":host")


def _is_root_qualified(compound: str) -> bool:
    """Does this compound address the DOCUMENT (``html``, ``html.dark``, ``:root[data-t=x]``)?"""
    lowered = compound.strip().lower()
    for head in _ROOT_COMPOUND_HEADS:
        if lowered == head:
            return True
        if lowered.startswith(head):
            rest = lowered[len(head) :]
            if rest[:1] in (".", "#", "[", ":"):
                return True
    return False


def _split_root_prefix(selector: str) -> tuple[str, str]:
    """The run of leading DOCUMENT compounds, and what addresses the section after them.

    ``html.dark .btn`` → ``("html.dark", ".btn")``; ``html > body .y`` → ``("html > body", ".y")``.
    A selector with no root prefix, or one that is nothing BUT a root prefix, returns ``("", …)``
    so the caller falls back to its ordinary handling.

    The run matters. Splitting only the first compound left `body` inside the wrapper for
    ``html > body .y`` — an element that can never appear there, which is the same dead-rule
    shape this rewrite exists to prevent, one compound further along.
    """
    prefix: list[str] = []
    rest = selector.strip()
    while rest:
        leading, remainder = _split_leading_compound(rest)
        if not _is_root_qualified(leading) or not remainder:
            break
        prefix.append(leading)
        combinator = ""
        if remainder[:1] in ">+~":
            combinator = remainder[0]
            remainder = remainder[1:].strip()
        if combinator:
            prefix.append(combinator)
        rest = remainder
    if not prefix or not rest:
        return "", selector
    # A trailing combinator described the ROOT's relationship to what follows; after re-anchoring
    # it describes the WRAPPER's, which is the closest honest analogue inside a section.
    if prefix[-1] in ">+~":
        return " ".join(prefix[:-1]), f"{prefix[-1]} {rest}"
    return " ".join(prefix), rest


def _split_leading_compound(selector: str) -> tuple[str, str]:
    """``html.dark .a > .b`` → ``("html.dark", ".a > .b")``. No combinator ⇒ empty remainder.

    Depth- and quote-aware, so a combinator inside ``:not(…)`` or ``[href*=" "]`` is not one.
    """
    depth = 0
    quote: str | None = None
    for index, char in enumerate(selector):
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            continue
        if char in "([":
            depth += 1
            continue
        if char in ")]":
            depth = max(0, depth - 1)
            continue
        if depth == 0 and (char.isspace() or char in ">+~"):
            return selector[:index].strip(), selector[index:].strip()
    return selector.strip(), ""


def _split_on_commas(tokens: Sequence[object]) -> list[list[object]]:
    groups: list[list[object]] = [[]]
    for token in tokens:
        if isinstance(token, ast.LiteralToken) and token.value == ",":
            groups.append([])
        else:
            groups[-1].append(token)
    return groups


def _keyframes_name(prelude: Sequence[object]) -> str:
    for token in prelude:
        if isinstance(token, ast.IdentToken):
            return token.value
        if isinstance(token, ast.StringToken):
            return token.value
    return ""


def _declared_keyframe_names(rules: Sequence[object]) -> set[str]:
    """Every ``@keyframes`` name this stylesheet declares, at any nesting depth."""
    names: set[str] = set()
    for rule in rules:
        if not isinstance(rule, ast.AtRule) or rule.content is None:
            continue
        if rule.lower_at_keyword in _KEYFRAMES_AT_RULES:
            name = _keyframes_name(rule.prelude)
            if name:
                names.add(name)
        elif rule.lower_at_keyword not in _GLOBAL_BLOCK_AT_RULES:
            names |= _declared_keyframe_names(
                tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
            )
    return names


# --------------------------------------------------------------------------- #
# declaration blocks: url() gating + animation-name namespacing
# --------------------------------------------------------------------------- #


def _declaration_block(
    tokens: Sequence[object],
    *,
    renames: Mapping[str, str],
    rehosted: Mapping[str, str],
    digests: set[str],
) -> str:
    """Serialize one ``{…}`` body, rewriting references and animation names IN PLACE.

    Deliberately token-level rather than ``parse_declaration_list``: the token list keeps the
    author's exact whitespace, comments, vendor prefixes and even declarations tinycss2 considers
    malformed (which browsers routinely still honour). A cloned section's CSS is not ours to
    reformat — we are re-anchoring it, not rewriting it.
    """
    mutable = list(tokens)
    _rewrite_urls(mutable, rehosted=rehosted, digests=digests)
    if renames:
        _rewrite_animation_names(mutable, renames=renames)
    return tinycss2.serialize(mutable)


def _rewrite_urls(
    tokens: Sequence[object], *, rehosted: Mapping[str, str], digests: set[str]
) -> None:
    """Gate every byte-loading reference, refuse the unreadable, and defuse ``<`` in strings.

    One walk rather than three, because each of the three has to see the same tokens at the same
    depth: a reference nested two functions down still loads bytes, an unreadable one is still
    unreadable, and a string that can end a ``<style>`` element does not care where it sits.
    """
    for token in tokens:
        if isinstance(token, ast.ParseError):
            # tinycss2 could not tokenize this at all. Serializing it would store the literal
            # text `url([bad url]))` in an immutable artifact — neither the author's CSS nor
            # anything a browser can use — and it is precisely the shape a reference we cannot
            # read takes (`url(var(--x))`), so it must not pass a fail-closed gate.
            if token.kind in ("bad-url", "bad-string"):
                raise FragmentRefused(
                    "fragment.unreadable_reference",
                    f"fragment css has an unreadable token ({token.kind}): {token.message}",
                    reference=token.kind,
                )
            continue

        if isinstance(token, ast.URLToken):
            digest = resolve_asset_reference(token.value, rehosted)
            if digest is None:
                # URLToken serializes its `representation`, not its value.
                token.representation = _defuse(token.representation)
                continue
            digests.add(digest)
            token.value = asset_reference_url(token.value, digest)
            token.representation = f"url({_quoted_reference(token.value)})"

        elif isinstance(token, ast.StringToken):
            token.representation = _defuse(token.representation)

        elif isinstance(token, ast.FunctionBlock):
            if token.lower_name == "url":
                _rewrite_url_function(token, rehosted=rehosted, digests=digests)
            elif token.lower_name in _IMAGE_SET_FUNCTIONS:
                _rewrite_image_set(token, rehosted=rehosted, digests=digests)
            else:
                _rewrite_urls(token.arguments, rehosted=rehosted, digests=digests)

        elif isinstance(
            token, (ast.ParenthesesBlock, ast.SquareBracketsBlock, ast.CurlyBracketsBlock)
        ):
            _rewrite_urls(token.content, rehosted=rehosted, digests=digests)


def _defuse(representation: str) -> str:
    """``<`` → the CSS escape ``\\3c ``, so a string cannot end the ``<style>`` it is written in.

    Escaped rather than refused because a ``<`` inside a CSS string is ordinary content — a
    breadcrumb separator, a tooltip caret — and it means exactly the same thing afterwards.
    Whatever ``</`` survives this is outside any string, and :func:`_refuse_markup_breakout`
    refuses the fragment for it.
    """
    return representation.replace("<", _ESCAPED_LT)


def _quoted_reference(value: str) -> str:
    # A preserved URL fragment may contain quotes, backslashes, or markup. Keep its value
    # without letting it become CSS syntax or end a downstream raw-text <style> element.
    return _defuse('"' + serialize_string_value(value) + '"')


def _rewrite_url_function(
    token: ast.FunctionBlock, *, rehosted: Mapping[str, str], digests: set[str]
) -> None:
    arguments = [item for item in token.arguments if item.type not in ("whitespace", "comment")]
    for argument in arguments:
        if len(arguments) == 1 and isinstance(argument, ast.StringToken):
            digest = resolve_asset_reference(argument.value, rehosted)
            if digest is None:
                argument.representation = _defuse(argument.representation)
                # Only a same-document SVG paint/filter reference is successful
                # here. External URLs still require custody above; malformed and
                # empty quoted URLs still take the refusal below.
                if argument.value.strip().startswith("#"):
                    return
                continue
            digests.add(digest)
            argument.value = asset_reference_url(argument.value, digest)
            argument.representation = _quoted_reference(argument.value)
            return
    # `url(var(--x))` and friends: a reference we cannot read is a reference we cannot vouch for.
    raise FragmentRefused(
        "fragment.unreadable_reference",
        f"fragment css has a url() we cannot resolve: {tinycss2.serialize([token])}",
        reference=tinycss2.serialize([token]),
    )


def _rewrite_image_set(
    token: ast.FunctionBlock, *, rehosted: Mapping[str, str], digests: set[str]
) -> None:
    """``image-set()`` loads bytes through a BARE STRING, not through ``url()``.

    ``image-set("hero.png" 1x, url(hero@2x.png) 2x)`` — the first candidate is a plain string and
    is a URL only by this function's own grammar, so a walk that inspects ``url()`` and nothing
    else lets it straight through the one gate that is supposed to be fail-closed. Each string
    argument is therefore resolved and rewritten exactly like a ``url()``; the ``url()``
    candidates in the same list keep going through the generic path.
    """
    for argument in token.arguments:
        if isinstance(argument, ast.StringToken):
            digest = resolve_asset_reference(argument.value, rehosted)
            if digest is None:
                argument.representation = _defuse(argument.representation)
                continue
            digests.add(digest)
            argument.value = asset_reference_url(argument.value, digest)
            argument.representation = _quoted_reference(argument.value)
        else:
            _rewrite_urls([argument], rehosted=rehosted, digests=digests)


def _rewrite_animation_names(tokens: list[object], *, renames: Mapping[str, str]) -> None:
    for segment in _split_declarations(tokens):
        property_name = _declaration_property(segment)
        if property_name not in _ANIMATION_PROPERTIES:
            continue
        for token in segment:
            if isinstance(token, ast.IdentToken) and token.value in renames:
                token.value = renames[token.value]


def _split_declarations(tokens: Sequence[object]) -> list[list[object]]:
    segments: list[list[object]] = [[]]
    for token in tokens:
        if isinstance(token, ast.LiteralToken) and token.value == ";":
            segments.append([])
        else:
            segments[-1].append(token)
    return segments


def _declaration_property(segment: Sequence[object]) -> str | None:
    for token in segment:
        if isinstance(token, ast.WhitespaceToken) or isinstance(token, ast.Comment):
            continue
        if isinstance(token, ast.IdentToken):
            return token.value.lower()
        return None
    return None

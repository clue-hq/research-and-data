"""Incremental extraction of the assistant's prose out of a streaming tool-call argument.

FI Lane D slice **D3**, charter §3.3(2) — the mechanism ratified §6-D2 depends on. The Head-of-ABM
conversation surface binds its model with ``tool_choice="required"``, so **every** user-visible word
the assistant writes exists only inside one JSON string field of one streamed tool call:
``finalize_turn.user_message``. Streaming "the assistant's text" therefore means decoding that one
field out of a JSON document that is arriving a few characters at a time, and emitting *only* the
characters of that field — never the surrounding JSON, never another argument of the same call,
never another tool's arguments, and never anything the provider says about its own reasoning.

Everything here is **pure**: no database, no LangChain, no I/O, no clock. It consumes fragments and
returns the newly decoded text. That is deliberate — the hard part of this slice is a parser, and a
parser that needs a Postgres connection to be tested is a parser nobody tests properly.

The four correctness properties the charter names, and how each is met:

* **Arbitrary chunk boundaries.** Every scrap of state — the container stack, whether a string is
  open, a half-read escape, a half-read ``\\uXXXX``, a pending surrogate half, a partially decoded
  multibyte UTF-8 sequence — lives on the instance, never in a local. A fragment may split anywhere,
  including between the two halves of a surrogate pair or in the middle of a UTF-8 code point.
* **Escapes.** ``\\"``, ``\\\\``, ``\\/``, ``\\b``, ``\\f``, ``\\n``, ``\\r``, ``\\t`` and
  ``\\uXXXX`` (including surrogate pairs) decode to their real characters. A character is emitted
  only once it is fully decoded, so a consumer never sees ``\\u00`` or a lone high surrogate.
* **Split multibyte UTF-8.** :meth:`FinalizeTextDeltaExtractor.feed_bytes` runs the fragments
  through an incremental UTF-8 decoder first, so a code point split across two byte fragments is
  reassembled before the JSON scanner ever sees it.
* **Nothing else leaks.** The scanner tracks depth and key position: only the *top-level*
  ``user_message`` key of the tool call's own argument object arms the value decoder. A nested
  object that happens to contain a ``user_message`` key, another argument of the same call, and any
  other tool call in the same round all emit nothing.

**Malformed input fails closed, never loudly guesses.** A byte sequence that is not valid JSON
string content (a bad escape, an unpaired surrogate, a raw control character) sets ``failed`` and
stops emission for that call. Nothing is invented and nothing already emitted is retracted; the
turn's own reconciliation step (§3.3(5)) then finds the mismatch against the durable message and
tells the client to re-fetch the canonical text. The durable turn is never rewritten by a parser.
"""

from __future__ import annotations

import codecs
from typing import Final

__all__ = [
    "FINALIZE_TEXT_FIELD",
    "FINALIZE_TOOL_NAME",
    "FinalizeTextDeltaExtractor",
    "JsonStringFieldDecoder",
]

#: The tool whose argument carries user-visible prose on the conversation surface, and the field
#: inside it. Named constants because three modules must agree on them: this extractor, the
#: emitter that installs it, and the streaming suite that proves it.
FINALIZE_TOOL_NAME: Final = "finalize_turn"
FINALIZE_TEXT_FIELD: Final = "user_message"

_HEX_DIGITS: Final = frozenset("0123456789abcdefABCDEF")
_WHITESPACE: Final = frozenset(" \t\n\r")
_SHORT_ESCAPES: Final = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


class JsonStringFieldDecoder:
    """Decode one named top-level string field out of a JSON object arriving in fragments.

    A tiny hand-written scanner rather than a JSON parser, because a parser wants a complete
    document and the whole point here is to emit characters *before* the document exists. It only
    ever needs to answer three questions — "are we inside the object", "is this string a key at
    depth 1", "is this the value of the field we want" — so the state is small enough to be
    exhaustively testable.
    """

    __slots__ = (
        "_complete",
        "_escape",
        "_failed",
        "_field",
        "_high_surrogate",
        "_in_string",
        "_key_chars",
        "_pending_key",
        "_stack",
        "_string_is_key",
        "_text",
        "_unicode_digits",
        "_value_active",
        "_value_armed",
        "_value_seen",
        "_expect_key",
    )

    def __init__(self, *, field: str = FINALIZE_TEXT_FIELD) -> None:
        self._field = field
        self._stack: list[str] = []
        self._expect_key = False
        self._in_string = False
        self._string_is_key = False
        self._key_chars: list[str] = []
        self._pending_key: str | None = None
        self._value_armed = False
        self._value_active = False
        self._value_seen = False
        self._escape = False
        self._unicode_digits: str | None = None
        self._high_surrogate: int | None = None
        self._text: list[str] = []
        self._complete = False
        self._failed = False

    # -- observations ---------------------------------------------------------------------------

    @property
    def text(self) -> str:
        """Everything decoded so far — the exact concatenation of every delta returned."""

        return "".join(self._text)

    @property
    def complete(self) -> bool:
        """The field's closing quote was seen: this value will never grow again."""

        return self._complete

    @property
    def failed(self) -> bool:
        """The fragments stopped being decodable. Emission has stopped; nothing was invented."""

        return self._failed

    @property
    def started(self) -> bool:
        """The field's *opening* quote was seen — even if no character has decoded yet.

        Load-bearing for the empty-string case: ``{"user_message": ""}`` must still produce a text
        part (a ``text.start`` and a ``text.end`` around zero deltas), not silence.
        """

        return self._value_seen

    # -- the scanner ----------------------------------------------------------------------------

    def feed(self, fragment: str) -> str:
        """Consume one fragment; return the characters of the target field newly decoded by it."""

        if self._complete or self._failed or not fragment:
            return ""
        out: list[str] = []
        for char in fragment:
            if self._complete or self._failed:
                break
            if self._value_active:
                self._value_char(char, out)
            else:
                self._structural_char(char)
        return "".join(out)

    def _structural_char(self, char: str) -> None:
        """Walk the document *around* the target value: containers, keys, and other values."""

        if self._in_string:
            self._other_string_char(char)
            return
        if char in _WHITESPACE:
            return
        if char == "{":
            self._stack.append("{")
            self._expect_key = True
            self._value_armed = False
            return
        if char == "[":
            self._stack.append("[")
            self._expect_key = False
            # An array where the target string should be: the field is not a string on this call.
            self._value_armed = False
            return
        if char in "}]":
            if self._stack:
                self._stack.pop()
            self._expect_key = False
            return
        if char == ",":
            self._expect_key = bool(self._stack) and self._stack[-1] == "{"
            self._value_armed = False
            return
        if char == ":":
            # Only a key at depth 1 — the tool call's own argument object — names our field.
            if self._pending_key == self._field and len(self._stack) == 1:
                self._value_armed = True
            self._pending_key = None
            self._expect_key = False
            return
        if char == '"':
            if self._value_armed:
                self._value_armed = False
                self._value_active = True
                self._value_seen = True
            else:
                self._in_string = True
                self._string_is_key = self._expect_key
                self._key_chars = []
                self._expect_key = False
            return
        # A bare literal (a number, true/false/null). If it stood where our field's value belongs,
        # the field simply is not a string on this call and there is nothing to stream.
        self._value_armed = False

    def _other_string_char(self, char: str) -> None:
        """Consume a string that is *not* the target value — a key, or somebody else's value.

        Keys are decoded (an escaped key must still match the field name); other values are only
        skipped, because emitting them is precisely what §3.3 forbids.
        """

        if self._unicode_digits is not None:
            if char not in _HEX_DIGITS:
                self._fail()
                return
            self._unicode_digits += char
            if len(self._unicode_digits) == 4:
                if self._string_is_key:
                    self._key_chars.append(chr(int(self._unicode_digits, 16)))
                self._unicode_digits = None
            return
        if self._escape:
            self._escape = False
            if char == "u":
                self._unicode_digits = ""
                return
            decoded = _SHORT_ESCAPES.get(char)
            if decoded is None:
                self._fail()
                return
            if self._string_is_key:
                self._key_chars.append(decoded)
            return
        if char == "\\":
            self._escape = True
            return
        if char == '"':
            self._in_string = False
            if self._string_is_key:
                self._pending_key = "".join(self._key_chars)
                self._string_is_key = False
            return
        if self._string_is_key:
            self._key_chars.append(char)

    def _value_char(self, char: str, out: list[str]) -> None:
        """Consume one character *inside* the target string, emitting only completed characters."""

        if self._unicode_digits is not None:
            if char not in _HEX_DIGITS:
                self._fail()
                return
            self._unicode_digits += char
            if len(self._unicode_digits) < 4:
                return
            code_point = int(self._unicode_digits, 16)
            self._unicode_digits = None
            if 0xD800 <= code_point <= 0xDBFF:
                # A high surrogate is half a character: hold it until its partner arrives, so a
                # consumer never receives a code point that cannot be UTF-8 encoded.
                if self._high_surrogate is not None:
                    self._fail()
                    return
                self._high_surrogate = code_point
                return
            if 0xDC00 <= code_point <= 0xDFFF:
                if self._high_surrogate is None:
                    self._fail()
                    return
                combined = 0x10000 + ((self._high_surrogate - 0xD800) << 10) + (code_point - 0xDC00)
                self._high_surrogate = None
                self._emit(chr(combined), out)
                return
            if self._high_surrogate is not None:
                self._fail()
                return
            self._emit(chr(code_point), out)
            return
        if self._escape:
            self._escape = False
            if char == "u":
                self._unicode_digits = ""
                return
            if self._high_surrogate is not None:
                # A high surrogate followed by anything other than a ``\\u`` escape is unpaired.
                self._fail()
                return
            decoded = _SHORT_ESCAPES.get(char)
            if decoded is None:
                self._fail()
                return
            self._emit(decoded, out)
            return
        if char == "\\":
            # Not a decision point: the next characters may still be the low half of a surrogate
            # pair, so a pending high surrogate stays pending.
            self._escape = True
            return
        if self._high_surrogate is not None:
            self._fail()
            return
        if char == '"':
            self._value_active = False
            self._complete = True
            return
        if ord(char) < 0x20:
            # A raw control character is invalid JSON string content.
            self._fail()
            return
        self._emit(char, out)

    def _emit(self, text: str, out: list[str]) -> None:
        self._text.append(text)
        out.append(text)

    def _fail(self) -> None:
        self._failed = True
        self._value_active = False
        self._escape = False
        self._unicode_digits = None
        self._high_surrogate = None


class _CallState:
    """One streamed tool call: its name, its byte decoder, and (if it is ours) its field decoder."""

    __slots__ = ("bytes_decoder", "decoder", "name", "saw_args")

    def __init__(self, *, name: str | None, decoder: JsonStringFieldDecoder | None) -> None:
        self.name = name
        self.decoder = decoder
        self.saw_args = False
        self.bytes_decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")


class FinalizeTextDeltaExtractor:
    """Turn a stream of provider-neutral tool-call chunks into assistant-text deltas.

    Provider-neutral by construction: it consumes the *normalized* ``(index, name, args)`` triple
    that every LangChain chat model produces for a streamed tool call, so no provider's raw wire
    shape reaches this module. Nothing about OpenAI, OpenRouter, or the Responses API appears here.

    One extractor covers one model round. A round can stream several tool calls at once (each with
    its own ``index``), and only the one named :data:`FINALIZE_TOOL_NAME` decodes; the others are
    tracked purely so their fragments cannot be mistaken for ours.
    """

    __slots__ = ("_calls", "_field", "_tool_name")

    def __init__(
        self,
        *,
        tool_name: str = FINALIZE_TOOL_NAME,
        field: str = FINALIZE_TEXT_FIELD,
    ) -> None:
        self._tool_name = tool_name
        self._field = field
        self._calls: dict[int, _CallState] = {}

    def feed_tool_call_chunk(
        self,
        *,
        index: int | None,
        name: str | None,
        args: str | bytes | None,
    ) -> str:
        """Consume one tool-call chunk; return the newly decoded assistant text (often ``""``).

        ``name`` arrives on a call's first chunk only, which is why call state is keyed on
        ``index``. A call whose first chunk carries no name is treated as *not ours*: guessing that
        an unnamed stream is the finalize call is exactly how surrounding JSON leaks.
        """

        slot = index if index is not None else 0
        state = self._calls.get(slot)
        if state is None:
            matched = name == self._tool_name
            state = _CallState(
                name=name,
                decoder=JsonStringFieldDecoder(field=self._field) if matched else None,
            )
            self._calls[slot] = state
        elif state.name is None and name is not None and not state.saw_args:
            # Some providers name a call on a later chunk. Adopting the name is safe only while no
            # argument fragment has been dropped yet — starting a JSON scanner half-way through a
            # document is how surrounding syntax leaks into a "text" delta.
            state.name = name
            if name == self._tool_name:
                state.decoder = JsonStringFieldDecoder(field=self._field)
        if args is not None:
            state.saw_args = True
        if args is None or state.decoder is None:
            return ""
        fragment = (
            state.bytes_decoder.decode(args, False) if isinstance(args, bytes | bytearray) else args
        )
        return state.decoder.feed(fragment)

    def feed(self, args: str | bytes) -> str:
        """Feed one anonymous argument fragment of the finalize call (the single-call shorthand)."""

        return self.feed_tool_call_chunk(index=0, name=self._tool_name, args=args)

    # -- observations ---------------------------------------------------------------------------

    @property
    def decoder(self) -> JsonStringFieldDecoder | None:
        """The finalize call's decoder, once one has been seen."""

        for state in self._calls.values():
            if state.decoder is not None:
                return state.decoder
        return None

    @property
    def text(self) -> str:
        decoder = self.decoder
        return "" if decoder is None else decoder.text

    @property
    def started(self) -> bool:
        decoder = self.decoder
        return decoder is not None and decoder.started

    @property
    def complete(self) -> bool:
        decoder = self.decoder
        return decoder is not None and decoder.complete

    @property
    def failed(self) -> bool:
        decoder = self.decoder
        return decoder is not None and decoder.failed

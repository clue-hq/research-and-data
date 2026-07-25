"""Deterministic normalizers — the shared, side-effect-free folding rules (M2.1/M2.2).

Identity resolution's deterministic stage (substrate §2: *deterministic first, probabilistic
second*) rests entirely on **stable normal forms**: two records that mean the same strong key must
fold to byte-identical strings so an exact-key lookup hits without a model call. These functions are
that folding, kept pure and dependency-free so they are trivially testable and identical on both
sides of every comparison (the observation and the stored value normalize through the *same* code).

* :func:`registrable_domain` — a URL or bare host → its registrable domain key (scheme/port/path
  stripped, ``www.`` dropped, lower-cased). Public-suffix reduction (``co.uk``) is a documented,
  swappable refinement; deterministic host folding is what exact matching needs today.
* :func:`normalize_name` — a company/person name → a folded form (unicode NFKD accent-fold,
  lower-case, every non-alphanumeric run → a single space, trimmed). ``"Açme, Inc."`` → ``"acme
  inc"``.
* :func:`strip_legal_suffix` — drop a trailing legal-entity token (``inc``/``llc``/``gmbh``/…) from
  an already-:func:`normalize_name`-d string, so ``"acme inc"`` and ``"acme"`` fold together.
* :func:`name_key` — a name's canonical match key: ``strip_legal_suffix(normalize_name(x))``.
* :func:`canonical_registry_id` — a registry id → ``(NAMESPACE_UPPER, value_without_separators)`` so
  ``DUNS "12-345-6789"`` and ``duns "123456789"`` fold to one key.

The normalizer *ruleset version* is part of M2.2's scorer config (policy-as-data): a normalizer
change is a versioned config bump, not a silent behaviour change under existing claims.
"""

from __future__ import annotations

import re
import unicodedata

# The normalizer ruleset version. Bumped when a folding rule changes; M2.2's scorer config records
# it so a re-normalization is an explicit, auditable event (conventions §2 — policy is data).
NORMALIZER_VERSION = 1

# Trailing legal-entity tokens stripped by strip_legal_suffix (already lower-cased, punctuation
# removed). Order-independent; matched as whole trailing words. Open list — adding a token is a
# one-line change, not a pipeline fork.
_LEGAL_SUFFIXES = frozenset(
    {
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "llc",
        "lp",
        "llp",
        "ltd",
        "limited",
        "plc",
        "gmbh",
        "ag",
        "sa",
        "sas",
        "srl",
        "bv",
        "nv",
        "oy",
        "ab",
        "as",
        "pty",
        "kk",
        "kg",
        "aps",
        "spa",
        "pte",
        "holdings",
        "group",
    }
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)
_HOSTNAME = re.compile(r"[a-z0-9.\-]+")


def fold_unicode(text: str) -> str:
    """NFKD-decompose and drop combining marks, so ``"Açmé"`` → ``"Acme"`` (case preserved)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_name(name: str) -> str:
    """Fold a name to its stable normal form: accent-fold, lower-case, every non-alphanumeric run
    to one space, trimmed. Empty/whitespace-only input folds to ``""``."""
    folded = fold_unicode(name).lower()
    return _NON_ALNUM.sub(" ", folded).strip()


def strip_legal_suffix(normalized_name: str) -> str:
    """Drop trailing legal-entity tokens from an already-:func:`normalize_name`-d string.

    Strips repeatedly (``"acme co ltd"`` → ``"acme"``) but never strips the last remaining token
    (a company literally named ``"Group"`` keeps its name). Input is assumed already normalized.
    """
    tokens = normalized_name.split()
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def name_key(name: str) -> str:
    """The canonical match key for a name: :func:`strip_legal_suffix` ∘ :func:`normalize_name`."""
    return strip_legal_suffix(normalize_name(name))


def registrable_domain(url_or_domain: str) -> str | None:
    """Extract the registrable-domain key from a URL or bare host, or ``None`` if there is none.

    Strips scheme, userinfo, port, path/query/fragment, and a leading ``www.``; lower-cases the
    result. ``"https://www.Acme.com/about?x=1"`` → ``"acme.com"``. A value with no dot (a bare word)
    returns ``None`` — it is a name, not a domain. Public-suffix reduction (so ``a.example.co.uk``
    → ``example.co.uk``) is a deliberate later refinement behind this same function.
    """
    candidate = url_or_domain.strip()
    if not candidate:
        return None
    candidate = _SCHEME.sub("", candidate)
    candidate = candidate.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    candidate = candidate.rsplit("@", 1)[-1]  # drop userinfo
    candidate = candidate.split(":", 1)[0]  # drop port
    host = fold_unicode(candidate).lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    if "." not in host or not host:
        return None
    # Reject anything with characters a hostname cannot contain (so a sentence isn't a "domain").
    if not _HOSTNAME.fullmatch(host):
        return None
    return host


def canonical_registry_id(namespace: str, value: str) -> tuple[str, str]:
    """Fold a registry id to ``(NAMESPACE_UPPER, compact_value)`` — separators/whitespace removed.

    ``("duns", "12-345 6789")`` → ``("DUNS", "123456789")``. Keeps alphanumerics only in the value
    (some registries — e.g. LEI — are alphanumeric), upper-cased for case-stability.
    """
    ns = namespace.strip().upper()
    compact = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return ns, compact

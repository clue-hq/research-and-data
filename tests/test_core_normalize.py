"""The shared ``clue_core.normalize_host`` URL-host fold (M9.4 DRY consolidation).

One host normalizer for the M9.4 identity-binding ``normalize_url``, the M9.2 corroboration
independence ``_host``, and the M4.5/M11 resolver target-lock ``registrable_host`` — the three
previously-divergent copies now delegate here, so the fold is asserted once.
"""

from __future__ import annotations

from clue_core import normalize_host


def test_normalize_host_folds_scheme_case_and_www() -> None:
    assert normalize_host("https://www.Acme.com/about?x=1") == "acme.com"
    assert normalize_host("http://acme.com") == "acme.com"
    assert normalize_host("acme.com") == "acme.com"  # a bare domain is a netloc, not a path


def test_normalize_host_scheme_less_authority_is_recognised() -> None:
    # The two-pass parse: urlsplit finds no host, so the input is re-parsed with a `//` prefix.
    assert normalize_host("acme.com/x") == "acme.com"
    # The single "'//' in url" heuristic (the old resolver copies) mis-parsed a doubled-slash
    # path as path-only and dropped the host; the shared fold keeps it.
    assert normalize_host("acme.com/a//b") == "acme.com"


def test_normalize_host_strips_userinfo_port_and_ipv6_brackets() -> None:
    assert normalize_host("https://user:pw@WWW.Acme.com:443/x") == "acme.com"
    assert normalize_host("https://[2001:db8::1]/path") == "2001:db8::1"
    assert normalize_host("https://[2001:db8::1]:8443/path") == "2001:db8::1"


def test_normalize_host_host_less_input_is_empty() -> None:
    # Callers needing None write `normalize_host(url) or None`.
    assert normalize_host("") == ""
    assert normalize_host("   ") == ""
    assert normalize_host("/path-only") == ""

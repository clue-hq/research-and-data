from __future__ import annotations

from clue_api.dns_observe import DnsLookupError, DnsObservation, observe_hostname


class FakeResolver:
    def __init__(self, records: dict[tuple[str, str], list[str]], *, fail: bool = False) -> None:
        self.records = records
        self.fail = fail

    def resolve(self, name: str, rdtype: str) -> list[str]:
        if self.fail:
            raise DnsLookupError("SERVFAIL")
        return self.records.get((name, rdtype), [])


def test_observation_reports_cname_and_txt_values() -> None:
    resolver = FakeResolver(
        {
            ("go.acme.com", "CNAME"): ["pages.cluehq.ai"],
            ("_cf-custom-hostname.go.acme.com", "TXT"): ["tok-1", "other"],
        }
    )
    seen = observe_hostname("go.acme.com", "_cf-custom-hostname.go.acme.com", resolver=resolver)
    assert seen == DnsObservation(
        cname="pages.cluehq.ai", txt_values=("tok-1", "other"), error=None
    )


def test_missing_records_are_none_and_empty() -> None:
    seen = observe_hostname(
        "go.acme.com", "_cf-custom-hostname.go.acme.com", resolver=FakeResolver({})
    )
    assert seen.cname is None and seen.txt_values == () and seen.error is None


def test_resolver_failure_is_reported_not_raised() -> None:
    seen = observe_hostname(
        "go.acme.com", "_cf-custom-hostname.go.acme.com", resolver=FakeResolver({}, fail=True)
    )
    assert seen.cname is None and "SERVFAIL" in (seen.error or "")

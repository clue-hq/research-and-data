"""DNS observation for custom hostnames (spec §7.4): CNAME of the hostname and TXT at the ownership
name, through PUBLIC resolvers so a cached local answer cannot mislead. Synchronous (dnspython);
callers run it in a thread."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

PUBLIC_NAMESERVERS = ("1.1.1.1", "8.8.8.8")
_LIFETIME_S = 5.0


class DnsLookupError(Exception):
    """The resolver itself failed (timeout, SERVFAIL); distinct from "no such record"."""


class DnsResolver(Protocol):
    def resolve(self, name: str, rdtype: str) -> list[str]: ...


@dataclass(frozen=True)
class DnsObservation:
    cname: str | None
    txt_values: tuple[str, ...]
    error: str | None


class PublicDnsResolver:
    def __init__(self, nameservers: tuple[str, ...] = PUBLIC_NAMESERVERS) -> None:
        import dns.resolver  # lazy: importing this module must not need dnspython at import time

        self._resolver = dns.resolver.Resolver(configure=False)
        self._resolver.nameservers = list(nameservers)
        self._resolver.lifetime = _LIFETIME_S

    def resolve(self, name: str, rdtype: str) -> list[str]:
        import dns.exception
        import dns.resolver

        try:
            answer = self._resolver.resolve(name, rdtype, raise_on_no_answer=False)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoNameservers) as error:
            if isinstance(error, dns.resolver.NXDOMAIN):
                return []
            raise DnsLookupError(str(error)) from error
        except dns.exception.DNSException as error:
            raise DnsLookupError(str(error)) from error
        values: list[str] = []
        for rdata in answer:
            if rdtype == "CNAME":
                values.append(str(rdata.target).rstrip(".").lower())
            elif rdtype == "TXT":
                values.append(b"".join(rdata.strings).decode("utf-8", "replace"))
            else:
                values.append(str(rdata))
        return values


def observe_hostname(hostname: str, txt_name: str, *, resolver: DnsResolver) -> DnsObservation:
    try:
        cnames = resolver.resolve(hostname, "CNAME")
        txts = resolver.resolve(txt_name, "TXT")
    except DnsLookupError as error:
        return DnsObservation(cname=None, txt_values=(), error=str(error))
    return DnsObservation(
        cname=cnames[0].rstrip(".").lower() if cnames else None, txt_values=tuple(txts), error=None
    )

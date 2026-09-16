"""Logo.dev Brand API adapter; the wide ``brandmark`` is the full lockup.

Contract: https://www.logo.dev/docs/brand/introduction and
https://www.logo.dev/docs/logo-images/get (verified 2026-09-15).
The provider exposes one optional wide brandmark and a square logo, not a
Brandfetch-style array of original theme variants. Square logos stay alternatives;
missing original variants stay empty. ``theme=auto`` preserves original colors,
and ``fallback=404`` prevents invented monograms. Banners are not logos.

Returned CDN URLs can expire after 24 hours. Consume their bytes immediately and
retain only query-free provenance. The caller owns configuration and persistence.
"""

from __future__ import annotations

import io
import logging
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

import httpx

from .logo_family import FamilyCell, cell_name
from .logo_vendor import VendorCredentialsMissing, VendorLookupFailed

_MAX_ASSET_BYTES = 15 * 1024 * 1024


class _SafeLogoRequestLog(logging.Filter):
    """HTTPX logs each request URL at INFO, including CDN query credentials."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                value.copy_with(query=None)
                if isinstance(value, httpx.URL) and value.host == "img.logo.dev"
                else value
                for value in record.args
            )
        return True


logging.getLogger("httpx").addFilter(_SafeLogoRequestLog())


def _asset_urls(src: str, requested_domain: str) -> tuple[str, str] | None:
    """Validate before fetching; return private download URL and public origin."""
    try:
        url = urlsplit(src)
        if (
            url.scheme != "https"
            or url.hostname != "img.logo.dev"
            or url.port not in (None, 443)
            or url.username is not None
            or url.password is not None
            or not url.path.strip("/")
        ):
            return None
        token = dict(parse_qsl(url.query)).get("token", "")
        if not token:
            return None
        parts = unquote(url.path).strip("/").split("/")
        if any(part in ("", ".", "..") for part in parts):
            return None
        asset_domain = parts[1] if parts[0] == "brand" and len(parts) > 2 else parts[0]
        if asset_domain.lower().rstrip(".") != requested_domain:
            return None
    except ValueError:
        return None
    params = {
        "token": token,
        "theme": "auto",
        "greyscale": "false",
        "fallback": "404",
        "format": "png",
        "size": "800",
    }
    origin = urlunsplit((url.scheme, url.netloc, url.path, "", ""))
    return urlunsplit((url.scheme, url.netloc, url.path, urlencode(params), "")), origin


def _transparent_png(body: bytes) -> tuple[int, int] | None:
    """Verify a real, nonempty transparent PNG without changing its bytes."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(body)) as image:
            if image.format != "PNG":
                return None
            image.load()
            alpha_min, alpha_max = image.convert("RGBA").getchannel("A").getextrema()
            if alpha_min != 0 or alpha_max == 0:
                return None
            return image.size
    except Exception:  # noqa: BLE001 - unreadable artwork is a missing candidate
        return None


def _download(http: httpx.Client, url: str, timeout_s: float) -> tuple[bytes | None, str]:
    """Bound the response while streaming; never forward a client's credentials."""
    try:
        request = http.build_request("GET", url, timeout=timeout_s)
        for header in ("Authorization", "Cookie"):
            request.headers.pop(header, None)
        response = http.send(request, auth=None, follow_redirects=False, stream=True)
        try:
            if response.status_code != 200:
                return None, f"download returned HTTP {response.status_code}"
            chunks = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > _MAX_ASSET_BYTES:
                    return None, "download exceeded the asset size limit"
                chunks.append(chunk)
            return b"".join(chunks), ""
        finally:
            response.close()
    except httpx.HTTPError:
        return None, "download failed"


def fetch_logo_dev_family(
    domain: str,
    *,
    company_name: str | None = None,
    secret_key: str = "",
    base_url: str = "https://api.logo.dev",
    timeout_s: float = 30.0,
    client: httpx.Client | None = None,
) -> tuple[dict[str, FamilyCell], list[FamilyCell], list[str]]:
    """Retrieve the provider's available originals, never derive extra variants.

    A 404 is an empty answer; credentials, quota, indexing and identity failures
    use the same typed degrade seam as Brandfetch. HTTP bodies/exception text are
    deliberately not exposed: both can contain credentials or signed asset URLs.
    """
    from .provider_identity import (
        ProviderIdentityError,
        normalized_host,
        validate_vendor_identity,
    )

    key = secret_key.strip()
    if not key:
        raise VendorCredentialsMissing(("LOGO_DEV_SECRET_KEY",))
    host = normalized_host(domain)
    if not host:
        raise VendorLookupFailed("http", "Logo.dev lookup needs a company domain")
    base = base_url.rstrip("/")
    if base.endswith("/brand"):
        base = base[:-6]

    def run(http: httpx.Client):
        try:
            response = http.get(
                f"{base}/brand/{host}",
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                timeout=timeout_s,
                auth=None,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            raise VendorLookupFailed("timeout", "Logo.dev brand lookup timed out") from None
        except httpx.HTTPError:
            raise VendorLookupFailed("http", "Logo.dev brand lookup failed") from None
        if response.status_code == 404:
            return {}, [], ["Logo.dev has no brand data (HTTP 404)"]
        if response.status_code != 200:
            code = {202: "pending", 401: "auth", 402: "quota", 403: "auth", 429: "quota"}.get(
                response.status_code, "http"
            )
            raise VendorLookupFailed(
                code, f"Logo.dev brand lookup returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError:
            raise VendorLookupFailed("malformed", "Logo.dev brand response was not JSON") from None
        if not isinstance(payload, dict):
            raise VendorLookupFailed("malformed", "Logo.dev brand response was not an object")
        try:
            identity = validate_vendor_identity(
                payload, requested_domain=host, company_name=company_name
            )
        except ProviderIdentityError as error:
            raise VendorLookupFailed(error.code, error.message) from None

        cells: dict[str, FamilyCell] = {}
        extras: list[FamilyCell] = []
        notes: list[str] = []
        for kind in ("brandmark", "logo"):
            src = payload.get(kind)
            if not isinstance(src, str) or not src:
                notes.append(f"Logo.dev has no {kind} asset")
                continue
            urls = _asset_urls(src, host)
            if urls is None:
                notes.append(f"Logo.dev {kind} has no safe authenticated CDN asset URL")
                continue
            fetch_url, safe_origin = urls
            body, failure = _download(http, fetch_url, timeout_s)
            if body is None:
                notes.append(f"Logo.dev {kind} {failure}")
                continue
            dimensions = _transparent_png(body)
            if dimensions is None:
                notes.append(
                    f"Logo.dev {kind} refused: could not decode nonempty transparent PNG artwork"
                )
                continue
            from .logo_ladder import LadderCandidate, analyze_appearance

            verdict = analyze_appearance(LadderCandidate(url="", fmt="png", body=body))["verdict"]
            theme = "dark" if verdict == "dark_variant" else "light"
            name = cell_name(theme, "lockup") if kind == "brandmark" else ""
            evidence = {
                "vendor": "logo_dev",
                "vendor_identity": identity,
                "provider_asset_kind": kind,
                "vendor_type": "logo" if kind == "brandmark" else "icon",
                "theme": theme,
                "measured_verdict": verdict,
                "format": "png",
                "transparent": True,
                "width": dimensions[0],
                "height": dimensions[1],
            }
            found = FamilyCell(name, body, "image/png", "logo_dev", safe_origin, evidence)
            if name:
                cells[name] = found
            else:
                found.evidence.update(
                    {"competed_for": None, "reason": "square logo is not a verified bare symbol"}
                )
                extras.append(found)
        notes.append(
            "Logo.dev supplies one wide brandmark and one square logo; "
            "missing original variants remain empty"
        )
        return cells, extras, notes

    if client is not None:
        return run(client)
    with httpx.Client() as owned:
        return run(owned)

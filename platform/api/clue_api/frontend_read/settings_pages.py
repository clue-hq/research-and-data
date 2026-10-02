"""Settings → Pages control plane (custom-domain publishing §7): page defaults, the Clue address
label, and (Task 8) connecting / checking / removing ONE customer hostname.

Everything here is workspace-scoped by the router's own dependency; every *write* additionally
requires ``workspace.manage_settings`` (clue_auth policy revision 3 — admins and owners), checked
route-side so an unauthorised caller never reaches the DAL.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from clue_api.auth_wiring import principal_from_request
from clue_api.cloudflare_custom_hostnames import CloudflareCustomHostnames, CloudflareError
from clue_api.dns_observe import DnsResolver, PublicDnsResolver, observe_hostname
from clue_api.frontend_read.accounts_list import WireModel
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.pages_hostname_status import ProviderState, derive_status
from clue_config import Secrets, Settings
from clue_db import ConnFactory
from clue_design.storage import register_design_bytes
from clue_obs import get_logger
from clue_spine.hostnames import (
    HostnameRefused,
    HostnameStatus,
    delete_custom_hostname,
    get_custom_hostname,
    hostname_exists,
    insert_custom_hostname,
    public_origin,
    record_custom_hostname_check,
    replace_system_label,
    set_custom_hostname_provider,
    set_custom_hostname_status,
    system_hostname,
    validate_custom_hostname,
)
from clue_spine.pages_settings import UNSET, Unset, get_pages_settings, update_pages_settings
from clue_storage import StorageBackend, content_address

log = get_logger("clue_api.frontend_read.settings_pages")

FAVICON_TYPES = {"image/png", "image/x-icon", "image/vnd.microsoft.icon", "image/svg+xml"}
SOCIAL_TYPES = {"image/png", "image/jpeg"}
FAVICON_MAX = 256 * 1024
SOCIAL_MAX = 2 * 1024 * 1024
# A custom hostname is re-derived at most once every 5 s per workspace: the screen polls while a
# connection provisions, and each derivation costs two DNS lookups plus a Cloudflare GET.
CHECK_INTERVAL_S = 5.0


# --- wire (spec §7.2) ------------------------------------------------------
class PagesSettingsWire(WireModel):
    fallback_url: str | None
    page_title: str | None
    page_description: str | None
    favicon_url: str | None
    social_preview_url: str | None


class SystemHostnameWire(WireModel):
    hostname: str
    label: str
    url: str


class DnsRecordWire(WireModel):
    type: Literal["CNAME", "TXT"]
    name: str
    required: str
    observed: str | None
    ok: bool


class HostnameErrorWire(WireModel):
    code: str
    detail: str | None


class CustomHostnameWire(WireModel):
    hostname: str
    status: str
    records: list[DnsRecordWire]
    last_checked_at: str | None
    error: HostnameErrorWire | None
    url: str | None


class PagesSettingsReadWire(WireModel):
    settings: PagesSettingsWire
    system_hostname: SystemHostnameWire
    custom_hostname: CustomHostnameWire | None


class PagesSettingsPatch(BaseModel):
    """A partial update: an absent key is ``UNSET`` (untouched), an explicit ``null`` clears.

    ``arbitrary_types_allowed`` is what lets the :class:`~clue_spine.pages_settings.Unset` sentinel
    appear in the annotation at all; ``populate_by_name`` accepts the snake_case field names too.
    """

    fallback_url: str | None | Unset = Field(default=UNSET, alias="fallbackUrl")
    page_title: str | None | Unset = Field(default=UNSET, alias="pageTitle")
    page_description: str | None | Unset = Field(default=UNSET, alias="pageDescription")
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, populate_by_name=True)


class LabelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str


class ConnectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hostname: str


def _refusal(
    status_code: int, code: str, message: str, *, extra: dict[str, Any] | None = None
) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message, **(extra or {})}
    )


def require_manage_settings(request: Request, *, allow_local_mutations: bool) -> None:
    principal = principal_from_request(request)
    if principal is not None:
        if "workspace.manage_settings" not in principal.permissions:
            raise _refusal(403, "PERMISSION_REQUIRED", "workspace.manage_settings is required")
        return
    if not allow_local_mutations:
        raise _refusal(401, "UNAUTHORIZED", "An authenticated session is required.")


class PagesSettingsService:
    def __init__(
        self,
        conn_factory: ConnFactory,
        *,
        settings: Settings,
        storage: StorageBackend | None,
        cloudflare: CloudflareCustomHostnames | None,
        resolver: DnsResolver | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._conn_factory = conn_factory
        self._settings = settings
        self._storage = storage
        self._cloudflare = cloudflare
        self._resolver = resolver
        self._clock = clock

    # -- shapes --------------------------------------------------------------
    def _origin(self, hostname: str) -> str:
        return public_origin(
            hostname,
            scheme=self._settings.pages_public_scheme,
            port=self._settings.pages_public_port,
        )

    async def read(self, workspace_id: str) -> PagesSettingsReadWire:
        async with self._conn_factory() as conn:
            row = await get_pages_settings(conn, workspace_id)
            system = await system_hostname(conn, workspace_id)
            custom = await get_custom_hostname(conn, workspace_id)
        if system is None:
            raise _refusal(500, "SYSTEM_HOSTNAME_MISSING", "run `make pages-backfill-hostnames`")
        origin = self._origin(system)
        settings_wire = PagesSettingsWire(
            fallback_url=row.fallback_url,
            page_title=row.page_title,
            page_description=row.page_description,
            favicon_url=f"{origin}/favicon.ico" if row.favicon_sha256 else None,
            social_preview_url=(
                f"{origin}/asset-store/{row.social_preview_sha256}"
                if row.social_preview_sha256
                else None
            ),
        )
        suffix = "." + self._settings.pages_system_suffix
        return PagesSettingsReadWire(
            settings=settings_wire,
            system_hostname=SystemHostnameWire(
                hostname=system, label=system.removesuffix(suffix), url=origin
            ),
            custom_hostname=self._custom_wire(custom) if custom is not None else None,
        )

    def _custom_wire(self, row: Any) -> CustomHostnameWire:
        records = [
            DnsRecordWire(
                type="CNAME",
                name=row.hostname,
                required=row.cname_target,
                observed=row.observed_cname,
                ok=(row.observed_cname or "").lower() == row.cname_target.lower(),
            ),
            DnsRecordWire(
                type="TXT",
                name=row.ownership_txt_name,
                required=row.ownership_txt_value,
                observed=row.ownership_txt_value if row.observed_txt_present else None,
                ok=bool(row.observed_txt_present),
            ),
        ]
        return CustomHostnameWire(
            hostname=row.hostname,
            status=row.status,
            records=records,
            last_checked_at=row.last_checked_at.isoformat() if row.last_checked_at else None,
            error=(
                HostnameErrorWire(code=row.last_error_code, detail=row.last_error_detail)
                if row.last_error_code
                else None
            ),
            url=f"https://{row.hostname}" if row.status == "active" else None,
        )

    # -- settings ------------------------------------------------------------
    async def update_settings(
        self, workspace_id: str, patch: PagesSettingsPatch
    ) -> PagesSettingsReadWire:
        if isinstance(patch.fallback_url, str) and not patch.fallback_url.startswith("https://"):
            raise _refusal(422, "VALIDATION_ERROR", "fallbackUrl must start with https://")
        async with self._conn_factory() as conn:
            await update_pages_settings(
                conn,
                workspace_id=workspace_id,
                fallback_url=patch.fallback_url,
                page_title=patch.page_title,
                page_description=patch.page_description,
            )
        return await self.read(workspace_id)

    async def store_image(
        self, workspace_id: str, kind: Literal["favicon", "social_preview"], upload: UploadFile
    ) -> PagesSettingsReadWire:
        if self._storage is None:
            raise _refusal(503, "PAGES_STORAGE_UNAVAILABLE", "Image storage is unavailable.")
        allowed, limit = (
            (FAVICON_TYPES, FAVICON_MAX) if kind == "favicon" else (SOCIAL_TYPES, SOCIAL_MAX)
        )
        media_type = (upload.content_type or "").split(";")[0].strip().lower()
        if media_type not in allowed:
            raise _refusal(
                415,
                "UNSUPPORTED_MEDIA_TYPE",
                f"{media_type or 'unknown'} is not allowed for {kind}",
            )
        # One byte past the cap is enough to know it is over it, and never buffers a huge upload.
        data = await upload.read(limit + 1)
        if len(data) > limit:
            raise _refusal(413, "PAYLOAD_TOO_LARGE", f"{kind} must be at most {limit} bytes")
        async with self._conn_factory() as conn:
            await register_design_bytes(
                conn,
                self._storage,
                workspace_id=workspace_id,
                data=data,
                media_type=media_type,
                source_key=f"pages_settings_{kind}",
            )
            digest = content_address(data)
            if kind == "favicon":
                await update_pages_settings(conn, workspace_id=workspace_id, favicon_sha256=digest)
            else:
                await update_pages_settings(
                    conn, workspace_id=workspace_id, social_preview_sha256=digest
                )
        return await self.read(workspace_id)

    async def change_label(self, workspace_id: str, label: str) -> PagesSettingsReadWire:
        try:
            async with self._conn_factory() as conn:
                await replace_system_label(
                    conn,
                    workspace_id=workspace_id,
                    label=label,
                    suffix=self._settings.pages_system_suffix,
                )
        except HostnameRefused as refused:
            raise _refusal(
                422 if refused.code != "label_taken" else 409, refused.code, refused.message
            ) from refused
        return await self.read(workspace_id)

    # -- custom hostname (spec §7.3–7.6) --------------------------------------
    async def connect(self, workspace_id: str, raw_hostname: str) -> PagesSettingsReadWire:
        try:
            hostname = validate_custom_hostname(
                raw_hostname, system_suffix=self._settings.pages_system_suffix
            )
        except HostnameRefused as refused:
            raise _refusal(422, refused.code, refused.message) from refused
        if self._cloudflare is None:
            raise _refusal(
                503,
                "PROVIDER_NOT_CONFIGURED",
                "Custom domains are not configured on this deployment.",
            )
        async with self._conn_factory() as conn:
            if await get_custom_hostname(conn, workspace_id) is not None:
                raise _refusal(
                    409,
                    "custom_hostname_exists",
                    "This workspace already has a custom hostname; remove it first.",
                )
            if await hostname_exists(conn, hostname):
                raise _refusal(
                    409, "hostname_taken", "This hostname is already connected to a workspace."
                )
            try:
                async with conn.begin_nested():
                    await insert_custom_hostname(
                        conn,
                        workspace_id=workspace_id,
                        hostname=hostname,
                        cname_target=self._settings.pages_cname_target,
                    )
            except IntegrityError as error:
                raise _refusal(
                    409, "hostname_taken", "This hostname is already connected to a workspace."
                ) from error
        # Committed. Now the provider; a refusal deletes the row again.
        try:
            record = await self._cloudflare.create(hostname)
        except CloudflareError as error:
            async with self._conn_factory() as conn:
                await delete_custom_hostname(conn, hostname=hostname)
            raise _refusal(502, "provider_error", error.message) from error
        async with self._conn_factory() as conn:
            await set_custom_hostname_provider(
                conn,
                hostname=hostname,
                cf_custom_hostname_id=record.id,
                ownership_txt_name=record.ownership_txt_name or f"_cf-custom-hostname.{hostname}",
                ownership_txt_value=record.ownership_txt_value or "",
            )
        log.info("pages.custom_hostname.connected", workspace_id=workspace_id, hostname=hostname)
        return await self.read(workspace_id)

    async def _provider_state(self, row: Any) -> ProviderState | None:
        if self._cloudflare is None or not row.cf_custom_hostname_id:
            return None
        record = await self._cloudflare.get(row.cf_custom_hostname_id)
        if record is None:
            return None
        return ProviderState(
            status=record.status,
            ssl_status=record.ssl_status,
            verification_errors=record.verification_errors,
            ssl_validation_errors=record.ssl_validation_errors,
        )

    async def check(self, workspace_id: str, *, force: bool = True) -> PagesSettingsReadWire:
        """Re-derive the custom hostname's status from DNS + the provider (spec §7.4).

        ``force`` is what separates the explicit "Check now" button from the passive GET refresh:
        only a forced check retries a stuck ``disconnecting`` delete (and so only a forced check
        can answer 502). The ``CHECK_INTERVAL_S`` rate limit governs the DNS/provider *observation*
        only — it never defers that removal retry.
        """
        now = self._clock()
        async with self._conn_factory() as conn:
            row = await get_custom_hostname(conn, workspace_id)
        if row is None:
            return await self.read(workspace_id)
        # A stuck removal is retried ABOVE the rate limit: the retry is a provider call the user
        # explicitly asked for, not a DNS observation, so a Check now within 5 s of the failed
        # removal must still complete it rather than silently answer "disconnecting".
        if row.status == "disconnecting":
            if force:
                await self._finish_remove(row)
            return await self.read(workspace_id)
        if (
            row.last_checked_at is not None
            and (now - row.last_checked_at).total_seconds() < CHECK_INTERVAL_S
        ):
            return await self.read(workspace_id)
        resolver = self._resolver or PublicDnsResolver()
        observation = await asyncio.to_thread(
            observe_hostname, row.hostname, row.ownership_txt_name, resolver=resolver
        )
        try:
            provider = await self._provider_state(row)
        except CloudflareError as error:
            provider = ProviderState(
                status=row.status,
                ssl_status=None,
                verification_errors=(error.message,),
                ssl_validation_errors=(),
            )
        decision = derive_status(
            observation=observation,
            provider=provider,
            cname_target=row.cname_target,
            expected_txt_value=row.ownership_txt_value,
            connected_at=row.created_at,
            now=now,
        )
        async with self._conn_factory() as conn:
            await record_custom_hostname_check(
                conn,
                hostname=row.hostname,
                status=cast(HostnameStatus, decision.status),
                observed_cname=observation.cname,
                observed_txt_present=row.ownership_txt_value in observation.txt_values,
                last_error_code=decision.error_code,
                last_error_detail=decision.error_detail,
                checked_at=now,
            )
        return await self.read(workspace_id)

    async def read_with_refresh(self, workspace_id: str) -> PagesSettingsReadWire:
        """The GET: a cheap refresh when the custom row is non-active and stale (spec §7.1)."""
        async with self._conn_factory() as conn:
            row = await get_custom_hostname(conn, workspace_id)
        if row is not None and row.status != "active":
            return await self.check(workspace_id, force=False)
        return await self.read(workspace_id)

    async def _finish_remove(self, row: Any) -> None:
        if self._cloudflare is not None and row.cf_custom_hostname_id:
            try:
                await self._cloudflare.delete(row.cf_custom_hostname_id)
            except CloudflareError as error:
                raise _refusal(
                    502, "provider_error", error.message, extra={"retryable": True}
                ) from error
        async with self._conn_factory() as conn:
            await delete_custom_hostname(conn, hostname=row.hostname)

    async def remove(self, workspace_id: str) -> None:
        async with self._conn_factory() as conn:
            row = await get_custom_hostname(conn, workspace_id)
            if row is None:
                raise _refusal(404, "CUSTOM_HOSTNAME_NOT_FOUND", "No custom hostname is connected.")
            await set_custom_hostname_status(conn, hostname=row.hostname, status="disconnecting")
        await self._finish_remove(row)
        log.info("pages.custom_hostname.removed", workspace_id=workspace_id, hostname=row.hostname)


def build_cloudflare_client(
    settings: Settings, secrets: Secrets | None
) -> CloudflareCustomHostnames | None:
    token = (
        secrets.cloudflare_api_token.get_secret_value()
        if secrets and secrets.cloudflare_api_token
        else None
    )
    if not token or not settings.cloudflare_zone_id:
        return None
    return CloudflareCustomHostnames(zone_id=settings.cloudflare_zone_id, api_token=token)


def register_settings_pages_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    settings: Settings,
    secrets: Secrets | None,
    storage: StorageBackend | None,
    allow_local_mutations: bool,
    cloudflare: CloudflareCustomHostnames | None = None,
    resolver: DnsResolver | None = None,
) -> None:
    # Built ONCE, here: the Cloudflare client owns an HTTP client, and a per-request one would leak
    # a connection pool per call.
    service = PagesSettingsService(
        conn_factory,
        settings=settings,
        storage=storage,
        cloudflare=cloudflare
        if cloudflare is not None
        else build_cloudflare_client(settings, secrets),
        resolver=resolver if resolver is not None else PublicDnsResolver(),
    )

    def _service(request: Request) -> PagesSettingsService:
        # Tests inject fakes (provider, resolver, clock) through app.state; production has nothing
        # there and uses `service`. A test that sets only a clock still gets cloudflare=None.
        state = request.app.state
        if not any(
            hasattr(state, name) for name in ("pages_cloudflare", "pages_resolver", "pages_clock")
        ):
            return service
        return PagesSettingsService(
            conn_factory,
            settings=settings,
            storage=storage,
            cloudflare=getattr(state, "pages_cloudflare", None),
            resolver=getattr(state, "pages_resolver", None),
            clock=getattr(state, "pages_clock", None) or (lambda: datetime.now(UTC)),
        )

    @router.get("/settings/pages", response_model=PagesSettingsReadWire)
    async def read_pages_settings(
        request: Request, workspace_id: WorkspaceDep
    ) -> PagesSettingsReadWire:
        return await _service(request).read_with_refresh(workspace_id)

    @router.patch("/settings/pages", response_model=PagesSettingsReadWire)
    async def patch_pages_settings(
        request: Request, workspace_id: WorkspaceDep, body: PagesSettingsPatch
    ) -> PagesSettingsReadWire:
        require_manage_settings(request, allow_local_mutations=allow_local_mutations)
        return await _service(request).update_settings(workspace_id, body)

    @router.post("/settings/pages/favicon", response_model=PagesSettingsReadWire)
    async def upload_favicon(
        request: Request, workspace_id: WorkspaceDep, file: Annotated[UploadFile, File()]
    ) -> PagesSettingsReadWire:
        require_manage_settings(request, allow_local_mutations=allow_local_mutations)
        return await _service(request).store_image(workspace_id, "favicon", file)

    @router.post("/settings/pages/social-preview", response_model=PagesSettingsReadWire)
    async def upload_social_preview(
        request: Request, workspace_id: WorkspaceDep, file: Annotated[UploadFile, File()]
    ) -> PagesSettingsReadWire:
        require_manage_settings(request, allow_local_mutations=allow_local_mutations)
        return await _service(request).store_image(workspace_id, "social_preview", file)

    @router.patch("/settings/pages/system-hostname", response_model=PagesSettingsReadWire)
    async def patch_system_hostname(
        request: Request, workspace_id: WorkspaceDep, body: LabelPatch
    ) -> PagesSettingsReadWire:
        require_manage_settings(request, allow_local_mutations=allow_local_mutations)
        return await _service(request).change_label(workspace_id, body.label)

    @router.post(
        "/settings/pages/custom-hostname", response_model=PagesSettingsReadWire, status_code=201
    )
    async def connect_custom_hostname(
        request: Request, workspace_id: WorkspaceDep, body: ConnectBody
    ) -> PagesSettingsReadWire:
        require_manage_settings(request, allow_local_mutations=allow_local_mutations)
        return await _service(request).connect(workspace_id, body.hostname)

    # "Check now" is a read of the world, not a change to it: membership is enough.
    @router.post("/settings/pages/custom-hostname/check", response_model=PagesSettingsReadWire)
    async def check_custom_hostname(
        request: Request, workspace_id: WorkspaceDep
    ) -> PagesSettingsReadWire:
        return await _service(request).check(workspace_id)

    @router.delete("/settings/pages/custom-hostname", status_code=204)
    async def remove_custom_hostname(request: Request, workspace_id: WorkspaceDep) -> Response:
        require_manage_settings(request, allow_local_mutations=allow_local_mutations)
        await _service(request).remove(workspace_id)
        return Response(status_code=204)

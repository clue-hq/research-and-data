"""Settings → Pages control plane (custom-domain publishing §7): page defaults, the Clue address
label, and (Task 8) connecting / checking / removing ONE customer hostname.

Everything here is workspace-scoped by the router's own dependency; every *write* additionally
requires ``workspace.manage_settings`` (clue_auth policy revision 3 — admins and owners), checked
route-side so an unauthorised caller never reaches the DAL.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from clue_api.auth_wiring import principal_from_request
from clue_api.cloudflare_custom_hostnames import CloudflareCustomHostnames
from clue_api.dns_observe import DnsResolver, PublicDnsResolver
from clue_api.frontend_read.accounts_list import WireModel
from clue_api.frontend_read.app import WorkspaceDep
from clue_config import Secrets, Settings
from clue_db import ConnFactory
from clue_design.storage import register_design_bytes
from clue_obs import get_logger
from clue_spine.hostnames import (
    HostnameRefused,
    get_custom_hostname,
    public_origin,
    replace_system_label,
    system_hostname,
)
from clue_spine.pages_settings import UNSET, Unset, get_pages_settings, update_pages_settings
from clue_storage import StorageBackend, content_address

log = get_logger("clue_api.frontend_read.settings_pages")

FAVICON_TYPES = {"image/png", "image/x-icon", "image/vnd.microsoft.icon", "image/svg+xml"}
SOCIAL_TYPES = {"image/png", "image/jpeg"}
FAVICON_MAX = 256 * 1024
SOCIAL_MAX = 2 * 1024 * 1024


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
        return await _service(request).read(workspace_id)  # Task 8 switches to read_with_refresh

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

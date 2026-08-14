"""Replay-safe Insight Health onboarding fixture for authenticated browser acceptance.

The production Home surface assumes onboarding has already created a Clue user, an active
workspace membership, a brand, and at least one product. Browser acceptance needs those durable
rows. The base fixture stops there; the project-bound extension materializes the recorded official
site output that real onboarding would have produced, while deliberately stopping before ICP
synthesis, confirmation, discovery, or research. Both paths are tied to one verified Clerk subject.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.client_context_binding import bind_workspace_client
from clue_api.trial.discovery_fixture import (
    HOME_URL,
    SOURCE_KEY,
    OfficialSiteFixtureResolver,
    capture_insight_health_pages,
    claim_sources_for_pages,
    recorded_insight_health_pages,
)
from clue_auth.store import (
    create_platform_user,
    create_workspace_membership,
    get_auth_identity,
    get_platform_user,
    get_workspace_membership,
    link_auth_identity,
)
from clue_core import (
    AccountStatus,
    EntityId,
    EntityType,
    OnboardingInputId,
    OnboardingInputKind,
    RunId,
)
from clue_research.claimstore import load_core_pack
from clue_research.icp import load_starter_packs
from clue_research.identity import insert_account_entity, resolve_alias
from clue_research.sources import (
    bind_resolver,
    get_resolver,
    is_resolver_bound,
    seed_source_manifests,
    unbind_resolver,
)
from clue_research.stage0 import (
    ClientInput,
    get_onboarding_input,
    load_client_knowledge_pack,
    load_icp_feedback_pack,
    read_client_kb_claims,
    reverse_profile,
    submit_onboarding_input,
)
from clue_spine import (
    confirm_project_product,
    create_brand,
    create_product,
    create_workspace,
    get_brand,
    get_product,
    get_project,
    get_workspace,
)
from clue_storage import StorageBackend

WORKSPACE_ID = "ws_fixture_insight_health_browser"
BRAND_ID = "brd_fixture_insight_health_browser"
PRODUCT_ID = "prd_fixture_insight_health_aura_browser"

WORKSPACE_NAME = "Insight Health"
BRAND_NAME = "Insight Health"
PRODUCT_NAME = "Aura AI"
PRODUCT_ALIASES = ("Aura", "Aura AI Scribe")
BROWSER_ONBOARDING_FIXTURE_VERSION = "insight-health-browser-onboarding@1"
BROWSER_STAGE0_RUN_ID = RunId(
    uuid5(NAMESPACE_URL, "clue://fixtures/insight-health-browser/stage0-run")
)


class BrowserFixtureConflict(RuntimeError):
    """A stable fixture id already points at incompatible durable state."""


class InsightHealthBrowserFixtureResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    brand_id: str
    product_id: str
    user_id: str
    auth_identity_id: str
    membership_id: str
    provider_key: str
    provider_subject: str
    role_key: str


class InsightHealthProjectBindingResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    user_id: str
    membership_id: str
    project_id: str
    product_id: str
    client_entity_id: str
    onboarding_input_id: str


class InsightHealthBrowserOnboardingResult(InsightHealthProjectBindingResult):
    model_config = ConfigDict(frozen=True, extra="forbid")

    client_kb_version: int
    stage0_run_id: str
    website_onboarding_input_id: str
    client_claim_ids: dict[str, str]
    artifact_keys_by_url: dict[str, str]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BrowserFixtureConflict(message)


async def seed_insight_health_browser_fixture(
    conn: AsyncConnection,
    *,
    provider_subject: str,
    display_name: str | None = None,
    provider_key: str = "clerk",
) -> InsightHealthBrowserFixtureResult:
    """Provision one authenticated GTM lead without seeding any Stage-0 output.

    Replaying the same provider subject returns the same identity, membership, workspace, brand,
    and product. A stable id that names different state fails loudly instead of being repurposed.
    """

    subject = provider_subject.strip()
    provider = provider_key.strip()
    if not subject or not provider:
        raise ValueError("provider_key and provider_subject must be non-empty")

    workspace = await get_workspace(conn, WORKSPACE_ID)
    if workspace is None:
        workspace = await create_workspace(
            conn,
            workspace_id=WORKSPACE_ID,
            name=WORKSPACE_NAME,
        )
    _require(
        workspace.name == WORKSPACE_NAME and workspace.status == "active",
        "the Insight Health browser workspace id names incompatible state",
    )

    identity = await get_auth_identity(
        conn,
        provider_key=provider,
        provider_subject=subject,
    )
    if identity is None:
        user = await create_platform_user(conn, display_name=display_name)
        identity = await link_auth_identity(
            conn,
            user_id=user.user_id,
            provider_key=provider,
            provider_subject=subject,
        )
    else:
        existing_user = await get_platform_user(conn, identity.user_id)
        _require(identity.status == "active", "the browser auth identity is not active")
        _require(
            existing_user is not None and existing_user.status == "active",
            "the browser user is not active",
        )
        assert existing_user is not None
        user = existing_user

    membership = await get_workspace_membership(
        conn,
        workspace_id=workspace.workspace_id,
        user_id=user.user_id,
    )
    if membership is None:
        membership = await create_workspace_membership(
            conn,
            workspace_id=workspace.workspace_id,
            user_id=user.user_id,
            role_key="owner",
        )
    _require(
        membership.status == "active" and membership.role_key == "owner",
        "the browser identity has an incompatible Insight Health membership",
    )

    brand = await get_brand(conn, workspace_id=workspace.workspace_id, brand_id=BRAND_ID)
    if brand is None:
        brand = await create_brand(
            conn,
            workspace_id=workspace.workspace_id,
            brand_id=BRAND_ID,
            name=BRAND_NAME,
        )
    _require(
        brand.workspace_id == workspace.workspace_id and brand.name == BRAND_NAME,
        "the Insight Health browser brand id names incompatible state",
    )

    product = await get_product(conn, PRODUCT_ID)
    if product is None:
        product = await create_product(
            conn,
            workspace_id=workspace.workspace_id,
            brand_id=brand.brand_id,
            product_id=PRODUCT_ID,
            name=PRODUCT_NAME,
            aliases=PRODUCT_ALIASES,
        )
    _require(
        product.workspace_id == workspace.workspace_id
        and product.brand_id == brand.brand_id
        and product.name == PRODUCT_NAME
        and product.aliases == PRODUCT_ALIASES
        and product.status == "active",
        "the Insight Health browser product id names incompatible state",
    )

    # These are registry/config rows, not Stage-0 results. Production onboarding establishes them
    # before interview routing; without them the human-interview source correctly fails closed on
    # the otherwise-valid ``client`` field class.
    await load_core_pack(conn)
    await load_client_knowledge_pack(conn)
    await load_starter_packs(conn)
    await load_icp_feedback_pack(conn)
    await seed_source_manifests(conn)

    return InsightHealthBrowserFixtureResult(
        workspace_id=workspace.workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        user_id=user.user_id,
        auth_identity_id=identity.auth_identity_id,
        membership_id=membership.membership_id,
        provider_key=identity.provider_key,
        provider_subject=identity.provider_subject,
        role_key=membership.role_key,
    )


async def bind_insight_health_client_to_project(
    conn: AsyncConnection,
    *,
    provider_subject: str,
    project_id: str,
    display_name: str | None = None,
    provider_key: str = "clerk",
) -> InsightHealthProjectBindingResult:
    """Attach onboarding's client identity result to one signed-in user's project.

    The fixture establishes the same account-wide binding as production onboarding. It also
    appends a content-identical project input with the trusted client/product pins as immutable
    statement/evidence provenance; production identity resolution never infers from that row.
    """

    fixture = await seed_insight_health_browser_fixture(
        conn,
        provider_subject=provider_subject,
        display_name=display_name,
        provider_key=provider_key,
    )
    project = await get_project(conn, project_id)
    _require(
        project is not None
        and project.workspace_id == fixture.workspace_id
        and project.brand_id == fixture.brand_id,
        "the requested project is not an Insight Health project owned by this fixture workspace",
    )
    assert project is not None
    confirmed_project = await confirm_project_product(
        conn,
        workspace_id=fixture.workspace_id,
        project_id=project.project_id,
        product_id=fixture.product_id,
    )
    _require(
        confirmed_project is not None,
        "the Insight Health product could not be bound to the project",
    )
    assert confirmed_project is not None
    project = confirmed_project

    client_entity_id = await resolve_alias(
        conn,
        "insighthealth.ai",
        EntityType.ACCOUNT,
        workspace_id=fixture.workspace_id,
    )
    if client_entity_id is None:
        client_entity_id = await insert_account_entity(
            conn,
            canonical_name="Insight Health",
            primary_domain="insighthealth.ai",
            aliases=("Insight Health AI",),
            status=AccountStatus.ACTIVE,
            workspace_id=fixture.workspace_id,
        )
    await bind_workspace_client(
        conn,
        workspace_id=fixture.workspace_id,
        client_entity_id=client_entity_id,
    )

    binding_id = OnboardingInputId(
        uuid5(
            NAMESPACE_URL,
            f"clue://fixtures/insight-health-browser/{project.project_id}/client-binding",
        )
    )
    existing_binding = await get_onboarding_input(
        conn,
        binding_id,
        workspace_id=fixture.workspace_id,
    )
    if existing_binding is not None:
        _require(
            existing_binding.project_id == project.project_id
            and existing_binding.product_id == fixture.product_id
            and existing_binding.client_entity_id == client_entity_id
            and existing_binding.actor == "human",
            "the project onboarding binding replayed with incompatible identity context",
        )
        return InsightHealthProjectBindingResult(
            workspace_id=fixture.workspace_id,
            user_id=fixture.user_id,
            membership_id=fixture.membership_id,
            project_id=project.project_id,
            product_id=fixture.product_id,
            client_entity_id=str(UUID(str(client_entity_id))),
            onboarding_input_id=str(binding_id),
        )

    captured = (
        (
            await conn.execute(
                text(
                    """
                SELECT id, artifact_key, content_sha256, source_ref
                FROM onboarding_input
                WHERE workspace_id = :workspace_id
                  AND project_id = :project_id
                  AND kind = 'user_turn'
                  AND actor = 'human'
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
                ),
                {"workspace_id": fixture.workspace_id, "project_id": project.project_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    _require(captured is not None, "the project has no captured human onboarding turn to bind")
    assert captured is not None

    binding = await submit_onboarding_input(
        conn,
        workspace_id=fixture.workspace_id,
        brand_id=fixture.brand_id,
        product_id=fixture.product_id,
        project_id=project.project_id,
        client_entity_id=client_entity_id,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=str(captured["artifact_key"]),
        content_sha256=str(captured["content_sha256"]),
        source_ref=(None if captured["source_ref"] is None else str(captured["source_ref"])),
        actor="human",
        onboarding_input_id=binding_id,
    )
    stored = await get_onboarding_input(
        conn,
        binding.onboarding_input_id,
        workspace_id=fixture.workspace_id,
    )
    _require(
        stored is not None
        and stored.project_id == project.project_id
        and stored.product_id == fixture.product_id
        and stored.client_entity_id == client_entity_id
        and stored.actor == "human",
        "the project onboarding binding replayed with incompatible identity context",
    )

    return InsightHealthProjectBindingResult(
        workspace_id=fixture.workspace_id,
        user_id=fixture.user_id,
        membership_id=fixture.membership_id,
        project_id=project.project_id,
        product_id=fixture.product_id,
        client_entity_id=str(UUID(str(client_entity_id))),
        onboarding_input_id=str(binding.onboarding_input_id),
    )


async def seed_insight_health_browser_onboarding_result(
    conn: AsyncConnection,
    *,
    provider_subject: str,
    project_id: str,
    storage: StorageBackend,
    display_name: str | None = None,
    provider_key: str = "clerk",
) -> InsightHealthBrowserOnboardingResult:
    """Materialize the official-site Client KB that onboarding would have produced.

    The result remains before ICP synthesis and confirmation. Replays reuse one stable Stage-0 run,
    the same captured page artifacts, the same Client-KB claims, and one append-only website-input
    receipt tied to the authenticated user's existing project.
    """

    binding = await bind_insight_health_client_to_project(
        conn,
        provider_subject=provider_subject,
        project_id=project_id,
        display_name=display_name,
        provider_key=provider_key,
    )
    pages = recorded_insight_health_pages()
    claim_sources = claim_sources_for_pages(pages)
    artifact_keys = await capture_insight_health_pages(
        conn,
        pages=pages,
        storage=storage,
        workspace_id=binding.workspace_id,
        fixture_version=BROWSER_ONBOARDING_FIXTURE_VERSION,
    )

    prior_resolver = get_resolver(SOURCE_KEY) if is_resolver_bound(SOURCE_KEY) else None
    bind_resolver(
        SOURCE_KEY,
        OfficialSiteFixtureResolver(
            sources=claim_sources,
            artifact_keys_by_url=artifact_keys,
            run_id=BROWSER_STAGE0_RUN_ID,
        ),
    )
    try:
        profile = await reverse_profile(
            conn,
            ClientInput(name=WORKSPACE_NAME, website=HOME_URL),
            workspace_id=binding.workspace_id,
            run_id=BROWSER_STAGE0_RUN_ID,
            budget_cap_cents=Decimal("20"),
            product_id=binding.product_id,
            max_source_tier=2,
        )
    finally:
        if prior_resolver is None:
            unbind_resolver(SOURCE_KEY)
        else:
            bind_resolver(SOURCE_KEY, prior_resolver)

    _require(
        profile.ref.client_entity_id == EntityId(UUID(binding.client_entity_id)),
        "reverse profiling resolved a different Insight Health client entity",
    )
    website_input_id = OnboardingInputId(
        uuid5(
            NAMESPACE_URL,
            f"clue://fixtures/insight-health-browser/{project_id}/website-input",
        )
    )
    home_sha256 = hashlib.sha256(pages[HOME_URL].markdown.encode("utf-8")).hexdigest()
    existing_website_input = await get_onboarding_input(
        conn,
        website_input_id,
        workspace_id=binding.workspace_id,
    )
    if existing_website_input is None:
        website_input_ref = await submit_onboarding_input(
            conn,
            workspace_id=binding.workspace_id,
            brand_id=BRAND_ID,
            product_id=binding.product_id,
            project_id=binding.project_id,
            client_entity_id=profile.ref.client_entity_id,
            kind=OnboardingInputKind.WEBSITE,
            artifact_key=artifact_keys[HOME_URL],
            content_sha256=home_sha256,
            source_ref=HOME_URL,
            actor="human",
            onboarding_input_id=website_input_id,
        )
        website_input = await get_onboarding_input(
            conn,
            website_input_ref.onboarding_input_id,
            workspace_id=binding.workspace_id,
        )
    else:
        website_input = existing_website_input
    _require(
        website_input is not None
        and website_input.project_id == binding.project_id
        and website_input.product_id == binding.product_id
        and website_input.client_entity_id == profile.ref.client_entity_id
        and website_input.source_ref == HOME_URL
        and website_input.actor == "human",
        "the website onboarding receipt replayed with incompatible project context",
    )
    assert website_input is not None

    claims = await read_client_kb_claims(
        conn,
        profile.ref.client_entity_id,
        workspace_id=binding.workspace_id,
        version=profile.ref.client_kb_version,
        product_id=binding.product_id,
    )
    _require(
        set(claims) == set(claim_sources),
        "the browser Client KB does not match the recorded official-site evidence",
    )
    return InsightHealthBrowserOnboardingResult(
        **binding.model_dump(),
        client_kb_version=profile.ref.client_kb_version,
        stage0_run_id=str(BROWSER_STAGE0_RUN_ID),
        website_onboarding_input_id=str(website_input.id),
        client_claim_ids={field_key: str(claim.id) for field_key, claim in claims.items()},
        artifact_keys_by_url=artifact_keys,
    )

"""m12_3 handoff_event outbox

Revision ID: ebba8073cc2a
Revises: 9666e86a6e9a
Create Date: 2026-06-25 01:13:54.167247+00:00

M12.3 adds the **``handoff_event`` outbox** — the durable emit/notify path to the content layer
(overview §2/§3 ``→ [ Content layer → Design subsystem ]``; the WS-C M12 table the phase-3
pre-flight
assigns to M12.3). When an account reaches the ``handoff`` phase (Doc C §4) the subsystem emits one
row carrying everything a consumer needs to fetch the assembled object — ``(campaign_run_id,
account_entity_id, icp_spec_version, icp_key, handoff_ref)`` — so a content-layer consumer can
**pull**
(poll the outbox over the read API) or be **pushed** to via a ``HandoffPublisher``.

This is a **one-directional** seam (research → content): no content/design write ever flows back
through it into the claim store (substrate §5c / conventions §6 — "never write-through it").
Postgres
stays the only source of truth; the outbox is the durable record of intent, the push is best-effort
on top of it.

Emission is **idempotent on ``(campaign_run_id, account_entity_id, icp_spec_version, icp_key)``** (a
unique scope key, ``ON CONFLICT DO NOTHING``) so a re-entered handoff phase / crash-resume never
double-emits (mirrors the campaign-phase idempotency on ``(campaign_run, phase)``, Doc C §4 / M7.4).
``status`` is a ``text`` delivery-lifecycle column (``pending``/``delivered``/``failed``) guarded by
a
``CHECK`` (an operational lifecycle, not a ``core.enums`` domain enum — kept aligned to
``narrative.HandoffEventStatus`` by a drift test), with a CHECK that ``delivered_at`` is set iff
``delivered``.

``downgrade()`` drops the table (CI runs up → down → up). No enum type, no trigger, no ``claim``
ALTER
— this is a brand-new side table, not a change to any frozen contract (``core/handoff.py``
untouched).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ebba8073cc2a"
down_revision: str | None = "9666e86a6e9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE handoff_event (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_run_id   uuid NOT NULL,
            account_entity_id uuid NOT NULL,
            icp_spec_version  int NOT NULL,
            icp_key           text NOT NULL DEFAULT '',
            client_id         text NOT NULL,
            handoff_ref       text NOT NULL,
            schema_version    text NOT NULL,
            status            text NOT NULL DEFAULT 'pending',
            emitted_at        timestamptz NOT NULL DEFAULT now(),
            delivered_at      timestamptz,

            CONSTRAINT handoff_event_icp_version_positive CHECK (icp_spec_version >= 1),
            CONSTRAINT handoff_event_status_valid
                CHECK (status IN ('pending', 'delivered', 'failed')),
            CONSTRAINT handoff_event_delivered_iff
                CHECK ((status = 'delivered') = (delivered_at IS NOT NULL))
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE handoff_event IS 'M12.3 durable emit/notify outbox (overview §3): one "
        "row per account reaching the handoff phase, carrying (campaign_run_id, account_entity_id, "
        "icp_spec_version, icp_key, handoff_ref) so the content layer can pull/be-pushed the "
        "assembled handoff. One-directional (research->content); never a write-back path "
        "(conventions §6). Idempotent on the scope key.'"
    )
    # Idempotency key: re-emitting the same (run, account, icp segment) is a no-op (ON CONFLICT DO
    # NOTHING). icp_key is the ICP segment (D5: icp_spec_version restarts at 1 per icp_key).
    op.execute(
        "CREATE UNIQUE INDEX handoff_event_scope "
        "ON handoff_event (campaign_run_id, account_entity_id, icp_spec_version, icp_key)"
    )
    # Pull surface: a consumer polls a run's events (optionally by delivery status).
    op.execute("CREATE INDEX handoff_event_run_status ON handoff_event (campaign_run_id, status)")
    # Tenant scoping: a client only ever reads its own events (substrate §2).
    op.execute("CREATE INDEX handoff_event_client ON handoff_event (client_id)")

    # M12.3 also extends the M12.2 account_handoff materialisation (additive, never contradicting):
    #  * tier — the account's research tier (M6 two-pass), stamped by the emit path from the
    #    account_run so the list endpoint can filter "by tier" (spec §M12.3 list deliverable);
    #    nullable (a handoff materialised outside the emit path has an unknown tier).
    #  * the (client_id, campaign_run_id) composite index — the tenant-scoped list-serve query
    #    (handoff_store.list_handoffs_for_run filters on BOTH columns), so the planner satisfies the
    #    multi-tenant list at the index level rather than scanning a run's rows across tenants.
    op.execute("ALTER TABLE account_handoff ADD COLUMN tier text")
    op.execute(
        "CREATE INDEX account_handoff_client_run ON account_handoff (client_id, campaign_run_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS account_handoff_client_run")
    op.execute("ALTER TABLE account_handoff DROP COLUMN IF EXISTS tier")
    op.execute("DROP INDEX IF EXISTS handoff_event_client")
    op.execute("DROP INDEX IF EXISTS handoff_event_run_status")
    op.execute("DROP INDEX IF EXISTS handoff_event_scope")
    op.execute("DROP TABLE IF EXISTS handoff_event")

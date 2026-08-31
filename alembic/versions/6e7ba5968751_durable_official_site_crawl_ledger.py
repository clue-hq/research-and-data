"""Durable provider-neutral Stage-0 official-site crawl ledger.

Revision ID: 6e7ba5968751
Revises: da5f3fe5a90f
Create Date: 2026-08-14

C1 of ``FI-stage0-durable-official-site-crawl-plan.md``. PostgreSQL is both the frontier and
ledger. Every child relationship is run- and workspace-local, page ownership is generation
fenced, provider dispatch is durable, URL-level snapshots retain provenance even when artifacts
deduplicate by content, and corpus checkpoints are immutable verified snapshot sets.

Hand-written and reversible. The crawl enums use constrained text, matching repository style.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "6e7ba5968751"
down_revision: str | None = "da5f3fe5a90f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ``recon_run`` predates workspace-scoped composite children. C1 is its first such child.
    op.create_unique_constraint("recon_run_scope_anchor", "recon_run", ["id", "workspace_id"])

    op.execute(
        """
        CREATE TABLE official_site_crawl_run (
            id                          uuid PRIMARY KEY,
            workspace_id                text NOT NULL,
            brand_id                    text NOT NULL,
            client_entity_id            uuid,
            recon_run_id                uuid NOT NULL,
            root_discovered_url          text NOT NULL,
            root_fetch_key               text NOT NULL,
            allowed_registrable_domain   text NOT NULL,
            status                      text NOT NULL DEFAULT 'queued',
            max_graph_depth             smallint NOT NULL DEFAULT 2,
            fast_claim_deadline_at       timestamptz NOT NULL,
            overall_page_ceiling        integer NOT NULL,
            fast_page_ceiling           integer NOT NULL,
            provider_policy_version      text NOT NULL,
            url_policy_version           text NOT NULL,
            robots_policy_version        text NOT NULL,
            config_json                  jsonb NOT NULL,
            failure_code                 text,
            created_at                   timestamptz NOT NULL DEFAULT now(),
            updated_at                   timestamptz NOT NULL DEFAULT now(),
            completed_at                 timestamptz,
            failed_at                    timestamptz,
            cancelled_at                 timestamptz,

            CONSTRAINT official_site_crawl_run_scope_anchor UNIQUE (id, workspace_id),
            CONSTRAINT official_site_crawl_run_recon_once UNIQUE (workspace_id, recon_run_id),
            CONSTRAINT official_site_crawl_run_brand_fk
                FOREIGN KEY (brand_id, workspace_id)
                REFERENCES brand (brand_id, workspace_id),
            CONSTRAINT official_site_crawl_run_client_fk
                FOREIGN KEY (client_entity_id, workspace_id)
                REFERENCES account_entity (id, workspace_id),
            CONSTRAINT official_site_crawl_run_recon_fk
                FOREIGN KEY (recon_run_id, workspace_id)
                REFERENCES recon_run (id, workspace_id),
            CONSTRAINT official_site_crawl_run_status CHECK (status IN (
                'queued', 'fast_active', 'fast_closing', 'fast_complete',
                'background_active', 'completed', 'failed', 'cancelled'
            )),
            CONSTRAINT official_site_crawl_run_depth_two CHECK (max_graph_depth = 2),
            CONSTRAINT official_site_crawl_run_page_ceilings CHECK (
                overall_page_ceiling > 0 AND fast_page_ceiling > 0
                AND fast_page_ceiling <= overall_page_ceiling
            ),
            CONSTRAINT official_site_crawl_run_config_object
                CHECK (jsonb_typeof(config_json) = 'object'),
            CONSTRAINT official_site_crawl_run_terminal_coherent CHECK (
                (status = 'completed' AND completed_at IS NOT NULL
                    AND failed_at IS NULL AND cancelled_at IS NULL AND failure_code IS NULL)
                OR (status = 'failed' AND failed_at IS NOT NULL
                    AND completed_at IS NULL AND cancelled_at IS NULL AND failure_code IS NOT NULL)
                OR (status = 'cancelled' AND cancelled_at IS NOT NULL
                    AND completed_at IS NULL AND failed_at IS NULL)
                OR (status NOT IN ('completed', 'failed', 'cancelled')
                    AND completed_at IS NULL AND failed_at IS NULL AND cancelled_at IS NULL
                    AND failure_code IS NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX official_site_crawl_run_schedule "
        "ON official_site_crawl_run (status, fast_claim_deadline_at, created_at, id)"
    )
    op.execute(
        "CREATE INDEX official_site_crawl_run_workspace "
        "ON official_site_crawl_run (workspace_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX official_site_crawl_run_host "
        "ON official_site_crawl_run (allowed_registrable_domain, status)"
    )

    op.execute(
        """
        CREATE TABLE official_site_crawl_page (
            id                           uuid PRIMARY KEY,
            workspace_id                 text NOT NULL,
            crawl_run_id                 uuid NOT NULL,
            fetch_key                    text NOT NULL,
            fetch_key_hash               text NOT NULL,
            representative_requested_url text NOT NULL,
            host                         text NOT NULL,
            graph_depth                  smallint,
            priority                     integer NOT NULL,
            priority_reason_json          jsonb NOT NULL DEFAULT '[]'::jsonb,
            eligibility                  text NOT NULL,
            state                        text NOT NULL DEFAULT 'discovered',
            lease_owner                  text,
            lease_generation             bigint NOT NULL DEFAULT 0,
            lease_acquired_at             timestamptz,
            lease_expires_at              timestamptz,
            attempt_count                integer NOT NULL DEFAULT 0,
            expanded_min_depth            smallint,
            next_attempt_at               timestamptz,
            latest_snapshot_id            uuid,
            terminal_reason               text,
            discovered_at                 timestamptz NOT NULL DEFAULT now(),
            queued_at                     timestamptz,
            fetched_at                    timestamptz,
            updated_at                    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT official_site_crawl_page_scope_anchor UNIQUE (id, workspace_id),
            CONSTRAINT official_site_crawl_page_run_anchor
                UNIQUE (id, crawl_run_id, workspace_id),
            CONSTRAINT official_site_crawl_page_run_fk
                FOREIGN KEY (crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_run (id, workspace_id),
            CONSTRAINT official_site_crawl_page_fetch_identity
                UNIQUE (crawl_run_id, fetch_key_hash, fetch_key),
            CONSTRAINT official_site_crawl_page_fetch_hash
                CHECK (fetch_key_hash ~ '^[0-9a-f]{64}$'),
            CONSTRAINT official_site_crawl_page_depths CHECK (
                (graph_depth IS NULL OR graph_depth BETWEEN 0 AND 2)
                AND (expanded_min_depth IS NULL OR expanded_min_depth BETWEEN 0 AND 2)
            ),
            CONSTRAINT official_site_crawl_page_nonnegative CHECK (
                priority >= 0 AND lease_generation >= 0 AND attempt_count >= 0
            ),
            CONSTRAINT official_site_crawl_page_reasons_array
                CHECK (jsonb_typeof(priority_reason_json) = 'array'),
            CONSTRAINT official_site_crawl_page_eligibility CHECK (
                eligibility IN ('fast', 'background', 'both', 'refused')
            ),
            CONSTRAINT official_site_crawl_page_state CHECK (state IN (
                'discovered', 'queued', 'leased', 'provider_started',
                'reconciliation_pending', 'persistence_pending', 'retry_wait',
                'fetched', 'failed', 'quarantined', 'refused'
            )),
            CONSTRAINT official_site_crawl_page_lease_shape CHECK (
                (state IN ('leased', 'provider_started')
                    AND lease_owner IS NOT NULL AND lease_acquired_at IS NOT NULL
                    AND lease_expires_at IS NOT NULL)
                OR (state IN ('reconciliation_pending', 'persistence_pending') AND (
                    (lease_owner IS NULL AND lease_acquired_at IS NULL AND lease_expires_at IS NULL)
                    OR (lease_owner IS NOT NULL AND lease_acquired_at IS NOT NULL
                        AND lease_expires_at IS NOT NULL)
                ))
                OR (state NOT IN (
                    'leased', 'provider_started', 'reconciliation_pending', 'persistence_pending'
                ) AND lease_owner IS NULL AND lease_acquired_at IS NULL
                    AND lease_expires_at IS NULL)
            ),
            CONSTRAINT official_site_crawl_page_lease_times CHECK (
                lease_expires_at IS NULL OR lease_expires_at > lease_acquired_at
            ),
            CONSTRAINT official_site_crawl_page_terminal_coherent CHECK (
                (state = 'fetched' AND fetched_at IS NOT NULL AND latest_snapshot_id IS NOT NULL
                    AND terminal_reason IS NULL AND next_attempt_at IS NULL)
                OR (state IN ('failed', 'quarantined', 'refused')
                    AND fetched_at IS NULL AND terminal_reason IS NOT NULL
                    AND next_attempt_at IS NULL)
                OR (state = 'retry_wait' AND fetched_at IS NULL AND latest_snapshot_id IS NULL
                    AND terminal_reason IS NULL AND next_attempt_at IS NOT NULL)
                OR (state NOT IN ('fetched', 'failed', 'quarantined', 'refused', 'retry_wait')
                    AND fetched_at IS NULL AND latest_snapshot_id IS NULL
                    AND terminal_reason IS NULL AND next_attempt_at IS NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX official_site_crawl_page_claim ON official_site_crawl_page "
        "(crawl_run_id, state, eligibility, priority, graph_depth, discovered_at, id) "
        "WHERE state IN ('queued', 'retry_wait')"
    )
    op.execute(
        "CREATE INDEX official_site_crawl_page_host_capacity "
        "ON official_site_crawl_page (host, state, lease_expires_at)"
    )
    op.execute(
        "CREATE INDEX official_site_crawl_page_reclaim "
        "ON official_site_crawl_page (state, lease_expires_at) "
        "WHERE state IN ('leased', 'provider_started', 'reconciliation_pending', "
        "'persistence_pending')"
    )
    op.execute(
        "CREATE INDEX official_site_crawl_page_progress "
        "ON official_site_crawl_page (workspace_id, crawl_run_id, state)"
    )

    op.execute(
        """
        CREATE TABLE official_site_url_observation (
            id                uuid PRIMARY KEY,
            workspace_id      text NOT NULL,
            crawl_run_id      uuid NOT NULL,
            page_id           uuid,
            parser_replay_key text NOT NULL,
            discovered_url    text NOT NULL,
            discovered_via    text NOT NULL,
            source_page_id    uuid,
            graph_depth       smallint,
            link_text_bounded text,
            sitemap_url       text,
            observed_at       timestamptz NOT NULL DEFAULT now(),
            policy_outcome    text NOT NULL,
            policy_reason     text,

            CONSTRAINT official_site_url_observation_run_fk
                FOREIGN KEY (crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_run (id, workspace_id),
            CONSTRAINT official_site_url_observation_page_fk
                FOREIGN KEY (page_id, crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_page (id, crawl_run_id, workspace_id),
            CONSTRAINT official_site_url_observation_source_page_fk
                FOREIGN KEY (source_page_id, crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_page (id, crawl_run_id, workspace_id),
            CONSTRAINT official_site_url_observation_replay
                UNIQUE (crawl_run_id, parser_replay_key),
            CONSTRAINT official_site_url_observation_origin CHECK (
                discovered_via IN ('root', 'link', 'sitemap', 'redirect', 'canonical')
            ),
            CONSTRAINT official_site_url_observation_policy CHECK (
                policy_outcome IN ('admitted', 'refused')
            ),
            CONSTRAINT official_site_url_observation_sitemap_depth CHECK (
                discovered_via <> 'sitemap' OR graph_depth IS NULL
            ),
            CONSTRAINT official_site_url_observation_depth CHECK (
                graph_depth IS NULL OR graph_depth BETWEEN 0 AND 2
            ),
            CONSTRAINT official_site_url_observation_link_text CHECK (
                link_text_bounded IS NULL OR length(link_text_bounded) <= 500
            ),
            CONSTRAINT official_site_url_observation_admitted_page CHECK (
                policy_outcome <> 'admitted' OR page_id IS NOT NULL
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX official_site_url_observation_page "
        "ON official_site_url_observation (crawl_run_id, page_id, observed_at)"
    )
    op.execute(
        "CREATE INDEX official_site_url_observation_origin_idx "
        "ON official_site_url_observation (crawl_run_id, discovered_via)"
    )

    op.execute(
        """
        CREATE TABLE official_site_link_edge (
            id             uuid PRIMARY KEY,
            workspace_id   text NOT NULL,
            crawl_run_id   uuid NOT NULL,
            from_page_id   uuid NOT NULL,
            to_page_id     uuid NOT NULL,
            discovered_url text NOT NULL,
            link_relation  text NOT NULL,
            observed_at    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT official_site_link_edge_run_fk
                FOREIGN KEY (crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_run (id, workspace_id),
            CONSTRAINT official_site_link_edge_from_fk
                FOREIGN KEY (from_page_id, crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_page (id, crawl_run_id, workspace_id),
            CONSTRAINT official_site_link_edge_to_fk
                FOREIGN KEY (to_page_id, crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_page (id, crawl_run_id, workspace_id),
            CONSTRAINT official_site_link_edge_relation CHECK (
                link_relation IN ('anchor', 'redirect', 'canonical_hint')
            ),
            CONSTRAINT official_site_link_edge_unique UNIQUE (
                crawl_run_id, from_page_id, to_page_id, discovered_url, link_relation
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX official_site_link_edge_from "
        "ON official_site_link_edge (crawl_run_id, from_page_id)"
    )
    op.execute(
        "CREATE INDEX official_site_link_edge_to "
        "ON official_site_link_edge (crawl_run_id, to_page_id)"
    )

    op.execute(
        """
        CREATE TABLE official_site_fetch_attempt (
            id                      uuid PRIMARY KEY,
            workspace_id            text NOT NULL,
            crawl_run_id            uuid NOT NULL,
            page_id                 uuid NOT NULL,
            attempt_number          integer NOT NULL,
            lease_generation        bigint NOT NULL,
            worker_id               text NOT NULL,
            operation_key           text NOT NULL,
            provider_key            text NOT NULL,
            state                   text NOT NULL DEFAULT 'prepared',
            provider_request_id     text,
            provider_receipt_json   jsonb,
            requested_url           text NOT NULL,
            final_url               text,
            redirect_chain_json     jsonb NOT NULL DEFAULT '[]'::jsonb,
            provider_status         text,
            http_status             integer,
            media_type              text,
            size_bytes              bigint,
            cost_cents              numeric,
            cost_kind               text NOT NULL DEFAULT 'none',
            spend_status            text NOT NULL DEFAULT 'no_spend',
            retry_class             text,
            artifact_key            text,
            content_sha256          text,
            started_at              timestamptz NOT NULL DEFAULT now(),
            dispatched_at           timestamptz,
            provider_completed_at   timestamptz,
            persisted_at            timestamptz,
            finished_at             timestamptz,

            CONSTRAINT official_site_fetch_attempt_scope_anchor UNIQUE (id, workspace_id),
            CONSTRAINT official_site_fetch_attempt_snapshot_anchor
                UNIQUE (id, crawl_run_id, page_id, workspace_id),
            CONSTRAINT official_site_fetch_attempt_run_fk
                FOREIGN KEY (crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_run (id, workspace_id),
            CONSTRAINT official_site_fetch_attempt_page_fk
                FOREIGN KEY (page_id, crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_page (id, crawl_run_id, workspace_id),
            CONSTRAINT official_site_fetch_attempt_artifact_fk
                FOREIGN KEY (artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT official_site_fetch_attempt_operation UNIQUE (operation_key),
            CONSTRAINT official_site_fetch_attempt_number UNIQUE (page_id, attempt_number),
            CONSTRAINT official_site_fetch_attempt_state CHECK (state IN (
                'prepared', 'dispatched', 'provider_succeeded', 'persisted',
                'retryable_no_spend', 'failed', 'spend_unknown', 'reconciled_no_spend',
                'reconciled_succeeded', 'quarantined'
            )),
            CONSTRAINT official_site_fetch_attempt_cost_kind CHECK (
                cost_kind IN ('actual', 'estimated', 'none')
            ),
            CONSTRAINT official_site_fetch_attempt_spend_status CHECK (
                spend_status IN ('spend_confirmed', 'spend_unknown', 'no_spend')
            ),
            CONSTRAINT official_site_fetch_attempt_retry_class CHECK (
                retry_class IS NULL OR retry_class IN (
                    'success', 'retryable_no_spend', 'permanent', 'robots_refused',
                    'policy_refused', 'ambiguous'
                )
            ),
            CONSTRAINT official_site_fetch_attempt_positive CHECK (
                attempt_number > 0 AND lease_generation > 0
                AND (size_bytes IS NULL OR size_bytes >= 0)
                AND (cost_cents IS NULL OR cost_cents >= 0)
            ),
            CONSTRAINT official_site_fetch_attempt_hash CHECK (
                content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT official_site_fetch_attempt_json_shapes CHECK (
                jsonb_typeof(redirect_chain_json) = 'array'
                AND (provider_receipt_json IS NULL
                    OR jsonb_typeof(provider_receipt_json) = 'object')
            ),
            CONSTRAINT official_site_fetch_attempt_dispatch_coherent CHECK (
                (state = 'prepared' AND dispatched_at IS NULL)
                OR (state = 'failed')
                OR (state NOT IN ('prepared', 'failed') AND dispatched_at IS NOT NULL)
            ),
            CONSTRAINT official_site_fetch_attempt_provider_success CHECK (
                state NOT IN ('provider_succeeded', 'persisted', 'reconciled_succeeded')
                OR (provider_completed_at IS NOT NULL AND final_url IS NOT NULL
                    AND provider_status IS NOT NULL AND media_type IS NOT NULL
                    AND size_bytes IS NOT NULL AND retry_class = 'success')
            ),
            CONSTRAINT official_site_fetch_attempt_persisted CHECK (
                state <> 'persisted'
                OR (artifact_key IS NOT NULL AND content_sha256 IS NOT NULL
                    AND size_bytes IS NOT NULL AND media_type IS NOT NULL
                    AND persisted_at IS NOT NULL AND finished_at IS NOT NULL)
            ),
            CONSTRAINT official_site_fetch_attempt_spend_unknown CHECK (
                state <> 'spend_unknown'
                OR (spend_status = 'spend_unknown'
                    AND retry_class = 'ambiguous')
            ),
            CONSTRAINT official_site_fetch_attempt_cost_coherent CHECK (
                (cost_kind = 'none' AND cost_cents IS NULL)
                OR (cost_kind IN ('actual', 'estimated') AND cost_cents IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX official_site_fetch_attempt_page "
        "ON official_site_fetch_attempt (page_id, attempt_number DESC)"
    )
    op.execute(
        "CREATE INDEX official_site_fetch_attempt_reconcile "
        "ON official_site_fetch_attempt (state, dispatched_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX official_site_fetch_attempt_provider_receipt "
        "ON official_site_fetch_attempt (provider_key, provider_request_id) "
        "WHERE provider_request_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX official_site_fetch_attempt_spend_audit "
        "ON official_site_fetch_attempt (workspace_id, spend_status, started_at)"
    )

    op.execute(
        """
        CREATE TABLE official_site_page_snapshot (
            id                    uuid PRIMARY KEY,
            workspace_id          text NOT NULL,
            crawl_run_id          uuid NOT NULL,
            page_id               uuid NOT NULL,
            fetch_attempt_id      uuid NOT NULL,
            requested_url         text NOT NULL,
            final_url             text NOT NULL,
            redirect_chain_json   jsonb NOT NULL DEFAULT '[]'::jsonb,
            fetched_at            timestamptz NOT NULL,
            provider_key          text NOT NULL,
            provider_request_id   text,
            http_status           integer,
            media_type            text NOT NULL,
            artifact_key          text NOT NULL,
            content_sha256        text NOT NULL,
            size_bytes            bigint NOT NULL,
            robots_decision_ref   text NOT NULL,
            policy_version        text NOT NULL,
            created_at            timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT official_site_page_snapshot_scope_anchor UNIQUE (id, workspace_id),
            CONSTRAINT official_site_page_snapshot_page_anchor
                UNIQUE (id, page_id, crawl_run_id, workspace_id),
            CONSTRAINT official_site_page_snapshot_run_fk
                FOREIGN KEY (crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_run (id, workspace_id),
            CONSTRAINT official_site_page_snapshot_page_fk
                FOREIGN KEY (page_id, crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_page (id, crawl_run_id, workspace_id),
            CONSTRAINT official_site_page_snapshot_attempt_fk
                FOREIGN KEY (fetch_attempt_id, crawl_run_id, page_id, workspace_id)
                REFERENCES official_site_fetch_attempt (id, crawl_run_id, page_id, workspace_id),
            CONSTRAINT official_site_page_snapshot_artifact_fk
                FOREIGN KEY (artifact_key, workspace_id)
                REFERENCES artifact (storage_key, workspace_id),
            CONSTRAINT official_site_page_snapshot_attempt_once UNIQUE (fetch_attempt_id),
            CONSTRAINT official_site_page_snapshot_hash
                CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT official_site_page_snapshot_size CHECK (size_bytes >= 0),
            CONSTRAINT official_site_page_snapshot_http CHECK (
                http_status IS NULL OR http_status BETWEEN 100 AND 599
            ),
            CONSTRAINT official_site_page_snapshot_redirects_array
                CHECK (jsonb_typeof(redirect_chain_json) = 'array')
        )
        """
    )
    op.execute(
        "CREATE INDEX official_site_page_snapshot_page "
        "ON official_site_page_snapshot (crawl_run_id, page_id, fetched_at DESC)"
    )
    op.execute(
        "CREATE INDEX official_site_page_snapshot_content "
        "ON official_site_page_snapshot (workspace_id, content_sha256)"
    )
    op.execute(
        "CREATE INDEX official_site_page_snapshot_artifact "
        "ON official_site_page_snapshot (artifact_key)"
    )
    op.execute(
        """
        ALTER TABLE official_site_crawl_page
            ADD CONSTRAINT official_site_crawl_page_latest_snapshot_fk
            FOREIGN KEY (latest_snapshot_id, id, crawl_run_id, workspace_id)
            REFERENCES official_site_page_snapshot (id, page_id, crawl_run_id, workspace_id)
            DEFERRABLE INITIALLY DEFERRED
        """
    )

    op.execute(
        """
        CREATE TABLE official_site_alias_observation (
            id                    uuid PRIMARY KEY,
            workspace_id          text NOT NULL,
            crawl_run_id          uuid NOT NULL,
            source_page_id        uuid NOT NULL,
            alias_url             text NOT NULL,
            kind                  text NOT NULL,
            verification_status   text NOT NULL DEFAULT 'observed',
            target_page_id        uuid,
            observed_at           timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT official_site_alias_observation_run_fk
                FOREIGN KEY (crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_run (id, workspace_id),
            CONSTRAINT official_site_alias_observation_source_fk
                FOREIGN KEY (source_page_id, crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_page (id, crawl_run_id, workspace_id),
            CONSTRAINT official_site_alias_observation_target_fk
                FOREIGN KEY (target_page_id, crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_page (id, crawl_run_id, workspace_id),
            CONSTRAINT official_site_alias_observation_kind CHECK (
                kind IN ('redirect', 'canonical_hint')
            ),
            CONSTRAINT official_site_alias_observation_status CHECK (
                verification_status IN (
                    'observed', 'verified_same_content', 'verified_redirect',
                    'rejected_external', 'conflicting'
                )
            ),
            CONSTRAINT official_site_alias_observation_unique
                UNIQUE (crawl_run_id, source_page_id, alias_url, kind),
            CONSTRAINT official_site_alias_observation_external CHECK (
                verification_status <> 'rejected_external' OR target_page_id IS NULL
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX official_site_alias_observation_target "
        "ON official_site_alias_observation (crawl_run_id, target_page_id)"
    )
    op.execute(
        "CREATE INDEX official_site_alias_observation_status_idx "
        "ON official_site_alias_observation (crawl_run_id, verification_status)"
    )

    op.execute(
        """
        CREATE TABLE official_site_corpus_checkpoint (
            id                   uuid PRIMARY KEY,
            workspace_id         text NOT NULL,
            crawl_run_id         uuid NOT NULL,
            phase                text NOT NULL,
            version              integer NOT NULL,
            snapshot_ids_json    jsonb NOT NULL,
            snapshot_set_sha256  text NOT NULL,
            coverage_json        jsonb NOT NULL,
            created_at           timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT official_site_corpus_checkpoint_scope_anchor
                UNIQUE (id, workspace_id),
            CONSTRAINT official_site_corpus_checkpoint_run_fk
                FOREIGN KEY (crawl_run_id, workspace_id)
                REFERENCES official_site_crawl_run (id, workspace_id),
            CONSTRAINT official_site_corpus_checkpoint_version
                UNIQUE (crawl_run_id, phase, version),
            CONSTRAINT official_site_corpus_checkpoint_phase
                CHECK (phase IN ('fast', 'background')),
            CONSTRAINT official_site_corpus_checkpoint_version_positive CHECK (version > 0),
            CONSTRAINT official_site_corpus_checkpoint_hash
                CHECK (snapshot_set_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT official_site_corpus_checkpoint_json_shapes CHECK (
                jsonb_typeof(snapshot_ids_json) = 'array'
                AND jsonb_typeof(coverage_json) = 'object'
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX official_site_corpus_checkpoint_latest "
        "ON official_site_corpus_checkpoint (crawl_run_id, phase, version DESC)"
    )
    op.execute(
        "CREATE INDEX official_site_corpus_checkpoint_workspace "
        "ON official_site_corpus_checkpoint (workspace_id, created_at DESC)"
    )

    op.execute(
        r"""
        CREATE FUNCTION official_site_validate_corpus_checkpoint() RETURNS trigger AS $$
        DECLARE
            canonical_json jsonb;
            canonical_payload text;
            valid_snapshot_count bigint;
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM jsonb_array_elements(NEW.snapshot_ids_json) AS item(value)
                WHERE jsonb_typeof(item.value) <> 'string'
                   OR trim(both '"' from item.value::text) !~
                        '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            ) THEN
                RAISE EXCEPTION 'checkpoint snapshot IDs must be lowercase UUID strings';
            END IF;

            SELECT COALESCE(jsonb_agg(value ORDER BY value), '[]'::jsonb),
                   '[' || COALESCE(string_agg(to_json(value)::text, ',' ORDER BY value), '') || ']'
              INTO canonical_json, canonical_payload
              FROM (
                  SELECT DISTINCT value
                  FROM jsonb_array_elements_text(NEW.snapshot_ids_json) AS ids(value)
              ) AS canonical_ids;

            IF NEW.snapshot_ids_json <> canonical_json THEN
                RAISE EXCEPTION 'checkpoint snapshot IDs must be unique and lexically sorted';
            END IF;

            SELECT count(*)
              INTO valid_snapshot_count
              FROM official_site_page_snapshot snapshot
              JOIN artifact captured
                ON captured.storage_key = snapshot.artifact_key
               AND captured.workspace_id = snapshot.workspace_id
             WHERE snapshot.workspace_id = NEW.workspace_id
               AND snapshot.crawl_run_id = NEW.crawl_run_id
               AND captured.erased_at IS NULL
               AND snapshot.id::text IN (
                   SELECT value
                   FROM jsonb_array_elements_text(NEW.snapshot_ids_json) AS ids(value)
               );

            IF valid_snapshot_count <> jsonb_array_length(NEW.snapshot_ids_json) THEN
                RAISE EXCEPTION 'checkpoint contains absent, erased, or cross-scope snapshot';
            END IF;

            NEW.snapshot_set_sha256 := encode(
                sha256(convert_to(canonical_payload, 'UTF8')),
                'hex'
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER official_site_corpus_checkpoint_validate "
        "BEFORE INSERT ON official_site_corpus_checkpoint "
        "FOR EACH ROW EXECUTE FUNCTION official_site_validate_corpus_checkpoint()"
    )
    op.execute(
        """
        CREATE FUNCTION official_site_reject_checkpoint_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'official_site_corpus_checkpoint is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER official_site_corpus_checkpoint_append_only "
        "BEFORE UPDATE ON official_site_corpus_checkpoint "
        "FOR EACH ROW EXECUTE FUNCTION official_site_reject_checkpoint_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER official_site_corpus_checkpoint_append_only "
        "ON official_site_corpus_checkpoint"
    )
    op.execute("DROP FUNCTION official_site_reject_checkpoint_mutation()")
    op.execute(
        "DROP TRIGGER official_site_corpus_checkpoint_validate ON official_site_corpus_checkpoint"
    )
    op.execute("DROP FUNCTION official_site_validate_corpus_checkpoint()")
    op.execute("DROP TABLE official_site_corpus_checkpoint")
    op.execute("DROP TABLE official_site_alias_observation")
    op.drop_constraint(
        "official_site_crawl_page_latest_snapshot_fk",
        "official_site_crawl_page",
        type_="foreignkey",
    )
    op.execute("DROP TABLE official_site_page_snapshot")
    op.execute("DROP TABLE official_site_fetch_attempt")
    op.execute("DROP TABLE official_site_link_edge")
    op.execute("DROP TABLE official_site_url_observation")
    op.execute("DROP TABLE official_site_crawl_page")
    op.execute("DROP TABLE official_site_crawl_run")
    op.drop_constraint("recon_run_scope_anchor", "recon_run", type_="unique")

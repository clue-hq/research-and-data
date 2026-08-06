"""M6A D0 — the discovery-envelope field definitions against the real registry validator."""

from __future__ import annotations

import pytest

from clue_research.claimstore import ValueSchemaError, get_field, validate_value

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_discovery_envelope_fields_load_and_validate_in_real_postgres_registry() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            expected = {
                "core.company_linkedin_url",
                "core.industry",
                "core.employee_range",
                "core.hq_location",
                "core.annual_revenue",
                "core.revenue_band",
                "core.company_email",
                "core.company_phone",
            }
            for field_key in expected:
                assert await get_field(conn, field_key) is not None

            await validate_value(
                conn,
                "core.employee_range",
                {"label": "11-50", "min": 11, "max": 50},
            )
            await validate_value(
                conn,
                "core.hq_location",
                {
                    "raw": "Denver, Colorado, United States",
                    "city": "Denver",
                    "region": "Colorado",
                    "country_code": "US",
                },
            )
            await validate_value(
                conn,
                "core.annual_revenue",
                {
                    "amount": 12500000,
                    "currency": "USD",
                    "as_of": "2025-12-31",
                    "estimate_kind": "provider_estimate",
                },
            )
            await validate_value(conn, "core.revenue_band", "10m_50m")

            with pytest.raises(ValueSchemaError, match="missing required key 'label'"):
                await validate_value(conn, "core.employee_range", {"min": 11, "max": 50})
            with pytest.raises(ValueSchemaError, match="not one of"):
                await validate_value(
                    conn,
                    "core.annual_revenue",
                    {
                        "amount": 12500000,
                        "currency": "USD",
                        "as_of": "2025-12-31",
                        "estimate_kind": "reported_or_maybe_estimated",
                    },
                )
            with pytest.raises(ValueSchemaError, match="not one of"):
                await validate_value(conn, "core.revenue_band", "unknown")

    run_async(_run())

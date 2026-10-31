"""Shared fixtures for the spend tests that touch the database or Sentry.

The claim-store harness and the incident tests' Sentry capture live in sibling packages; a fixture
is only visible to a module that imports it, so they are re-exported here once.
"""

from tests.api.test_provider_incidents_db import StubTransport, sentry  # noqa: F401
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
)

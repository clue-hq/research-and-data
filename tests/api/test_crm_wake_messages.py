"""What a paused write batch tells the agent (live check L13, R-11.10).

A reconnect always creates a new connection, and Clue never sends a change on another
connection, so the paused wake must not tell the agent the changes carry on by themselves after
an expired connection — the agent repeated that promise to the person in the live check.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from clue_api.crm.connections import CrmConnection
from clue_api.crm.wake import crm_writes_paused_message
from clue_api.crm.write_executor import _expired_reason
from clue_api.crm.writes import WriteCounts


def _counts() -> WriteCounts:
    return WriteCounts(done=0, failed=0, skipped=0, not_chosen=0, waiting=1)


def test_an_expired_connection_promises_no_resume() -> None:
    connection = CrmConnection(
        connection_id=uuid4(),
        workspace_id="ws_test",
        provider="hubspot",
        composio_connected_account_id="ca_test",
        composio_auth_config_id="ac_test",
        status="expired",
        connected_by_user_id="usr_test",
        connected_at=datetime.now(UTC),
    )
    reason, next_step = _expired_reason(connection)
    message = crm_writes_paused_message(uuid4(), _counts(), reason=reason, next_step=next_step)
    assert "continue by themselves" not in message
    assert "works again" not in message
    assert "not sent" in message and "propose" in message


SENTENCE = "They continue by themselves when Salesforce's daily API allowance allows it again."


def test_a_budget_pause_says_when_it_carries_on() -> None:
    message = crm_writes_paused_message(
        uuid4(),
        _counts(),
        reason="Salesforce's daily API allowance for Clue is used up",
        next_step=SENTENCE,
    )
    assert SENTENCE in message

"""The canonical human action receipt — ``turn-action:<turn_id>`` (Lane D charter §3-P2).

A human gate (directive confirmation, budget approval, a tier checkpoint) may only be satisfied by
*an actual thing the user did*. The durable record of that act already exists: the ``agent_turn``
row the surface persisted, together with its captured ``onboarding_input`` and the artifact holding
the exact bytes the user sent. This module gives that act one **opaque** client-facing name and one
server-side resolution of it.

Two halves, deliberately separate:

* :func:`derive_turn_action_ref` is the single authority for the *format*. The engine mints the ref
  from a turn id it already trusts (:mod:`clue_api.turn_binding` serves it to tools as
  ``source_turn_ref``; the C5 seam stamps it as the ambient ``ToolContext.action_ref``). Nothing
  else in the platform may spell this string by hand.
* :func:`resolve_turn_action` is the *verification*: given a ref that arrived from anywhere, prove
  it names a real human turn of **this** workspace, that the turn's captured message still agrees
  with its artifact, that the turn carries an internal submitter, and that the acting principal is
  that submitter. Anything short of all four is a typed refusal — Lane B ruling 10 (deny by
  default): a missing turn, a cross-workspace ref, a failed integrity join, a NULL submitter, or a
  different actor never yields a receipt.

The ref grammar is closed on purpose: an exact ``turn-action:`` prefix followed by the canonical
text of one UUID. There is no client-extensible grammar, no query part, and no second flavour — so
a caller cannot smuggle scope, a subject, or a decision into the reference itself.

The artifact/capture triple is *derivation evidence*, never the client-facing reference (charter
§3-P2): a caller says ``turn-action:<turn_id>`` and the server re-derives everything else.

Gate-answer resolution — the charter's ``agent_gate`` leg, where the receipt proves *which gate*
the human answered — is **D4's**, and lands as a second resolver over the durable gate/answer
records. It is not built here: a gate answer is a different durable object with its own
addressee/decision rules, and stubbing it now would invite callers to treat a turn receipt as gate
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from clue_core import OnboardingInputKind
from clue_db import ConnFactory, transaction

__all__ = [
    "ACTOR_MISMATCH",
    "CAPTURE_DIGEST_MISMATCH",
    "CAPTURE_NOT_FOUND",
    "MESSAGE_REF_MISSING",
    "PROJECT_SCOPE_MISSING",
    "REF_MALFORMED",
    "SUBMITTER_MISSING",
    "TURN_ACTION_PREFIX",
    "TURN_NOT_FOUND",
    "ResolvedTurnAction",
    "TurnActionUnresolvable",
    "derive_turn_action_ref",
    "parse_turn_action_ref",
    "resolve_turn_action",
]

#: The one prefix. Opaque to clients: it is matched exactly, never parsed for meaning by a caller.
TURN_ACTION_PREFIX = "turn-action:"

#: Reason codes. Stable and machine-readable — a surface renders them, tests assert them, and each
#: names exactly one thing that failed, so "deny by default" never collapses into one mystery code.
#: The ref is not ``turn-action:<canonical uuid>``.
REF_MALFORMED = "turn_action_ref_malformed"
#: No such turn *in this workspace*. A cross-workspace ref lands here too — existence is not leaked.
TURN_NOT_FOUND = "turn_action_turn_not_found"
#: The turn has no project scope, so its human capture cannot be resolved fail-closed.
PROJECT_SCOPE_MISSING = "turn_action_project_scope_missing"
#: The turn persisted no ``user_message`` artifact ref, so there are no bytes to verify.
MESSAGE_REF_MISSING = "turn_action_message_ref_missing"
#: The turn's message is not a human-captured onboarding input of the turn's project.
CAPTURE_NOT_FOUND = "turn_action_capture_not_found"
#: The capture record and the turn's artifact ref record different digests.
CAPTURE_DIGEST_MISMATCH = "turn_action_capture_digest_mismatch"
#: The turn carries no internal submitter (Lane B §7 requires user *and* membership before enqueue).
SUBMITTER_MISSING = "turn_action_submitter_missing"
#: The acting principal is not the user whose turn this is.
ACTOR_MISMATCH = "turn_action_actor_mismatch"


class TurnActionUnresolvable(ValueError):
    """This reference does not prove a human action, so no gated effect may cite it.

    ``reason_code`` is the stable vocabulary above; the message is for humans and never quotes the
    turn's bytes.
    """

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class ResolvedTurnAction:
    """A proven human action: who acted, in which workspace, over which captured bytes."""

    action_ref: str
    turn_id: str
    workspace_id: str
    submitted_by_user_id: str
    submitted_via_membership_id: str
    onboarding_input_id: str
    sha256: str


def derive_turn_action_ref(turn_id: UUID | str) -> str:
    """Mint the canonical action ref for a turn the engine already trusts.

    Accepts the :class:`~uuid.UUID` the turn substrate uses and the string form a durable row hands
    back; both produce the identical canonical text, so a ref minted at the tool seam and one minted
    from a persisted row are the same string.
    """

    if isinstance(turn_id, UUID):
        return f"{TURN_ACTION_PREFIX}{turn_id}"
    value = turn_id.strip()
    if not value:
        raise ValueError("a turn action ref cannot be derived from an empty turn id")
    return f"{TURN_ACTION_PREFIX}{_canonical_uuid(value)}"


def parse_turn_action_ref(ref: str) -> UUID:
    """Refuse anything that is not exactly ``turn-action:<canonical uuid>``.

    Canonical is load-bearing: ``{...}``, ``urn:uuid:…``, upper case, and the dashless spelling all
    parse as the same UUID in Python, and accepting them would give one action several names — a
    replay/audit hazard, and the beginning of a grammar clients extend.
    """

    if not ref.startswith(TURN_ACTION_PREFIX):
        raise TurnActionUnresolvable(
            "an action reference must be an opaque turn-action reference",
            reason_code=REF_MALFORMED,
        )
    return UUID(_canonical_uuid(ref[len(TURN_ACTION_PREFIX) :]))


def _canonical_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise TurnActionUnresolvable(
            "a turn-action reference must name one turn by its canonical identifier",
            reason_code=REF_MALFORMED,
        ) from exc
    if str(parsed) != value:
        raise TurnActionUnresolvable(
            "a turn-action reference must spell its turn identifier canonically",
            reason_code=REF_MALFORMED,
        )
    return str(parsed)


_TURN_QUERY = text(
    """
    SELECT t.id AS turn_id,
           t.project_id,
           t.submitted_by_user_id,
           t.submitted_via_membership_id,
           r.artifact_key,
           r.artifact_sha256
    FROM agent_turn t
    LEFT JOIN agent_artifact_ref r
      ON r.owner_kind = 'turn'
     AND r.owner_id = t.id
     AND r.ref_role = 'user_message'
     AND r.ordinal = 0
     AND r.workspace_id = t.workspace_id
    WHERE t.id = :turn_id AND t.workspace_id = :workspace_id
    """
)


async def resolve_turn_action(
    ref: str,
    *,
    workspace_id: str,
    actor_id: str,
    conn_factory: ConnFactory = transaction,
) -> ResolvedTurnAction:
    """Prove one action reference, or refuse it with a stable reason code.

    Resolution is a pure read: it mutates nothing, so resolving the same ref twice returns the same
    identity (replay-safe by construction — a receipt is evidence, not a state transition).

    The workspace scope is the caller's authorized workspace, never a value read out of the ref, and
    it is applied in SQL: a ref minted in another workspace is simply not found here.
    """

    # ``turn_binding`` owns the human-capture integrity join and depends on *this* module for the
    # canonical ref format, so the borrow is imported here rather than at module scope: one
    # direction of the pair has to be late, and a human gate resolves far more rarely than a turn
    # binds.
    from clue_api.turn_binding import CAPTURE_NOT_FOUND as BINDER_CAPTURE_NOT_FOUND
    from clue_api.turn_binding import CapturedTurnUnavailable, load_human_capture

    turn_id = parse_turn_action_ref(ref)
    if not workspace_id.strip():
        raise TurnActionUnresolvable(
            "a turn action resolves only inside an authorized workspace",
            reason_code=TURN_NOT_FOUND,
        )
    if not actor_id.strip():
        raise TurnActionUnresolvable(
            "a turn action resolves only for an authenticated principal",
            reason_code=ACTOR_MISMATCH,
        )
    async with conn_factory() as conn:
        row = (
            (
                await conn.execute(
                    _TURN_QUERY,
                    {"turn_id": turn_id, "workspace_id": workspace_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise TurnActionUnresolvable(
                "no such turn in this workspace",
                reason_code=TURN_NOT_FOUND,
            )
        project_id = row["project_id"]
        if project_id is None:
            raise TurnActionUnresolvable(
                "the turn carries no project scope, so its capture cannot be resolved",
                reason_code=PROJECT_SCOPE_MISSING,
            )
        artifact_key = row["artifact_key"]
        digest = row["artifact_sha256"]
        if artifact_key is None or digest is None:
            raise TurnActionUnresolvable(
                "the turn persisted no user message, so there is nothing to verify",
                reason_code=MESSAGE_REF_MISSING,
            )
        try:
            captured = await load_human_capture(
                conn,
                workspace_id=workspace_id,
                project_id=str(project_id),
                artifact_key=str(artifact_key),
                digest=str(digest),
                kind=OnboardingInputKind.USER_TURN,
            )
        except CapturedTurnUnavailable as exc:
            raise TurnActionUnresolvable(
                str(exc),
                reason_code=(
                    CAPTURE_NOT_FOUND
                    if exc.reason_code == BINDER_CAPTURE_NOT_FOUND
                    else CAPTURE_DIGEST_MISMATCH
                ),
            ) from exc
    submitted_by = row["submitted_by_user_id"]
    submitted_via = row["submitted_via_membership_id"]
    if submitted_by is None or submitted_via is None:
        raise TurnActionUnresolvable(
            "the turn records no internal submitter, so it proves no human action",
            reason_code=SUBMITTER_MISSING,
        )
    if str(submitted_by) != actor_id:
        raise TurnActionUnresolvable(
            "the acting principal did not submit this turn",
            reason_code=ACTOR_MISMATCH,
        )
    return ResolvedTurnAction(
        action_ref=derive_turn_action_ref(turn_id),
        turn_id=str(turn_id),
        workspace_id=workspace_id,
        submitted_by_user_id=str(submitted_by),
        submitted_via_membership_id=str(submitted_via),
        onboarding_input_id=str(captured.id),
        sha256=str(digest),
    )

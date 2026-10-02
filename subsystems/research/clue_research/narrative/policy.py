"""The positioning step's config-as-data (M12.1, policy-as-data — conventions §2).

The DB half of the prompt-as-data split (the code half — the system prompt + per-persona angle
templates — is :mod:`clue_research.narrative.prompts`). A :class:`PositioningPolicy` is a
versioned, per-client-overridable row in ``positioning_policy``: the gateway ``narrative_model``
id, the ``prompt_version``, the coverage thresholds, and the **field-relevance map** (which
verified account fields feed which persona). Swapping any of these is a config change, never code
— so a model swap, a prompt bump, or re-pointing a persona's lens at different evidence is a row
edit (M12.1 AC8).

The loader mirrors :func:`clue_research.verification.faithfulness.load_judge_policy` exactly:
most-specific scope (per-client → global) wins, latest ``version`` with a deterministic
``created_at`` / ``policy_id`` tie-break, fail-soft to :data:`DEFAULT_POSITIONING_POLICY` when no
row matches; a ``prompt_version`` not registered in ``narrative.prompts.PROMPTS`` degrades to the
default with a logged warning (a stale config row never raises per-account mid-run).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config.gateway import DEFAULT_GATEWAY_CONFIG
from clue_core import Persona, decode_jsonb
from clue_obs.otel import get_logger
from clue_research.narrative.prompts import PROMPT_VERSION, PROMPTS

_log = get_logger(__name__)

# The narrative-relevant verified account fields (CORE_PACK; substrate §8 / Doc C §2). The
# positioner reads these via the merge view (verified-only) as the account side of every argument.
ACCOUNT_OPERATIONAL_PAIN = "account.operational_pain"
ACCOUNT_STRATEGIC_MOVES = "account.strategic_moves"
ACCOUNT_RESONANCE_CULTURE = "account.resonance.culture"

# Which account fields feed which persona's argument (substrate §7 — the economic buyer argues ROI
# from pain+moves; the technical evaluator argues fit from culture+moves; the two cite *different*
# evidence, which is what makes their narratives genuinely distinct — M12.1 AC3). Config, not code:
# the DB row's ``field_relevance`` jsonb overrides this default.
DEFAULT_FIELD_RELEVANCE: dict[Persona, tuple[str, ...]] = {
    Persona.CHAMPION: (ACCOUNT_OPERATIONAL_PAIN, ACCOUNT_RESONANCE_CULTURE),
    Persona.ECONOMIC_BUYER: (ACCOUNT_OPERATIONAL_PAIN, ACCOUNT_STRATEGIC_MOVES),
    Persona.TECHNICAL_EVALUATOR: (ACCOUNT_RESONANCE_CULTURE, ACCOUNT_STRATEGIC_MOVES),
    Persona.BLOCKER: (ACCOUNT_OPERATIONAL_PAIN, ACCOUNT_STRATEGIC_MOVES),
    Persona.USER: (ACCOUNT_OPERATIONAL_PAIN, ACCOUNT_RESONANCE_CULTURE),
}

# All account fields any persona may read — the batch the positioner fetches once per account.
NARRATIVE_ACCOUNT_FIELDS: tuple[str, ...] = tuple(
    sorted({f for fields in DEFAULT_FIELD_RELEVANCE.values() for f in fields})
)


class PositioningPolicy(BaseModel):
    """The positioning config as data (policy-as-data). Persisted as typed columns + a
    ``field_relevance`` jsonb in ``positioning_policy`` (per-client overridable); the positioner
    reads it at construction. Swapping the model / prompt / thresholds / relevance map is config.

    * ``narrative_model`` — the gateway model id the positioner calls (defaults to the shared
      gateway *synthesis* model, since positioning IS grounded synthesis — so the two never
      drift).
    * ``prompt_version`` — which versioned ``narrative.prompts.PROMPTS`` entry + angle templates
      to use (stamped on each narrative's ``value_json`` lineage).
    * ``min_account_evidence`` / ``min_client_chunks`` — the floor of *both-sided* grounding an
      argument needs (M12.1 AC1: ≥1 account-evidence AND ≥1 client-knowledge id, else a coverage
      gap).
    * ``retrieval_limit`` — client-knowledge passages retrieved per persona.
    * ``max_evidence_chars`` — cap on the assembled ``evidence_span`` the faithfulness judge sees.
    * ``field_relevance`` — persona → account field keys (the distinct-evidence map; M12.1 AC3).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    narrative_model: str = DEFAULT_GATEWAY_CONFIG.synthesis_model
    prompt_version: str = PROMPT_VERSION
    min_account_evidence: int = Field(default=1, ge=1)
    min_client_chunks: int = Field(default=1, ge=1)
    retrieval_limit: int = Field(default=8, ge=1)
    max_evidence_chars: int = Field(default=4000, ge=1)
    field_relevance: dict[Persona, tuple[str, ...]] = DEFAULT_FIELD_RELEVANCE
    version: int = Field(default=1, ge=1)

    def fields_for(self, persona: Persona) -> tuple[str, ...]:
        """The account fields feeding ``persona``'s argument (empty if the persona is unmapped)."""
        return self.field_relevance.get(persona, ())


DEFAULT_POSITIONING_POLICY = PositioningPolicy()


def _parse_field_relevance(raw: object) -> dict[Persona, tuple[str, ...]]:
    """Parse the ``field_relevance`` jsonb into a typed ``{persona: (field_key, ...)}`` map.

    Tolerates the column arriving as a dict (decoded jsonb) or a JSON string / bytes. An unknown
    persona key or a non-list value is skipped with a warning (a stale/typo'd config row degrades
    to the known-good subset rather than raising mid-run). Returns the default map if nothing
    parses.
    """
    try:
        decoded = decode_jsonb(raw)
    except ValueError:
        _log.warning("positioning_policy field_relevance is not valid JSON; using default")
        return DEFAULT_FIELD_RELEVANCE
    if not isinstance(decoded, dict):
        return DEFAULT_FIELD_RELEVANCE
    parsed: dict[Persona, tuple[str, ...]] = {}
    for key, value in decoded.items():
        try:
            persona = Persona(key)
        except ValueError:
            _log.warning("positioning_policy field_relevance has unknown persona %r; skipping", key)
            continue
        if not isinstance(value, list) or not all(isinstance(f, str) for f in value):
            _log.warning(
                "positioning_policy field_relevance for %r is not a list[str]; skipping", key
            )
            continue
        parsed[persona] = tuple(value)
    return parsed or DEFAULT_FIELD_RELEVANCE


async def load_positioning_policy(
    conn: AsyncConnection, *, workspace_id: str | None = None
) -> PositioningPolicy:
    """Load the most-specific :class:`PositioningPolicy` for a scope: per-client → global
    default row → :data:`DEFAULT_POSITIONING_POLICY`.

    The latest ``version`` within the matched scope wins (deterministic ``created_at`` /
    ``policy_id`` tie-break). Fail-soft: returns the built-in default when no row matches, and
    degrades an unregistered ``prompt_version`` to the default with a warning.
    """
    candidates: list[str | None] = []
    if workspace_id is not None:
        candidates.append(workspace_id)
    candidates.append(None)  # the global default row

    for scope_client in candidates:
        row = (
            await conn.execute(
                text(
                    """
                    SELECT narrative_model, prompt_version, min_account_evidence, min_client_chunks,
                           retrieval_limit, max_evidence_chars, field_relevance, version
                    FROM positioning_policy
                    WHERE workspace_id IS NOT DISTINCT FROM :workspace_id
                    ORDER BY version DESC, created_at DESC, policy_id DESC
                    LIMIT 1
                    """
                ),
                {"workspace_id": scope_client},
            )
        ).first()
        if row is not None:
            prompt_version = row[1]
            if prompt_version not in PROMPTS:
                _log.warning(
                    "positioning_policy prompt_version %r is not registered in code; "
                    "falling back to %r",
                    prompt_version,
                    DEFAULT_POSITIONING_POLICY.prompt_version,
                )
                prompt_version = DEFAULT_POSITIONING_POLICY.prompt_version
            return PositioningPolicy(
                narrative_model=row[0],
                prompt_version=prompt_version,
                min_account_evidence=max(1, int(row[2])),
                min_client_chunks=max(1, int(row[3])),
                retrieval_limit=max(1, int(row[4])),
                max_evidence_chars=max(1, int(row[5])),
                field_relevance=_parse_field_relevance(row[6]),
                version=int(row[7]),
            )
    return DEFAULT_POSITIONING_POLICY

"""m10.4 three postures as per-client config — client_policy gather/store/override columns

Revision ID: 196d37e4a179
Revises: 8074999828fe
Create Date: 2026-06-25 00:00:00.000000+00:00

M10.4 ships the three deep-research postures (Doc D §6) as per-client config on the *same*
``use_class × jurisdiction`` machinery — **not** permanent forks (Option 1 conservative default,
Option 2 gather-broadly-gate-at-use, Option 3 professional-public-only). M10.3 already built the
``client_policy`` table (posture + the ``allow_map`` / ``regime_overrides`` the gate reads); this
migration adds the **gather/store-side** columns the postures turn on and the legally-reviewed
sensitive-override register — additive ALTERs to the M10-owned ``client_policy`` table (no shared
mutable surface touched):

* ``source_scope`` — the collection-time source-level lever (Doc D §6 Option 3): ``full_sweep``
  (Options 1 & 2 — the full deep sweep, governed at/after extraction by the allow-map) vs
  ``professional_public_only`` (Option 3 — research scoped to professional-public surfaces, the deep
  personal-life dimension never collected). Read by M8 / the M4.6 Source Planner before spend.
* ``store_sensitive`` — the Doc D §4 minimization sub-flag: whether ``sensitive`` (special-category)
  claims are persisted at all. Option 1 (conservative default) and Option 3 do **not** store them
  (minimize retained personal data); Option 2 stores everything (and the gate still locks *use* —
  the M10.3 hard floor). Read by M8 at the contact-claim insert site.
* ``gather_scope`` — an explicit source-key allow-list (jsonb array) the M4.6 planner narrows to
  (empty = no explicit narrowing; ``source_scope`` is then the lever). Future-proofs a fine-grained
  per-client source allow-list on top of the coarse ``source_scope``.
* ``sensitive_overrides`` — the legally-reviewed sensitive-override register (jsonb array of
  ``{field_key, lawful_basis, reviewed_by, note}``). This is the **only** sanctioned relaxation of
  the gate's Art. 9 hard floor (Doc D §4): a specific reviewed exception per field, never a blanket
  config toggle (the M10.3 validator still forbids ``sensitive: usable`` in ``allow_map`` /
  ``regime_overrides``). Default empty → the floor holds.

Defaults match the **Option 1 conservative default** (the platform default for a client with no
posture set, D3): ``full_sweep`` + ``store_sensitive = false`` (minimize) + empty allow-list + empty
override register. A jsonb-typeof CHECK guards each array column (the M9.4 ``binding_policy``
pattern). ``downgrade()`` cleanly drops the four columns (CI runs up → down → up).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "196d37e4a179"
down_revision: str | None = "8074999828fe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The Option-1 conservative default (the platform default; D3): full sweep, do NOT store
    # sensitive (minimize), no explicit source allow-list, no reviewed overrides. NOT NULL with
    # defaults — there are no client_policy rows yet (M10.3 created the table; no writer), so the
    # defaults simply seed the column for future rows.
    op.execute(
        "ALTER TABLE client_policy "
        "ADD COLUMN source_scope text NOT NULL DEFAULT 'full_sweep', "
        "ADD COLUMN store_sensitive boolean NOT NULL DEFAULT false, "
        "ADD COLUMN gather_scope jsonb NOT NULL DEFAULT '[]', "
        "ADD COLUMN sensitive_overrides jsonb NOT NULL DEFAULT '[]'"
    )
    op.execute(
        "ALTER TABLE client_policy "
        "ADD CONSTRAINT client_policy_gather_scope_is_array "
        "CHECK (jsonb_typeof(gather_scope) = 'array'), "
        "ADD CONSTRAINT client_policy_sensitive_overrides_is_array "
        "CHECK (jsonb_typeof(sensitive_overrides) = 'array')"
    )
    op.execute(
        "COMMENT ON COLUMN client_policy.source_scope IS 'M10.4 collection-time source-level scope "
        "(Doc D §6): full_sweep (Options 1/2) vs professional_public_only (Option 3 — deep "
        "personal-life never collected). Read by M8 / the M4.6 planner before spend.'"
    )
    op.execute(
        "COMMENT ON COLUMN client_policy.store_sensitive IS 'M10.4 minimization sub-flag: "
        "whether sensitive (special-category) claims are persisted at all. Option 1/3 = false "
        "(minimize); Option 2 = true (gate still locks use). Read by M8 at the insert site.'"
    )
    op.execute(
        "COMMENT ON COLUMN client_policy.sensitive_overrides IS 'M10.4 legally-reviewed "
        "sensitive-override register (jsonb array of {field_key, lawful_basis, reviewed_by}) — "
        "the ONLY sanctioned relaxation of the gate Art. 9 hard floor (Doc D §4); default empty.'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE client_policy "
        "DROP CONSTRAINT IF EXISTS client_policy_sensitive_overrides_is_array, "
        "DROP CONSTRAINT IF EXISTS client_policy_gather_scope_is_array"
    )
    op.execute(
        "ALTER TABLE client_policy "
        "DROP COLUMN IF EXISTS sensitive_overrides, "
        "DROP COLUMN IF EXISTS gather_scope, "
        "DROP COLUMN IF EXISTS store_sensitive, "
        "DROP COLUMN IF EXISTS source_scope"
    )

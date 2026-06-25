"""M10.4 — the three deep-research postures as per-client config (Doc D §6; D3 default: Option 1).

The three postures are **not permanent forks** (Doc D §6): each is a *preset* over the *same*
``use_class × jurisdiction`` machinery, materialized into a
:class:`~clue_research.compliance.use_gate.ClientPolicy`. A regulated client dials down to Option 3;
an aggressive US client dials up to Option 2 — a config write, never a code path. Crucially the
**use-side is identical for all three** (the conservative allow-map; the gate floors ``sensitive``
regardless): the postures differ only on the **gather/store-side** (Doc D §6), so "what is usable"
is one machinery and the posture is a configuration decision, not a branch.

* **Option 1 — conservative default** (the platform default for a client with no posture set, D3):
  full deep sweep gathered; ``sensitive`` not stored (minimize, Doc D §4) and never usable (gate
  floor). Best risk-adjusted (Doc D §6).
* **Option 2 — gather broadly, gate at use:** same full sweep, ``sensitive`` *stored* (you become a
  controller of special-category data) — but the gate still locks its *use* (the M10.3 hard floor);
  a reviewed ``sensitive_overrides`` entry is the only path to using it.
* **Option 3 — professional-public only:** research scoped to professional-public surfaces
  (``source_scope = professional_public_only``); the deep personal-life dimension is never collected
  and ``sensitive`` is not stored; the use-gate is light.

This module is the **resolution layer**: it maps a :class:`~clue_research.config.Posture` to the
materialized ``ClientPolicy`` via a data table (:data:`POSTURE_PRESETS`), so there is **no
posture-named ``if``/``else``** anywhere in the gate or the collection path — the posture is data,
the gate reads only the materialized parameters. The api root calls
:func:`client_policy_for_posture` (or ``load_client_policy`` for a DB row). Architecture: Doc D §6;
docs/specs/M10-compliance-and-personal-data.md §M10.4.
"""

from __future__ import annotations

from dataclasses import dataclass

from clue_research.compliance.use_gate import ClientPolicy
from clue_research.config import DEFAULT_POSTURE, Posture, SourceScope


@dataclass(frozen=True)
class PosturePreset:
    """The gather/store-side parameters one posture turns on (Doc D §6). The use-side (the allow-map
    + per-regime relaxation) is the conservative default for **every** posture — the gate floors
    ``sensitive`` regardless — so a posture is purely these collection-time settings."""

    source_scope: SourceScope
    store_sensitive: bool


# The posture -> preset table (DATA, not branching): the M10.4 deliverable that postures are
# settings, not forks. Adding/retuning a posture is a row here; nothing in the gate or collection
# code reads a posture name (the no-posture-`if`/`else` acceptance criterion).
POSTURE_PRESETS: dict[Posture, PosturePreset] = {
    # Option 1: full sweep, minimize (do not store sensitive) — the conservative default.
    Posture.CONSERVATIVE_DEFAULT: PosturePreset(
        source_scope=SourceScope.FULL_SWEEP, store_sensitive=False
    ),
    # Option 2: full sweep, store everything incl. sensitive (the gate still locks its use).
    Posture.GATHER_BROADLY_GATE_AT_USE: PosturePreset(
        source_scope=SourceScope.FULL_SWEEP, store_sensitive=True
    ),
    # Option 3: source-scoped to professional-public; personal-life uncollected, sensitive unstored.
    Posture.PROFESSIONAL_PUBLIC_ONLY: PosturePreset(
        source_scope=SourceScope.PROFESSIONAL_PUBLIC_ONLY, store_sensitive=False
    ),
}


def client_policy_for_posture(posture: Posture, *, version: int = 1) -> ClientPolicy:
    """Materialize ``posture`` into a :class:`ClientPolicy` (the conservative use-side + the
    posture's gather/store preset). A pure data lookup — no posture-named branch. The api root calls
    this to resolve a client's policy from its chosen posture; with ``DEFAULT_POSTURE`` it is the
    platform default (equal to ``DEFAULT_CLIENT_POLICY``)."""
    preset = POSTURE_PRESETS[posture]
    return ClientPolicy(
        posture=posture,
        source_scope=preset.source_scope,
        store_sensitive=preset.store_sensitive,
        version=version,
    )


# The platform default for a client with no posture set (D3): Option 1, materialized.
DEFAULT_POSTURE_POLICY = client_policy_for_posture(DEFAULT_POSTURE)

"""Design substrate — the design subsystem's platform-native persistence layer.

Owned by the design-integration master plan, Part II (docs/specs/design-integration-master-plan.md;
implementation contract docs/specs/PD-part2-design-substrate.md). Scaffold (slice D0):
empty-but-contracted — the import rules are live; the ``design_*`` schema DAL lands in slices
D1/D2.

Seam discipline: this package imports only the shared base (clue_core / clue_db / clue_config /
clue_obs / clue_storage) — never another subsystem, never the execution planes. The engine seam
(Rust ``lumen-api-helper``) and the merged design apps live in ``subsystems/clue-design/`` and are
NOT this package; they consume it once they re-enter the uv workspace (slice D2).
"""

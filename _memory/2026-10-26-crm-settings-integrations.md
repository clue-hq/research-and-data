# CRM Settings → Integrations (2026-10-25 → 26)

Branch `feat/crm-settings-integrations` (cut from `c73899926`, unpushed). Plan
`docs/superpowers/plans/2026-10-25-crm-settings-integrations.md`; design Figma
`NcLl2r0dzVDN28xAQCwvM1` section `2308:1590`; rulings R-14.6, R-15.1–R-15.3, R-6.5 note.
SDD ledger: `.superpowers/sdd/2026-10-25-crm-settings-integrations/progress.md` (rulings there).

## Built
- T1 Clue tier → "Clue fit level" (High/Medium/Low); `clue_fields_set_up` gate; Head of ABM v85.
- T2 migration `280cce98bc76` (`external_account_name`, chat-less connect requests), Composio delete.
- T3 `crm/settings_view.py` + `/crm/integration`, `/crm/connect-request`, `/crm/disconnect`,
  `/crm/permissions/{id}/revoke`, `/crm/overwrites` (`tests/api/test_crm_settings_db.py`, 29).
- T4 overwrites `follow_grants` lets a grant cover an overwrite; propose tool counts only overwrites on the card.
- T5 FE data layer (`features/integrations/model/crm-settings.ts`, repository, contract doc,
  fixture env `CLUE_CRM_SETTINGS_FIXTURE=<provider>:<state>[:expired][:member]`, ignored in prod).
- T6 overview + connect dialogs; T7 provider page; T8 `/projects/{id}?prompt=` prefill.
- Live-check fixes: `619b4eb4d` (founder page review + 5 s refresh while preparing), `690f47bdd`
  (allowed card reads Preparing), `48a13caf8` (callback page fills the window).

## Live check
Findings: `docs/superpowers/specs/crm-integration/2026-10-26-settings-integrations-live-check-findings.md`.
Stack DB `clue_nashville_pm` migrated to `280cce98bc76`; stack UP. Conduit HubSpot is now connection
`654f13fc…` (portal 247744687; old `c50cc5ea` disconnected). Two grants were seeded with
`writes.insert_grant` for the revoke test (Garner `607b8b87…` revoked; Conduit `7810c1b0…`
revoked by disconnect). Frontend gate green before the stack started.

## Owed
- Member view (founder testing with a member login), live proof of the 5 s Preparing refresh.
- Whole-branch review; parked minors in the ledger (crmDay dup, revoke copy parses descriptions,
  no hook render tests). Founder questions still open: reconnect to a different portal (design
  says Clue asks; backend switches), member text when nothing is connected.

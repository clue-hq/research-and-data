# ARV2 frontend polish backlog (opened 2026-09-10; NOT to be applied in the R4 session)

Founder ruling 2026-09-10: no frontend change of any kind in R4, including the screens lifted from
the dummy frontend. Suggestions are stored here for a separate polishing session. Each line says
what discovery (R4) already stores so the polish is a display change only.

| # | Suggestion | What the store already has | Where |
|---|---|---|---|
| 1 | A **target-accounts tab beside Gallery** inside a project, listing the project's discovered and approved accounts (the founder's own design intent). | `project_account` rows with `added_via = 'discovered'`; `arv2_discovery_candidate` rows with `decision` | project shell |
| 2 | A **chat gate card** for cohort approval (set-valued, pre-checked = Best fit), the same shape as O6's product-set gate, writing the same `project_account` rows. | candidate rows + verdicts; the gate pattern exists (`open_product_set_selection_gate@1`) | Head of ABM tools + chat card |
| 3 | An **"unclear" tone** on the ICP-qualification badge (today `badge` renders positive only for the literal "High", neutral otherwise). | `client.icp_qualification` value "Unclear" | `accounts-table.tsx` badge tone map |
| 4 | A **"Qualification" section on the account detail** page: one row per hard gate with verdict, reason and source link. | `arv2_discovery_candidate.verdicts_json` (gate, verdict, reason, references) | detail recipes + a registered field per gate |
| 5 | An **Overall-fit filter value for "Unclear"** in the filter panel. | fit score already honest; badge value "Unclear" | `accounts-filter-panel.tsx` |
| 6 | Show the **discovery source** (Websets item URL, the run) as provenance on the account detail rail. | `arv2_discovery_candidate.provider_snapshot_json`, `source` | detail rail |
| 7 | Frontend follow-ups already recorded by O6 (wrapped Knowledge titles visual check; refresh hook arming). | — | see `_memory/2026-09-09-arv2-onboarding-o6-head-of-abm.md` |

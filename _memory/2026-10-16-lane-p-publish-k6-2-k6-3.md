# 2026-10-16 — Lane P: publishing defects K6-2 (Republish) and K6-3 (noindex)

Branch `site/publish-durability` (main checkout). Commits 42f0208ee, be6e928b3, 24cd45774, 58034b515.
Full report: `.superpowers/sdd/2026-10-16-site-publish-durability/lane-publish-report.md`.

- Design API publish state (`_publish_state`) now returns `current_version` and `noindex` in both states;
  `PUT /documents/{id}/web-noindex` + `design_set_web_noindex` accept site documents (scene still 409).
- Chat-born site/web documents for a tagged account are born `web_noindex = true` (design_leg_tools
  `_birth_web_document`), the ABM batch's rule. Existing documents untouched (no migration).
- Share menu: "Changes since you published" + Republish when current version > published doc_version
  (server's or the open site editor's); publish of a site waits for frame typing + saves
  (`SiteSaveController.settled()`, stage `publish.prepare`) and stops with the reason on a failed save;
  "Allow indexing" derived from the durable flag; a changed choice is PUT before the publish.
- Owed: live UI check after a design-API restart (the running :8019 serves the old state body).
- Pre-existing failure seen: `test_write_path_governance::test_converted_domain_mutations_are_only_called_from_the_toolbelt`
  (asset_enrichment.py create_asset_record) — not this lane's.

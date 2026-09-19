# PE15 generated scene asset inspection

Live reference-artwork QA found scene `view(asset:<id>)` unable to inspect newly generated images even though core upserts, saved scene/registry records, placement and source bytes existed. Scene view consulted only frozen brand/library manifests.

After the active run ended, applied the reviewed fallback in `tools/view.py`: preserve kit then library precedence, then read the current scene asset record through the same shared preview resolver/current asset store. Include current scene ids in view discovery. No API/config mutation, global asset lookup, storage scan, engine change or provider call.

Prepared regression evidence: 5 failures/4 passes against the former source; all 9 cases pass with the fix. Tests cover post-start registration, existing manifests, collision precedence, id discovery, current-scene admission, separate workspace stores and thumbnail preference. Compatibility subset: 60 passed. Full runtime suite exited 0; 1657 passed, 7 skipped, counted from its complete pytest progress output. A final focused rerun passed after an import-only test lint cleanup. New-test strict lint and source syntax/name lint passed.

Provider-free applied proof used a workspace/document-scoped read-only DB transaction to load the existing candidate saved scene v34. The actual exposed view tool returned both generated A/B assets with brand/library catalogs absent. Original and thumbnail digests matched stored bytes; emitted 512px pixels matched the expected upscale of each stored 256px thumbnail. Scene and operation ledger were unchanged. Ignored receipt: `.local-setup/ad-control/generated-view-fix/saved-assets-view-receipt.json`; patch/test logs and report alongside it.

This proves the repaired active Python read path against saved real assets, not creative quality or a fresh model run. Root owns service reload/next creative test. No services restarted, providers called, engine rebuilt, remote pushed or unrelated candidate-memory note included.

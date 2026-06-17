---
name: tools
description: The Lumen deepagent's function surface — every tool the coordinator can call, what it returns, whether it mutates the scene, and which loop step it belongs to. Use to choose the right function for the step you're on.
---

# Tools & Functions

Every scene change flows through these. Tools marked **mutates** replace the
canonical scene; the rest are read-only. Inputs that are JSON are passed as JSON
strings.

## Knowledge

- **`load_knowledge(query)`** → ranked knowledge snippets. Read-only. Call first,
  before authoring, and reload when the task shifts (branded, effects, repair).

## Author & compile

- **`compile_dsl_block(source)`** → `{compile:{status, diagnostics[], halted_at,
  operation_error}, operations[], checkpoint_label}`. **Mutates** the scene on
  success. Guards against re-declaring an existing page (`LUMA0200`). One block per
  call; on failure, author a small continuation/modify — never recompile the whole
  design.

## Checked operations (targeted edits)

- **`apply_operations(operations_json)`** → applies a list of core operations.
  **Mutates.** For known, multi-node operation lists (e.g. asset placement).
- **`apply_structured_edit(edit_json)`** → applies one checked edit. **Mutates.**
  This is the **precise repair actuator**. Shape:
  ```json
  { "kind": "modify|create|delete|move_before|move_after|move_to_parent|replace_node",
    "target": { "kind": "node|page|slot", "id": "instruction" },
    "patch":  { "kind": "node", "value": { "size": {"height":140}, "text": {"content": {"kind":"set","value":"…"}} } },
    "scope":  { "mode": "strict", "allowed": [{ "kind": "node", "id": "instruction" }] } }
  ```
  With `scope`, the engine **fails closed** (`edit.scope_violation`) if the edit
  would touch anything outside `allowed`. Use a scope on every issue-specific
  repair so a fix can't silently mutate unrelated nodes.

## Preflight

- **`preflight_design()`** → `{preflight:{has_errors, diagnostics[]},
  effective_brand}`. Read-only check: layout/fit (`LUMV…`), brand governance
  (`LUMB…`). Run after a clean compile; repair errors before previewing.

## Preview & export

- **`export_preview_bundle(critic_format?, debug_only?, debug_reason?)`** →
  canonical SVG + critic PNG/SVG. Preferred. `debug_only=True` exports a broken
  scene for human inspection **without** passing the acceptance gate.
- **`export_preview(format?)`** → single format. Read-only; writes artifacts to
  disk. If `validation_errors` are present, the preview is invalid — do **not**
  send it to review.
- **`get_latest_preview_for_critique(max_svg_chars?)`** → embeds SVG text / PNG
  base64 so the reviewer sees pixels, not a path. Call right before review.

## Visual review

- **`submit_visual_critique(critique_json)`** → validates and persists the
  reviewer's `VisualCritique` (accepted, issues[target,category,message,
  suggested_repair], repair_instruction). A malformed critique stops the run
  (`critic_failed`).

## Repair helpers

- **`recommend_edit_surface(intent, context_json?)`** → `dsl | structured_ops |
  asset_tool | external_planner`. A conservative hint, not an actuator. When a
  `target.node_id` is present, treat it as "edit that node in place" and prefer
  `apply_structured_edit` with a scope — regardless of the keyword hint.
- **`create_repair_request(exact_feedback, diagnostics_json?, target_json?,
  allowed_edit_surface?, forbidden_changes_json?, repair_class?, cluster_json?,
  permissions_json?, prohibitions_json?)`** → persists the *verbatim* feedback,
  target, repair class, bounded layout cluster, permissions, prohibitions, and
  forbidden changes so the author repairs the right thing. Never paraphrase the
  feedback. For `layout_cluster`, the cluster constrains allowed page/node IDs
  and the permissions/prohibitions are part of the contract.

## Scene inspection (read-only)

- **`summarize_scene()`** — document, pages, counts, slots, effective brand.
- **`summarize_page(page_id)`** / **`summarize_node_tree(page_id)`** — node tree
  with geometry and slot bindings; use to confirm a node id before targeting it.
- **`summarize_slots()`** — slot key → bound nodes.

## Assets

- **`generate_qr(data, ec_level?, print_media?, target_width_mm?, label?)`** →
  deterministic SVG QR asset. **Mutates** (adds an asset). For print, set
  `print_media=True` + `target_width_mm`. Place with an asset-placement operation.

## Gaps & telemetry

- **`record_gap(...)`** — when a needed repair requires unsupported semantics,
  record it instead of faking the feature.
- **`finalize_run(status, reason, summary, …)`** — end the run. `accepted` only
  after the reviewer accepts; otherwise `failed` with the stop reason (the best
  compiled draft still shows on the canvas).

## Loop order (quick map)

`load_knowledge → compile_dsl_block → preflight_design → export_preview_bundle →
get_latest_preview_for_critique → submit_visual_critique → (repair via
apply_structured_edit / compile_dsl_block) → finalize_run`.

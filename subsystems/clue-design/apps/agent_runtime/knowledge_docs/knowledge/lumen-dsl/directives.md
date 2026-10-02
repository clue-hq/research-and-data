# Lumen DSL — Directives & Targeted Edits

These are how you change an **existing** scene surgically, without re-declaring
the page or re-authoring nodes. This is the heart of reliable repair: a diagnostic
that names a node should be fixed with one of these, not a full rewrite.

All of the directives below are lowered to checked operations and covered by
tests. The one exception is `ds(...)` (design-system switch), which is parsed but
not yet lowered (`LUMD0700`); `undo()`/`redo()` require a history adapter.

## Modify line — `#<ref> prop(...)`

Edit one existing object in place. The ref selects what you target:

| Ref form | Targets | Example |
|----------|---------|---------|
| `#node_id` | a node | `#headline s(440,hug) font_size(22)` |
| `#page:id` | a page | `#page:page_a4 size(1080,1920,px)` |
| `#slot:key` | a slot | `#slot:contact.name required(true) sample("Jane Q. Patient")` |
| `#slot:key` (image) | an image-like slot's policy | `#slot:account.logo image_policy(cover)` — the `LUMV0820` fix |
| `#asset:id` | an asset | `#asset:logo_main name("Primary logo")` |
| `#export:name` | an export profile | `#export:web format(png)` |
| `#document` | document metadata | `#document medium(print)` |

A leading `#ref` line is a **modify**, not a comment. Properties that don't apply
to the target type warn (e.g. `font(...)` on a page → `LUMD0903`). Missing target
→ `LUMD0901`.

**The #1 ref mistake** (observed to burn whole runs):

```text
#page_a4 size(1080,1350,px)        ✗  bare #page_a4 is NODE grammar → LUMD0901
#page:page_a4 size(1080,1350,px)   ✓  pages need the #page: form
```

```text
# Fix an overflowing instruction box — change only that node:
#instruction s(352,140) max_lines(6) lh(1.4)
# Or make its card taller instead:
#card s(400,560)
```

## Structural directives

All structural directives take **NODE ids only**, never page ids —
`replace(page_a4)` halts `LUMD0901`. To rebuild a page's content, keep the page
and `replace(<its existing root node>)` with your new single-root subtree.

| Directive | Form | Use |
|-----------|------|-----|
| `delete` | `delete(id [,if_exists] [,hard])` — also `delete(page:id)`, `delete(slot:key)`, `delete(asset:id[,hard])`, `delete(export:name)` | remove a node/page/slot/asset/export profile; `if_exists` downgrades a missing target to info |
| `parent` | `parent(id, pid [,index:N \| before:anchor \| after:anchor])` | re-home a node |
| `before` / `after` | `before(id, anchor)` · `after(id, anchor)` | reorder siblings |
| `clone` | `clone(src, new_id, after:anchor [,slots:copy\|detach\|suffix:_x] [,computed:clear\|preserve])` | duplicate a subtree (e.g. another card) without re-authoring it |
| `replace` | `replace(id [,slots:preserve])` then an indented single-root subtree | swap a node's subtree atomically |
| `ungroup` | `ungroup(id [,allow_layout])` | dissolve a group, keeping child order |
| `override` | `override(clone_root)` then indented `#child …` modify lines | vary one cloned instance |
| `remove_effect` | `#node remove_effect(effect_id)` | drop one shadow/effect by id (modify-line only; else `LUMD0616`) |

```text
# Duplicate a card and tweak just the copy:
clone(card_a, card_b, after:card_a, slots:suffix:_b)
override(card_b)
  #card_b p(520,221)
  #title_b text "Second Option"
```

Bad syntax in any of these → `LUMD0207`. Block `replace` requires exactly one
staged root (`LUMD0914`). Its replacement subtree needs fresh ids throughout,
including its root: it stages alongside the old subtree before the swap. Use
`reconcile` when retaining existing ids.

`parent` takes a bare node id as its second argument: `parent(logo_mark,logo_chip)`.
For a page parent, use `parent(logo_mark,page:page_a4,0)`. The `parent:` prefix is
a **clone placement** form; it is not valid in the `parent(...)` directive.

## Reconcile a container — `reconcile(<container_id>)` + subtree

`reconcile(target)` is THE way to **add, remove, or restructure** the children of
an existing container. Indent the container's **full intended child subtree**:
re-emit every child you want to keep (same id, same fields) alongside the ones you
add or change. The engine diffs the block against the live subtree and emits the
MINIMAL operations — an unchanged re-emitted child costs zero ops.

```text
reconcile(hero)
  eyebrow text "INTRODUCING" style($type.eyebrow)     # unchanged → no-op
  headline text "New Headline" style($type.h1)        # kept id, new copy → update
  cta_shot image asset(asset_ing_9394e96d) p(0,0) s(400,300)   # new id → insert
```

Re-emitting existing ids inside the block is the POINT, not a duplicate-id error:
the block stages DETACHED, duplicate-id checks (`LUMD0401`) are suspended inside
it, and it never applies directly — only the computed diff ops do.

**Diff semantics** (by child id):

- present in both block and live subtree → `UpdateNode` with only the changed
  fields (`MoveNode` if its parent/index changed); identical → zero ops.
- in the block only → `InsertNode` at its block position.
- in the live subtree only → depends on **provenance** (the protection rule).

**The protection rule** (the human contract):

- An **agent-authored** live child omitted from the block is REMOVED — the
  declarative contract for the agent's own material.
- A **protected** child (seed-born / human) omitted from the block is **KEPT**,
  with a loud `LUMD0262` warning — omission never deletes human content. To remove
  protected content, write `delete(<id>)` explicitly (allowed inside the block).
- A protected child re-emitted with changed fields IS updated (an explicit
  re-author, same legitimacy as a `#node` modify line).

`reconcile(target)` requires a NODE container — frame/group/autolayout — never a
page id (`LUMD0264`, which names the valid containers in the live scene). To fill
an *empty* page use the `#page:<page_id>` continuation form instead. Each close
emits one `LUMD0263` info summary: `reconciled <container>: N updated, N inserted,
N removed, N moved, N kept-protected`.

```text
# Add a testimonial under `main` and drop the old placeholder, keeping the rest:
reconcile(main)
  headline text "Trusted by teams" style($type.h2)   # kept verbatim
  quote text "\"Best tool we've adopted.\"" style($type.body)   # new → insert
  attribution text "— A. Patient" style($type.caption)          # new → insert
```

## Repair discipline (do this, not that)

- **Do** target the failing node with a `#id` modify, a `delete`/`parent`, or a
  scoped `apply_structured_edit`.
- **Do NOT** re-emit `page …` or re-declare existing node ids — that is a repair
  *failure* (`LUMA0200` / duplicate id), and the partial deletes it often pairs
  with can wipe the good scene.
- For a precise, *checked* edit on a named node, prefer the tool
  `apply_structured_edit` with a `scope` over hand-writing DSL — it fails closed if
  the edit would touch anything outside the named target. See `skills/repair-design`
  and `skills/tools`.

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
| `#asset:id` | an asset | `#asset:logo_main name("Primary logo")` |
| `#export:name` | an export profile | `#export:web format(png)` |
| `#document` | document metadata | `#document medium(print)` |

A leading `#ref` line is a **modify**, not a comment. Properties that don't apply
to the target type warn (e.g. `font(...)` on a page → `LUMD0903`). Missing target
→ `LUMD0901`.

```text
# Fix an overflowing instruction box — change only that node:
#instruction s(352,140) max_lines(6) lh(1.4)
# Or make its card taller instead:
#card s(400,560)
```

## Structural directives

| Directive | Form | Use |
|-----------|------|-----|
| `delete` | `delete(id [,if_exists] [,hard])` | remove a node/asset; `if_exists` downgrades a missing target to info |
| `parent` | `parent(id, parent:pid [,index:N \| before:anchor \| after:anchor])` | re-home a node |
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
staged root (`LUMD0914`).

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

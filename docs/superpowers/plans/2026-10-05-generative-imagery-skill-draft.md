# Draft for founder review — generated imagery guidance for the scene agent

Status: DRAFT, nothing written into any skill yet. Paths below are relative to
`subsystems/clue-design/apps/agent_runtime/knowledge_docs/views/scene/`. Inside a run the agent
reaches every skill at `/.deepagent/skills/<name>/SKILL.md` (the same virtual path on the VM and on
a local machine; the file backend maps it).

Part A is the new skill, the single home of the framework. Part B is the one standard pointer every
other place uses. Part C lists every edit, before → after.

---

## Part A — `skills/generative-imagery/SKILL.md` (full new text)

```markdown
---
name: generative-imagery
description: Read before any generate_image call, and whenever a scene creative might need new imagery. Says how to decide what the image is for, how to take its look only from the seller's own imagery, and how to write the prompt so it asks for nothing those references do not show.
---

# Generated imagery

This skill covers every image you generate for a scene creative: a background, an
illustration, a supporting shape or figure, a scene around a real product, or a
texture. It works for any seller. The seller's look never comes from this file; it
comes from the seller's own imagery, which you look at during the turn.

Reference roles, the exact tool call, custody of reference bytes and contrast
sampling are in `/knowledge_docs/knowledge/scene/references.md`. This skill decides what to make
and what to ask the image model for.

## 1. Decide what the image is for

Before choosing references or writing a prompt, name the image's job in one line
and record it in the layer's `purpose` in the direction record. Most images are one
of these:

- **Background**: sits behind copy or other layers and fills its frame.
- **Illustration**: a drawn or rendered subject that carries part of the message.
- **Supporting shape or figure**: an abstract form, an icon-like mark, a divider or
  a decorative element.
- **Product scene**: the surroundings for a real product image or screenshot.
- **Texture or pattern**: a surface treatment that other layers sit on.

If the job is something else, describe it plainly and use the closest of these.
The job decides which references fit and what the prompt has to say.

## 2. Gather the seller's own imagery for that job

The seller's look lives in its published ads, the images on its own website and its
brand kit. Find candidates with `search_assets` and the brand card's image list,
read `ad-assets.md` when it exists, and `view` the ones that might fit.

Prefer references that do the same job. For a background, look at the seller's
backgrounds; for an illustration, its illustrations; for a supporting figure, its
icons, marks and shapes. If the seller has nothing of that kind, take only the look
(colour, light, finish, line, material) from its closest imagery, and do not copy
that image's subject.

Pick at most four references, in a deliberate order, and give each an honest role.
A reference you did not view is a guess; view it first.

## 3. Decide the subject and the look separately

**The subject** comes from the message the creative is making, and it must serve
that message.

- A background has no subject unless the seller's own imagery shows one in its
  backgrounds.
- The target account's world (what the target account does, makes or where it
  works) may appear only when the seller's own imagery already shows that kind of
  subject, or when the person supplied that material. Otherwise leave it out.
- Never put the seller's or anyone's logo, words, interface or product into the
  generated image. Those are separate layers placed from real assets.

**The look** comes only from the references you viewed. Describe colour, light,
material, edge softness, line, depth and texture the way they appear there. Do not
add a light source, a colour, a material or a mood that none of them shows.

## 4. Write the call

The prompt says four things and stops:

1. what the image is (its job and, if it has one, its subject);
2. its shape and how it sits in the layout, including where copy will go;
3. the look you are keeping, in the references' own terms;
4. any deliberate change you are making, and why the message needs it.

Leave out everything else. A long list of extra colours, lights and moods pulls the
image away from the references. `reference_framing` and `brand_notes` reach the
image model too, so the same rules apply to them.

## 5. By job

**Background.** Keep the area under the copy simple enough for the copy to read, in
whatever style the references show: blur, photo, flat colour, gradient or pattern.
Put any detail and interest away from the copy. Check contrast after placing it.

**Illustration.** Match the seller's illustration style: line weight, fill (flat,
gradient or textured), level of detail, how it draws people and objects, and its
palette. One clear subject that serves the message, with nothing added beside it.

**Supporting shape or figure.** Match the seller's geometry, corners, stroke and
fill. If native shapes in the design can do the job, use them instead of
generating.

**Product scene.** The real product image or screenshot is always its own authentic
layer; generate only what surrounds it, in the seller's look. Never generate the
product, its interface or its results.

**Texture or pattern.** Copy the scale, rhythm and contrast of the seller's own
textures or patterns. Keep it quiet enough not to compete with what sits on it.

## 6. When nothing fits

If none of the seller's imagery shows a usable look for this job, ask the person, or
build it from native shapes and brand colours instead of generating. Say which you
did in the direction record. If the references you chose are textured, blurred or
photographic, a flat brand-colour fill is a different treatment, not the same one;
use it only when that is the intended direction.

## 7. Check the result

`view` every generated image before placing it. Compare it with the references you
used: is it in the seller's look, does it carry anything you did not ask for, and
does it work in place with the copy? If not, repair the prompt or the references
once, or report the gap. A placeholder or failed generation is not finished
imagery.
```

---

## Part B — the standard pointer (used everywhere below)

> **Generated imagery.** Before writing any `generate_image` call, read
> `/.deepagent/skills/generative-imagery/SKILL.md` if you have not read it this
> turn. In short: decide what the image is for, take its look only from the
> seller's own imagery, and ask for nothing those references do not show.

Below, "[pointer]" means this block. Where a sentence has to fit inside a paragraph,
the short form is: "Read `/.deepagent/skills/generative-imagery/SKILL.md` before
writing the call."

---

## Part C — every edit, before → after

### C1. `knowledge/scene/references.md`

- **Top of the file**, after the title, add:
  > This file covers reference roles, the generation and edit calls, custody of
  > reference bytes and contrast checks. What to generate and how to write the prompt
  > are in `/.deepagent/skills/generative-imagery/SKILL.md`; read it before any
  > `generate_image` call.
- **Remove** (now in the skill, §3): "A new subject does not authorize invented
  lighting or materials: do not translate a concept word into a luminous network
  unless the sources or request justify it."
- **Replace** the whole paragraph "Specify the component, aspect, quiet copy region and
  observed treatment. … without erasing the defining material behavior." with
  **[pointer]**.

### C2. `knowledge/scene/components.md`

- **Code example** (around line 136). Before:
  ```python
  # When new artwork is needed; [] deliberately uses no references in this example.
  generated = json.loads(asset(action="generate_image", target_node_id="artwork",
      prompt="An isolated folded paper form, no text or logos", reference_asset_ids=[]))
  ```
  After:
  ```python
  # When new artwork is needed: purpose, subject and look decided under
  # /.deepagent/skills/generative-imagery/SKILL.md; ref_id is a seller image you viewed.
  generated = json.loads(asset(action="generate_image", target_node_id="artwork",
      prompt="<the image's job, its subject if any, its shape, and the look kept from the reference>",
      reference_asset_ids=[ref_id], reference_roles=["treatment"]))
  ```
- **Replace** the paragraph "An inspected reference's soft material, blur, tonal
  variation or texture is part of its treatment. … use a flat field only when that is
  the intended and justified visual direction." with **[pointer]**.

### C3. `skills/brand-imagery/SKILL.md` (full new text)

```markdown
---
name: brand-imagery
description: Use when deciding whether imagery helps a scene creative and whether a real asset, a generated image or typography alone should carry the message.
---

# brand imagery

Start with the request. When it asks for new imagery or artwork variants, the
deliverable includes actual generated images, in the requested number of distinct
outputs. Existing imagery, a flat fill or a native gradient does not fulfil a
request for new artwork.

When imagery is optional, choose what best carries the message: a suitable real
image from the seller's library, a generated image, or typography alone. Look at the
real candidates before deciding.

[pointer]

Read `/knowledge_docs/knowledge/scene/components.md` for native text and geometry and for
independent authentic logo and product layers. Keep those editable, and inspect the
finished composition as well as every generated image.
```

### C4. `skills/account-identity-composition/SKILL.md`

- Before: "Match a generated image's ground to the neighboring field, or use a
  deliberate frame/bleed supported by the references."
  After: "Where a generated image meets the neighbouring field, decide its edge
  under `/.deepagent/skills/generative-imagery/SKILL.md`, or use a deliberate
  frame or bleed supported by the references."
- Before: "Preserve the advertiser's observed material, color and blur/texture
  language. Generate the separate artwork; keep original logos, factual product
  pixels and native copy independent."
  After: "Generate the separate artwork under
  `/.deepagent/skills/generative-imagery/SKILL.md`, taking its look from the
  advertiser's own imagery; keep original logos, factual product pixels and native
  copy independent."

### C5. `skills/type-led-positioning/SKILL.md`

- Before: "Follow `knowledge/scene/references.md` for inspected reference bytes and
  output review. A flat palette match does not preserve an observed textured, blurred
  or tonal treatment. Reserve readable space within that treatment rather than
  deleting it."
  After: "Read `/.deepagent/skills/generative-imagery/SKILL.md` before writing the
  call; keep readable space for the type within the treatment you take from the
  references."

### C6. `skills/offer-conversion/SKILL.md`

- Before: "do not replace material imagery with a flat field merely to fit more copy."
  After: "do not replace the original's imagery with a flat field merely to fit more
  copy; new imagery follows `/.deepagent/skills/generative-imagery/SKILL.md`."

### C7. `skills/editorial-pov/SKILL.md`

- Before: "Do not remove observed texture or expressive imagery to default to a flat
  statement panel."
  After: "Do not remove the original's texture or expressive imagery to default to a
  flat statement panel; new imagery follows
  `/.deepagent/skills/generative-imagery/SKILL.md`."

### C8. `skills/customer-spotlight/SKILL.md`

- After the "Customer world" bullet, add:
  > Real material from the customer or the person (photos, venue, product) can lead
  > as authentic layers. Generated imagery stays in the seller's look and shows the
  > customer's world only when the seller's own imagery already shows that kind of
  > subject; see `/.deepagent/skills/generative-imagery/SKILL.md`.
- "Read `knowledge/scene/components.md` and `knowledge/scene/references.md`." →
  "Read `knowledge/scene/components.md`, and
  `/.deepagent/skills/generative-imagery/SKILL.md` before any generated layer."

### C9. Skills that send generation to `references.md`

Same change in each: the generation instruction points to the skill.

| Skill | Before | After |
|---|---|---|
| `product-in-use` | "generate the contextual layer under `knowledge/scene/references.md`" | "generate the contextual layer under `/.deepagent/skills/generative-imagery/SKILL.md` (product scene)" |
| `authentic-product` | "if a generated setting helps, also read `knowledge/scene/references.md`" | "if a generated setting helps, also read `/.deepagent/skills/generative-imagery/SKILL.md` (product scene)" |
| `launch-announcement` | "If new imagery is required, follow `knowledge/scene/references.md` and generate a separate scene or treatment" | "If new imagery is required, follow `/.deepagent/skills/generative-imagery/SKILL.md` and generate a separate scene or treatment" |
| `feature-deep-dive` | "Read `knowledge/scene/references.md` when imagery is involved." | "Read `/.deepagent/skills/generative-imagery/SKILL.md` before generating any imagery." |
| `case-study-narrative` | "Follow `knowledge/scene/references.md` for separately generated contextual artwork." | "Follow `/.deepagent/skills/generative-imagery/SKILL.md` for separately generated contextual artwork." |
| `comparison-alternatives` | "Use `knowledge/scene/references.md` for independent background imagery." | "Use `/.deepagent/skills/generative-imagery/SKILL.md` for independent background imagery." |
| `effects` | "`knowledge/scene/references.md` owns that decision." | "`/.deepagent/skills/generative-imagery/SKILL.md` owns that decision." |
| `problem-solution` | "Choose the image treatment from inspected sources, including their actual texture, lighting and spatial behavior." … "Read `knowledge/scene/references.md` for source roles and image operations." | "Choose the image treatment from the seller's inspected imagery under `/.deepagent/skills/generative-imagery/SKILL.md`." … "Read `knowledge/scene/references.md` for source roles and image operations." (unchanged) |
| `objection-handling` | "requested new artwork is generated separately under `knowledge/scene/references.md`" | "requested new artwork is generated separately under `/.deepagent/skills/generative-imagery/SKILL.md`" |
| `visual-metaphor` | "Read `knowledge/scene/components.md` and `knowledge/scene/references.md` for source roles and independent artwork generation." | "Read `knowledge/scene/components.md`, and `/.deepagent/skills/generative-imagery/SKILL.md` (illustration) before generating the metaphor." |
| `reference-image-direction` | (only points to `references.md`) | add [pointer] after its existing sentence |
| `reference-conditioned-ads` | (only points to `references.md`) | add [pointer] after its existing sentence |

### C10. `knowledge/scene/direction-contract.md`

- After "Generated layers can name ordered `reference_asset_ids` and aligned
  `reference_roles` (source/treatment/composition, at most four)." add:
  > A generated layer's `purpose` names what the image is for (background,
  > illustration, supporting shape, product scene, texture or another stated job), as
  > `/.deepagent/skills/generative-imagery/SKILL.md` describes.

### C11. Code — the `asset` tool description (`lumen_agent/tools/substrate.py`)

- In the `generate_image` paragraph, after "`brand_notes`, `transparent_background`,
  `label`." add:
  > `brand_notes` and `reference_framing` are appended to the prompt the image model
  > receives; they follow the same rules as the prompt
  > (`/.deepagent/skills/generative-imagery/SKILL.md`).

### C12. Code — the solo scene prompt (`lumen_agent/prompts.py`)

- After "Then generate, edit, crop or reuse imagery as the validated direction
  requires." add:
  > Before any generate_image call, read
  > /.deepagent/skills/generative-imagery/SKILL.md if you have not read it this
  > turn.

### Not changed now

- `IMAGERY_RUBRIC` (`prompts.py`): used only by the archived pipeline and the eval
  scripts; align it when those evals are next used.
- Mentions of pre-generated backgrounds in the solo prompt and `ad-assets.md`: they go
  when pre-generation is removed.

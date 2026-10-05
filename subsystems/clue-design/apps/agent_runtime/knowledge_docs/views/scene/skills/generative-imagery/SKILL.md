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

Prefer references without text, cards or interface: the image model copies what it
sees, including words. If the look you want sits behind text or cards in an ad,
crop the clean area with `asset(action="crop_image")` and use the crop, or choose
a text-free image with the same look.

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
does it work in place with the copy? Look closely for words, letters, logos or
interface the model added on its own.

If the image is not what you asked for, do not place it. Find the cause, fix it and
generate a new image: swap a text-heavy reference for a text-free or cropped one,
remove what pulled the image off the look, or say more plainly what the image must
not contain. Then view the new image the same way. If it keeps failing in the same
way, change approach (other references, native shapes and brand colours) or report
the gap. A placeholder or failed generation is not finished imagery.

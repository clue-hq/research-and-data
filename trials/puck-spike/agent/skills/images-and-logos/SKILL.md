---
name: images-and-logos
description: Use when a section needs an image: choosing one of the brand's images, generating a new one, or placing the account's logo.
---

# Images and logos

## 1. Start from the brand's own images

- The brand's images are in `brand/brand.md`, each with a description. A description can be wrong
  or missing, so look at an image with `view_asset` before you use it.
- Anything real comes only from these images: product screenshots, the seller's photos of its
  people and customers, logos, customer stories. Never generate them.
- Check that the image fits the words beside it. A product screenshot must show what the copy
  says. A graphic with its own words baked in rarely fits a new heading.

## 2. Generate only a scene or a mood

Generate an image only when a section needs one and none of the brand's images fits. A generated
image may show a scene or a mood: a school-district setting for a school district, or an abstract
background in the brand's colours. It must not show:
- words, numbers or logos;
- real people, or anyone presented as a real person;
- a product screen, or anything presented as the seller's product;
- anything presented as the account's own building, staff or customers.

To keep it in the brand's style, pass one to three of the brand's own photos as
`style_references`, and ask for the shape the section needs. Look at the result. If it breaks a
rule above or looks off-brand, try once more with a clearer prompt, or leave the image out.

## 3. No image beats a weak image

If nothing fits and a generated image would not help the reader, choose a section without an
image.

## 4. Logos

- The account's logo goes only in the header's "Prepared for" place. It is in `brand/brand.md`
  under "The account's logo". If there is none, leave `accountLogo` empty.
- Never put the account's logo anywhere else on the page.
- A row of the seller's customer logos must not suggest the account is already a customer. Leave
  out a logo of a company with the same or a similar name as the account, or one that could be its
  parent or subsidiary.

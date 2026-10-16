# Account templates and focused campaign assembly

Read `web-account-personalization` for audience modes and evidence, and
`campaign-landing-page` for the argument and chrome choice. A target account
does not force a pilot, a booking CTA, seven sections or a minimal header.
Use inspected source anatomy and the actual offer. One-to-few, one-to-many,
event and regular pages are different intents; do not turn them into 1:1
account templates merely to use this recipe.

## Reusable account template mechanics

For an account template, preserve markers in cloned slot values such as
`{{account.name}}`, `{{account.domain}}`, `{{account.logo}}`. Derivation fills
those per account. Do not bake an account's name into the shared template.
If a healthy band needs a new slot/shape, derive a source-based campaign
variant; unsupported original motion is a separate fidelity issue. Use
attribute-level `data-var`/`data-slot`/`data-slot-when` only where required by
typed content. The create-website reference owns their exact grammar.

Fetch missing target marks through the available `fetch_logo` capability.
Inspect identity and surface fit: `light_lockup`/`dark_lockup` for corresponding
surfaces, `light_mark`/`dark_mark` for symbols. An empty or `needs_review` result
is not permission to synthesize a logo. Use supported name-only presentation
and report the gap. A logo found for a named account is persisted through
`bind_account_logo(account_id, asset_id)` when this role exposes it. Derivation
uses that binding; it does not fetch missing logos by itself. A successful
asset lookup is not proof of account binding or derivation.

Publish only the resolved derived page when a reusable template contains
markers. Existing publish validation refuses unresolved templates; preserve
that contract. Report draft/template/derived/published states separately.
Derived pages may be noindex, but noindex and an unlisted URL are not privacy
or authentication. Never claim otherwise.

## Focused single-conversion route

Use `mint_campaign_shells` + `assemble_abm_page` only when the plan calls for
minimal campaign chrome. It selects released campaign header/footer shells;
it does not silently substitute global navigation when shells are missing.
Existing pinned navigation (or a nav passed as hero) is retained with advice,
not blocked or removed. Review that advice against the intended journey. Respect
actual draft/release status and refusals. For a native-navigation page, use
the ordinary cloned-section assembly tools instead. Do not silently change the
plan to escape a refusal.

Build the source-based section set first, then assemble the shells. A later
whole-page `author_web_page` would discard pinned clones. Use existing slots
and small operations for subsequent copy changes. Composed account bands use
`abm_` ids; existing source pins preserve their ids.

The plan selects sections from the evidenced argument: personalized hero,
relevant features, actual peer proof, verified resources, proposal/next steps,
and a closing action when useful. Those are options, not required counts.
Proof absent means omit proof. Customer logos and target logos have distinct
roles; an addressed target is not a customer endorsement. Resource journeys
may use real relevant links, while a focused booking page concentrates its
primary actions on one verified destination. Preserve legal links.

## Evidence and finish

The seller's measured visual system remains dominant. Target identity is
quoted authentically; do not recolor or redraw marks, imply partnership, or
write unsupported target priorities. Use verified platform evidence when
available, attributed supplied facts otherwise, and stated proposals when
research is missing. Personal facets need identity and appropriate-use gates.

Choose CTA wording from the actual offer and destination. No endpoint means
an unresolved conversion requirement: do not invent a booking URL, disguise a
homepage as booking, or leave a functional-looking placeholder. A useful draft
can be retained with the limitation stated outside the visitor copy.

`review-website` checks the current derived output, all relevant viewports,
source fidelity, logo placement, evidence, interactions and real destinations.
Completing template assembly alone does not establish those outcomes.

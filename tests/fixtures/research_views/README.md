# C7 research-view fixture map

These fixtures translate the 2026-07-27 account/contact frontend requirements into sanitized,
executable backend calibration data.

- `account_view_manifest.json` freezes the account page's required semantic sections and the
  authority each section references.
- `contact_view_manifest.json` freezes the contact page's required semantic sections, including
  the separate governed-personalization section.
- `adversarial_cases.json` maps each known contamination/governance failure to its first required
  guard and final expected outcome.

The fixtures intentionally contain no customer, attachment, screenshot, or proprietary source
text. They do not assert visual layout. C7.0 tests validate the manifests against the core
source-species and nine-block maps; later slices reuse the same case ids for resolver, handoff, and
end-to-end tests.

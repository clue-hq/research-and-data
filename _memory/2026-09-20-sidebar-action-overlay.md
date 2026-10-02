# Sidebar action overlay

- Founder requested project/chat names use the row's available width, with compose
  and more-options controls overlaid instead of reserving blank space.
- Found the project action group was an opacity-hidden flex sibling reserving 52px
  at all times. Made it an absolute trailing overlay with the existing hover surface.
  Founder clarified the backing must be opaque only in the button area: the 48x24px
  group composites the translucent hover token over an opaque neutral base, without
  a fade over adjacent text. It stays visible on hover, keyboard focus and menu-open.
  Label width stays stable as controls appear; existing marquee and row sizing remain.
- Conversation rows have no compose/menu action group and already use the available
  width aside from actual run-status indicators. No changes to those indicators.
- Live browser: 223px row and toggle now match; Q3 title is fully visible while idle.
  Title width remained 142.25px with controls shown; final overlay is 48x24px with an
  opaque white base plus the canonical hover tint and no adjacent text mask. Screenshots
  reviewed. Keyboard Tab reached New chat and More options; Enter opened the menu and
  Escape closed it. Did not create chats or mutate projects. Restored temporary expansion
  state and closed the review tab; user's account preview was left undisturbed.
- Design-system generation, lint and final production build passed. The two pre-existing
  canvasOperations unused-function warnings remain. No new tests for this CSS-only change.
  Closing state: complete, saved locally, no remote publication.

## 14px sidebar preview

- Founder requested a live preview of all primary sidebar text at 14px after
  reviewing the existing 13px items and 12px section labels. Applied the canonical
  text-default font-size token to navigation items, project/chat names, profile
  name, section labels and empty-chat copy. Preserved existing weights, line
  heights (18px items, 16px labels), row heights and opaque action overlays.
- Live accounts page confirmed 14px computed font size across the requested roles;
  expanded a project to verify its chat label also renders at 14px/18px in a 32px
  row. Left it expanded so the preview includes a chat name. Reviewed screenshots
  and showed the browser. The preview is implemented locally pending visual feedback.
- Design-system generation, lint and production build passed; only the two known
  canvasOperations unused-function warnings remain. Diff whitespace check passed.
  No new tests for this CSS-only preview; no remote publication.

## Regular-weight sidebar follow-up

- Founder requested weight 400 instead of 500 for the 14px sidebar preview.
  Updated navigation (including selected items), project/chat names, profile name
  and empty-chat copy to the canonical text-default regular-weight token. Section
  labels already use weight 400. Font sizes and spacing remain as approved.
- Live computed styles confirmed 14px/400 for navigation, heading, project/chat
  names and profile text. Reviewed the chat page screenshot. Browser verification
  used read-only inspection after an unnecessary tab-retention mark was rejected;
  no tab-retention change was needed for this request.
- Closing verification: design-system generation, lint, production build and diff
  whitespace check passed. Lint retains the two existing canvasOperations warnings.
  Saved locally; no remote publication.

## Medium-weight sidebar final preference

- Founder changed the sidebar preference back to weight 500. Applied the canonical
  text-default-medium weight to primary navigation, project/chat names, section
  labels, profile name and empty-chat copy, retaining the approved 14px size and
  existing spacing. This supersedes the regular-weight preference above.
- Live chat page computed styles and screenshot confirm 14px/500 throughout these
  sidebar roles, including the selected chat. Changes remain on
  `rebase-and-expand-attachment-types`.
- Closing verification: token generation, lint, production build and diff whitespace
  check passed. Only the two existing canvasOperations lint warnings remain. Founder
  explicitly requested committing and pushing all pending visual work on this branch;
  unrelated untracked attachments and samples are excluded from the commit.

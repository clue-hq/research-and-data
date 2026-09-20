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

# Composer alignment and long drafts — 2026-09-12

- Founder requested matching placeholder/caret alignment and stable textbox height for long pasted text on Home and project chats, including the Gallery split. Any extra chat composer height should take space upward.
- Shared composer now stays 126px tall (151px with attachments), with a constrained flex editor that scrolls vertically. Attachment chips and errors retain their own space; the Send/Stop footer stays fixed. Paragraphs use the normal 22px line height and position Slate's placeholder relative to the text line, inside editor padding.
- Chat dock sizes to content and aligns its frame to the bottom. Additional attachments, edit targets, research cards or queue controls take height from the conversation above instead of overflowing below the viewport.
- Live Semarang browser checks at 1293x988: placeholder text and caret both measured y=356, height=18.5px. A 100-paragraph draft with long unbroken tokens kept Home at 126px and its bottom at y=466. With Gallery open, chat stayed at 126px, bottom y=964; editor content scrolled inside 73px with no horizontal overflow. Closing Gallery retained the same height and bottom position.
- Cleared temporary browser drafts by reloading; the browser fill-empty helper did not clear Slate reliably. No message was sent. Returned to Home. No runtime configuration, backend, database or sibling workspace changes.
- Verification: design-system build, frontend lint and production build passed. Lint retains the two existing unused-variable warnings in design engine canvasOperations.ts. Diff whitespace check passed.
- Closing state: live on Semarang frontend 3040; scoped commit/push follows the founder's standing instruction. No unresolved layout defect in this slice.

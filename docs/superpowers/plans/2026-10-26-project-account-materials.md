# Project account materials

User approved implementation: extend the original Target Accounts table and use Direct Mail's interface inside chat Gallery. V2 only, frontend only; no email scope.

1. Add an account/contact-scoped material read model over canonical mailers and creative records. Test isolation, revisions, multiple contacts and pagination.
2. Add Snowflake as an existing target account with explicitly fictional demo contacts. Preserve saved V2 records through additive migrations.
3. Extend the original table with an optional Artifacts column. Keep it mounted while Gallery reviews materials. Retire the parallel project plan route.
4. Reuse Direct Mail review/tracking and its table/layout tokens inside a shared materials browser. Connect Gallery, account Artifacts and global Artifacts.
5. Verify focused tests, frontend gate and browser walkthrough. Fresh reviewer checks the final diff; local checkpoint only.

No backend payload contracts change. New scoped preview links are frontend-only; live adapters retain their original screens. No new runtime flags.

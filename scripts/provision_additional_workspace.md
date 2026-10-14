# Adding a workspace to an existing account

Use this when someone who already has a Clue account needs one more workspace they own, on the
same login. Self-serve signup only creates a person's first workspace, so a second one goes
through `provision_additional_workspace.py` and the onboarding link it prints.

## Before you start

- The account must already exist and be active. The script refuses an unknown email, an email
  shared by two users, or a suspended user.
- Running it twice for the same company is refused, so you can't create duplicates by accident.
- Step 3 spends money: it is a real onboarding run.

## Steps

**1. Dry run.** From your laptop, in this repo's root, run the command below with the account's
email, the new company's website, and its name. It prints the workspace it would create and the
onboarding link, then rolls everything back.

```bash
ssh ubuntu@40.160.37.148 'sudo docker exec -i vm-batch1-1 python - --email shank@cluehq.ai --website https://acme.com --company-name "Acme" --app-origin https://app.cluehq.ai' < scripts/provision_additional_workspace.py
```

**2. Create it.** If the dry run looks right, run the same command again with `--apply` added at
the end. It creates the workspace, its brand, and the owner membership, and prints the real
onboarding link. Run it from the repo root, since it reads the script from there.

```bash
ssh ubuntu@40.160.37.148 'sudo docker exec -i vm-batch1-1 python - --email shank@cluehq.ai --website https://acme.com --company-name "Acme" --app-origin https://app.cluehq.ai --apply' < scripts/provision_additional_workspace.py
```

**3. Onboard it.** Sign in to app.cluehq.ai as that account, then open the printed link in the
same browser. The app switches to the new workspace and shows the normal setup screen while
onboarding and brand ingestion run. Open the link only while signed in as that account: anyone
else sees "You don't have access to this workspace" and nothing starts.

**4. Check it.** When setup finishes it drops you into the app. The new workspace should appear
in the workspace switcher, Brand context should fill in, and Settings should show the website.

## Why it works this way

- The script only creates rows: the workspace, its single brand, and an owner membership. It
  starts nothing and spends nothing.
- Onboarding starts from the browser, not the script, because it also starts brand-kit
  ingestion on the design API, which only the platform API inside Railway can reach.
- The link carries the workspace id, and the setup screen switches to that workspace (with a
  server-side membership check) before it starts anything, so the link can never onboard
  whichever workspace you happened to have open.

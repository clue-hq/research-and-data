#!/usr/bin/env bash
# The forced command behind CI's SSH key on the worker VM. In /home/clue/.ssh/authorized_keys:
#   command="/srv/clue/app/deploy/vm/ci_deploy.sh",restrict ssh-ed25519 AAAA… clue-ci-deploy
# so whatever CI asks for arrives here as SSH_ORIGINAL_COMMAND and nothing else ever runs: it must be
# one full 40-character commit sha, which goes to deploy.sh (it checks the database is at head and
# refuses otherwise). Anything else is refused before deploy.sh is touched.
set -Eeuo pipefail
requested="${SSH_ORIGINAL_COMMAND:-}"
if [[ ! "$requested" =~ ^[0-9a-f]{40}$ ]]; then
  echo "refused: CI may only request a deploy of one full commit sha" >&2
  exit 2
fi
# Check the requested commit out FIRST, then run ITS deploy.sh. deploy.sh checks the commit out
# too, but by then the previous release's copy of deploy.sh is the one running: a release that
# changed deploy.sh got its new compose file and the old deploy steps (2026-10-04: #96's design
# workspace preparation never ran, the mount came up root-owned, and design failed for a day).
app="$(cd "$(dirname "$0")/../.." && pwd)"
git -C "$app" fetch origin main
git -C "$app" checkout --detach "$requested"
exec "$app/deploy/vm/deploy.sh" "$requested"

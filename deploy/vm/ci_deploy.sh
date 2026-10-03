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
exec "$(dirname "$0")/deploy.sh" "$requested"

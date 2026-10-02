#!/usr/bin/env bash
# One-time worker VM setup (first deployment spec §6, §9.4). Idempotent. Run as root on a fresh
# Ubuntu 24.04 VM, with harden_ssh.sh beside it: sudo bash bootstrap.sh
set -Eeuo pipefail
[ "$(id -u)" = "0" ] || { echo "run as root" >&2; exit 1; }
# Password login off first (refuses, changing nothing, until your SSH key is installed).
bash "$(dirname "$0")/harden_ssh.sh"
apt-get update
apt-get install -y ca-certificates curl git ufw python3
command -v docker > /dev/null || curl -fsSL https://get.docker.com | sh
ufw default deny incoming
ufw allow OpenSSH
ufw --force enable

id clue > /dev/null 2>&1 || useradd --uid 1000 --create-home --shell /bin/bash clue
usermod -aG docker clue
mkdir -p /srv/clue/workspaces /srv/clue/engine-cache
chown 1000:1000 /srv/clue /srv/clue/workspaces /srv/clue/engine-cache
chmod 700 /srv/clue/workspaces

[ -d /srv/clue/app/.git ] || sudo -u clue git clone --branch main git@github.com:clue-hq/research-and-data.git /srv/clue/app
for f in env pgbouncer.env backup.env compose.env; do
  touch "/srv/clue/$f"
  chown 1000:1000 "/srv/clue/$f"
  chmod 600 "/srv/clue/$f"
done
DOCKER_GID="$(stat -c %g /var/run/docker.sock)"
grep -q '^DOCKER_GID=' /srv/clue/compose.env || echo "DOCKER_GID=$DOCKER_GID" >> /srv/clue/compose.env
grep -q '^PGBOUNCER_CLIENT_PASSWORD=' /srv/clue/compose.env || echo "PGBOUNCER_CLIENT_PASSWORD=" >> /srv/clue/compose.env

cp /srv/clue/app/deploy/vm/systemd/*.service /srv/clue/app/deploy/vm/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now clue-db-backup.timer clue-watchdog.timer
echo "bootstrap done — fill /srv/clue/{env,pgbouncer.env,backup.env} and PGBOUNCER_CLIENT_PASSWORD in compose.env, then run deploy.sh <sha> as clue"

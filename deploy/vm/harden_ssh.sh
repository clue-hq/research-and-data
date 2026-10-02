#!/usr/bin/env bash
# Turn off SSH password login on the worker VM (first deployment runbook §4). Run as root; bootstrap.sh
# runs it first. Refuses — changing nothing — until the operator who logs in (the sudo caller,
# else `ubuntu`, OVHcloud's login user) has an SSH key installed, so it can never lock them out.
# The drop-in is named 00-… because sshd takes the FIRST value it reads and Ubuntu cloud images
# ship a 50-cloud-init.conf that turns password login on.
set -Eeuo pipefail
DIR="${CLUE_SSHD_CONFIG_DIR:-/etc/ssh/sshd_config.d}"
DROPIN="$DIR/00-clue-hardening.conf"
OPERATOR="${SUDO_USER:-ubuntu}"
[ "$OPERATOR" = "root" ] && OPERATOR=ubuntu
HOME_DIR="$(getent passwd "$OPERATOR" | cut -d: -f6)"
KEYS="$HOME_DIR/.ssh/authorized_keys"

if ! grep -Eq '^(ssh-|ecdsa-|sk-)' "$KEYS" 2>/dev/null; then
  echo "harden_ssh FAILED: $OPERATOR has no SSH key in $KEYS — turning password login off now" >&2
  echo "would lock you out. From your own machine run: ssh-copy-id $OPERATOR@<vm>, then re-run." >&2
  exit 1
fi

mkdir -p "$DIR"
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' > "$DROPIN"
chmod 644 "$DROPIN"
if ! sshd -t; then
  rm -f "$DROPIN"
  echo "harden_ssh FAILED: sshd rejected the config; removed it, SSH unchanged" >&2
  exit 1
fi
systemctl reload ssh
echo "harden_ssh: password login off; $OPERATOR logs in with a key only"

#!/usr/bin/env bash
# Idempotent harness host setup (run as ubuntu on the EC2 host; repo at ~/bharatbench).
# Needs: docker `redroid` container with adb on 127.0.0.1:5555, adb, iproute2.
# Does NOT create harness/.env (it holds HARNESS_TOKEN; see harness/README.md).
set -euo pipefail
REPO=~/bharatbench
# 1. NOPASSWD sudo for tc only (traffic shaping on the container's veth)
echo 'ubuntu ALL=(root) NOPASSWD: /usr/sbin/tc' | sudo tee /etc/sudoers.d/bharatbench-tc >/dev/null
sudo chmod 440 /etc/sudoers.d/bharatbench-tc
sudo visudo -cf /etc/sudoers.d/bharatbench-tc >/dev/null
# 1a. NOPASSWD sudo for the one fixed tcpdump invocation (cleartext-traffic security check; capped by `timeout`)
echo 'ubuntu ALL=(root) NOPASSWD: /usr/bin/timeout 240 /usr/bin/tcpdump -i any -nn -A -s 1024 -l tcp dst port 80' | sudo tee /etc/sudoers.d/bharatbench-tcpdump >/dev/null
sudo chmod 440 /etc/sudoers.d/bharatbench-tcpdump
sudo visudo -cf /etc/sudoers.d/bharatbench-tcpdump >/dev/null
command -v tcpdump >/dev/null || sudo apt-get install -y tcpdump
# 1b. tc kernel modules (not autoloaded under sudo on the AWS kernel: "Specified qdisc kind is unknown")
printf '%s
' sch_netem sch_prio sch_ingress cls_u32 act_police act_gact | sudo tee /etc/modules-load.d/bharatbench-tc.conf >/dev/null
for m in sch_netem sch_prio sch_ingress cls_u32 act_police act_gact; do sudo modprobe "$m"; done
# 2. deps
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
(cd "$REPO/harness" && ~/.local/bin/uv sync --frozen --no-dev)
# 3. service (adb connect runs before every start)
sudo cp "$REPO/deploy/bharatbench-harness.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bharatbench-harness
if [ -f "$REPO/harness/.env" ]; then
  sudo systemctl restart bharatbench-harness
else
  echo "harness/.env missing: create it with HARNESS_TOKEN=... then: sudo systemctl restart bharatbench-harness" >&2
fi

#!/usr/bin/env bash
# Called by CI over SSH on every push to main: pull, sync deps, restart, health-check.
set -euo pipefail
cd ~/bharatbench
git fetch --quiet origin main
git reset --hard origin/main
cd api && ~/.local/bin/uv sync --frozen --no-dev
sudo systemctl restart bharatbench-api
# harness (only once setup_harness_ec2.sh has installed its unit)
if [ -f /etc/systemd/system/bharatbench-harness.service ]; then
  (cd ~/bharatbench/harness && ~/.local/bin/uv sync --frozen --no-dev)
  sudo cp ~/bharatbench/deploy/bharatbench-harness.service /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl restart bharatbench-harness
fi
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null; then echo "API healthy"; exit 0; fi
  sleep 1
done
echo "API failed health check" >&2
sudo journalctl -u bharatbench-api -n 50 --no-pager >&2
exit 1

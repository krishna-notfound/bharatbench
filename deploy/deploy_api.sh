#!/usr/bin/env bash
# Called by CI over SSH on every push to main: wait for running tests, pull, sync deps, restart, health-check.
set -euo pipefail

# Never restart while a test is running: a restart would interrupt it. Wait up to 15 minutes.
active_runs() {
  curl -fsS --max-time 5 http://127.0.0.1:8000/api/runs 2>/dev/null \
    | python3 -c 'import sys,json; print(sum(r["status"] in ("queued","analyzing","provisioning","running","scoring") for r in json.load(sys.stdin)))' \
    2>/dev/null || echo 0
}
for i in $(seq 1 90); do
  n=$(active_runs)
  [ "$n" = "0" ] && break
  echo "Waiting for $n running test(s) to finish before deploying... (${i}/90)"
  sleep 10
done

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

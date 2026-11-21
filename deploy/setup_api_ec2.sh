#!/usr/bin/env bash
# One-time API host setup on Ubuntu 24.04 (run as ubuntu). Repo must already be cloned at ~/bharatbench
# and api/.env copied in (never committed).
set -euo pipefail
sudo apt-get update -y
sudo apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl git
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
  sudo apt-get update -y && sudo apt-get install -y caddy
fi
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
cd ~/bharatbench/api && ~/.local/bin/uv sync --frozen --no-dev
sudo cp ~/bharatbench/deploy/bharatbench-api.service /etc/systemd/system/
sudo cp ~/bharatbench/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl daemon-reload
sudo systemctl enable --now bharatbench-api
sudo systemctl reload caddy || sudo systemctl restart caddy

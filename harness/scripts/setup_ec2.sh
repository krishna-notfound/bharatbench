#!/usr/bin/env bash
# One-time setup for the BharatBench harness on Ubuntu 24.04 (EC2 with KVM). Run as the normal user (ubuntu).
# Idempotent: safe to re-run.
set -euo pipefail

ANDROID_HOME="${ANDROID_HOME:-$HOME/android-sdk}"
# Version of the cmdline-tools zip; "latest" file name pattern verified 2026-11-21 (see README).
CMDLINE_TOOLS_ZIP="${CMDLINE_TOOLS_ZIP:-commandlinetools-linux-15859902_latest.zip}"
SYSTEM_IMAGE="system-images;android-34;google_apis;x86_64"
AVD_NAME="bb_budget"

if [ ! -e /dev/kvm ]; then
  cat >&2 <<'MSG'
ERROR: /dev/kvm not found. The Android emulator needs hardware virtualization.
Use an EC2 instance type that exposes it:
  - nested-virtualization capable (8th-gen Intel such as c8i / m8i / r8i; enable it at launch), or
  - any *.metal instance (e.g. c5.metal, m5.metal).
Plain t3/m5/c5 virtual instances do NOT have /dev/kvm.
MSG
  exit 1
fi

echo "==> apt packages"
sudo apt-get update -y
sudo apt-get install -y openjdk-17-jdk-headless unzip curl ca-certificates libpulse0 libnss3 libgl1 qemu-kvm

echo "==> kvm group"
sudo usermod -aG kvm "$USER"
if [ ! -r /dev/kvm ] || [ ! -w /dev/kvm ]; then
  echo "NOTE: /dev/kvm not yet accessible to this shell; log out and back in (or run 'newgrp kvm') before start_emulator.sh"
fi

echo "==> Android cmdline-tools -> $ANDROID_HOME"
mkdir -p "$ANDROID_HOME/cmdline-tools"
if [ ! -x "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ]; then
  tmp="$(mktemp -d)"
  curl -fL --retry 3 -o "$tmp/cmdline-tools.zip" "https://dl.google.com/android/repository/${CMDLINE_TOOLS_ZIP}"
  unzip -q "$tmp/cmdline-tools.zip" -d "$tmp"
  rm -rf "$ANDROID_HOME/cmdline-tools/latest"
  mv "$tmp/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest"
  rm -rf "$tmp"
fi

export ANDROID_HOME ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

echo "==> sdkmanager licenses and packages"
yes | sdkmanager --licenses >/dev/null || true
sdkmanager "platform-tools" "emulator" "$SYSTEM_IMAGE"

echo "==> AVD $AVD_NAME"
echo no | avdmanager create avd --force -n "$AVD_NAME" -k "$SYSTEM_IMAGE" -d pixel_4

CONFIG="$HOME/.android/avd/${AVD_NAME}.avd/config.ini"
set_ini() { # set_ini key value : replace if present, else append
  if grep -q "^$1=" "$CONFIG"; then sed -i "s|^$1=.*|$1=$2|" "$CONFIG"; else echo "$1=$2" >> "$CONFIG"; fi
}
set_ini hw.ramSize 2048
set_ini disk.dataPartition.size 6G
set_ini hw.keyboard yes

echo "==> Maestro"
if ! command -v maestro >/dev/null 2>&1 && [ ! -x "$HOME/.maestro/bin/maestro" ]; then
  curl -Ls "https://get.maestro.mobile.dev" | bash
fi

echo "==> uv"
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

cat > "$HOME/bharatbench-env.sh" <<ENV
export ANDROID_HOME="$ANDROID_HOME"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="\$ANDROID_HOME/cmdline-tools/latest/bin:\$ANDROID_HOME/platform-tools:\$ANDROID_HOME/emulator:\$HOME/.maestro/bin:\$HOME/.local/bin:\$PATH"
ENV

echo
echo "Setup complete. Next: log out/in (kvm group), 'source ~/bharatbench-env.sh', then scripts/start_emulator.sh"

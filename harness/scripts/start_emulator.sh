#!/usr/bin/env bash
# Start the headless bb_budget emulator and wait until Android has fully booted. Safe to re-run.
set -euo pipefail

ANDROID_HOME="${ANDROID_HOME:-$HOME/android-sdk}"
export ANDROID_HOME ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
SERIAL="${ANDROID_SERIAL:-emulator-5554}"
LOG="${EMULATOR_LOG:-$HOME/emulator.log}"
BOOT_TIMEOUT="${BOOT_TIMEOUT:-300}"

[ -e /dev/kvm ] || { echo "ERROR: /dev/kvm missing (see setup_ec2.sh)" >&2; exit 1; }

adb start-server >/dev/null

if adb -s "$SERIAL" get-state >/dev/null 2>&1; then
  echo "Emulator $SERIAL already running"
else
  echo "Starting emulator (log: $LOG)"
  setsid nohup emulator -avd bb_budget -no-window -no-audio -no-boot-anim \
    -gpu swiftshader_indirect -no-snapshot-save >"$LOG" 2>&1 &
fi

echo "Waiting for device..."
timeout "$BOOT_TIMEOUT" adb -s "$SERIAL" wait-for-device

deadline=$((SECONDS + BOOT_TIMEOUT))
until [ "$(adb -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "ERROR: boot not completed within ${BOOT_TIMEOUT}s; see $LOG" >&2
    exit 1
  fi
  sleep 3
done

for key in window_animation_scale transition_animation_scale animator_duration_scale; do
  adb -s "$SERIAL" shell settings put global "$key" 0
done
echo "Emulator $SERIAL booted (Android $(adb -s "$SERIAL" shell getprop ro.build.version.release | tr -d '\r'))"

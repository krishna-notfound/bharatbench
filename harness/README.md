# BharatBench harness (f04)

FastAPI service that installs an APK on a headless Android emulator, applies condition profiles, crawls a
bounded journey and returns real evidence (`HarnessResult`). API: `contracts/README.md` section 4.
It is the only component that touches ADB. Binds `127.0.0.1` only; every route needs `X-Harness-Token`.

## Device kinds (f14)

`DEVICE_KIND=redroid` (default) drives an Android 12 redroid Docker container at `ANDROID_SERIAL=127.0.0.1:5555`
(no KVM needed); `DEVICE_KIND=emulator` keeps the original emulator-console mechanisms.
On redroid: budget_2gb = docker `--memory=2g` + `tc netem` on the container's host-side veth (download 2mbit/200ms,
upload policed); flaky_network = `tc netem loss 100%` 6 s on / 4 s off; low_storage is **not applied** (container
`/data` is the shared host disk); battery_saver / process_death use adb. `tc` runs via `sudo -n` (NOPASSWD drop-in
for `/usr/sbin/tc` only). Host setup: `bash deploy/setup_harness_ec2.sh` (needs `harness/.env` with `HARNESS_TOKEN`).

## Local dev (no emulator needed)

```bash
cd harness
uv sync && uv run pytest -q && uv run ruff check .
HARNESS_TOKEN=x uv run uvicorn harness.main:app --port 8110
curl -i http://127.0.0.1:8110/health                          # 401
curl -i -H "X-Harness-Token: x" http://127.0.0.1:8110/health  # 200 (adb:false without the SDK)
```

## EC2 instance guidance

- The emulator needs `/dev/kvm`. Choose a **nested-virtualization-capable** type (8th-gen Intel such as
  `c8i` / `m8i` / `r8i`, with nested virtualization enabled at launch) **or any `*.metal`** instance.
  Ordinary virtual instances (t3, m5, c5, ...) have no `/dev/kvm` and will not work.
- 4+ vCPU, 16 GB RAM, 60 GB gp3 root volume, Ubuntu 24.04 LTS.
- Security group: **only port 22** inbound. The harness listens on 127.0.0.1:8100 and is reached by SSH tunnel.

## Setup order (on the instance, as `ubuntu`)

```bash
git clone https://github.com/krishna-notfound/bharatbench && cd bharatbench/harness
bash scripts/setup_ec2.sh          # fails fast if /dev/kvm is missing
# log out and back in (kvm group), then:
source ~/bharatbench-env.sh
bash scripts/start_emulator.sh     # waits for sys.boot_completed, disables animations
cp .env.example .env && nano .env  # set a long random HARNESS_TOKEN
uv sync && uv run pytest -q        # optional sanity check
```

### systemd

```bash
sudo cp scripts/harness.service /etc/systemd/system/harness.service
sudo systemctl daemon-reload
sudo systemctl enable --now harness
journalctl -u harness -f
```

The unit assumes user `ubuntu`, repo at `/home/ubuntu/bharatbench`, SDK at `/home/ubuntu/android-sdk`; edit if different.
The emulator is started separately by `start_emulator.sh` (re-run it after a reboot); `/health` reports
`emulator_booted:false` and `POST /jobs` returns 503 until it is up.

## Laptop SSH tunnel

```bash
ssh -i secrets/<key>.pem -N -L 8100:127.0.0.1:8100 ubuntu@<ip>
```

Then the API uses `HARNESS_URL=http://127.0.0.1:8100` and the same `HARNESS_TOKEN`.

## Configuration (env / `.env`)

`HARNESS_TOKEN` (required), `ANDROID_SERIAL=emulator-5554`, `JOBS_DIR=./jobs`, `ADB_PATH=adb`, `MAESTRO_PATH=maestro`.

## Security notes

Constant-time token check (`hmac.compare_digest`) on all routes; adb/emulator invoked with argument lists only
(never `shell=True`); every subprocess has a timeout; artifact paths are resolved and must stay inside the job
dir; job ids must be 32-hex; `package_name` is regex-validated before use in adb commands; every profile revert
runs in `try/finally` and revert failures are recorded as job events, never raised.

## Verified vs assumed

Verified on 2026-11-21 (fetched from Google's servers):
- cmdline-tools URL pattern `https://dl.google.com/android/repository/commandlinetools-linux-<N>_latest.zip`;
  `<N>`=15859902 is what developer.android.com listed and returned HTTP 200 (override with `CMDLINE_TOOLS_ZIP`).
- sdkmanager package `system-images;android-34;google_apis;x86_64` exists in the Google sys-img repository.
- `https://get.maestro.mobile.dev` redirects to `storage.googleapis.com/mobile.dev/maestro/install.sh` (200);
  `https://astral.sh/uv/install.sh` reachable.
- Bash syntax of the scripts (`bash -n`); all Python behaviour via unit tests with a mocked adb.

Assumed (not run, no Android SDK/KVM on the dev machine):
- `platform-tools` and `emulator` package names; `avdmanager create avd -d pixel_4` accepting the `pixel_4` profile
  and the `echo no` answer to the custom-hardware prompt; AVD `config.ini` path/keys.
- apt extras (`libpulse0 libnss3 libgl1 qemu-kvm`) are sufficient for the headless emulator on 24.04.
- Real `uiautomator dump`, `am start -W`, `dumpsys` output on Android 14 matches the parsers (fixtures are written
  from known formats); `adb emu network speed/delay` accepted by the emulator console; `fallocate` available on the
  image (falls back to `dd`); `svc wifi` on the emulator.
- Emulator boot within 300 s and swiftshader rendering performance on the chosen instance.

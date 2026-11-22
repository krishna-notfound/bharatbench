# Limitations

## Not simulated (needs physical devices)
Thermal throttling, slow CPU (host CPU is not throttled), OEM background killers. Battery saver on redroid is
`approximated` and its effect is unverified. `low_storage` is not applied on redroid (shared host disk) and is
reported as not applied (`harness/harness/profiles.py`).

## Not built (planned or deferred)
GitHub repo -> APK build from source (import of release APKs exists), Resend emails, multi-device concurrency and a
job queue (one device, one job), Supabase Storage bucket for artifacts, a web unit-test suite.

## Not verified
Real-device behaviour is covered by mocked-adb unit tests plus a few observed runs (`docs/METRICS.md`); there is no
device-matrix acceptance run. Live LLM/STT/TTS quality, Supabase RLS against a live project, and `users_exposed`
values (assumptions) are not verified.

## Scope
Auth is implemented (Supabase guest and Google) but `AUTH_REQUIRED` is off by default, so a default deployment is
not a locked-down multi-user service. One run's APK size cap is 200 MB.

## Known inconsistencies
- The REST voice agent and the realtime engine default to different chat models (`docs/CONFIG.md`).
- `harness/scripts/` (emulator setup) is legacy; the deployed path is `deploy/setup_harness_ec2.sh` (redroid).

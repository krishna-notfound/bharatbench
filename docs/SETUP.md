# BharatBench setup guide

This guide takes a fresh Ubuntu 24.04 EC2 host to a working BharatBench stack: API behind Caddy with HTTPS,
the harness on a redroid Android 12 container, Supabase tables, and the web app on Vercel.

For local development without a server, the quick start in the [README](../README.md#quick-start) is enough.

> **Two placeholders to replace before you start:** `<EC2_HOST>` is the public IP or DNS name of the host, and
> `<API_HOST>` is the HTTPS hostname Caddy serves (for example `<dashed-ip>.sslip.io`). The current hostname is
> in `deploy/Caddyfile` and in the health check in `.github/workflows/ci-cd.yml`. Update both if the host changes.

---

## 0. What you need

| Item | Notes |
| :--- | :--- |
| EC2 instance | Ubuntu 24.04, x86_64, enough RAM and disk for the redroid container, APKs and job artifacts. The repo does not pin an instance type for redroid. |
| DNS name | `<API_HOST>` pointing at the host (sslip.io needs no DNS record; it resolves from the IP). |
| Security group | Inbound **22** (SSH), **80** and **443** (Caddy and Let's Encrypt). Do **not** open 8000 or 8100. |
| Supabase project | For `STORAGE_BACKEND=supabase`. SQLite works without it. |
| Sarvam API key | Server-side only, for the voice agent and explanations. |
| Vercel account | Hosts the web app. Connected to this GitHub repository. |

---

## 1. Base packages on the host

```bash
sudo apt-get update -y
sudo apt-get install -y git curl docker.io adb iproute2
sudo usermod -aG docker "$USER"     # log out and back in so the group applies
```

`tcpdump` and `uv` are installed by the setup scripts in step 4.

---

## 2. Clone the repository

```bash
git clone https://github.com/krishna-notfound/bharatbench.git ~/bharatbench
cd ~/bharatbench
```

The deploy scripts expect the repository at `~/bharatbench`. The systemd units expect `api/.env` and
`harness/.env` in that tree.

---

## 3. Start the redroid device

The harness drives an Android 12 device through adb at `127.0.0.1:5555`, with the container named `redroid`
(`CONTAINER_NAME` in `harness/.env`).

> **Open item.** The repository does not yet contain the exact `docker run` command for the redroid container.
> Start a redroid Android 12 container that exposes adb on host port 5555 and is named `redroid`, following the
> [redroid project documentation](https://github.com/remote-android/redroid-doc) for your kernel (redroid needs
> Android binder support on the host). Once it works, record the exact command here so the setup is reproducible.

Check the device:

```bash
adb connect 127.0.0.1:5555
adb devices                       # 127.0.0.1:5555 should show "device"
adb -s 127.0.0.1:5555 shell getprop ro.build.version.release    # expect 12
```

> `harness/scripts/setup_ec2.sh` and `harness/scripts/start_emulator.sh` are the older emulator-based path
> (`DEVICE_KIND=emulator`, needs `/dev/kvm`). The redroid path above is the default and does not need KVM.

---

## 4. Install and start the harness

```bash
cd ~/bharatbench/harness
cp .env.example .env
```

Edit `harness/.env` and set a long random secret. The same value goes into `api/.env` later.

```bash
openssl rand -hex 32              # paste the output as HARNESS_TOKEN in harness/.env
```

Run the setup script. It installs `uv` if needed, installs `tcpdump`, adds two NOPASSWD sudo drop-ins (`tc`, and one
fixed `tcpdump` call that `timeout` caps at 240 s), loads the kernel traffic-shaping modules, and installs the systemd unit:

```bash
cd ~/bharatbench
bash deploy/setup_harness_ec2.sh
sudo systemctl status bharatbench-harness --no-pager
```

The harness listens on `127.0.0.1:8100` only. Check it with the token:

```bash
curl -s -H "X-Harness-Token: $(grep ^HARNESS_TOKEN ~/bharatbench/harness/.env | cut -d= -f2-)" \
  http://127.0.0.1:8100/health
```

A response with `adb: true` and `device_status` means the lab sees the device. Otherwise check
`journalctl -u bharatbench-harness -n 50`.

---

## 5. Configure and start the API

```bash
cd ~/bharatbench/api
cp .env.example .env
```

Set these in `api/.env` (see the [README environment tables](../README.md#environment-variables)):

| Variable | Value on this host |
| :--- | :--- |
| `HARNESS_URL` | `http://127.0.0.1:8100` |
| `HARNESS_TOKEN` | the same value as in `harness/.env` |
| `SARVAM_API_KEY` | your Sarvam key |
| `CORS_ORIGINS` | `https://<your-vercel-domain>` (add `http://localhost:3000` for local testing) |
| `STORAGE_BACKEND` | `sqlite`, or `supabase` after step 7 |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | only when `STORAGE_BACKEND=supabase` |

Keep `api/.env` on the host only. Do not commit it.

---

## 6. Caddy, HTTPS and the API service

Before running the API setup, make sure `deploy/Caddyfile` names your host:

```text
<API_HOST> {
	encode gzip
	reverse_proxy 127.0.0.1:8000
}
```

Caddy obtains a Let's Encrypt certificate for that name, so ports 80 and 443 must be reachable. Then run the API
setup script. It installs Caddy and uv, syncs the API dependencies, installs the systemd unit
`deploy/bharatbench-api.service`, and reloads Caddy:

```bash
cd ~/bharatbench
bash deploy/setup_api_ec2.sh
sudo systemctl status bharatbench-api --no-pager
curl -fsS https://<API_HOST>/api/health
```

The health response reports `harness.configured` and `harness.reachable`. If `reachable` is `false`, runtime
testing is skipped, and runs still produce static findings.

---

## 7. Supabase (optional, needed for `STORAGE_BACKEND=supabase` and web sign-in)

1. Create a Supabase project.
2. Apply the migrations in `supabase/migrations/` in filename order:
   `20261121000000_bharatbench_core.sql`, then `20261121010000_users_conversations.sql`, then
   `20261121020000_revoke_rls_auto_enable_public.sql`. Either paste each file into the SQL editor, or use the
   Supabase CLI against your project.
3. From project settings, copy the project URL and the anon key (web) and the service-role key (API only).
4. Put the service-role key in `api/.env` only. Put the URL and anon key in the web environment (step 9).

The tables enable RLS with no public policies. Only the API's service-role key reads and writes them.

---

## 8. GitHub secrets for automatic API deploys

`.github/workflows/ci-cd.yml` deploys the API on each push to `main`. In the repository settings, create the
`production` environment and add:

| Secret | Value |
| :--- | :--- |
| `EC2_HOST` | the host's public IP or DNS name (used for SSH) |
| `EC2_SSH_KEY` | a private key whose public half is in `~ubuntu/.ssh/authorized_keys` on the host |

The deploy job runs `deploy/deploy_api.sh` over SSH: it resets `~/bharatbench` to `origin/main`, syncs the API
(and the harness when its unit is installed), restarts the services, and waits for `http://127.0.0.1:8000/api/health`.

> The public health check in `ci-cd.yml` uses a hard-coded sslip.io hostname. Update it when `<API_HOST>` changes.

---

## 9. Vercel (web)

1. In Vercel, import the GitHub repository.
2. Set **Root Directory** to `web`. The framework is detected as Next.js.
3. Add these environment variables for Production (and Preview if you want):

| Name | Value |
| :--- | :--- |
| `NEXT_PUBLIC_API_URL` | `https://<API_HOST>` |
| `NEXT_PUBLIC_SUPABASE_URL` | your Supabase project URL (optional) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | your Supabase anon key (optional) |

4. Deploy. Pushes to `main` deploy automatically through the GitHub integration.
5. Add the Vercel domain to `CORS_ORIGINS` in `api/.env` on the host and restart the API:
   `sudo systemctl restart bharatbench-api`.

Never put the Supabase service-role key or any Sarvam key in Vercel. Only `NEXT_PUBLIC_*` values belong there,
and they are visible to every visitor.

---

## 10. Verify end to end

```bash
curl -fsS https://<API_HOST>/api/health            # ok: true, harness.reachable reflects step 4
curl -fsS https://<API_HOST>/api/profiles          # the six profile definitions
```

Then open the Vercel URL, upload a small APK, and watch the run page. With the harness reachable, the run
executes the selected profiles and produces screenshots and logcat. Without it, the run completes with static
findings and says runtime was skipped.

---

## Troubleshooting

| Symptom | Check |
| :--- | :--- |
| `harness.reachable: false` | `sudo systemctl status bharatbench-harness`; `adb devices`; `HARNESS_URL` and `HARNESS_TOKEN` match on both sides |
| Harness returns 401 | `X-Harness-Token` header does not match `harness/.env` |
| Harness returns 409 | A job is already running (one device, one job). Wait or cancel the job |
| Caddy cannot get a certificate | DNS or sslip hostname does not point at the host, or ports 80 and 443 are closed |
| Browser CORS errors | `CORS_ORIGINS` in `api/.env` does not include the Vercel origin. Restart the API after changing it |
| Runtime says disk is low | Free space under the job directory and `DATA_DIR`; the harness refuses jobs below `HARD_MIN_FREE_MB` |
| Deploy job fails at health check | `sudo journalctl -u bharatbench-api -n 50 --no-pager` on the host |

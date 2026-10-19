# Running LiteLLM in production: HTTPS, backups, upgrades and security

This guide takes the stack from "runs on my laptop" to "runs on a server for real users". You get HTTPS with an automatic certificate, a LiteLLM admin UI that is never on the internet, a tested backup and restore procedure, a safe upgrade routine, the minimum versions that close known LiteLLM and Open WebUI security holes, and notes on monitoring and scaling.

Everything here uses Docker Compose on one server. If you want Kubernetes, LiteLLM publishes an official Helm chart (`helm install litellm oci://ghcr.io/berriai/litellm-helm -f values.yaml`, see the [LiteLLM deploy docs](https://docs.litellm.ai/docs/proxy/deploy) and the [chart source](https://github.com/BerriAI/litellm/tree/main/helm/litellm-helm), as of 2026-10-16). This repo does not ship Kubernetes manifests.

## Contents

- [Server sizing](#server-sizing)
- [HTTPS with compose.tls.yaml and DNS](#https-with-composetlsyaml-and-dns)
- [Keep LiteLLM private](#keep-litellm-private)
- [Firewall](#firewall)
- [The .env file and its secrets](#the-env-file-and-its-secrets)
- [Backups](#backups)
- [Restore test](#restore-test)
- [Upgrades](#upgrades)
- [Security advisories and minimum versions](#security-advisories-and-minimum-versions)
- [Verify images with cosign](#verify-images-with-cosign)
- [Monitoring](#monitoring)
- [Logs and log level](#logs-and-log-level)
- [Scaling](#scaling)
- [The weekly CI run](#the-weekly-ci-run)
- [Go-live checklist](#go-live-checklist)
- [Common problems](#common-problems)
- [Related guides](#related-guides)

## Server sizing

LiteLLM's production page asks for **1 vCPU and 4 GiB of memory per worker** and calls 4 GiB "a floor rather than a target", because the Prisma query engine keeps its peak memory ([LiteLLM production docs](https://docs.litellm.ai/docs/proxy/prod), as of 2026-10-16). `compose.yaml` starts LiteLLM with one worker.

Measured in this repo's test stack, idle, after the end-to-end tests (Docker Desktop, so treat it as a rough guide):

| Container | Memory |
|---|---|
| open-webui | about 780 MiB |
| litellm | about 710 MiB |
| presidio-analyzer (only with `compose.pii.yaml`) | about 1.0 GiB |
| postgres | about 85 MiB |
| redis, presidio-anonymizer | under 50 MiB each |

The images take about 7 GB of disk (Open WebUI alone is about 4 GB). A reasonable starting point for a few hundred staff is therefore **2 to 4 vCPU, 8 GiB RAM and 40 GB of disk**, more if you enable PII masking or let people upload many documents. This is our estimate from the numbers above, not a load test. Watch memory after go-live and adjust.

## HTTPS with compose.tls.yaml and DNS

`compose.tls.yaml` adds [Caddy](https://caddyserver.com/docs/automatic-https) in front of Open WebUI. Caddy requests a Let's Encrypt certificate on its own and renews it. Only Open WebUI goes through Caddy. LiteLLM is not proxied at all.

**Create the first admin before the page is public.** The first account that signs up becomes admin. If you start on a public domain and sign up afterwards, whoever reaches the page first gets admin. So start without the HTTPS overlay, create your account over an SSH tunnel, and only then add the DNS record and `compose.tls.yaml`:

```bash
docker compose up -d --wait
python3 scripts/bootstrap.py
```

On your laptop:

```bash
ssh -L 3000:127.0.0.1:3000 -L 4000:127.0.0.1:4000 your-server
```

Open <http://localhost:3000>, create your account (it becomes admin, and Open WebUI closes sign-up after it), then continue:

1. Create a DNS record (A, and AAAA if the server has IPv6) for your chat domain, for example `chat.example.com`, pointing to the server's public IP. Wait until `dig +short chat.example.com` returns that IP.
2. Open ports 80 and 443 (TCP) and 443 (UDP) in the cloud firewall. Port 80 is needed for the certificate challenge and the redirect to HTTPS.
3. Set these lines in `.env`:

   ```bash
   DOMAIN=chat.example.com
   WEBUI_URL=https://chat.example.com
   ```

4. Start the stack with both files:

   ```bash
   docker compose -f compose.yaml -f compose.tls.yaml up -d --wait
   ```

5. Open `https://chat.example.com` and log in with the admin account you created over the tunnel. Change the WebUI URL in the admin panel (see the note below), because Open WebUI stored `http://localhost:3000` on the first start.

To avoid typing the `-f` list every time (and forgetting it during an upgrade), put it into `.env`. Compose reads `COMPOSE_FILE` from there ([Docker docs](https://docs.docker.com/compose/how-tos/environment-variables/envvars/)); the CI workflow uses the same variable:

```bash
COMPOSE_FILE=compose.yaml:compose.tls.yaml
```

What the overlay does, from the repo files:

- `ports: !reset []` removes the `127.0.0.1:3000` port of Open WebUI, so the only way in is through Caddy.
- `caddy/Caddyfile` compresses responses, sets `Strict-Transport-Security "max-age=31536000"`, `X-Content-Type-Options nosniff` and `Referrer-Policy strict-origin-when-cross-origin`, and removes the `Server` header.
- Against clickjacking it sends `Content-Security-Policy "frame-ancestors 'self'"` and `X-Frame-Options SAMEORIGIN`. `Permissions-Policy "camera=(), geolocation=(), microphone=(self)"` switches off camera and location and keeps the microphone for voice input.
- Certificates live in the `caddy_data` volume. If you lose it, Caddy simply requests new ones, but Let's Encrypt has rate limits, so keep the volume.

**If Open WebUI already ran under `http://localhost:3000`:** Open WebUI writes `WEBUI_URL` into its database on the first start (key `webui.url`, read in the v0.12.2 source). A new value in `.env` is then ignored. Change it in **Admin Panel > Settings > General > WebUI URL**. Single sign-on needs the correct value ([Open WebUI env docs](https://docs.openwebui.com/reference/env-configuration), as of 2026-10-16).

## Keep LiteLLM private

`compose.yaml` publishes LiteLLM only on `127.0.0.1:4000`. Nobody outside the server can reach it, and `compose.tls.yaml` does not change that. Open WebUI talks to LiteLLM over the internal Docker network (`http://litellm:4000/v1`).

To use the LiteLLM admin UI, open an SSH tunnel from your laptop:

```bash
ssh -L 4000:127.0.0.1:4000 your-server
```

Then open `http://localhost:4000/ui`. User `admin`, password = `LITELLM_MASTER_KEY` from `.env` (tested in this repo).

Keep it that way:

- Do not change `127.0.0.1:${LITELLM_PORT:-4000}:4000` to `4000:4000`. The master key is a full admin credential for the gateway and every provider key behind it.
- The master key as UI password is "a shared cleartext admin credential meant for bootstrapping only". LiteLLM recommends per-user admin accounts and then `general_settings.disable_env_credential_login: true` ([config settings](https://docs.litellm.ai/docs/proxy/config_settings), as of 2026-10-16). This repo does not set it, because you need to create the other admin accounts first.
- `general_settings.ui_access_mode: "admin_only"` restricts the UI to admins (same source).
- Do not set `ENABLE_SSO_DEBUG`. The `/sso/debug/*` routes return 404 unless it is set (since v1.105.0).

## Firewall

On the server, allow inbound:

| Port | Why |
|---|---|
| 22/tcp | SSH, ideally only from your office or VPN IPs |
| 80/tcp | Let's Encrypt challenge and redirect to HTTPS |
| 443/tcp and 443/udp | Open WebUI through Caddy (UDP is HTTP/3) |

Nothing else. Postgres, Redis, Presidio and the Open WebUI container port are not published at all. LiteLLM is published only on the loopback interface.

Be aware that ports Docker publishes are handled by Docker's own packet filter rules, so a host firewall such as ufw does not see them the way you might expect ([Docker docs: packet filtering and firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/)). That is one more reason to keep the `127.0.0.1:` bindings and to filter in the cloud provider's firewall as well.

## The .env file and its secrets

`scripts/init-env.sh` creates `.env` with mode 600 (`umask 077`), and `.gitignore` keeps it out of git. It holds every secret the stack has:

| Variable | What breaks if you lose or change it |
|---|---|
| `LITELLM_SALT_KEY` | LiteLLM encrypts provider credentials stored in its database with it. "Set once, never change it" ([deploy docs](https://docs.litellm.ai/docs/proxy/deploy)). Without it, stored credentials are unreadable. |
| `POSTGRES_PASSWORD` | Only applied when the Postgres volume is created. A new value later means LiteLLM and Open WebUI cannot connect. |
| `WEBUI_SECRET_KEY` | Signs Open WebUI sessions and encrypts some data at rest. A new value logs everyone out. |
| `OPENWEBUI_LITELLM_KEY` | The virtual key Open WebUI uses. Open WebUI stores it in its database after the first start. |
| `LITELLM_MASTER_KEY` | Admin access to LiteLLM. Can be replaced, then restart LiteLLM. |
| `REDIS_PASSWORD` | Redis keeps no data on disk in this repo (`--save "" --appendonly no`), so a new one is harmless. |

In this repo's default setup the provider keys (for example `MISTRAL_API_KEY`) come from `.env` through `os.environ/`, not from the database, and `STORE_MODEL_IN_DB` is `"False"`. The salt key still matters as soon as anyone stores a credential through the admin UI. Treat it as unrecoverable.

Store a copy of `.env` in your password manager or secret vault, separate from the database backups.

## Backups

Back up these five things:

| What | Where it lives | How |
|---|---|---|
| LiteLLM database `litellm` (keys, budgets, end users, spend logs) | `postgres_data` volume | `pg_dump` |
| Open WebUI database `openwebui` (users, chats, settings, RAG vectors) | same Postgres, own database (`postgres/init/10-openwebui.sql`) | `pg_dump` |
| Open WebUI data directory (uploaded files, caches) | `openwebui_data` volume, mounted at `/app/backend/data` | `tar` |
| `.env` | repo root | copy to your vault |
| Your edits to `litellm/*.yaml`, `caddy/Caddyfile`, compose files | repo | commit them to your own git remote |

Redis needs no backup. Caddy's `caddy_data` volume is optional.

The script below was tested in this repo against the running stack (Postgres 16 with pgvector 0.8.1). Save it as `backup.sh` in the repo root and run it from there. It stops at the first failing command and checks that no file is empty, so a failed dump makes cron see a non-zero exit code instead of a silent 0-byte file. The volume name gets the project name as prefix (`llm-gateway` from `compose.yaml`, or `COMPOSE_PROJECT_NAME` if you set it).

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

BACKUP=/var/backups/llm-gateway/$(date +%Y-%m-%d)
VOLUME="${COMPOSE_PROJECT_NAME:-llm-gateway}_openwebui_data"
mkdir -p "$BACKUP" && chmod 700 "$BACKUP"

# Both databases, custom format (compressed, restorable with pg_restore)
docker compose exec -T postgres pg_dump -U llm -d litellm -Fc > "$BACKUP/litellm.dump"
docker compose exec -T postgres pg_dump -U llm -d openwebui -Fc > "$BACKUP/openwebui.dump"

# Open WebUI data volume, mounted read-only
docker volume inspect "$VOLUME" > /dev/null
docker run --rm -v "$VOLUME":/data:ro -v "$BACKUP":/backup alpine:3.20.9 \
  tar czf /backup/openwebui_data.tar.gz -C /data .

# Configuration and secrets (encrypt or move this file to your vault)
cp .env "$BACKUP/env.backup" && chmod 600 "$BACKUP/env.backup"

for file in litellm.dump openwebui.dump openwebui_data.tar.gz env.backup; do
  test -s "$BACKUP/$file" || { echo "backup file $file is empty" >&2; exit 1; }
done
echo "backup written to $BACKUP"
```

If you set `COMPOSE_PROJECT_NAME` in `.env` only, export it for the script too, or write the volume name into `VOLUME` directly.

`pg_dump` takes a consistent snapshot while the stack runs ([PostgreSQL docs](https://www.postgresql.org/docs/16/app-pgdump.html)), so you do not need to stop anything.

A daily cron entry, assuming you saved the script as `/opt/llm-gateway/backup.sh` and made it executable with `chmod 700` (the `purge-chats.sh` cron line in `scripts/` uses the same `/opt/llm-gateway` path):

```bash
15 2 * * * cd /opt/llm-gateway && ./backup.sh >> /var/log/llm-backup.log 2>&1
```

The `backups/` folder in the repo is in `.gitignore`, but keep scheduled backups outside the repo folder anyway, as above.

Copy the backup folder off the server (object storage, another data centre). Backups contain chats and therefore personal data: encrypt them, restrict access, and delete old ones. Chats removed by `scripts/purge-chats.sh` stay in older backups until those backups are deleted, so align the backup retention with `CHAT_RETENTION_DAYS`. See the [GDPR checklist](gdpr.md).

## Restore test

A backup you never restored is a hope, not a backup. Test the dumps on a throwaway Postgres container. This exact sequence was tested in this repo: both restores exited with code 0 and the row counts in `LiteLLM_VerificationToken` and `user` matched the live stack.

```bash
BACKUP=/var/backups/llm-gateway/2026-10-16

docker run -d --name restore-test -e POSTGRES_USER=llm -e POSTGRES_PASSWORD=x \
  -e POSTGRES_DB=litellm pgvector/pgvector:0.8.1-pg16
until docker exec restore-test pg_isready -U llm -d litellm; do sleep 1; done
# The image restarts Postgres once after its first init
sleep 3

docker exec restore-test psql -U llm -d litellm -c "CREATE DATABASE openwebui OWNER llm;"
docker exec -i restore-test pg_restore -U llm -d litellm --clean --if-exists --no-owner < "$BACKUP/litellm.dump"
docker exec -i restore-test pg_restore -U llm -d openwebui --clean --if-exists --no-owner < "$BACKUP/openwebui.dump"

# Compare with the live stack
docker exec restore-test psql -U llm -d litellm -tAc 'SELECT count(*) FROM "LiteLLM_VerificationToken";'
docker exec restore-test psql -U llm -d openwebui -tAc 'SELECT count(*) FROM "user";'

docker rm -f restore-test
```

For a real restore onto the stack (same server or a new one with the old `.env`), stop the two apps, restore, and start again. This in-place sequence was also tested by hand on a separate test stack in this repo (the `vector` extension survived, the stack came back healthy):

```bash
docker compose stop litellm open-webui
docker compose exec -T postgres pg_restore -U llm -d litellm --clean --if-exists --no-owner < "$BACKUP/litellm.dump"
docker compose exec -T postgres pg_restore -U llm -d openwebui --clean --if-exists --no-owner < "$BACKUP/openwebui.dump"
docker run --rm -v "${COMPOSE_PROJECT_NAME:-llm-gateway}_openwebui_data":/data -v "$BACKUP":/backup alpine:3.20.9 \
  sh -c 'rm -rf /data/* && tar xzf /backup/openwebui_data.tar.gz -C /data'
docker compose up -d --wait
```

On a new server, restore `.env` first, then `docker compose up -d --wait` once so Postgres creates both databases, then run the sequence above.

## Upgrades

### How LiteLLM releases work

- Stable releases are plain version tags such as `v1.105.1`. Weekly releases bump the minor number, patch numbers are hotfixes. Release candidates (`-rc.N`) get "a 7-day window for early testers" ([release cycle](https://docs.litellm.ai/docs/proxy/release_cycle), as of 2026-10-16).
- "LiteLLM supports the four most recent stable minor lines." Older lines get no fixes. On 2026-10-16 that is 1.105, 1.104, 1.103 and 1.102 ([version support](https://docs.litellm.ai/docs/enterprise/version_support)).
- LiteLLM's advice: pin one minor line, install its latest patch, move to a newer line before yours drops out of the window.
- Never use `main-latest`: it is deprecated and no longer updated. `main-stable` is deprecated too. Avoid `latest` in production ([image security docs](https://docs.litellm.ai/docs/proxy/docker_image_security)).

Open WebUI publishes versioned tags such as `v0.12.2`. Do not run `main`, `latest` or `dev` in production.

### Procedure

The versions are pinned in `compose.yaml` and can be overridden in `.env` with `LITELLM_VERSION` and `OPEN_WEBUI_VERSION`.

1. **Read the release notes** for every version between yours and the target: [LiteLLM releases](https://github.com/BerriAI/litellm/releases), [Open WebUI releases](https://github.com/open-webui/open-webui/releases). Look for breaking changes, renamed config keys and security fixes.
2. **Test with the test overlay** on a laptop or staging VM, never on the production server: the test overlay replaces your models, and the tests sign up an Open WebUI admin on a fresh stack. Use a separate clone with its own `COMPOSE_PROJECT_NAME` and ports, as in [Run the tests](quickstart.md#run-the-tests). The mock LLM costs nothing. Put the new versions into the first line:

   ```bash
   export LITELLM_VERSION=v1.105.1 OPEN_WEBUI_VERSION=v0.12.2
   docker compose -f compose.yaml -f compose.pii.yaml -f compose.test.yaml up -d --wait
   python3 scripts/bootstrap.py
   python3 -m venv .venv && .venv/bin/pip install pytest pyyaml
   .venv/bin/pytest tests
   ```

   The 15 tests in `tests/test_gateway.py` check budgets, rate limits, model access, fallbacks, per-user spend, the route restriction of the Open WebUI key, prompt storage and PII masking. The Open WebUI sign-up tests need a fresh stack (`docker compose ... down -v` first, test machine only).
3. **Pin** the new versions in `.env` on the server:

   ```bash
   LITELLM_VERSION=v1.105.1
   OPEN_WEBUI_VERSION=v0.12.2
   ```

4. **Back up** (see [Backups](#backups)). Both apps migrate their database schema on start.
5. **Pull and start:**

   ```bash
   docker compose pull litellm open-webui
   docker compose up -d --wait
   ```

6. **Check:** `docker compose ps` shows every service as healthy, `curl -s http://127.0.0.1:4000/health/readiness` returns `"db":"connected"`, and a chat in Open WebUI works.

### Rolling back

Rolling back to an older image after a schema migration is not just a tag change. LiteLLM documents cleaning up `_prisma_migrations` ([rollback guide](https://docs.litellm.ai/docs/troubleshoot/rollback)), and Open WebUI warns that downgrading migrations "can cause permanent data loss" ([Open WebUI migration docs](https://docs.openwebui.com/troubleshooting/manual-database-migration)). The simplest safe rollback is: old version tags in `.env`, restore the backup from step 4, start. Never change `LITELLM_SALT_KEY` during a rollback.

## Security advisories and minimum versions

Both projects publish many advisories. LiteLLM had 17 repository advisories plus 42 entries in the GitHub advisory database for the pip package, and Open WebUI had 165 [security advisories](https://github.com/open-webui/open-webui/security/advisories), 158 of them published in 2026 (queried 2026-10-16). Pinning old versions is not "stable", it is unpatched.

### Minimum versions (as of 2026-10-16)

| Component | Pinned in this repo | Do not run below |
|---|---|---|
| LiteLLM | `v1.105.1` | `1.102.2` on a supported line (1.102 to 1.105). Never `1.82.7` or `1.82.8`. |
| Open WebUI | `v0.12.2` | `0.11.4` (fixed 19 advisories, including session token theft from any website, GHSA-vpq8-f445-hcq7) |
| Postgres | `pgvector/pgvector:0.8.1-pg16` | |
| Redis | `redis:7.4.11-alpine` | LiteLLM needs Redis 7.0 or newer |

The LiteLLM floor of 1.102.2 comes from the newest critical advisory. Selected LiteLLM advisories:

| Advisory | Severity | Issue | Fixed in |
|---|---|---|---|
| [GHSA-7hp6-4w63-5g45](https://github.com/BerriAI/litellm/security/advisories/GHSA-7hp6-4w63-5g45) | critical | Privilege escalation to proxy_admin and remote code execution via salt key reuse | 1.100.4, 1.101.3, 1.102.2, 1.103.1 |
| [GHSA-g5ff-637f-6q2m](https://github.com/BerriAI/litellm/security/advisories/GHSA-g5ff-637f-6q2m) | high | `internal_user_viewer` can read local files, which can disclose `LITELLM_MASTER_KEY` and provider keys | 1.95.0 |
| [GHSA-4xpc-pv4p-pm3w](https://github.com/advisories/GHSA-4xpc-pv4p-pm3w) (CVE-2026-49468) | critical | Authentication bypass via Host header injection | 1.84.0 |
| [GHSA-r75f-5x8p-qvmc](https://github.com/advisories/GHSA-r75f-5x8p-qvmc) (CVE-2026-42208) | critical | SQL injection in API key verification | 1.83.7 |
| [GHSA-jjhc-v7c2-5hh6](https://github.com/advisories/GHSA-jjhc-v7c2-5hh6) (CVE-2026-35030) | critical | Auth bypass via OIDC userinfo cache key collision | 1.83.0 |
| [GHSA-wxxx-gvqv-xp7p](https://github.com/advisories/GHSA-wxxx-gvqv-xp7p) (CVE-2026-40217) | high | Sandbox escape in the custom code guardrail | 1.83.10 |

For GHSA-7hp6-4w63-5g45 the advisory says versions after 1.91.0 "are exploitable in the default configuration". If you cannot upgrade at once, the documented workaround is `EXPERIMENTAL_UI_LOGIN=false`, which also breaks CLI SSO login. Upgrading is the fix.

No published advisory targeted Open WebUI 0.12.x on 2026-10-16, but the v0.12.0 notes say some security fixes "may be withheld for a short time". Watch the [Open WebUI advisories](https://github.com/open-webui/open-webui/security/advisories) and the [LiteLLM advisories](https://github.com/BerriAI/litellm/security/advisories). On GitHub you can "Watch > Custom > Security alerts" on both repos.

### The March 2026 supply-chain incident

On 2026-03-25 LiteLLM published [GHSA-5mg7-485q-xm76](https://github.com/advisories/GHSA-5mg7-485q-xm76) (critical): "Two LiteLLM versions published containing credential harvesting malware". After an API token was exposed through a compromised Trivy dependency, versions **1.82.7 and 1.82.8** were uploaded to PyPI with malware that ran automatically, harvested credentials and files, and sent them to a remote server. The advisory says: "Anyone who has installed and run the project should assume any credentials available to litellm environment may have been exposed, and revoke/rotate them accordingly."

What it means for you:

- Both versions are gone from PyPI. This repo uses the Docker image, pinned to `v1.105.1`, not `pip install litellm`.
- If any machine of yours ever ran 1.82.7 or 1.82.8 (for example a developer laptop with `pip install litellm` in March 2026), rotate every provider key, database password and master key that process could read.
- Since then LiteLLM signs its Docker images with cosign and pins its base images by digest. Use that (next section).

## Verify images with cosign

LiteLLM signs every image on `ghcr.io/berriai/` with cosign since v1.83.0. The public key was added in commit `0112e53`. The release notes of v1.105.1 give this command ([release v1.105.1](https://github.com/BerriAI/litellm/releases/tag/v1.105.1)); install cosign first ([Sigstore docs](https://docs.sigstore.dev/cosign/system_config/installation/)):

```bash
cosign verify \
  --key https://raw.githubusercontent.com/BerriAI/litellm/0112e53046018d726492c814b3644b7d376029d0/cosign.pub \
  ghcr.io/berriai/litellm:v1.105.1
```

The expected output includes "The signatures were verified against the specified public key" ([image security docs](https://docs.litellm.ai/docs/proxy/docker_image_security)). We copied the command from the release notes and did not run cosign in this repo.

Tags can in theory be moved. A digest cannot. Pin the digest after you verified the tag:

```bash
docker pull ghcr.io/berriai/litellm:v1.105.1
docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/berriai/litellm:v1.105.1
# ghcr.io/berriai/litellm@sha256:<digest>
```

Because `compose.yaml` builds the image name as `ghcr.io/berriai/litellm:${LITELLM_VERSION}`, you can put tag and digest together into `.env`. We checked with `docker compose config` that the result is a valid reference:

```bash
LITELLM_VERSION=v1.105.1@sha256:<digest>
```

For Open WebUI we found no signing key or verification command in the sources we used. Check the [Open WebUI releases page](https://github.com/open-webui/open-webui/releases) and the project's documentation for current information on image provenance. Until then, pin the tag and, if you like, the digest the same way (`OPEN_WEBUI_VERSION=v0.12.2@sha256:<digest>`).

## Monitoring

### Health endpoints

| URL | Auth | What it tells you |
|---|---|---|
| `http://127.0.0.1:4000/health/liveliness` | none | LiteLLM process is up (`"I'm alive!"`). `/health/liveness` is an alias. |
| `http://127.0.0.1:4000/health/readiness` | none | LiteLLM can reach its database: `{"status":"healthy","db":"connected"}`, 503 if the database is unreachable. The compose healthcheck uses this. |
| `http://127.0.0.1:4000/health` | key | Sends a real test request to every model, so it costs tokens. Do not poll it every minute. |
| `https://chat.example.com/health` | none | Open WebUI is up: `{"status":true}`. Reachable from outside through Caddy. |

We called `/health/liveliness`, `/health/readiness` and the Open WebUI `/health` (on `localhost`) in this repo. The authenticated `/health` is described from the [LiteLLM health docs](https://docs.litellm.ai/docs/proxy/health).

A simple setup: an external uptime monitor on `https://chat.example.com/health`, and a cron job on the server that calls `/health/readiness` and alerts on anything other than HTTP 200. `docker compose ps` shows the healthcheck status of every container.

### Prometheus

Prometheus metrics are **not enabled** in this repo. The LiteLLM docs list them as open source (no enterprise banner, not in the enterprise feature list) and the client library is already in the image ([Prometheus docs](https://docs.litellm.ai/docs/proxy/prometheus), as of 2026-10-16). Older LiteLLM versions gated Prometheus behind the enterprise licence. We searched the Prometheus modules of the v1.105.1 image and found no licence check, but we did not run it.

To enable it, add to `litellm_settings` in `litellm/config.yaml`:

```yaml
litellm_settings:
  callbacks:
    - prometheus
```

Metrics are then at `/metrics` on port 4000. In v1.105.1 the endpoint requires a LiteLLM key (`Authorization: Bearer sk-...`) unless you set `litellm_settings.require_auth_for_metrics_endpoint: false`. Run Prometheus on the same Docker network or through the SSH tunnel, never by publishing port 4000.

Also watch spend (`/key/info`, `/customer/info`, see [troubleshooting](troubleshooting.md#debug-commands)) and disk: Postgres grows with chats and with spend logs, which this repo purges after 90 days (`maximum_spend_logs_retention_period: "90d"`).

## Logs and log level

Every service uses the Docker `json-file` driver with rotation (`max-size: "10m"`, `max-file: "3"`), so logs cannot fill the disk. Read them with:

```bash
docker compose logs --tail 200 litellm
docker compose logs -f open-webui
```

`compose.yaml` sets `LITELLM_LOG: ERROR` and `LITELLM_MODE: PRODUCTION` in the `environment:` block of LiteLLM, as the [LiteLLM production docs](https://docs.litellm.ai/docs/proxy/prod) recommend. Because the `environment:` block wins over `env_file: .env`, putting `LITELLM_LOG=DEBUG` into `.env` has no effect. Use a small override file instead (we checked the merge with `docker compose config`):

```yaml
# compose.debug.yaml (your own file, not part of the repo)
services:
  litellm:
    environment:
      LITELLM_LOG: DEBUG
  open-webui:
    environment:
      GLOBAL_LOG_LEVEL: DEBUG
```

```bash
docker compose -f compose.yaml -f compose.tls.yaml -f compose.debug.yaml up -d
```

`GLOBAL_LOG_LEVEL` is Open WebUI's level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`, default `INFO`). We have not checked which request fields each debug level prints. Treat debug logs as possibly containing personal data and switch back when you are done. LiteLLM's message logging to callbacks is off in this repo (`turn_off_message_logging: true`), which is a separate setting from the log level.

## Scaling

One server with one LiteLLM worker is enough for many organisations: the gateway mostly waits on the model provider. When you need more:

**More LiteLLM capacity on the same machine.** LiteLLM's docs say that on a single VM you can set `NUM_WORKERS` to the number of vCPUs ([production docs](https://docs.litellm.ai/docs/proxy/prod)). Memory and database connections scale per worker (4 GiB floor and `database_connection_pool_limit`, default 10, per worker).

**Several LiteLLM instances.** Redis is already wired for this. `router_settings` in `litellm/config.yaml` points to the `redis` service, so rate limit counters and cooldowns are shared. LiteLLM says to run Redis "as soon as you run more than one proxy instance". For more than one instance also note:

- Only one instance should run database migrations. LiteLLM uses `DISABLE_SCHEMA_UPDATE="true"` on the others ([deploy docs](https://docs.litellm.ai/docs/proxy/deploy)).
- `docker compose up --scale litellm=2` will not work as is, because every replica would try to bind `127.0.0.1:4000`.
- Redis here has no persistence (`--save ""`, `--appendonly no`). A Redis restart resets rate limit windows. Budgets are safe because spend is stored in Postgres.

**Open WebUI.** `compose.yaml` already sets `REDIS_URL`, `WEBSOCKET_MANAGER: redis` and `ENABLE_WEBSOCKET_SUPPORT`, which Open WebUI calls "Required for Multi-Worker and Multi-Node Deployments", and `WEBUI_SECRET_KEY` comes from `.env`, so every replica shares it.

**Beyond one server**, move to Kubernetes with the LiteLLM Helm chart and a managed Postgres. That is outside this repo.

## The weekly CI run

`.github/workflows/e2e.yml` runs on every push to `main`, on pull requests, and on a schedule every Monday at 05:17 UTC (`cron: "17 5 * * 1"`). The comment says why: "to notice when a pinned image disappears or upstream behaviour changes". It has two jobs:

- **static**: runs `tests/test_config_files.py` (secrets only from `os.environ/`, EU endpoints, prices set, fallbacks valid, settings not in included files, no `latest` or `main*` tags) and validates every compose combination and the Caddyfile.
- **e2e**: starts the full stack with the mock LLM and PII masking (`docker compose up -d --wait --wait-timeout 600`), runs `scripts/bootstrap.py` and all tests, and prints the last 200 log lines on failure.

The actions are pinned to commit SHAs (with the version in a comment), checkouts use `persist-credentials: false`, both jobs have `timeout-minutes`, and `pytest` and `pyyaml` are pinned. The run uses the pinned versions, so it does not test new releases for you. It tells you when a pinned tag vanished from the registry, or when GitHub's Docker version stops accepting the compose files. If you fork the repo, enable Actions and turn on failure notifications. For new versions use the test procedure in [Upgrades](#upgrades); you can also start the workflow by hand (`workflow_dispatch`).

## Go-live checklist

- [ ] DNS record set, `DOMAIN` and `WEBUI_URL=https://...` in `.env`, `COMPOSE_FILE` includes `compose.tls.yaml`.
- [ ] Firewall: only 22, 80, 443 inbound. LiteLLM still on `127.0.0.1:4000`.
- [ ] First Open WebUI account created by you over the SSH tunnel, before the domain was public (it becomes admin).
- [ ] `scripts/bootstrap.py` ran, budgets in `.env` match what you want.
- [ ] Prices for every model in `litellm/models.yaml` checked.
- [ ] `.env` copied to the vault.
- [ ] Backup cron running, off-site copy, one restore test done.
- [ ] `scripts/purge-chats.sh --apply` in cron with your `CHAT_RETENTION_DAYS`.
- [ ] Uptime monitor on `/health`, alert on `/health/readiness`.
- [ ] Watching security advisories of both projects. Versions at or above the minimums.
- [ ] Optional: [single sign-on with Entra ID](sso-entra-id.md).

## Common problems

**Caddy does not get a certificate.** Check that the DNS record points to this server and ports 80 and 443 are open in every firewall on the path. `docker compose logs caddy` shows the ACME error.

**Open WebUI suddenly reachable on port 3000 again, or not at all.** You started without `-f compose.tls.yaml`. Set `COMPOSE_FILE` in `.env`.

**Upgrade fails or the stack is unhealthy afterwards.** `docker compose logs litellm open-webui`, then follow [Rolling back](#rolling-back).

More in [LiteLLM and Open WebUI troubleshooting](troubleshooting.md).

## Related guides

- [LiteLLM and Open WebUI troubleshooting: common errors and fixes](troubleshooting.md)
- [Open WebUI single sign-on with Microsoft Entra ID](sso-entra-id.md)
- [LiteLLM config.yaml explained](configuration.md)
- [GDPR checklist for an internal LLM gateway](gdpr.md)
- [LiteLLM budgets and rate limits](budgets.md)
- [PII masking with Presidio and LiteLLM](pii-masking.md)
- [LiteLLM open source vs enterprise](open-source-vs-enterprise.md)

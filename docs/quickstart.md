# Install LiteLLM proxy and Open WebUI: step-by-step Docker Compose setup

This guide takes you from an empty server to a working, ChatGPT-like chat in about 10 minutes. You run the LiteLLM Proxy and Open WebUI with Docker Compose, connect one model provider, log in as admin and make a first API call with a LiteLLM virtual key. Along the way it explains why the defaults in this repo are what they are, so you know what you can change safely.

Versions used and tested in this repo: LiteLLM v1.105.1, Open WebUI v0.12.2, Postgres 16 with pgvector 0.8.1, Redis 7.4.

## Contents

- [What you get](#what-you-get)
- [Prerequisites](#prerequisites)
- [1. Clone the repo](#1-clone-the-repo)
- [2. Create the .env file](#2-create-the-env-file)
- [3. Add a provider key](#3-add-a-provider-key)
- [4. Start the stack](#4-start-the-stack)
- [5. Register the Open WebUI key and budgets](#5-register-the-open-webui-key-and-budgets)
- [6. First login to Open WebUI](#6-first-login-to-open-webui)
- [7. The LiteLLM admin UI](#7-the-litellm-admin-ui)
- [8. First API call with a virtual key](#8-first-api-call-with-a-virtual-key)
- [Switching to another provider](#switching-to-another-provider)
- [What each container does](#what-each-container-does)
- [Ports](#ports)
- [Stop, restart, reset](#stop-restart-reset)
- [Why the defaults are what they are](#why-the-defaults-are-what-they-are)
- [Common problems](#common-problems)
- [Next steps](#next-steps)
- [Run the tests](#run-the-tests)
- [Related guides](#related-guides)

## What you get

```text
Browser --> Open WebUI (127.0.0.1:3000) --> LiteLLM Proxy (127.0.0.1:4000) --> your model provider
                 |                                 |
                 +------ Postgres + pgvector ------+
                 +------ Redis (shared state) -----+
```

- **Open WebUI** is the chat interface for your staff: accounts, chats, file uploads, document search.
- **LiteLLM Proxy** is the gateway in between. It holds the provider keys, enforces budgets and rate limits, tracks spend per user and gives every client one OpenAI-compatible API.
- Open WebUI never sees a provider key. It talks to LiteLLM with one virtual key that has its own budget.

## Prerequisites

| Item | Requirement |
|---|---|
| Docker | Docker Engine with Docker Compose v2.24 or newer (`docker compose version`) |
| RAM | About 4 GB for the base stack, about 8 GB with PII masking |
| Disk | A few GB for images and the Postgres volume |
| Tools | `git`, `openssl` (used by `init-env.sh`, which stops if it is missing), `python3` (for `bootstrap.py`, standard library only; the tests need a virtual environment, see [Run the tests](#run-the-tests)), `curl` |
| Provider | An API key for one model provider. The default is Mistral via its EU endpoint. |

Why Compose v2.24 or newer: the HTTPS overlay `compose.tls.yaml` uses the `!reset` YAML tag to remove the published port of Open WebUI, so it is only reachable through the reverse proxy. Older Compose versions do not understand that tag. See the Docker docs on [merging Compose files](https://docs.docker.com/reference/compose-file/merge/).

On macOS the default shell is zsh. It treats `#` at the start of a pasted line as a command, not a comment, unless you run `setopt interactivecomments` first. The commands in these guides keep comments on their own lines, so at worst zsh prints `command not found: #` and carries on.

Why these RAM numbers: measured idle memory on a fresh stack in this repo was about 0.9 GB for Open WebUI and 0.8 GB for LiteLLM, with Postgres and Redis below 100 MB each. The German Presidio analyzer for PII masking adds about 1 GB on top. The 4 GB and 8 GB figures leave headroom for the operating system, uploads and load.

## 1. Clone the repo

```bash
git clone https://github.com/pexon-consulting/litellm-open-webui
cd litellm-open-webui
```

## 2. Create the .env file

```bash
./scripts/init-env.sh
```

The script writes `.env` with random secrets and file mode 600 (`umask 077`). It never overwrites an existing `.env`, and it stops with an error if `openssl` is missing or a secret comes out empty. It creates:

| Variable | What it is |
|---|---|
| `LITELLM_MASTER_KEY` | LiteLLM admin key, starts with `sk-`. Also the password of the LiteLLM admin UI. |
| `LITELLM_SALT_KEY` | Encrypts provider credentials that LiteLLM stores in its database. Set once, never change it. |
| `OPENWEBUI_LITELLM_KEY` | The virtual key Open WebUI uses to call LiteLLM. |
| `POSTGRES_PASSWORD`, `REDIS_PASSWORD` | Internal passwords. |
| `WEBUI_SECRET_KEY` | Signs Open WebUI sessions and encrypts sensitive data at rest. |
| `USER_BUDGET_USD`, `USER_BUDGET_PERIOD` | Default budget per Open WebUI user (20 USD, reset monthly on the 1st; the first period is shorter). |
| `OPENWEBUI_BUDGET_USD`, `OPENWEBUI_BUDGET_PERIOD` | Cap for all Open WebUI traffic together (500 USD, reset monthly on the 1st). |
| `WEBUI_URL` | Public URL of Open WebUI, `http://localhost:3000` by default. |

Keep `.env` out of git. The repo's `.gitignore` already excludes it.

## 3. Add a provider key

Open `.env` and fill in the key for the provider in `litellm/models.yaml`. The default file uses Mistral's EU endpoint (`api.eu.mistral.ai`):

```bash
MISTRAL_API_KEY=your-key-here
```

The default `models.yaml` offers three models: `mistral-small`, `mistral-medium` and `embedding` (used by Open WebUI for document search). If you want a different provider, do the [provider switch](#switching-to-another-provider) now, before the first start.

## 4. Start the stack

```bash
docker compose up -d --wait
```

`--wait` blocks until every container reports healthy. The start order is enforced by health checks: Postgres and Redis first, then LiteLLM (healthy when `/health/readiness` answers), then Open WebUI. The first start takes longer because the images are pulled.

Check the result:

```bash
docker compose ps
curl -s http://localhost:4000/health/readiness
```

The readiness endpoint answers without a key and should return `{"status":"healthy","db":"connected"}` (tested in this repo). See the [LiteLLM health docs](https://docs.litellm.ai/docs/proxy/health).

With PII masking (names, e-mail addresses, IBANs are replaced before the prompt leaves your network), start with the overlay instead:

```bash
docker compose -f compose.yaml -f compose.pii.yaml up -d --wait
```

The first run builds a custom Presidio analyzer image with the German spaCy model. Details are in [PII masking with Presidio](pii-masking.md).

## 5. Register the Open WebUI key and budgets

```bash
python3 scripts/bootstrap.py
```

This script talks to LiteLLM with the master key and does two things:

1. It creates or updates the budget `per-user-default` (default 20 USD with period `30d`, which LiteLLM resets monthly on the 1st; the first period is shorter, see [Budgets](budgets.md#budget_duration-and-reset-dates)). `config.yaml` assigns this budget to every Open WebUI user who has no budget of their own, via `litellm_settings.max_end_user_budget_id`. No enterprise license is needed (tested in this repo).
2. It registers `OPENWEBUI_LITELLM_KEY` as a virtual key with the alias `open-webui` and its own budget (default 500 USD, reset monthly on the 1st). The key may only call the LLM API routes (`allowed_routes: ["llm_api_routes"]`): chat, embeddings and the model list work, management endpoints such as `/key/generate` answer 403 (tested in this repo).

The script is safe to run again. Run it whenever you change the budget values in `.env`. For variables that are in `.env`, the `.env` value wins over a variable exported in your shell; the script prints a one-line warning to stderr when the two differ. Expected output:

```text
Created budget per-user-default: 20.0 USD per user, period 30d
Created key open-webui: 500.0 USD for all Open WebUI traffic, period 30d
```

Without this step Open WebUI has a key that LiteLLM does not know, and the model list stays empty.

Anyone who holds the Open WebUI key can send any `X-OpenWebUI-User-Id` header and spend another person's budget. Do not reuse that key for other clients; see the trust model in [Open WebUI with LiteLLM](open-webui.md#trust-model-for-the-key-and-the-user-header).

## 6. First login to Open WebUI

Open [http://localhost:3000](http://localhost:3000) and create an account. **The first account becomes admin.** Do this right away on a new server, before anyone else can reach the page.

What happens next (tested in this repo with Open WebUI v0.12.2):

- After the first account exists, Open WebUI switches sign-up off in its own database, even though `compose.yaml` sets `ENABLE_SIGNUP=true`. Further sign-ups get HTTP 403.
- To let colleagues register, switch sign-up on in **Admin Panel > Settings > General**. New accounts then have the role `pending` (`DEFAULT_USER_ROLE=pending`) and wait until an admin approves them.

Pick `mistral-small` in the model selector and send a message. If you get an answer, the whole chain works: Open WebUI, LiteLLM, provider.

More on users, roles and the settings that matter: [Open WebUI with LiteLLM](open-webui.md).

## 7. The LiteLLM admin UI

Open [http://localhost:4000/ui](http://localhost:4000/ui).

- User: `admin`
- Password: the value of `LITELLM_MASTER_KEY` in `.env`

Here you see keys, spend, budgets and end users. Per-user spend from Open WebUI shows up as "customers" (end users), identified by the Open WebUI user id.

The LiteLLM docs describe this env-based login as a shared cleartext admin credential meant for bootstrapping, and recommend per-user admin accounts plus `general_settings.disable_env_credential_login: true` for production ([config settings](https://docs.litellm.ai/docs/proxy/config_settings), as of 2026-10-16). Note that SSO for the LiteLLM admin UI is free for up to 5 users; beyond that it needs a LiteLLM Enterprise license ([LiteLLM enterprise page](https://docs.litellm.ai/docs/enterprise), as of 2026-10-16).

## 8. First API call with a virtual key

Never give the master key to an application. Create a virtual key with a model list and a budget instead. Load the master key into your shell without printing it:

```bash
export LITELLM_MASTER_KEY=$(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2)
```

Create a key that may only use `mistral-small`, with a budget of 1 USD (`30d`, reset monthly on the 1st):

```bash
curl -s http://localhost:4000/key/generate \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key_alias": "first-test", "models": ["mistral-small"], "max_budget": 1, "budget_duration": "30d"}'
```

The answer contains `"key": "sk-..."`. Store it in a variable:

```bash
export TEST_KEY=sk-paste-the-key-here
```

Send a chat request. The API is OpenAI-compatible, so any OpenAI SDK works with `base_url=http://localhost:4000/v1`:

```bash
curl -s http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $TEST_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "mistral-small", "messages": [{"role": "user", "content": "Say hello in German."}]}'
```

With the PII overlay (`compose.pii.yaml`) running, this sample prompt reaches the provider as `<PERSON> in <LOCATION>.`, because the German analyzer with threshold 0 tags "Say hello" and "German" (tested in this repo). That is a known false positive, not an error; see [PII masking](pii-masking.md).

What the key enforces (all tested in this repo, see `tests/test_gateway.py`):

- A model not in the key's `models` list returns HTTP 403, and the request never reaches the provider.
- An `rpm_limit` on the key returns HTTP 429 when exceeded.
- An exceeded budget returns HTTP 422 with `error.type` `budget_exceeded` in LiteLLM v1.105.1. The LiteLLM docs say 429, so handle both in clients. The first request on a fresh, tiny budget passes, because no spend exists yet.

Delete the test key when you are done:

```bash
curl -s http://localhost:4000/key/delete \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"keys\": [\"$TEST_KEY\"]}"
```

Budgets, rate limits and per-user spend in depth: [Budgets](budgets.md).

## Switching to another provider

The repo ships ready-made model files in `examples/providers/`:

| File | Provider | Key variables in `.env` |
|---|---|---|
| `mistral.yaml` | Mistral, EU endpoint | `MISTRAL_API_KEY` |
| `azure-openai.yaml` | Azure OpenAI, EU Data Zone | `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION` |
| `aws-bedrock.yaml` | AWS Bedrock, `eu.` inference profiles | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| `google-vertex.yaml` | Google Vertex AI, `eu` multi-region | `VERTEX_PROJECT`, `VERTEX_CREDENTIALS` |
| `openai-eu.yaml` | OpenAI with European data residency | `OPENAI_EU_API_KEY` |
| `stackit.yaml` | STACKIT AI Model Serving | `STACKIT_AI_TOKEN` |
| `ionos.yaml` | IONOS AI Model Hub | `IONOS_API_TOKEN` |
| `ovhcloud.yaml` | OVHcloud AI Endpoints | `OVHCLOUD_API_KEY` |
| `scaleway.yaml` | Scaleway Generative APIs | `SCW_SECRET_KEY` |
| `t-systems.yaml` | T-Systems LLM Hub | `TSYSTEMS_LLMHUB_API_KEY` |
| `self-hosted.yaml` | vLLM or Ollama | `VLLM_API_BASE` |

To switch:

1. Copy the file over `litellm/models.yaml` (or copy single entries into it).
2. Add the provider key to `.env`, for example `STACKIT_AI_TOKEN=...`.
3. Uncomment the `embedding` entry in the new file (or follow the note there if the provider has none), and update `router_settings.fallbacks` in `litellm/config.yaml`. Both are explained in the checks below.
4. Run the static checks before you restart: `.venv/bin/pytest tests/test_config_files.py` (virtual environment as in [Run the tests](#run-the-tests)). They fail if a fallback points to a missing model or there is no `embedding` model.
5. Restart LiteLLM.

```bash
cp examples/providers/stackit.yaml litellm/models.yaml
.venv/bin/pytest tests/test_config_files.py
docker compose up -d --force-recreate litellm
```

`--force-recreate` makes sure the container picks up the new `.env` values; a plain restart does not reload `env_file`.

Three things to check after a switch:

1. **Keep a model called `embedding`.** Open WebUI uses it for document search (`RAG_EMBEDDING_MODEL=embedding` in `compose.yaml`). Every file in `examples/providers/` has a commented `embedding` entry, or a note that the provider has none and which alternative to use. Without it, document upload and search fail, and LiteLLM gives no warning. Documents uploaded with the old embedding model must be embedded again.
2. **Fix the fallback.** `config.yaml` contains `fallbacks: - mistral-medium: ["mistral-small"]`. Model names that do not exist in your new `models.yaml` must be changed there too. The static test `tests/test_config_files.py` checks this.
3. **Check prices.** LiteLLM can only enforce budgets if it knows what a token costs. Providers without built-in prices (STACKIT, IONOS, T-Systems, Scaleway, self-hosted) need `input_cost_per_token` and `output_cost_per_token`, or spend stays 0 and budgets never trigger. LiteLLM has no currency: the EUR prices in some example files are just numbers, so do not mix them with USD-priced models in one budget.

The [configuration guide](configuration.md) explains every key in these files.

## What each container does

| Service | Image | Job | Data |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:0.8.1-pg16` | Database `litellm` (keys, budgets, spend) and database `openwebui` (users, chats, settings, document vectors) | Volume `postgres_data` |
| `redis` | `redis:7.4.11-alpine` | Shared state: LiteLLM rate limits and cooldowns, Open WebUI websockets | None, persistence is off |
| `litellm` | `ghcr.io/berriai/litellm:v1.105.1` | The gateway on port 4000 | Config files mounted read-only from `litellm/` |
| `open-webui` | `ghcr.io/open-webui/open-webui:v0.12.2` | The chat UI on port 8080 inside, 3000 outside | Volume `openwebui_data` (uploads, cache) |

Optional overlays add more:

- `compose.pii.yaml`: `presidio-analyzer` (custom image with German NLP model) and `presidio-anonymizer`.
- `compose.tls.yaml`: `caddy` as HTTPS reverse proxy with an automatic Let's Encrypt certificate.
- `compose.entra.yaml`: no new container, it adds Microsoft Entra ID login to Open WebUI.
- `compose.test.yaml`: `mock-llm`, a local fake model for tests. It costs nothing and needs no provider key.

Postgres creates the second database `openwebui` with the `vector` extension through `postgres/init/10-openwebui.sql`. That script runs only once, on the first start with an empty volume.

## Ports

| Port on the host | Service | Bound to |
|---|---|---|
| 3000 | Open WebUI | `127.0.0.1` only |
| 4000 | LiteLLM API and admin UI | `127.0.0.1` only |
| 8000 | Mock LLM (only with `compose.test.yaml`), change with `MOCK_LLM_PORT` | `127.0.0.1` only |
| none | Postgres, Redis, Presidio | Not published, internal network only |

Everything is bound to `127.0.0.1`, so nothing is reachable from other machines by default. That is on purpose: Open WebUI over plain HTTP should not face your network, and the LiteLLM admin UI should never face the internet. Change ports with `OPEN_WEBUI_PORT` and `LITELLM_PORT` in `.env`.

For real users, use the HTTPS overlay. It publishes only Caddy on ports 80 and 443, removes the host port of Open WebUI, and keeps LiteLLM on `127.0.0.1:4000`. You reach the LiteLLM admin UI through an SSH tunnel:

```bash
ssh -L 4000:127.0.0.1:4000 your-server
```

Then open <http://localhost:4000/ui> on your laptop.

## Stop, restart, reset

| Command | Effect |
|---|---|
| `docker compose stop` | Stop the containers, keep everything |
| `docker compose start` | Start them again |
| `docker compose down` | Remove containers and network, keep the volumes |
| `docker compose down -v` | Remove containers AND volumes: full reset |

What `down -v` deletes, without asking:

- The Postgres volume: all LiteLLM keys, budgets and spend history, and all Open WebUI users, chats, settings and document vectors.
- The Open WebUI volume: uploaded files and caches.

After `down -v`, the next `up` is a fresh install: run `python3 scripts/bootstrap.py` again, and the first account you create becomes admin again. `.env` survives, because it is a file in the repo folder, not a volume.

Redis keeps no data on disk in this setup (`--save ""` and `--appendonly no`). Rate-limit counters and cooldowns start from zero after every Redis restart. Spend and budgets are in Postgres, so they survive.

If you overlay files, use the same `-f` list for `down` as for `up`, or set it once:

```bash
export COMPOSE_FILE=compose.yaml:compose.pii.yaml
docker compose up -d --wait
docker compose down
```

## Why the defaults are what they are

**Pinned image versions.** `compose.yaml` uses `ghcr.io/berriai/litellm:v1.105.1` and `ghcr.io/open-webui/open-webui:v0.12.2`, never a moving tag. A moving tag changes under you on the next `docker compose pull`, including database migrations you did not plan for. The LiteLLM docs say to "pin a version tag rather than `latest` or a moving tag" ([deploy docs](https://docs.litellm.ai/docs/proxy/deploy), as of 2026-10-16). The static test `test_images_are_pinned` fails if any compose file uses `latest` or a tag starting with `main`. You can override the versions with `LITELLM_VERSION` and `OPEN_WEBUI_VERSION` in `.env`.

**No `main-latest`.** Many older LiteLLM compose examples use `litellm:main-latest`. The LiteLLM docs state: "The rolling `main-latest` tag is deprecated and is no longer being updated" ([image security docs](https://docs.litellm.ai/docs/proxy/docker_image_security), as of 2026-10-16). A stack on that tag runs an old, unpatched LiteLLM without any warning.

**Why exactly these versions.** LiteLLM supports the four most recent stable minor lines with patches; older lines get no updates ([version support](https://docs.litellm.ai/docs/enterprise/version_support), as of 2026-10-16). On 2026-10-16 those are 1.105, 1.104, 1.103 and 1.102. v1.105.1 is the latest stable and contains the fixes for the 2026 advisories, including GHSA-7hp6-4w63-5g45 (critical, privilege escalation and remote code execution, fixed from 1.102.2 on the 1.102 line). For Open WebUI, stay at v0.11.4 or newer: that release fixed 19 advisories, including session token theft from any website. In March 2026, LiteLLM versions 1.82.7 and 1.82.8 on PyPI contained credential-stealing malware ([GHSA-5mg7-485q-xm76](https://github.com/advisories/GHSA-5mg7-485q-xm76)). The images are signed with cosign since then; the release notes of v1.105.1 show how to verify them.

**Offline mode for Open WebUI.** `OFFLINE_MODE=true` stops Open WebUI from downloading models from Hugging Face and from checking GitHub for new versions. Without it, Open WebUI downloads a sentence-transformers embedding model on start, and its image health check reports unhealthy during that download (tested in this repo). Embeddings run through LiteLLM instead (`RAG_EMBEDDING_ENGINE=openai`, model `embedding`), so document text goes to the same provider as chat and counts against the Open WebUI key's budget. Side effect: the local Whisper speech-to-text model cannot be downloaded either. See [Open WebUI with LiteLLM](open-webui.md#speech-to-text).

**Models in files, not in the database.** `STORE_MODEL_IN_DB=False` keeps `litellm/models.yaml` as the single source of truth. Model changes go through git and review, not through clicks in the admin UI. The [configuration guide](configuration.md#store_model_in_dbfalse) explains the reasons.

**Privacy defaults.** LiteLLM does not store prompts or responses in its spend log, keeps message content out of logging callbacks and deletes spend log rows after 90 days. Open WebUI has admin chat access, admin export and community sharing switched off, and telemetry disabled. Details in the [GDPR guide](gdpr.md).

**Secrets from .env, never in YAML.** Every provider key in the model files is read with `os.environ/NAME`. The test `test_secrets_come_from_env` enforces this.

## Common problems

**`run ./scripts/init-env.sh first` when starting.** `.env` is missing or lacks a required variable. Run `./scripts/init-env.sh`.

**`up --wait` hangs or a container is unhealthy.** Look at the logs:

```bash
docker compose ps
docker compose logs --tail 100 litellm
docker compose logs --tail 100 open-webui
```

A typo in a YAML file stops LiteLLM, and Open WebUI then waits for it, because it depends on a healthy LiteLLM.

**Empty model list in Open WebUI.** Usually `bootstrap.py` was not run, or the provider key is missing. Test the Open WebUI key directly:

```bash
export OWUI_KEY=$(grep '^OPENWEBUI_LITELLM_KEY=' .env | cut -d= -f2)
curl -s http://localhost:4000/v1/models -H "Authorization: Bearer $OWUI_KEY"
```

If that lists your models, the problem is in Open WebUI; see [Open WebUI with LiteLLM](open-webui.md#common-problems).

**`LiteLLM not reachable at http://localhost:4000` from bootstrap.py.** The stack is not up yet, or LiteLLM listens somewhere else. The script uses `LITELLM_PORT` from `.env` (default 4000); for another host set `LITELLM_URL` in `.env`. Over anything other than `localhost` the master key travels in plain HTTP, so use an SSH tunnel instead.

**Postgres authentication fails after you deleted and recreated `.env`.** Postgres sets its password only when the volume is created. A new `POSTGRES_PASSWORD` does not change the password inside the existing volume. Restore the old `.env`, or reset with `docker compose down -v` (this deletes all data). Never regenerate `.env` on a running installation: a new `LITELLM_SALT_KEY` also makes credentials stored in the LiteLLM database unreadable.

**Colleagues get 403 on sign-up.** Expected after the first admin. Switch sign-up on in **Admin Panel > Settings > General** and approve the pending accounts.

**HTTP 422 `budget_exceeded`.** The user, the key or the Open WebUI key has used its budget. Raise the value in `.env` and run `python3 scripts/bootstrap.py` again, or adjust single users in the LiteLLM admin UI. The `.env` value wins over an exported shell variable of the same name.

## Next steps

1. Read the [configuration guide](configuration.md) before you add models.
2. Set budgets that fit your organisation: [Budgets](budgets.md).
3. Put HTTPS in front: set `DOMAIN` and `WEBUI_URL=https://<domain>` in `.env`, then `docker compose -f compose.yaml -f compose.tls.yaml up -d --wait`.
4. Add single sign-on with Microsoft Entra ID (`compose.entra.yaml`).
5. Set up chat retention (`scripts/purge-chats.sh`) and review the [GDPR guide](gdpr.md).
6. Run the end-to-end tests against a mock model, without a provider key: see [Run the tests](#run-the-tests).

## Run the tests

> **Warning:** Never run the tests against a production stack. In your real install folder the test overlay replaces your models with the mock, and on a fresh stack the tests sign up the first Open WebUI admin (`e2e-admin@example.com`) with a random password nobody knows. Use a separate clone, or a test VM, with its own `COMPOSE_PROJECT_NAME` and other ports.

A separate clone next to a running installation:

```bash
git clone https://github.com/pexon-consulting/litellm-open-webui llm-gateway-test
cd llm-gateway-test
./scripts/init-env.sh
printf '%s\n' COMPOSE_PROJECT_NAME=llm-gateway-test OPEN_WEBUI_PORT=3100 LITELLM_PORT=4100 MOCK_LLM_PORT=8100 >> .env
```

The tests and `bootstrap.py` derive their URLs from `LITELLM_PORT`, `OPEN_WEBUI_PORT` and `MOCK_LLM_PORT` (or take `LITELLM_URL` and `MOCK_LLM_URL` if set). Start the stack with the mock model and run the tests in a virtual environment (Debian 12 and Ubuntu 24.04 refuse `pip install` for the system Python):

```bash
export COMPOSE_FILE=compose.yaml:compose.pii.yaml:compose.test.yaml
docker compose up -d --wait
python3 scripts/bootstrap.py
python3 -m venv .venv && .venv/bin/pip install pytest pyyaml
.venv/bin/pytest tests
```

The tests delete the keys, end users and budget rows they create. The Open WebUI tests need a fresh stack, because they sign up the first admin themselves; on a stack that already has users they are skipped. Remove the test stack with `docker compose down -v`, inside the test clone only.

## Related guides

- [LiteLLM config.yaml explained](configuration.md)
- [Open WebUI with LiteLLM: connection, users and settings](open-webui.md)
- [Budgets and rate limits](budgets.md)
- [GDPR settings](gdpr.md)
- [PII masking with Presidio](pii-masking.md)

# LiteLLM and Open WebUI troubleshooting: common errors and fixes

This page is for whoever runs this stack (admins and platform engineers) and has to work out why a request, a container or a setting does not behave as expected.

This page lists the errors people actually hit with this stack, each with the symptom, the cause and the fix. Most of them were reproduced in this repo's end-to-end tests against LiteLLM v1.105.1 and Open WebUI v0.12.2, and the error bodies below are copied from real responses. Start with the debug commands, then jump to your symptom.

## Contents

- [Debug commands](#debug-commands)
- [LiteLLM returns 422 budget_exceeded](#litellm-returns-422-budget_exceeded)
- [LiteLLM returns 429](#litellm-returns-429)
- [LiteLLM returns 403 key_model_access_denied](#litellm-returns-403-key_model_access_denied)
- [The fallback model is not used](#the-fallback-model-is-not-used)
- [Open WebUI is not showing models](#open-webui-is-not-showing-models)
- [Open WebUI is unhealthy at start](#open-webui-is-unhealthy-at-start)
- [Sign-up returns 403](#sign-up-returns-403)
- [Spend shows 0 and budgets never trigger](#spend-shows-0-and-budgets-never-trigger)
- [A budget was overshot](#a-budget-was-overshot)
- [An environment change has no effect](#an-environment-change-has-no-effect)
- [Presidio: supported languages have to be consistent](#presidio-supported-languages-have-to-be-consistent)
- [Presidio analyzer stays unhealthy](#presidio-analyzer-stays-unhealthy)
- [Port 3000 is already in use](#port-3000-is-already-in-use)
- [Lost .env or LITELLM_SALT_KEY](#lost-env-or-litellm_salt_key)
- [Docker Compose is too old for !reset](#docker-compose-is-too-old-for-reset)
- [Voice input does not work](#voice-input-does-not-work)
- [Related guides](#related-guides)

## Debug commands

Run these from the repo root on the Docker host. The first two lines load only the two keys from `.env` into your shell, without printing them. Loading the whole `.env` with `set -a` is not a good idea: exported variables win over `.env` for `docker compose`, so later edits to `.env` would silently have no effect. Do not paste the keys into tickets or chat.

On macOS zsh, run `setopt interactivecomments` first, or zsh prints `command not found: #` for the comment lines.

```bash
export LITELLM_MASTER_KEY=$(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2)
export OPENWEBUI_LITELLM_KEY=$(grep '^OPENWEBUI_LITELLM_KEY=' .env | cut -d= -f2)

# State of every container, including healthchecks
docker compose ps

# Logs (add -f to follow). Use the same -f files you started with, or set COMPOSE_FILE in .env
docker compose logs --tail 200 litellm
docker compose logs --tail 200 open-webui

# LiteLLM health: process, then database. Readiness answers {"status":"healthy","db":"connected"}
curl -s http://127.0.0.1:4000/health/liveliness
curl -s http://127.0.0.1:4000/health/readiness

# Open WebUI health (port from OPEN_WEBUI_PORT, default 3000). Answers {"status":true}
curl -s http://127.0.0.1:3000/health

# Spend, budget and limits of the Open WebUI key
curl -s "http://127.0.0.1:4000/key/info?key=$OPENWEBUI_LITELLM_KEY" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"

# Spend and budget of one Open WebUI user (id from Admin Panel > Users)
curl -s "http://127.0.0.1:4000/customer/info?end_user_id=<open-webui-user-id>" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"

# The default per-user budget created by scripts/bootstrap.py
curl -s -X POST http://127.0.0.1:4000/budget/info -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' -d '{"budgets":["per-user-default"]}'

# Models the Open WebUI key can see, and their prices
curl -s http://127.0.0.1:4000/v1/models -H "Authorization: Bearer $OPENWEBUI_LITELLM_KEY"
curl -s http://127.0.0.1:4000/v1/model/info -H "Authorization: Bearer $LITELLM_MASTER_KEY"

# What the Open WebUI container really got
docker compose exec open-webui printenv OPENAI_API_BASE_URL
```

All of these were run against the stack in this repo. LiteLLM also returns headers such as `x-litellm-key-spend` and `x-litellm-key-rpm-limit` on chat responses (`curl -i` shows them).

Do not call `/health` (without a suffix) in a loop: it sends a real request to every model and costs tokens ([LiteLLM health docs](https://docs.litellm.ai/docs/proxy/health)).

## LiteLLM returns 422 budget_exceeded

**Symptom.** Requests fail with HTTP 422. In Open WebUI the chat shows an error. The body (real response, tested in this repo):

```json
{"error":{"message":"Budget has been exceeded! Key=doc-probe (sk-...1ryA) Current cost: 0.005, Max budget: 0.0001","type":"budget_exceeded","param":null,"code":"422"}}
```

**Cause.** A key budget or a per-user budget is used up. LiteLLM v1.105.1 answers **422**, although its [error reference](https://docs.litellm.ai/docs/proxy/error_reference) says 429. Both the key budget and the per-user budget (end users created through `X-OpenWebUI-User-Id` and `max_end_user_budget_id: per-user-default`) return 422 with `type: budget_exceeded` (both tested). Note that the first request on a fresh, tiny budget still passes, because no spend exists yet.

In this repo two budgets apply to Open WebUI traffic:

- the key `open-webui`: `OPENWEBUI_BUDGET_USD` (default 500) every `OPENWEBUI_BUDGET_PERIOD` (default 30d), for everyone together
- the per-user default: `USER_BUDGET_USD` (default 20) every `USER_BUDGET_PERIOD` (default 30d)

**Fix.**

1. Find out which one: the message says `Key=open-webui` for the shared key. Check `/key/info` and `/customer/info` (see [Debug commands](#debug-commands)).
2. To raise the defaults, change the values in `.env` and run `python3 scripts/bootstrap.py` again. It updates the existing budget and key, it does not create duplicates. The `.env` value wins over a variable of the same name exported in your shell; the script warns on stderr when they differ.
3. To give one person more, create or update that end user with their own budget in LiteLLM (the tests use `POST /customer/new` with `user_id` and `max_budget`). See [LiteLLM budgets and rate limits](budgets.md).
4. Otherwise wait for the reset (`budget_reset_at` in the `/key/info` and `/budget/info` output).

Client code that only handles 429 for budgets will miss this. Handle 422 with `error.type == "budget_exceeded"`.

## LiteLLM returns 429

**Symptom.** HTTP 429 with `type: throttling_error` and a `retry-after` header (tested in this repo, key with `rpm_limit: 1`):

```json
{"error":{"message":"Rate limit exceeded for api_key: 1bb8...df2. Limit type: requests. Current limit: 1, Remaining: 0. Limit resets at: 2026-10-16 09:03:28 UTC","type":"throttling_error","param":null,"code":"429"}}
```

**Cause.** A rate limit on the key (`rpm_limit`, `tpm_limit`) was reached. The provider can also answer 429 when your account at Mistral, Azure and so on hits its own quota. In that case LiteLLM retries (`num_retries: 2`).

A provider 429 does not take the model out of rotation in this repo's setup. In v1.105.1, a 429 or more than 50 % failures (with at least 5 requests per minute) trigger a cooldown only in model groups with more than one deployment, and every model group here has one. Non-retryable errors such as 401 or 404 always trigger a cooldown (`cooldown_time: 30`). See [configuration](configuration.md) for the details.

**Fix.**

- Read the message. "Limit type: requests" with "Current limit" is LiteLLM's own limit. Raise it with `POST /key/update` or remove it.
- If the message comes from the provider, check your provider quota. Add a second deployment with the same `model_name` in `litellm/models.yaml` (LiteLLM load balances them) or a fallback.
- Respect `retry-after` in scripts.

## LiteLLM returns 403 key_model_access_denied

**Symptom.** HTTP 403 (tested in this repo):

```json
{"error":{"message":"The requested model 'mistral-medium' is not available for this API key, or the model name is invalid. Check the models available to you and try again.","type":"key_model_access_denied","param":"model","code":"403"}}
```

**Cause.** The key has a `models` list and the requested model is not on it, or the model name does not exist in `litellm/models.yaml`. The request never reaches the provider (tested: the mock LLM received nothing).

**Fix.**

- Check the key: `/key/info` shows `models`. An empty list means all models.
- Check the spelling: `/v1/models` with that key lists what it may use. The name is the `model_name` from `litellm/models.yaml`, not the provider's model id.
- Add the model to the key with `POST /key/update`, or use a key without a model list.

## The fallback model is not used

**Symptom.** `litellm/config.yaml` defines `fallbacks: - mistral-medium: ["mistral-small"]`, but when Mistral Medium fails the user gets an error instead of an answer from Mistral Small.

**How the fallback normally works.** The primary is tried three times (one call plus `num_retries: 2`), then the fallback answers. Tested in this repo: the mock received `fail-always` three times, then `mock-small`.

**Cause 1: budget reservation.** Before each request LiteLLM reserves the worst-case cost against every budget the request counts toward (key, user, team, end user, and so on). Without `max_tokens`, LiteLLM reserves 16,384 output tokens (or the model maximum if that is lower).

The fallback check then reads only the key and user counters. If the reservation fills the remaining key budget, the fallback is **skipped silently** and the client sees the primary model's error.

Tested in this repo: key budget 100, price 0.02 per output token, no `max_tokens`: no fallback. With `max_tokens: 10`: fallback works. With `general_settings.enforce_fallback_budget: false`: fallback works.

Real numbers for this repo: 16,384 output tokens of Mistral Medium at 8.25e-6 USD is about 0.14 USD plus input per request without `max_tokens`. For Open WebUI that means the `open-webui` key: once less than about 0.14 USD of its `OPENWEBUI_BUDGET_USD` is left, fallbacks from Mistral Medium stop.

**Fix for cause 1**, pick one:

- Send `max_tokens` with requests. A realistic value (for example 4000) shrinks the reservation further.
- Keep a buffer: set `OPENWEBUI_BUDGET_USD` higher than what you want to spend, and use per-user budgets for the real cap.
- Use keys without a budget for service traffic where fallbacks matter.
- Set `general_settings.enforce_fallback_budget: false` in `litellm/config.yaml`. Then fallbacks to paid models are not budget-checked at all ([LiteLLM issue #41344](https://github.com/BerriAI/litellm/issues/41344)).

**Cause 2: the error is not a provider failure.** Budget errors (422) and model access errors (403) are decided by LiteLLM before any provider is called (tested for 403: the provider received nothing), so there is nothing to fall back from. The same is likely for rate limits on the key itself. We have not tested every error type against fallbacks.

**Cause 3: names do not match.** Fallback names must be `model_name` values from `litellm/models.yaml`. `tests/test_config_files.py` checks that, so run `.venv/bin/pytest tests/test_config_files.py` after edits (virtual environment as in [Run the tests](quickstart.md#run-the-tests)).

## Open WebUI is not showing models

**Symptom.** The model dropdown in Open WebUI is empty, or misses a model you just added.

**Check in this order:**

1. **Does LiteLLM list them for the Open WebUI key?**

   ```bash
   curl -s http://127.0.0.1:4000/v1/models -H "Authorization: Bearer $OPENWEBUI_LITELLM_KEY"
   ```

   An authentication error here means the key was never registered: run `python3 scripts/bootstrap.py`. It reads `OPENWEBUI_LITELLM_KEY` from `.env` and creates the key in LiteLLM. Without that step Open WebUI has a key that LiteLLM does not know.
2. **Did LiteLLM load your new model?** LiteLLM reads `litellm/config.yaml` and `litellm/models.yaml` at start. After an edit run `docker compose restart litellm`, then `docker compose logs --tail 50 litellm` for YAML or provider errors.
3. **Does Open WebUI point to LiteLLM?** `docker compose exec open-webui printenv OPENAI_API_BASE_URL` must print `http://litellm:4000/v1`. Not `localhost`: inside the container `localhost` is Open WebUI itself.
4. **Is the stored connection out of date?** Open WebUI saves the OpenAI connection (base URL and key, keys `openai.api_base_urls` and `openai.api_keys`) in its database on the first start.

   If you later changed `OPENWEBUI_LITELLM_KEY` or `OPENAI_API_BASE_URL`, Open WebUI still uses the old values. Fix it in **Admin Panel > Settings > Connections** (URL `http://litellm:4000/v1`, key = the value of `OPENWEBUI_LITELLM_KEY`), or see [An environment change has no effect](#an-environment-change-has-no-effect).
5. **Is the key blocked or out of budget?** `/key/info` shows `spend`, `max_budget` and `blocked`.
6. **Admins see the model, users do not.** This is Open WebUI's model access control (`BYPASS_MODEL_ACCESS_CONTROL` defaults to `False`). Check the model's access settings in **Admin Panel > Settings > Models**.

## Open WebUI is unhealthy at start

**Symptom.** `docker compose up -d --wait` waits a long time or fails, `docker compose ps` shows `open-webui` as `starting` or `unhealthy`.

**Causes and fixes:**

- **It waits for LiteLLM.** `open-webui` only starts after `postgres`, `redis` and `litellm` are healthy. If LiteLLM is unhealthy, look there first: `docker compose logs litellm`. Typical: a YAML error in `litellm/models.yaml`, or a database it cannot reach.
- **It downloads a model.** Open WebUI downloads a sentence-transformers embedding model from Hugging Face on start unless `RAG_EMBEDDING_ENGINE=openai` and `OFFLINE_MODE=true` are set, and the healthcheck reports unhealthy during that download (tested in this repo). `compose.yaml` sets both, so this only happens if you changed them. The log then shows requests to `huggingface.co`.
- **It is just slow.** The healthcheck allows `start_period: 60s` and 30 retries every 10 seconds. A first start with database migrations on a small VM can take a few minutes. The CI waits up to 600 seconds (`--wait-timeout 600`).
- **The database is missing.** Open WebUI uses its own database `openwebui`, created by `postgres/init/10-openwebui.sql`. That script only runs when the Postgres volume is empty. If you reused an old `postgres_data` volume from another setup, create it by hand:

  ```bash
  docker compose exec postgres psql -U llm -d litellm -c "CREATE DATABASE openwebui OWNER llm;"
  docker compose exec postgres psql -U llm -d openwebui -c "CREATE EXTENSION IF NOT EXISTS vector;"
  ```

## Sign-up returns 403

**Symptom.** The first account worked. A colleague tries to sign up and gets an error, the API answers 403.

**Cause.** After the first account (which becomes admin), Open WebUI v0.12.2 stores `ui.enable_signup=false` in its database, regardless of `ENABLE_SIGNUP=true` in `compose.yaml` (tested in this repo).

**Fix.** Sign in as admin, open **Admin Panel > Settings > General**, and enable sign-up. New accounts are then `pending` (`DEFAULT_USER_ROLE=pending`) and need approval under **Admin Panel > Users** (tested). Switch sign-up off again when everyone is in, or use [single sign-on](sso-entra-id.md) instead.

## Spend shows 0 and budgets never trigger

**Symptom.** Chats work, but `/key/info` and `/customer/info` show `spend: 0`, and nobody ever hits a budget.

**Cause.** LiteLLM does not know what a token of that model costs. It has a built-in price list in USD, but providers such as STACKIT, IONOS, T-Systems, Scaleway and self-hosted models are not in it. Without a price, cost is 0 and budgets never fire.

**Fix.**

1. Check the prices LiteLLM uses:

   ```bash
   curl -s http://127.0.0.1:4000/v1/model/info -H "Authorization: Bearer $LITELLM_MASTER_KEY"
   ```

   Look at `input_cost_per_token` and `output_cost_per_token` in `model_info`.
2. Set them in `litellm/models.yaml` under `litellm_params`, as the Mistral entries do:

   ```yaml
   input_cost_per_token: 0.000000165
   output_cost_per_token: 0.00000066
   ```

3. `docker compose restart litellm`.

Two more traps:

- **Currency.** LiteLLM has no currency. If you enter EUR prices, the numbers are EUR, but the built-in prices of other models are USD. Do not mix both in one budget.
- **EU endpoints cost more.** Mistral's EU endpoint costs 1.1 times the global list price, which is why `litellm/models.yaml` sets prices explicitly. For Azure, `model_info.base_model` (for example `azure/eu/gpt-5-2025-08-07`) tells LiteLLM to use the EU Data Zone price, because Azure deployment names are free text.

Spend also appears with a delay: LiteLLM writes it in batches every 10 seconds in this repo (`proxy_batch_write_at: 10`, plus 0-5 seconds of random jitter).

## A budget was overshot

**Symptom.** A key with a 20 USD budget shows 20.40 USD spend.

**Cause.** LiteLLM checks budgets against the spend in the database, which is written in batches (every 10 seconds here). Requests that are already running, or that arrive in parallel before the next write, are not stopped. Under parallel load a budget can be overshot by the cost of the requests in flight (tested in this repo).

**Fix.** There is no exact fix. Plan for it:

- Set budgets slightly below the real limit.
- Lower `proxy_batch_write_at` further if you need tighter limits. Each write costs database load.
- Use `rpm_limit` or `max_parallel_requests` to cap how many requests can be in flight per key.

## An environment change has no effect

**Symptom.** You changed a value in `.env` or `litellm/config.yaml`, restarted, and nothing changed.

There are four separate causes. Find yours:

**1. Open WebUI's persistent config.** Open WebUI stores many settings in its database on the first start (`ENABLE_PERSISTENT_CONFIG`, default true). After that, the environment is ignored for those settings. In v0.12.2 this includes `WEBUI_URL`, `ENABLE_SIGNUP`, `ENABLE_LOGIN_FORM`, `DEFAULT_USER_ROLE`, `OPENAI_API_BASE_URL`, `OPENAI_API_KEY`, `ENABLE_OLLAMA_API`, `RAG_EMBEDDING_ENGINE`, `RAG_EMBEDDING_MODEL` and `ENABLE_COMMUNITY_SHARING` (keys seen in the source). OAuth settings are the exception: they are read from the environment on every start unless `ENABLE_OAUTH_PERSISTENT_CONFIG=true`.

Fix: change the setting in the Open WebUI admin panel. Or, if you want the environment to be the only truth, set `ENABLE_PERSISTENT_CONFIG=false` in an override file. Then admin panel changes are not saved, and every value in `compose.yaml` applies on each start, including `ENABLE_SIGNUP: "true"`.

**2. The variable never reaches the container.** The `open-webui` service has no `env_file`. It only gets the variables listed under `environment:` in the compose files. A new Open WebUI variable in `.env` (for example `ENABLE_OAUTH_GROUP_MANAGEMENT`) does nothing. Fix: add it in your own override file and include it with `-f` or `COMPOSE_FILE`:

```yaml
# compose.local.yaml
services:
  open-webui:
    environment:
      ENABLE_OAUTH_GROUP_MANAGEMENT: "true"
```

`docker compose config` shows the merged result, so you can check before starting.

**3. `environment:` wins over `.env` for LiteLLM.** LiteLLM gets all of `.env` through `env_file: .env`, but the values in its `environment:` block win: `LITELLM_LOG: ERROR`, `LITELLM_MODE: PRODUCTION`, `STORE_MODEL_IN_DB: "False"`, `DATABASE_URL`, `REDIS_*`. Setting `LITELLM_LOG=DEBUG` in `.env` has no effect. Use an override file as above. See [Logs and log level](production.md#logs-and-log-level).

**4. LiteLLM's `include:` replaces settings.** `litellm/config.yaml` includes `models.yaml` and `guardrails.yaml`. The include merges only top-level keys: `model_list` (a list) is appended, but a dictionary such as `router_settings` or `litellm_settings` in an included file **replaces** the one in `config.yaml` (tested in this repo). Keep `router_settings`, `litellm_settings` and `general_settings` in `config.yaml` only. `tests/test_config_files.py` (`test_config_keeps_settings_out_of_includes`) fails if an included file has them.

And the simple one: after editing `litellm/*.yaml` run `docker compose restart litellm`. After editing `.env` or compose files run `docker compose up -d` (a plain `restart` does not apply new environment values).

## Presidio: supported languages have to be consistent

**Symptom.** With `compose.pii.yaml`, `presidio-analyzer` does not become healthy, and its log shows:

```text
ValueError: Misconfigured engine, supported languages have to be consistent
```

followed by the two language lists.

**Cause.** The Presidio analyzer (2.2.362) compares the languages of the recognizer registry with the languages of the analyzer engine and refuses to start if they differ (seen in `presidio_analyzer/analyzer_engine.py`). This repo's recognizers file lists `de` and `en`. Without a matching analyzer config the engine uses its default language list and the check fails.

**Fix.** `presidio/analyzer.yaml` sets the same languages, and `presidio/Dockerfile` points `ANALYZER_CONF_FILE` to it:

```yaml
supported_languages:
  - de
  - en
default_score_threshold: 0
```

If you add a language, add it in all three files: `presidio/analyzer.yaml`, `presidio/recognizers.yaml` and `presidio/nlp.yaml` (with a spaCy model for it, installed in `presidio/Dockerfile`), then rebuild:

```bash
docker compose -f compose.yaml -f compose.pii.yaml build presidio-analyzer
docker compose -f compose.yaml -f compose.pii.yaml up -d --wait
```

More in [PII masking with Presidio and LiteLLM](pii-masking.md).

## Presidio analyzer stays unhealthy

The analyzer log stops after `Control socket listening at /app/gunicorn.ctl` and never shows `Booting worker with pid`. `docker compose up --wait` then fails with `container ... presidio-analyzer-1 is unhealthy`.

Cause: the Presidio 2.2.362 images run gunicorn 25.1.0, whose new control socket can deadlock the worker at start. It happens intermittently, more often on some hosts than others (seen in GitHub Actions, see the [gunicorn discussion](https://github.com/benoitc/gunicorn/discussions/3530)). `compose.pii.yaml` therefore sets `GUNICORN_CMD_ARGS: --no-control-socket` for both Presidio services. If you run Presidio from your own compose file, set the same variable.

## Port 3000 is already in use

**Symptom.** `docker compose up` fails because the port is already allocated, or `http://localhost:3000` shows a different application (common on developer machines with a Node or Grafana app on 3000).

**Cause.** `compose.yaml` publishes Open WebUI on `127.0.0.1:${OPEN_WEBUI_PORT:-3000}`.

**Fix.** Pick another port in `.env`, and change `WEBUI_URL` with it:

```bash
OPEN_WEBUI_PORT=3080
WEBUI_URL=http://localhost:3080
```

Then `docker compose up -d --wait` and open `http://localhost:3080`. This is the setup we use on a machine where 3000 is taken, and `tests/conftest.py` reads `OPEN_WEBUI_PORT` too. If Open WebUI already ran, also update the WebUI URL in **Admin Panel > Settings > General**, because it is stored in the database. LiteLLM's port works the same way with `LITELLM_PORT` (default 4000); `scripts/bootstrap.py` and the tests read it too. The mock LLM of the test overlay uses `MOCK_LLM_PORT` (default 8000).

With `compose.tls.yaml` Open WebUI publishes no host port at all, so this does not apply on a server.

## Lost .env or LITELLM_SALT_KEY

**Symptom.** `.env` was deleted or overwritten, or someone ran `init-env.sh` on a copy of the repo and copied the new `.env` over the old one. LiteLLM or Open WebUI cannot connect to Postgres, users are logged out, or credentials stored in LiteLLM are unreadable.

**First: look for the old file.** Your vault copy or the `env.backup` in your backups (see [Backups](production.md#backups)). Restoring the original `.env` fixes everything. `scripts/init-env.sh` never overwrites an existing `.env`, it warns: "a new LITELLM_SALT_KEY makes provider keys stored in the database unreadable".

**If the old `.env` is gone**, the damage depends on the variable. We describe this from the repo files and the docs; we have not tested a full recovery.

| Lost value | Effect | Recovery |
|---|---|---|
| `LITELLM_SALT_KEY` | Provider credentials stored in LiteLLM's database are unreadable. "Set once, never change it" ([LiteLLM deploy docs](https://docs.litellm.ai/docs/proxy/deploy)). | None. Re-enter those credentials with the new key. In this repo's default setup provider keys come from `.env` via `os.environ/` and `STORE_MODEL_IN_DB` is off, so models in `litellm/models.yaml` keep working. |
| `POSTGRES_PASSWORD` | LiteLLM and Open WebUI cannot log in to Postgres. The password was set when the volume was created. | Inside the container local connections need no password, so set the new one: `docker compose exec postgres psql -U llm -d litellm -c "ALTER USER llm PASSWORD '<new POSTGRES_PASSWORD>';"`, then `docker compose up -d`. |
| `OPENWEBUI_LITELLM_KEY` | Open WebUI's stored key no longer matches anything you know. | `python3 scripts/bootstrap.py` registers the new key. Enter it in **Admin Panel > Settings > Connections**. Delete the old key in the LiteLLM admin UI. |
| `WEBUI_SECRET_KEY` | All Open WebUI sessions are invalid; data Open WebUI encrypted with it is lost. | Users sign in again. |
| `LITELLM_MASTER_KEY` | Admin access with the old key is gone. | Use the new one, `docker compose up -d`. |
| `REDIS_PASSWORD` | Nothing persistent; Redis keeps no data on disk here. | `docker compose up -d`. |

To make a new `.env` without destroying the old database: move any broken `.env` away, run `./scripts/init-env.sh`, fill in your provider keys, then apply the recovery steps above.

## Docker Compose is too old for !reset

**Symptom.** `docker compose -f compose.yaml -f compose.tls.yaml ...` fails with an error about the YAML tag `!reset` or the `ports` value of `open-webui`, or Open WebUI is still published on port 3000 with the TLS overlay. With the old Python `docker-compose` (with a hyphen) the overlay does not work at all.

**Cause.** `compose.tls.yaml` uses `ports: !reset []` to remove Open WebUI's host port. `!reset` is a Compose Specification feature ([Docker docs: merge](https://docs.docker.com/reference/compose-file/merge/)). Docker's documentation does not name the minimum version for `!reset`. The related `!override` tag needs Docker Compose 2.24.4 or later (as of 2026-10-16). This repo was tested with Docker Compose 2.40.0, and the CI uses the current version on GitHub's `ubuntu-latest` runner.

**Fix.** Check your version and update to a current Compose v2 ([install docs](https://docs.docker.com/compose/install/linux/)):

```bash
docker compose version
```

Then validate before starting. CI runs exactly this:

```bash
DOMAIN=chat.example.com docker compose -f compose.yaml -f compose.tls.yaml config -q
```

## Voice input does not work

**Symptom.** The microphone button in Open WebUI does nothing useful or speech-to-text fails.

**Cause.** Whisper speech-to-text in Open WebUI runs locally by default and needs a model download. `OFFLINE_MODE: "true"` in `compose.yaml` blocks downloads.

**Fix.** Either keep voice input off, or route speech-to-text to an API in the Open WebUI admin settings. Check where that API processes audio before you enable it. See the [GDPR checklist](gdpr.md).

## Related guides

- [Running LiteLLM in production: HTTPS, backups, upgrades and security](production.md)
- [Open WebUI single sign-on with Microsoft Entra ID](sso-entra-id.md)
- [LiteLLM and Open WebUI with Docker Compose: quick start](quickstart.md)
- [LiteLLM config.yaml explained](configuration.md)
- [Open WebUI with LiteLLM: connection, users and settings that matter](open-webui.md)
- [LiteLLM budgets and rate limits](budgets.md)
- [PII masking with Presidio and LiteLLM](pii-masking.md)
- [GDPR checklist for an internal LLM gateway](gdpr.md)

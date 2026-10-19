# LiteLLM config.yaml explained

This guide walks through the LiteLLM Proxy configuration in this repo line by line: `litellm/config.yaml`, `litellm/models.yaml` and the environment variables in `compose.yaml`. For every setting you get what it does, why it is set the way it is, what LiteLLM would do without it, and a link to the official docs. It also covers the traps that cost real time: the `include` merge, missing prices, budget reservations that silently skip fallbacks, and the salt key.

Versions: LiteLLM v1.105.1. Doc links and defaults are as of 2026-10-16. The full reference is the LiteLLM [config settings page](https://docs.litellm.ai/docs/proxy/config_settings).

## Contents

- [How the files fit together](#how-the-files-fit-together)
- [The include merge pitfall](#the-include-merge-pitfall)
- [litellm_settings](#litellm_settings)
- [router_settings](#router_settings)
- [general_settings](#general_settings)
- [models.yaml and the model_list structure](#modelsyaml-and-the-model_list-structure)
- [Load balancing with the same model_name](#load-balancing-with-the-same-model_name)
- [Fallbacks, retries and cooldowns](#fallbacks-retries-and-cooldowns)
- [Prices: input_cost_per_token and base_model](#prices-input_cost_per_token-and-base_model)
- [Environment variables in compose.yaml](#environment-variables-in-composeyaml)
- [Applying changes](#applying-changes)
- [Common problems](#common-problems)
- [Related guides](#related-guides)

## How the files fit together

| File | Content | Mounted as |
|---|---|---|
| `litellm/config.yaml` | All settings: `litellm_settings`, `router_settings`, `general_settings` | `/app/config.yaml` |
| `litellm/models.yaml` | Only `model_list`: your models and prices | `/app/models.yaml` |
| `litellm/guardrails.yaml` | Only `guardrails`, empty by default | `/app/guardrails.yaml` |
| `litellm/guardrails.pii.yaml` | Presidio PII masking, replaces the file above with `compose.pii.yaml` | `/app/guardrails.yaml` |
| `examples/providers/*.yaml` | Ready-made `model_list` files per provider | not mounted, copy into `models.yaml` |

LiteLLM starts with `--config /app/config.yaml --port 4000`. All files are mounted read-only. Secrets are never in these files: they come from `.env` through `os.environ/NAME`.

The top of `config.yaml`:

```yaml
include:
  - models.yaml
  - guardrails.yaml
```

`include` loads other YAML files next to the config file and merges them into it ([config management docs](https://docs.litellm.ai/docs/proxy/config_management)). The split exists so that switching provider means replacing one file, and so that the PII overlay can swap the guardrails file without touching the rest.

## The include merge pitfall

`include` does not deep-merge. It merges **top-level keys** only (tested in this repo, and visible in the LiteLLM source, `proxy/common_utils/config_includes.py`):

- If both values are lists, they are concatenated. That is why `model_list` from `models.yaml` and `guardrails` from `guardrails.yaml` work as expected.
- Otherwise, the value from the included file **replaces** the value in `config.yaml` completely. Dicts like `router_settings`, `litellm_settings` and `general_settings` are not merged key by key.

Example of what goes wrong. Someone wants a fallback for a new model and adds it next to the models, in `models.yaml`:

```yaml
# litellm/models.yaml  (do NOT do this)
model_list:
  - model_name: mistral-large
    litellm_params:
      model: mistral/mistral-large-2512
      api_base: https://api.eu.mistral.ai/v1
      api_key: os.environ/MISTRAL_API_KEY

router_settings:
  fallbacks:
    - mistral-large: ["mistral-medium"]
```

LiteLLM starts without an error. But the effective `router_settings` is now only the `fallbacks` line. Everything else from `config.yaml` is gone:

- `redis_host`, `redis_port`, `redis_password`: rate limits and cooldowns are no longer shared through Redis.
- `cooldown_time: 30` falls back to the default of 5 seconds.
- The fallback `mistral-medium -> mistral-small` disappears.

The same happens with `litellm_settings` in an included file. You would lose `max_end_user_budget_id` (no more default budget per Open WebUI user), `turn_off_message_logging` and `global_disable_no_log_param`, all without a warning.

The rule in this repo: **settings stay in `config.yaml`, included files contain only lists.** The static test `test_config_keeps_settings_out_of_includes` in `tests/test_config_files.py` fails if an included file contains `router_settings`, `litellm_settings` or `general_settings`.

## litellm_settings

```yaml
litellm_settings:
  drop_params: true
  turn_off_message_logging: true
  redact_user_api_key_info: true
  global_disable_no_log_param: true
  request_timeout: 600
  max_end_user_budget_id: per-user-default
```

| Key | Repo value | LiteLLM default | Docs |
|---|---|---|---|
| `drop_params` | `true` | `false` | [drop_params](https://docs.litellm.ai/docs/completion/drop_params) |
| `turn_off_message_logging` | `true` | `false` | [logging](https://docs.litellm.ai/docs/proxy/logging) |
| `redact_user_api_key_info` | `true` | `false` | [logging](https://docs.litellm.ai/docs/proxy/logging) |
| `global_disable_no_log_param` | `true` | not set | [logging](https://docs.litellm.ai/docs/proxy/logging) |
| `request_timeout` | `600` | `6000` seconds | [config settings](https://docs.litellm.ai/docs/proxy/config_settings) |
| `max_end_user_budget_id` | `per-user-default` | not set | [users and budgets](https://docs.litellm.ai/docs/proxy/users) |

**`drop_params: true`.** Clients like Open WebUI send OpenAI parameters that not every provider supports. Without this setting, LiteLLM raises an error for an unsupported parameter. With it, LiteLLM silently drops the parameter and the request goes through. The trade-off: a parameter you rely on can be ignored without notice. If you need strictness for an API client, test that client against each provider.

**`turn_off_message_logging: true`.** Keeps prompts and responses out of every logging callback (Langfuse, OpenTelemetry and others). Metadata and spend are still logged. No callback is configured in this repo, so this is a guard: if someone adds one later, message content does not leak into it by default.

**`redact_user_api_key_info: true`.** Removes key alias, user id and team id from what logging callbacks receive. Same idea: data minimisation for anything you add later.

**`global_disable_no_log_param: true`.** A client can send `"no-log": true` in the request body to skip logging for one request. This setting makes LiteLLM ignore that flag, so the operator decides what is logged, not the client.

**`request_timeout: 600`.** Seconds before LiteLLM gives up on a provider call. The LiteLLM default is 6000 seconds (100 minutes). 600 matches the default of the OpenAI Python SDK and is long enough for long answers, while a hanging provider does not tie up a connection for over an hour.

**`max_end_user_budget_id: per-user-default`.** Open WebUI forwards the user id with every request (see `user_header_mappings` below). LiteLLM treats each of those users as an end user ("customer"). This setting gives every end user without a budget of their own the budget row `per-user-default`, which `scripts/bootstrap.py` creates from `USER_BUDGET_USD` and `USER_BUDGET_PERIOD` in `.env`. Every end user without an own budget gets the limits of that row, whether or not the end user already exists in the LiteLLM database; a per-key `end_user_budget_id` takes precedence. No enterprise license is needed (tested in this repo). When a user exceeds it, the request fails with HTTP 422 `budget_exceeded`. The LiteLLM docs say the budget object is cached for 60 seconds, so edits take up to a minute to apply. If the budget row does not exist (you skipped `bootstrap.py`), the default budget cannot apply.

## router_settings

```yaml
router_settings:
  routing_strategy: simple-shuffle
  num_retries: 2
  allowed_fails: 3
  cooldown_time: 30
  fallbacks:
    - mistral-medium: ["mistral-small"]
  redis_host: os.environ/REDIS_HOST
  redis_port: os.environ/REDIS_PORT
  redis_password: os.environ/REDIS_PASSWORD
```

| Key | Repo value | LiteLLM default | Docs |
|---|---|---|---|
| `routing_strategy` | `simple-shuffle` | `simple-shuffle` | [load balancing](https://docs.litellm.ai/docs/proxy/load_balancing) |
| `num_retries` | `2` | `2` | [reliability](https://docs.litellm.ai/docs/proxy/reliability) |
| `allowed_fails` | `3` | `3` | [routing](https://docs.litellm.ai/docs/routing) |
| `cooldown_time` | `30` | `5` seconds | [routing](https://docs.litellm.ai/docs/routing) |
| `fallbacks` | `mistral-medium -> mistral-small` | `[]` | [reliability](https://docs.litellm.ai/docs/proxy/reliability) |
| `redis_host`, `redis_port`, `redis_password` | from env | `null` | [config settings](https://docs.litellm.ai/docs/proxy/config_settings) |

**`routing_strategy: simple-shuffle`.** Picks one of several deployments of the same model at random. The LiteLLM docs recommend it for best performance; it is also the default. It is written down so nobody has to look it up. Alternatives are `least-busy`, `usage-based-routing` (the docs mark it as bad for performance) and `latency-based-routing`.

**`num_retries: 2`, `allowed_fails: 3`, `cooldown_time: 30`.** Explained together in [Fallbacks, retries and cooldowns](#fallbacks-retries-and-cooldowns). Retries and allowed fails equal the defaults. Because `allowed_fails` equals the default, v1.105.1 does not use the count-based cooldown logic at all, so `allowed_fails: 3` has no effect here. The cooldown is raised from 5 to 30 seconds.

**Redis.** LiteLLM keeps rate-limit counters and cooldown state in memory by default. With Redis, that state is shared between several LiteLLM instances. The LiteLLM docs say: "Run Redis (7.0 or newer) as soon as you run more than one proxy instance" ([production docs](https://docs.litellm.ai/docs/proxy/prod)). This repo runs one instance, but includes Redis from the start, so scaling to a second instance needs no config change. Redis in `compose.yaml` keeps nothing on disk (`--save ""`, `--appendonly no`): this state is short-lived, and budgets and spend live in Postgres. The values come from `REDIS_HOST`, `REDIS_PORT` and `REDIS_PASSWORD`, which `compose.yaml` sets for the LiteLLM container.

## general_settings

```yaml
general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  store_prompts_in_spend_logs: false
  maximum_spend_logs_retention_period: "90d"
  maximum_spend_logs_retention_interval: "1d"
  proxy_batch_write_at: 10
  user_header_mappings:
    - header_name: X-OpenWebUI-User-Id
      litellm_user_role: customer
  allow_public_health_readiness_details: false
```

| Key | Repo value | LiteLLM default | Docs |
|---|---|---|---|
| `master_key` | env `LITELLM_MASTER_KEY` | falls back to `LITELLM_MASTER_KEY` | [config settings](https://docs.litellm.ai/docs/proxy/config_settings) |
| `database_url` | env `DATABASE_URL` | falls back to `DATABASE_URL` | [config settings](https://docs.litellm.ai/docs/proxy/config_settings) |
| `store_prompts_in_spend_logs` | `false` | `false` | [config settings](https://docs.litellm.ai/docs/proxy/config_settings) |
| `maximum_spend_logs_retention_period` | `"90d"` | `null` (no cleanup) | [spend log deletion](https://docs.litellm.ai/docs/proxy/spend_logs_deletion) |
| `maximum_spend_logs_retention_interval` | `"1d"` | `1d` | [spend log deletion](https://docs.litellm.ai/docs/proxy/spend_logs_deletion) |
| `proxy_batch_write_at` | `10` | `10` seconds (see note) | [config settings](https://docs.litellm.ai/docs/proxy/config_settings) |
| `user_header_mappings` | `X-OpenWebUI-User-Id` as `customer` | `null` | [Open WebUI tutorial](https://docs.litellm.ai/docs/tutorials/openweb_ui) |
| `allow_public_health_readiness_details` | `false` | not set | [health](https://docs.litellm.ai/docs/proxy/health) |

**`master_key`.** The admin credential for the API and the admin UI. It must start with `sk-`. The LiteLLM docs say the proxy will not start when the master key is unset, empty or a known unsafe value. `init-env.sh` generates `sk-` plus 64 random hex characters, and `compose.yaml` refuses to start when `LITELLM_MASTER_KEY` or `LITELLM_SALT_KEY` is empty (`${VAR:?...}`).

**`database_url`.** Postgres for keys, budgets, end users and spend. LiteLLM needs a database for virtual keys and spend tracking. `compose.yaml` builds the URL from `POSTGRES_PASSWORD` and points it at the `litellm` database.

**`store_prompts_in_spend_logs: false`.** The spend log table (`LiteLLM_SpendLogs`) gets one row per request. With this setting `false`, the `messages` and `response` columns stay empty. It is already the default; it is written down so a reviewer can see the decision. A test checks that a unique marker sent in a prompt never appears in that table (tested in this repo).

**`maximum_spend_logs_retention_period: "90d"` and `maximum_spend_logs_retention_interval: "1d"`.** Spend log rows still contain user id, key, model, token counts and cost. By default LiteLLM never deletes them. These settings delete rows older than 90 days, checked once a day. The LiteLLM docs state that retention and cleanup work without an enterprise license. Pick the period your data protection officer agrees to; budgets with a 30-day period do not need older rows.

**`proxy_batch_write_at: 10`.** LiteLLM does not write spend to the database after every request. It collects spend and writes it in batches every N seconds. Budgets are checked against these numbers, so a shorter interval means less overshoot when many requests arrive at the same time. Under parallel load a budget can still be overshot by the requests in flight (tested in this repo). Note on the default: the LiteLLM config settings page and the source code give 10 seconds as the default, while the example in the LiteLLM [production guide](https://docs.litellm.ai/docs/proxy/prod) uses 60 to reduce database writes. The repo sets 10 explicitly, so the behaviour does not depend on which default a future version uses.

**`user_header_mappings`.** With `ENABLE_FORWARD_USER_INFO_HEADERS=true` (set in `compose.yaml`), Open WebUI sends headers like `X-OpenWebUI-User-Id` with every request. This mapping tells LiteLLM to treat the value of that header as an end user with the role `customer`. Result: spend is tracked per Open WebUI user, and the per-user default budget applies (tested in this repo). The repo uses the user id and not the e-mail or name, because Open WebUI users can change their name, and admins can change names and e-mails. With the e-mail as key, a changed address would start a new end user with a fresh budget.

Be aware that any client holding a valid virtual key can set this header itself. Per-user budgets are only as trustworthy as the clients you hand keys to. The Open WebUI key is the only key that should send this header. Who can get that key, and what follows from it: [trust model](open-webui.md#trust-model-for-the-key-and-the-user-header).

**`allow_public_health_readiness_details: false`.** `/health/readiness` answers without authentication, which Docker health checks and load balancers need. With `false`, it returns only status and database state, no details about callbacks, cache or version. Full details remain available at the authenticated `/health/readiness/details`.

## models.yaml and the model_list structure

The default `litellm/models.yaml`, one entry:

```yaml
model_list:
  - model_name: mistral-small                 # name clients send and users see
    litellm_params:                           # how LiteLLM calls the provider
      model: mistral/mistral-small-2603       # provider prefix / provider model id
      api_base: https://api.eu.mistral.ai/v1  # EU endpoint instead of the global one
      api_key: os.environ/MISTRAL_API_KEY     # read from the environment
      input_cost_per_token: 0.000000165       # USD per input token
      output_cost_per_token: 0.00000066       # USD per output token
    model_info:
      description: "Mistral Small, processed in the EU (api.eu.mistral.ai)"
```

The structure ([config docs](https://docs.litellm.ai/docs/proxy/configs)):

- **`model_name`** is the public name. Open WebUI shows it in the model picker, API clients send it as `model`, virtual keys list it in `models`, and `fallbacks` refer to it. Keep names stable and provider-neutral if you can: `mistral-small` is fine, a deployment id is not.
- **`litellm_params`** describes the actual call. `model` is `<provider prefix>/<provider model id>`. The prefix selects the LiteLLM provider integration (`mistral/`, `azure/`, `bedrock/`, `vertex_ai/`, `openai/` for any OpenAI-compatible API, and so on). Everything in `litellm_params` is passed to the provider call.
- **`model_info`** is metadata for LiteLLM itself: `description`, `mode: embedding` for embedding models, `base_model` for price lookup (see below). It is not sent to the provider.

The three models in the default file:

| `model_name` | Provider model | Purpose |
|---|---|---|
| `mistral-small` | `mistral/mistral-small-2603` | Default chat model, cheap |
| `mistral-medium` | `mistral/mistral-medium-3-5` | Stronger chat model, falls back to `mistral-small` |
| `embedding` | `mistral/mistral-embed` | Document embeddings for Open WebUI (`mode: embedding`) |

**Why `api_base: https://api.eu.mistral.ai/v1`.** Mistral's global host `api.mistral.ai` has no location commitment; `api.eu.mistral.ai` processes in EU/EFTA data centres ([Mistral regional inference](https://docs.mistral.ai/inference/regional-inference.md), as of 2026-10-16). The LiteLLM Mistral provider honours `api_base` and appends `/v1` if it is missing (checked in the LiteLLM source). The static test `test_no_global_endpoints` fails if `api.mistral.ai` or `api.openai.com` appear in a model file.

**`os.environ/NAME`.** Any value in the config can be read from the environment with this syntax; LiteLLM runs `os.getenv("NAME")` ([config docs](https://docs.litellm.ai/docs/proxy/configs)). The LiteLLM container gets all of `.env` through `env_file`, so adding a key to `.env` and recreating the container is enough. The test `test_secrets_come_from_env` enforces that `api_key`, `aws_access_key_id`, `aws_secret_access_key` and `vertex_credentials` always use `os.environ/`.

## Load balancing with the same model_name

Several entries with the same `model_name` form one model group. LiteLLM spreads requests across them with the `routing_strategy` ([load balancing docs](https://docs.litellm.ai/docs/proxy/load_balancing)). Example: two Azure deployments in different EU regions behind one name.

```yaml
model_list:
  - model_name: gpt-5
    litellm_params:
      model: azure/<deployment-in-sweden>
      api_base: os.environ/AZURE_API_BASE_SE
      api_version: os.environ/AZURE_API_VERSION
      api_key: os.environ/AZURE_API_KEY_SE
    model_info:
      base_model: azure/eu/gpt-5-2025-08-07

  - model_name: gpt-5
    litellm_params:
      model: azure/<deployment-in-second-region>
      api_base: os.environ/AZURE_API_BASE_2
      api_version: os.environ/AZURE_API_VERSION
      api_key: os.environ/AZURE_API_KEY_2
    model_info:
      base_model: azure/eu/gpt-5-2025-08-07
```

The variable names with suffixes are examples; add them to `.env` yourself. Users see one `gpt-5`. If one deployment returns 429 or fails often enough (see the cooldown rules below), it goes into cooldown and the other one takes the traffic. Only group deployments that are interchangeable for your users, with the same data residency and similar price.

## Fallbacks, retries and cooldowns

These three mechanisms work on different levels:

1. **Retries** (`num_retries: 2`): the same model group is tried again, up to 2 more times. With several deployments in the group, a retry can land on another deployment.
2. **Cooldowns** (`cooldown_time: 30`): a deployment in cooldown is taken out of rotation for 30 seconds. In v1.105.1 the count-based rule ("more than `allowed_fails` failures per minute") only runs when `allowed_fails` differs from the LiteLLM default of 3. With this repo's `allowed_fails: 3`, the rate-based rules apply instead (`router_utils/cooldown_handlers.py`):
   - A 429, or more than 50 % failures with at least 5 requests per minute, triggers a cooldown only in model groups with more than one deployment.
   - Non-retryable errors such as 401 or 404 always trigger it.
   - 100 % failures need at least 1,000 requests per minute in a single-deployment group.

   Every model group in this repo has a single deployment, so provider 429s and 5xx errors never trigger a cooldown, and `allowed_fails: 3` has no effect. `cooldown_time: 30` only matters once a model group has several deployments, or a non-retryable error occurs. The default of 5 seconds is short for an EU endpoint having a bad minute; 30 seconds avoids hammering a provider that is already struggling.
3. **Fallbacks** (`fallbacks`): when the model group still fails after retries, LiteLLM tries the next model group in the list. Fallbacks cover all error types, including 429 and 500 ([reliability docs](https://docs.litellm.ai/docs/proxy/reliability)).

In this repo, a request for `mistral-medium` that keeps failing is tried 3 times (1 attempt plus 2 retries) and then answered by `mistral-small`. The end-to-end test `test_fallback_to_second_model` checks exactly this order against a mock model that always fails (tested in this repo).

Fallback names must exist in `models.yaml`. `test_fallbacks_point_to_existing_models` checks that. If you switch provider, update the `fallbacks` line too.

### Budgets can silently skip a fallback

Before each request, LiteLLM reserves the worst-case cost against every budget the request counts toward (key, user, team, end user, and so on). Without `max_tokens`, LiteLLM reserves 16,384 output tokens (or the model maximum if that is lower). The fallback check then reads only the key and user counters. If the reservation fills the remaining key budget, a configured fallback is skipped silently, and the client sees the error of the primary model (tested in this repo).

Measured in this repo with a key budget of 100 and a price of 0.02 per output token: without `max_tokens`, no fallback; with `max_tokens: 10`, the fallback works; with `general_settings.enforce_fallback_budget: false`, the fallback works.

Real-world size: without `max_tokens`, 16,384 output tokens of Mistral Medium at 8.25e-6 USD is about 0.14 USD plus input per request. A key or user with less than that left will not get a fallback.

Options, in order of preference:

- Leave budget headroom, especially on keys that use expensive models.
- Have API clients send `max_tokens`.
- Use keys without a budget for service accounts where you control the client.
- Set `general_settings.enforce_fallback_budget: false`. The LiteLLM docs describe the default `true` as: fallbacks only run if the calling key and user are within budget ([config settings](https://docs.litellm.ai/docs/proxy/config_settings)). With `false`, fallbacks to paid models are no longer budget-checked (see LiteLLM issue #41344). This repo keeps the default.

This mostly matters near the end of a budget, or with tiny budgets and expensive models. More in [Budgets](budgets.md).

## Prices: input_cost_per_token and base_model

LiteLLM computes spend from token counts and a price per token. Budgets are compared against that spend. **No price means spend 0, and a budget that never triggers.**

LiteLLM ships a built-in price list in USD ([custom pricing docs](https://docs.litellm.ai/docs/proxy/custom_pricing)). This repo sets prices explicitly in three situations:

**1. The built-in price is the wrong price.** Mistral's list has the global price. The EU endpoint costs 1.1 times that ([Mistral regional inference](https://docs.mistral.ai/inference/regional-inference.md), as of 2026-10-16). So `models.yaml` sets list price times 1.1:

| Model | Mistral list price per 1M tokens (input / output) | Price in `models.yaml` per token (input / output) |
|---|---|---|
| `mistral-small-2603` | 0.15 / 0.60 USD | 0.000000165 / 0.00000066 |
| `mistral-medium-3-5` | 1.50 / 7.50 USD | 0.00000165 / 0.00000825 |

Check these against the [Mistral pricing page](https://docs.mistral.ai/inference/pricing) before you rely on them. The test `test_main_models_have_eu_prices` fails if a model in `models.yaml` has no `input_cost_per_token`.

**2. The model is not in the price list at all.** STACKIT, IONOS, T-Systems, Scaleway and self-hosted models need `input_cost_per_token` and `output_cost_per_token`. The example files contain them, except `t-systems.yaml`, where you must put your contract price. For self-hosted models, one approach is GPU cost per hour divided by tokens per hour.

Two warnings:

- **No currency.** LiteLLM has no currency field. The STACKIT, IONOS and Scaleway example prices are EUR amounts. Budgets compare plain numbers, so do not mix EUR-priced and USD-priced models under one budget, or convert first.
- **Explicit zero.** The LiteLLM docs state that a model with both prices explicitly set to `0` skips all budget checks ([custom pricing docs](https://docs.litellm.ai/docs/proxy/custom_pricing#zero-cost-models-bypass-budget-checks)). That is useful for a free on-premises model, and dangerous if you forget to replace a placeholder `0`.

**3. The deployment name hides the model.** Azure deployment names are free text, so LiteLLM cannot tell from `azure/my-deployment` which model and price apply. `model_info.base_model` tells it:

```yaml
  - model_name: gpt-5
    litellm_params:
      model: azure/<your-datazone-deployment-name>
      api_base: os.environ/AZURE_API_BASE
      api_version: os.environ/AZURE_API_VERSION
      api_key: os.environ/AZURE_API_KEY
    model_info:
      base_model: azure/eu/gpt-5-2025-08-07
```

`azure/eu/gpt-5-2025-08-07` points LiteLLM to the EU Data Zone price instead of the global one ([base_model docs](https://docs.litellm.ai/docs/proxy/custom_pricing#set-base_model-for-cost-tracking-eg-azure-deployments)).

## Environment variables in compose.yaml

`compose.yaml` sets these for the LiteLLM container, on top of everything in `.env`. Values under `environment` take precedence over `env_file`.

| Variable | Value | Why |
|---|---|---|
| `DATABASE_URL` | `postgresql://llm:${POSTGRES_PASSWORD}@postgres:5432/litellm` | Read by `general_settings.database_url` |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` | `redis`, `6379`, from `.env` | Read by `router_settings` |
| `LITELLM_MODE` | `PRODUCTION` | Disables `load_dotenv()` inside LiteLLM, so only the environment Docker passes counts ([production docs](https://docs.litellm.ai/docs/proxy/prod)) |
| `LITELLM_LOG` | `ERROR` | Recommended log level for production; `set_verbose` is deprecated |
| `STORE_MODEL_IN_DB` | `"False"` | See below |

From `.env`: `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY` and the provider keys.

### `STORE_MODEL_IN_DB=False`

With `STORE_MODEL_IN_DB=True`, the LiteLLM admin UI can add models and change settings, and stores them in the database. This repo switches that off on purpose:

- **One source of truth.** The LiteLLM docs say that with `store_model_in_db` off, "the database is never read for config, so your `config.yaml` is fully authoritative" ([config docs](https://docs.litellm.ai/docs/proxy/configs)). With it on, database values win over the YAML for `general_settings`, `router_settings` and `litellm_settings`. Editing the file and restarting then does not change the running value, which is confusing to debug.
- **No silent duplicates.** A model added in the UI with the same name as a YAML model does not replace it; it becomes an additional deployment that is load balanced with the YAML entry ([model management docs](https://docs.litellm.ai/docs/proxy/model_management)). Traffic could then go to a provider nobody reviewed.
- **Review and history.** Model changes go through git: who added which provider, with which EU endpoint and which price. That is useful for your records of processing.
- **Provider keys stay out of the database.** UI-added models store their provider credentials encrypted in the database, which ties them to `LITELLM_SALT_KEY`.

Virtual keys, budgets, end users and spend are still stored in the database. That is unaffected by this setting.

### `LITELLM_SALT_KEY`: set once, never change

`LITELLM_SALT_KEY` encrypts provider credentials stored in the LiteLLM database. The LiteLLM docs: "Set once, never change it" and "changing it makes them unreadable" ([deploy docs](https://docs.litellm.ai/docs/proxy/deploy)). If it is not set, LiteLLM falls back to the master key for this encryption ([model management docs](https://docs.litellm.ai/docs/proxy/model_management)), which would tie your stored credentials to the master key and make master key rotation risky. That is why `init-env.sh` generates a separate salt key.

With `STORE_MODEL_IN_DB=False` there should be few or no encrypted credentials in the database today. Treat the rule as absolute anyway: you may enable database models later, and `init-env.sh` refuses to overwrite an existing `.env` and prints a warning about exactly this. Keep a backup of `.env` with the same care as the database backup.

## Applying changes

| You changed | Run |
|---|---|
| `litellm/config.yaml` or `litellm/models.yaml` | `docker compose restart litellm` |
| A provider key or other value in `.env` | `docker compose up -d --force-recreate litellm` |
| Budget values in `.env` | `python3 scripts/bootstrap.py` |
| Image version (`LITELLM_VERSION`) | `docker compose pull litellm && docker compose up -d litellm` |

After any change, check that LiteLLM is healthy and that the models are there:

```bash
docker compose ps litellm
docker compose logs --tail 50 litellm
export OWUI_KEY=$(grep '^OPENWEBUI_LITELLM_KEY=' .env | cut -d= -f2)
curl -s http://localhost:4000/v1/models -H "Authorization: Bearer $OWUI_KEY"
```

Run the static checks before you commit config changes. They need no running stack. Use a virtual environment (Debian 12 and Ubuntu 24.04 refuse `pip install` for the system Python):

```bash
python3 -m venv .venv && .venv/bin/pip install pytest pyyaml
.venv/bin/pytest tests/test_config_files.py -v
```

## Common problems

**A setting has no effect.** Check whether an included file contains the same top-level key; it replaces yours completely. Run `.venv/bin/pytest tests/test_config_files.py`.

**Spend stays at 0, budgets never trigger.** The model has no price. Add `input_cost_per_token` and `output_cost_per_token`, or `model_info.base_model` for Azure.

**Fallback does not happen near the end of a budget.** The worst-case reservation filled the remaining budget. See [Budgets can silently skip a fallback](#budgets-can-silently-skip-a-fallback).

**LiteLLM does not start after a config edit.** Usually YAML indentation, or an `os.environ/` variable that is missing in `.env`. Read `docker compose logs litellm`.

**A changed `.env` value is not picked up.** `docker compose restart` does not reload `env_file`. Use `docker compose up -d --force-recreate litellm`.

**Open WebUI does not show a new model.** First check that LiteLLM lists it with the `curl` command above. If it does, reload Open WebUI and check the model's visibility in the Open WebUI admin panel. See [Open WebUI with LiteLLM](open-webui.md#common-problems).

## Related guides

- [Quick start](quickstart.md)
- [Open WebUI with LiteLLM: connection, users and settings](open-webui.md)
- [Budgets and rate limits](budgets.md)
- [GDPR settings](gdpr.md)
- [PII masking with Presidio](pii-masking.md)

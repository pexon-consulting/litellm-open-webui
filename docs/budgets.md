# LiteLLM budgets and rate limits: per user, per key, per team

This guide explains how LiteLLM cost tracking, budgets and rate limits work in this stack, and which of them you get without an enterprise licence. You get copy-paste `curl` commands for virtual keys, teams, end users and budget rows, the exact errors users see when a limit hits, and the traps we measured in our own tests (overshoot, worst-case reservation, silently skipped fallbacks).

Versions: LiteLLM `v1.105.1`, Open WebUI `v0.12.2`. Behaviour marked "tested in this repo" is covered by `tests/test_gateway.py` or was measured against the running stack on 2026-10-16.

## Contents

- [How spend is counted](#how-spend-is-counted)
- [Budget levels: key, user, team, end user](#budget-levels-key-user-team-end-user)
- [How this repo sets budgets](#how-this-repo-sets-budgets)
- [budget_duration and reset dates](#budget_duration-and-reset-dates)
- [API examples](#api-examples)
- [What users see when a limit hits](#what-users-see-when-a-limit-hits)
- [Overshoot: why a budget can be exceeded](#overshoot-why-a-budget-can-be-exceeded)
- [Worst-case reservation and the silent fallback skip](#worst-case-reservation-and-the-silent-fallback-skip)
- [Prices and currency](#prices-and-currency)
- [How to check spend](#how-to-check-spend)
- [Common problems](#common-problems)
- [Tests that prove each behaviour](#tests-that-prove-each-behaviour)
- [Related guides](#related-guides)

## How spend is counted

LiteLLM computes the cost of each request from the token counts and a price per token. It adds that cost to the spend of every object the request belongs to: the virtual key, the key's user and team, and the end user (customer) if one is set. Each of those objects can have a `max_budget`. If any of them is over budget, the request is refused.

Two things follow from this:

- Budgets only work if LiteLLM knows a price for the model. A model without a price costs 0, and a budget of any size never triggers. See [Prices and currency](#prices-and-currency).
- Spend is written to the database in batches, not per request. See [Overshoot](#overshoot-why-a-budget-can-be-exceeded).

## Budget levels: key, user, team, end user

LiteLLM documents this budget hierarchy: global proxy `max_budget`, team, team member, internal user, virtual key, and customer (end user) ([LiteLLM docs: users and budgets](https://docs.litellm.ai/docs/proxy/users), as of 2026-10-16). The docs add: "Customer budgets are global per deployment … can't be scoped to a single key or team."

| Level | What it is | Set with | Licence |
|---|---|---|---|
| Global | Cap for the whole proxy | `litellm_settings.max_budget` | Open source |
| Virtual key | One API key | `/key/generate`, `/key/update` | Open source |
| Internal user | A LiteLLM user who owns keys | `/user/new` with `max_budget` | Open source |
| Team | A group of keys and users | `/team/new` with `max_budget` | Open source |
| Team member | One user inside a team | `team_member_budget` on `/team/new` | Open source |
| End user (customer) | The person behind a request, identified by a header or the `user` field | `/customer/new`, or a default budget row | Open source |
| Model-specific budget per key or user | `model_max_budget` | `/key/generate` | Enterprise |
| Budget / rate limit tiers | A `/budget/new` row assigned to keys | `/budget/new` + `budget_id` on keys | Enterprise |
| Tag-based budgets, temporary budget increases, soft budget e-mail alerts | | | Enterprise |

Sources for the licence column: the LiteLLM docs mark "Virtual Key (Model Specific)" budgets, "Internal User (Model Specific)" budgets and "Budget / Rate Limit Tiers" with an enterprise banner ([users](https://docs.litellm.ai/docs/proxy/users), [rate limit tiers](https://docs.litellm.ai/docs/proxy/rate_limit_tiers)), and the [enterprise feature list](https://docs.litellm.ai/docs/enterprise) names tag-based budgets, temporary budget increases and soft budget e-mail alerts (all as of 2026-10-16). Global, team, team member, internal user, key and customer budgets have no enterprise banner. In this repo's stack, `/key/generate`, `/team/new`, `/customer/new` and `/budget/new` all answered HTTP 200 without a licence (tested in this repo, 2026-10-16).

A note on `/budget/new`: the endpoint itself works without a licence, and this repo uses it for the default end-user budget. What the docs mark as enterprise is assigning such a budget row to keys as a "tier". See [open-source-vs-enterprise.md](open-source-vs-enterprise.md) for the full matrix.

### Which level fits Open WebUI

Open WebUI talks to LiteLLM with one virtual key for all users. So a key budget is a cap for the whole Open WebUI installation, not per person. Per-person budgets need the end-user level: Open WebUI sends the user's id in a header, and LiteLLM maps it to an end user. That is what this repo does.

### Trust model of the user header

LiteLLM believes whatever `X-OpenWebUI-User-Id` says, as long as the request carries a valid key. Anyone who holds `OPENWEBUI_LITELLM_KEY` can send any user id: they can bill another person's budget, or invent new ids and get a fresh default budget for each one. Only the budget on the key itself (`OPENWEBUI_BUDGET_USD`) still holds.

Who can get that key: the Open WebUI container environment, Open WebUI admins (Admin Panel > Settings > Connections), any Open WebUI Tool or Function (Python code that runs inside that container), and any process on the host, because LiteLLM listens on `127.0.0.1:4000`. So:

- Never reuse the Open WebUI key for other clients. Give each application its own key with its own budget.
- Treat Open WebUI admins as trusted, and keep that role small.
- `scripts/bootstrap.py` restricts the key to the LLM API routes (`allowed_routes: ["llm_api_routes"]`), so it cannot call management endpoints such as `/key/generate` (tested in this repo).

## How this repo sets budgets

Three pieces work together.

**1. Open WebUI forwards the user.** `compose.yaml` sets `ENABLE_FORWARD_USER_INFO_HEADERS: "true"`, so Open WebUI sends `X-OpenWebUI-User-Id` with each request. `litellm/config.yaml` maps that header to a LiteLLM end user:

```yaml
general_settings:
  user_header_mappings:
    - header_name: X-OpenWebUI-User-Id
      litellm_user_role: customer
```

We use the id, not the e-mail. The LiteLLM docs warn that in Open WebUI "Users can modify their own usernames" and "Administrators can modify both usernames and emails of any account" ([LiteLLM Open WebUI tutorial](https://docs.litellm.ai/docs/tutorials/openweb_ui), as of 2026-10-16). Tested in this repo: spend appears per Open WebUI user, both for a direct request with the header and for a chat sent through Open WebUI.

**2. A default budget for every end user.** `litellm/config.yaml` sets:

```yaml
litellm_settings:
  max_end_user_budget_id: per-user-default
```

Every end user without an own budget gets the limits of the budget row `per-user-default`. Tested in this repo: with that row set to a tiny amount, a new end user created through the header got HTTP 422 `budget_exceeded`. No enterprise licence is needed.

**3. `scripts/bootstrap.py` creates the row and the Open WebUI key.** It reads `.env` and calls LiteLLM with the master key:

- `per-user-default` via `/budget/new` (or `/budget/update` if it exists), with `max_budget = USER_BUDGET_USD` and `budget_duration = USER_BUDGET_PERIOD`.
- The virtual key `OPENWEBUI_LITELLM_KEY` with alias `open-webui` via `/key/generate` (or `/key/update`), with `max_budget = OPENWEBUI_BUDGET_USD` and `budget_duration = OPENWEBUI_BUDGET_PERIOD`.

Defaults from `.env.example` and `scripts/init-env.sh`:

```bash
USER_BUDGET_USD=20
USER_BUDGET_PERIOD=30d
OPENWEBUI_BUDGET_USD=500
OPENWEBUI_BUDGET_PERIOD=30d
```

So each person can spend 20 USD per period, and all Open WebUI traffic together 500 USD. The key cap is a safety net for the whole installation. With 30 users, 30 times 20 USD is 600 USD, so the 500 USD key cap would stop everyone before all users reach their own limit. Size `OPENWEBUI_BUDGET_USD` as roughly users times `USER_BUDGET_USD`, plus a buffer (see [the reservation section](#worst-case-reservation-and-the-silent-fallback-skip) for why a buffer matters).

To change the amounts, edit `.env` and run the script again. It is safe to repeat:

```bash
python3 scripts/bootstrap.py
```

Expected output:

```text
Updated budget per-user-default: 20.0 USD per user, period 30d
Updated key open-webui: 500.0 USD for all Open WebUI traffic, period 30d
```

Measured in this repo: a change to `per-user-default` was not enforced within the first 15 seconds, but was after waiting 65 seconds. Allow about a minute before you test a new value.

## budget_duration and reset dates

`budget_duration` sets how often spend goes back to 0. The docs list seconds, minutes, hours and days (`"30s"`, `"30m"`, `"30h"`, `"30d"`) ([users](https://docs.litellm.ai/docs/proxy/users)). The parser in `v1.105.1` also accepts weeks (`w`) and months (`mo`) ([duration_parser.py @ v1.105.1](https://github.com/BerriAI/litellm/blob/v1.105.1/litellm/litellm_core_utils/duration_parser.py)).

Resets are aligned to calendar boundaries, not to the moment you created the budget. From `get_next_standardized_reset_time` in the same file (read in the `v1.105.1` image):

| `budget_duration` | Next reset |
|---|---|
| `1d` | Next midnight |
| `7d` or `1w` | Next Monday, midnight |
| `30d` or `1mo` | The 1st of the next month, midnight |
| Other `Nd` | N days from midnight today |
| `Nh`, `Nm`, `Ns` | Aligned to hour, minute or second boundaries |
| `2mo` and up | Not supported: "Monthly resets currently only support 1 month intervals" |

Tested in this repo: a key created on 2026-10-16 with `"1mo"`, and the `per-user-default` row with `"30d"`, both showed `budget_reset_at: 2026-11-01T00:00:00`. So `30d` means "monthly, on the 1st", and the first period after setup is shorter than 30 days.

Midnight is UTC by default. The `v1.105.1` source reads two optional `litellm_settings` keys: `timezone` (falls back to `"UTC"`) and `budget_reset_time` (24-hour `"HH:MM"`). This repo sets neither, so resets happen at 00:00 UTC, which is 01:00 or 02:00 in Germany. We read these keys in the source but did not test them.

Several windows on one key are possible with `budget_limits`, for example 10 USD per day and 100 USD per month (`30d`, reset on the 1st) ([users](https://docs.litellm.ai/docs/proxy/users)):

```json
"budget_limits": [
  {"budget_duration": "24h", "max_budget": 10},
  {"budget_duration": "30d", "max_budget": 100}
]
```

## API examples

All commands run on the server (LiteLLM listens on `127.0.0.1:4000` only). Load the master key from `.env` first (only this key, not the whole file: exported variables win over `.env` for `docker compose`):

```bash
export LITELLM_MASTER_KEY=$(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2)
export LITELLM=http://localhost:4000
```

Every endpoint below was called successfully against this repo's stack on 2026-10-16 without an enterprise licence.

### Create a virtual key with a budget and rate limits

```bash
curl -s "$LITELLM/key/generate" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "key_alias": "team-data-science",
    "models": ["mistral-small"],
    "max_budget": 50,
    "budget_duration": "30d",
    "rpm_limit": 60,
    "tpm_limit": 100000
  }'
```

The answer contains `key` (starts with `sk-`). It is shown once. Field names are from `GenerateKeyRequest` in [`_types.py` @ v1.105.1](https://github.com/BerriAI/litellm/blob/v1.105.1/litellm/proxy/_types.py). `models` limits the key to those model names; an empty list means all models.

### Change a key

```bash
curl -s "$LITELLM/key/update" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key": "sk-...", "max_budget": 80}'
```

### Read a key's spend and reset date

```bash
curl -s "$LITELLM/key/info?key=sk-..." \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```

The `info` object has `spend`, `max_budget`, `budget_duration`, `budget_reset_at`, `rpm_limit`, `tpm_limit` and `models` (seen in this repo's stack).

### Give one Open WebUI user a different budget

End users are identified by their Open WebUI user id. Look it up in the Open WebUI database:

```bash
docker compose exec -T postgres psql -U llm -d openwebui -tAc 'SELECT id, email FROM "user"'
```

Then create the end user with an own budget (tested in this repo with `user_id` and `max_budget`):

```bash
curl -s "$LITELLM/customer/new" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "<open-webui-user-id>", "max_budget": 100, "budget_duration": "30d"}'
```

Or link the end user to an existing budget row with `budget_id` (tested in this repo):

```bash
curl -s "$LITELLM/customer/new" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "<open-webui-user-id>", "budget_id": "power-users"}'
```

`/customer/new` creates the end user. If the user already sent a request, an end user row exists already. We did not test `/customer/new` on an existing id; if it fails, delete the row first with `/customer/delete` (`{"user_ids": ["<id>"]}`, tested in this repo) and create it again. Deleting the row also deletes its spend.

### Check an end user

```bash
curl -s "$LITELLM/customer/info?end_user_id=<open-webui-user-id>" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```

Returns `spend`, `budget_id` and the linked `litellm_budget_table` (with `max_budget`, `budget_duration`, `budget_reset_at`). Careful: an end user that only gets the default from `max_end_user_budget_id` shows `budget_id: null` here. The default is applied at request time, not stored on the row (seen in this repo's stack).

### Create a budget row

```bash
curl -s "$LITELLM/budget/new" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"budget_id": "power-users", "max_budget": 100, "budget_duration": "30d", "rpm_limit": 30}'
```

Fields from `BudgetNewRequest`: `budget_id`, `max_budget`, `soft_budget`, `max_parallel_requests`, `tpm_limit`, `rpm_limit`, `tpd_limit`, `budget_duration`, `model_max_budget`, `budget_reset_at`. Use the row as an end-user default or with `budget_id` on `/customer/new`. Assigning it to keys as a tier is an enterprise feature per the docs.

### Create a team

```bash
curl -s "$LITELLM/team/new" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"team_alias": "marketing", "max_budget": 200, "budget_duration": "30d"}'
```

Then create keys with `"team_id": "<team_id from the answer>"`. Team spend shows in `/team/info?team_id=...`. This repo does not use teams by default, because Open WebUI uses one key. Teams are useful for other clients (scripts, IDE plugins) that get their own keys.

## What users see when a limit hits

All three cases below are tested in this repo. The bodies are copied from the running stack.

### Budget exceeded: HTTP 422

```json
{"error": {"message": "Budget has been exceeded! Key=probe3 (sk-...dlBA) Current cost: 0.005, Max budget: 0.0001", "type": "budget_exceeded", "param": null, "code": "422"}}
```

For an end user:

```json
{"error": {"message": "ExceededBudget: End User=<id> over budget. Spend=0.055, Budget=0.0001", "type": "budget_exceeded", "param": null, "code": "422"}}
```

The LiteLLM error reference says `budget_exceeded` returns HTTP 429 ([error reference](https://docs.litellm.ai/docs/proxy/error_reference), as of 2026-10-16). `v1.105.1` returns 422. If your monitoring or client retries on 429, it will not see budget errors as throttling, which is good: retrying a budget error does not help.

The first request on a fresh, tiny budget passes, because no spend exists yet when it is checked.

In Open WebUI, the request goes to LiteLLM with the shared key, so a user who hits the per-user budget gets this error back through Open WebUI. This repo does not test how Open WebUI renders the error in the chat window. Tell users in advance what the message means and whom to ask for more budget.

### Rate limit: HTTP 429

```json
{"error": {"message": "Rate limit exceeded for api_key: <hash>. Limit type: requests. Current limit: 1, Remaining: 0. Limit resets at: 2026-10-16 08:59:08 UTC", "type": "throttling_error", "param": null, "code": "429"}}
```

`rpm_limit` (requests per minute) on a key is tested in this repo. `tpm_limit` (tokens per minute) and `tpd_limit` (tokens per day) exist as fields on keys and budget rows; we did not test them. For Open WebUI, a key `rpm_limit` applies to all users together. A per-person limit belongs on the budget row (`rpm_limit` on `per-user-default`), which we also did not test.

### Model not allowed: HTTP 403

```json
{"error": {"message": "The requested model 'mistral-medium' is not available for this API key, or the model name is invalid. Check the models available to you and try again.", "type": "key_model_access_denied", "param": "model", "code": "403"}}
```

The test also checks that the request never reaches the provider. So `models` on a key is a hard gate, not only a cost control.

### Response headers

Successful responses carry the current numbers, which helps when debugging (seen in this repo's stack): `x-litellm-response-cost`, `x-litellm-key-spend`, `x-litellm-key-max-budget`, `x-litellm-key-rpm-limit`, `x-litellm-key-tpm-limit`, `x-litellm-attempted-fallbacks`.

## Overshoot: why a budget can be exceeded

LiteLLM writes spend to the database in batches. The interval is `proxy_batch_write_at` ([config settings](https://docs.litellm.ai/docs/proxy/config_settings)). In v1.105.1 the default is 10 seconds plus a random 0-5 seconds (`litellm.constants.PROXY_BATCH_WRITE_AT`); the LiteLLM production guide's example uses 60 to reduce database writes. This repo sets 10 explicitly in `litellm/config.yaml`, so a different upstream default does not loosen budgets:

```yaml
general_settings:
  proxy_batch_write_at: 10
```

Budget checks see the numbers that were written. Requests that arrive before the next write all pass. Under parallel load, the overshoot is roughly the cost of all requests in flight.

What we measured on 2026-10-16:

- Key budget of 0.0001 USD, 0.005 USD per request: the second request was refused. Key budgets react almost at once.
- End-user default budget of 0.0001 USD, one request per second: 11 requests passed, the 12th got 422. Spend was 0.055 USD, 550 times the budget. End-user budgets lag by about the batch interval.

In practice: a user with 20 USD per month can end at 20 USD plus whatever they spend in about 10 seconds. That is small for chat. It can be larger for parallel API clients or document uploads with many embedding calls. Treat budgets as cost control, not as a hard billing limit. If you need a hard ceiling, set the provider-side spending limit too.

## Worst-case reservation and the silent fallback skip

### What LiteLLM does

Before each request, LiteLLM reserves the worst-case cost against every budget the request counts toward (key, user, team, end user, and the other levels that have a budget). The worst case is the input tokens plus the output tokens, times the prices. Without `max_tokens`, LiteLLM reserves 16,384 output tokens (or the model maximum if that is lower). After the answer, the reservation is replaced by the real cost. The code is in `litellm/proxy/spend_tracking/budget_reservation.py` (`v1.105.1`, `DEFAULT_MAX_OUTPUT_TOKENS_FALLBACK`).

For Mistral Medium in `litellm/models.yaml`, without `max_tokens`: 16,384 output tokens times 0.00000825 USD is about 0.14 USD plus input reserved for one request, even if the answer costs a fraction of a cent.

### Why fallbacks can disappear

This repo configures a fallback in `litellm/config.yaml`:

```yaml
router_settings:
  fallbacks:
    - mistral-medium: ["mistral-small"]
```

With `general_settings.enforce_fallback_budget` (default `true`), LiteLLM checks budgets again before it tries a fallback model. That check reads only the key and user counters. Team, end-user, organisation and per-model budgets are not part of it (source comment in `litellm/proxy/auth/fallback_budget.py`, `v1.105.1`).

If the reservation of the primary model fills the remaining key budget, the fallback is skipped without a message to the client. The client gets the primary model's error (for example 500), not the fallback's answer.

Measured in our tests, with a key budget of 100 and a price of 0.02 per output token:

| Setting | Fallback |
|---|---|
| No `max_tokens` | Skipped, client sees the primary error |
| `max_tokens: 10` | Works |
| `general_settings.enforce_fallback_budget: false` | Works |

`tests/test_gateway.py::test_fallback_to_second_model` proves the working case: with a realistic price and a key budget of 100, the failing model is tried three times (first attempt plus `num_retries: 2`), then `mistral-small` answers. `tests/models.test.yaml` keeps the price of the failing model realistic on purpose for this reason.

When it matters: near the end of a key budget, with small budgets, or with expensive models that have a large maximum output. With this repo's defaults (500 USD on the Open WebUI key), fallbacks start failing in the last ~0.14 USD of the period.

### Three countermeasures

1. **Set `max_tokens`.** Then the reservation is based on `max_tokens`, not on the model maximum. Clients that send `max_tokens` reserve far less. We measured that the fallback works with `max_tokens: 10`.
2. **Keep a buffer on the key budget.** Size `OPENWEBUI_BUDGET_USD` above the sum of all user budgets, so the key cap is never the limit that hits first. Per-user budgets then stop people before the key budget gets close to its end. Service keys for scripts can go without `max_budget` if other limits (end user, team) control the cost.
3. **Turn the fallback check off**, only if you understand the trade-off:

   ```yaml
   general_settings:
     enforce_fallback_budget: false
   ```

   Then fallbacks work again, but fallbacks to paid models are not checked against the budget at all. See [LiteLLM issue #41344](https://github.com/BerriAI/litellm/issues/41344). This repo keeps the default (`true`).

## Prices and currency

LiteLLM prices models in USD from a built-in price list. Budget values have no currency of their own; they are compared with these numbers.

- **Mistral EU endpoint.** The built-in list has Mistral's global prices. The EU endpoint `api.eu.mistral.ai` costs 1.1 times the list price, so `litellm/models.yaml` sets explicit `input_cost_per_token` and `output_cost_per_token` (USD, as of 2026-10-16). `tests/test_config_files.py::test_main_models_have_eu_prices` fails if a main model has no input price.
- **Providers without built-in prices** (STACKIT, IONOS, T-Systems, Scaleway, self-hosted models) need `input_cost_per_token` and `output_cost_per_token`. Without them spend stays 0 and budgets never trigger. The files in `examples/providers/` set them where a public price exists. `examples/providers/t-systems.yaml` has commented-out price lines for your contract price (do not use `0` as a placeholder, LiteLLM treats an explicit 0 as free), and `examples/providers/self-hosted.yaml` has none.
- **EUR prices.** The STACKIT, IONOS and Scaleway examples use EUR numbers. LiteLLM treats them as plain numbers. Do not mix EUR-priced and USD-priced models in one budget, or convert first.
- **Azure.** Deployment names are free text, so LiteLLM cannot look up the price. `examples/providers/azure-openai.yaml` sets `model_info.base_model` (for example `azure/eu/gpt-5-2025-08-07`) to point LiteLLM to the EU Data Zone price.

Check prices against the provider's price page before you rely on budgets. Prices change.

## How to check spend

### Admin UI

`http://localhost:4000/ui`, user `admin`, password = `LITELLM_MASTER_KEY` ([LiteLLM quick start](https://docs.litellm.ai/docs/proxy/docker_quick_start), as of 2026-10-16). With `compose.tls.yaml`, LiteLLM is not public; open an SSH tunnel first:

```bash
ssh -L 4000:127.0.0.1:4000 your-server
```

### Endpoints that work without a licence

All tested against this repo's stack on 2026-10-16:

```bash
# Last spend log rows (no prompts or answers: store_prompts_in_spend_logs is false)
curl -s "$LITELLM/spend/logs?limit=20" -H "Authorization: Bearer $LITELLM_MASTER_KEY"

# Spend per key (the open-webui key shows all Open WebUI traffic)
curl -s "$LITELLM/spend/keys" -H "Authorization: Bearer $LITELLM_MASTER_KEY"

# Spend per internal user
curl -s "$LITELLM/spend/users" -H "Authorization: Bearer $LITELLM_MASTER_KEY"

# One key, one end user, one team
curl -s "$LITELLM/key/info?key=sk-..." -H "Authorization: Bearer $LITELLM_MASTER_KEY"
curl -s "$LITELLM/customer/info?end_user_id=<id>" -H "Authorization: Bearer $LITELLM_MASTER_KEY"
curl -s "$LITELLM/team/info?team_id=<id>" -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```

The docs say `/spend/keys` and `/spend/users` are scoped to the caller; full tables need a `proxy_admin` or `proxy_admin_viewer` key ([cost tracking](https://docs.litellm.ai/docs/proxy/cost_tracking), as of 2026-10-16). `/spend/users` lists internal users, not end users, so it is empty in this repo's default setup. Use `/customer/info` per Open WebUI user.

### Enterprise only

`/global/spend/report` (spend grouped by team, key or customer) needs a licence. Without one, `v1.105.1` answers HTTP 400 with "You must be a LiteLLM Enterprise user to use this feature" (tested in this repo). For a monthly report per person without a licence, query the spend log table directly:

```bash
docker compose exec -T postgres psql -U llm -d litellm <<'SQL'
SELECT end_user, round(sum(spend)::numeric, 4) AS usd
  FROM "LiteLLM_SpendLogs"
 WHERE "startTime" >= date_trunc('month', now())
 GROUP BY end_user ORDER BY usd DESC;
SQL
```

Tested in this repo on 2026-10-16. `end_user` is the Open WebUI user id; an empty value means requests without the header (scripts, tests). The month starts at 00:00 UTC here, like the budget resets. Rows older than 90 days are deleted by `maximum_spend_logs_retention_period: "90d"` in `litellm/config.yaml`, so this table is not a long-term archive.

## Common problems

**Spend stays 0.** The model has no price. Add `input_cost_per_token` and `output_cost_per_token` to its entry in `litellm/models.yaml`.

**Every Open WebUI user has the same spend, or no end users appear.** Check that `ENABLE_FORWARD_USER_INFO_HEADERS` is `"true"` in `compose.yaml` and that `user_header_mappings` is in `general_settings` of `litellm/config.yaml`, not in an included file (includes replace dicts like `general_settings`; `tests/test_config_files.py::test_config_keeps_settings_out_of_includes` guards this).

**A user is over budget by more than expected.** That is the batch write lag. See [Overshoot](#overshoot-why-a-budget-can-be-exceeded).

**The budget resets on the 1st, not 30 days after setup.** That is how `30d` works in `v1.105.1`. See [budget_duration and reset dates](#budget_duration-and-reset-dates).

**A new budget value has no effect.** Wait about a minute after `python3 scripts/bootstrap.py`, then test again.

**Fallback stops working late in the month.** The worst-case reservation fills the key budget. See [the countermeasures](#three-countermeasures).

**Your monitoring expects 429 for budget errors.** `v1.105.1` returns 422 with `type: budget_exceeded`. Match on the type, not only the code.

## Tests that prove each behaviour

Run the tests on a fresh stack with the mock LLM (no provider key, no cost):

> **Warning:** Never run the tests against a production stack. The test overlay replaces your models with the mock, and on a fresh stack the tests sign up the first Open WebUI admin with a random password. Use a separate clone with its own `COMPOSE_PROJECT_NAME` and other ports (see [Quick start](quickstart.md#run-the-tests)).

```bash
docker compose -f compose.yaml -f compose.pii.yaml -f compose.test.yaml up -d --wait
python3 scripts/bootstrap.py
python3 -m venv .venv && .venv/bin/pip install pytest pyyaml
.venv/bin/pytest tests
```

| Behaviour | Test |
|---|---|
| Key budget exceeded returns 422 `budget_exceeded`, first request passes | `tests/test_gateway.py::test_key_budget_returns_422` |
| `rpm_limit` returns 429 | `tests/test_gateway.py::test_rpm_limit_returns_429` |
| Model not in `models` returns 403, provider never called | `tests/test_gateway.py::test_model_not_allowed_returns_403` |
| Fallback works when the reservation fits the key budget | `tests/test_gateway.py::test_fallback_to_second_model` |
| Spend per header user | `tests/test_gateway.py::test_header_user_gets_own_spend` |
| End-user budget exceeded returns 422 | `tests/test_gateway.py::test_header_user_budget_returns_422` |
| Open WebUI forwards the user id, spend lands on that end user | `tests/test_gateway.py::test_openwebui_forwards_user_to_litellm` |
| Prompts are not stored in spend logs | `tests/test_gateway.py::test_prompts_not_stored_in_spend_logs` |
| Main models have explicit prices | `tests/test_config_files.py::test_main_models_have_eu_prices` |
| Fallback targets exist | `tests/test_config_files.py::test_fallbacks_point_to_existing_models` |

Not covered by an automated test (measured by hand against the running stack on 2026-10-16): the default budget from `max_end_user_budget_id`, the reset dates, the skipped fallback without `max_tokens`, and the overshoot numbers.

## Related guides

- [LiteLLM open source vs enterprise](open-source-vs-enterprise.md)
- [LLM gateway comparison](llm-gateway-comparison.md)
- [GDPR settings](gdpr.md)
- [PII masking with Presidio](pii-masking.md)
- [Quick start](quickstart.md)
- [Configuration reference](configuration.md)
- [EU model providers](eu-models.md)
- [Open WebUI with LiteLLM](open-webui.md)

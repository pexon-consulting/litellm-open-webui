---
name: litellm-gateway-admin
description: Operate the LiteLLM + Open WebUI gateway from this repository. Create keys and teams, set or raise budgets, find out who spent what, add an EU model provider, and debug 422/429/403 answers. Use when the user asks to manage LiteLLM keys, budgets, spend, models or users of this stack.
---

# LiteLLM gateway admin

Works with the stack from this repository (LiteLLM v1.105.1, Open WebUI v0.12.2). All calls
go to the LiteLLM admin API on `http://localhost:4000` with the master key from `.env`.
On a server, LiteLLM is only on 127.0.0.1; open an SSH tunnel first
(`ssh -L 4000:127.0.0.1:4000 <server>`).

## Before any call

```bash
cd <repo>
export LITELLM_MASTER_KEY=$(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2)
H="Authorization: Bearer $LITELLM_MASTER_KEY"; J="Content-Type: application/json"; L=http://localhost:4000
curl -s $L/health/readiness
```

Never print `LITELLM_MASTER_KEY`, provider keys or generated keys into the chat. Show only
the key alias or the last four characters. Do not source the whole `.env` into the shell:
exported variables win over `.env` for `docker compose`, so later `.env` edits would be ignored.
Never hand out `OPENWEBUI_LITELLM_KEY` to other clients: anyone holding it can send any
`X-OpenWebUI-User-Id` header and spend another person's budget. Create a separate key.

## Tasks

**Key for an application or a team** (budget in USD, `budget_duration` like `30d`):

```bash
curl -s $L/team/new -H "$H" -H "$J" -d '{"team_alias":"finance","max_budget":50,"budget_duration":"30d","models":["mistral-small"]}'
curl -s $L/key/generate -H "$H" -H "$J" -d '{"team_id":"<team_id>","key_alias":"finance-app","max_budget":10}'
```

A team key gets 403 for models outside the team's `models` list.

**Budget of one Open WebUI user.** Open WebUI users appear in LiteLLM as end users
(customers) with their Open WebUI user id. New users get the `per-user-default` budget.

```bash
curl -s "$L/customer/info?end_user_id=<open-webui-user-id>" -H "$H"
curl -s $L/customer/update -H "$H" -H "$J" -d '{"user_id":"<open-webui-user-id>","max_budget":40}'
```

Tell the user that a changed budget is cached and does not apply instantly.

**Default budget for everyone:** change `USER_BUDGET_USD` / `USER_BUDGET_PERIOD` in `.env`,
then `python3 scripts/bootstrap.py`. The cap for all Open WebUI traffic is
`OPENWEBUI_BUDGET_USD`.

**Cut someone off:** deactivate the user in Open WebUI (Admin Panel > Users, role "pending").
For an application key: `curl -s $L/key/block -H "$H" -H "$J" -d '{"key":"<key>"}'` (then 401).
Do not use `/customer/block`: in v1.105.1 it returns 500 and does not stop requests.

**Who spent what:**

```bash
curl -s "$L/spend/logs?start_date=2026-10-01&end_date=2026-10-31" -H "$H"
```

Returns daily totals per model. The `users` field holds internal LiteLLM users, which are
empty for Open WebUI traffic. For per-person totals use `/customer/info` or the `end_user`
SQL in `docs/budgets.md`. Spend reaches the database every 10 seconds
(`proxy_batch_write_at`), so the last seconds are missing.

**Add a model provider:** copy entries from `examples/providers/<provider>.yaml` into
`litellm/models.yaml`, put the key into `.env`, then `docker compose up -d --force-recreate litellm`
(a plain `restart` reloads the YAML but not a changed `.env`). Keep the
price lines; without `input_cost_per_token` spend stays 0 and budgets never trigger. Do not
add `router_settings` or `general_settings` to `models.yaml`: the include replaces them.
When you replace the whole file, keep a model named `embedding` (Open WebUI document search)
and update `router_settings.fallbacks` in `litellm/config.yaml`, then run
`.venv/bin/pytest tests/test_config_files.py` before the restart.

## Reading error answers

| Status | Meaning | Fix |
| --- | --- | --- |
| 422 `budget_exceeded` | key, team or user budget used up | raise the budget or wait for the reset date |
| 429 | rpm/tpm limit of the key | wait or raise `rpm_limit` |
| 403 | model not allowed for this key or team | add the model to `models` |
| 401 | key unknown or blocked | check `/key/info?key=...` |
| 500 after a fallback model is configured | primary failed and the fallback was skipped because the worst-case cost reservation filled the key budget | set `max_tokens`, raise the budget, see docs/budgets.md |

## Boundaries

- Do not change `LITELLM_SALT_KEY`; stored provider keys become unreadable.
- Do not run `docker compose down -v` on a real installation: it deletes all chats, users and spend.
- Questions about GDPR, works council or contracts: explain the settings, and say that the
  legal assessment belongs to the data protection officer.

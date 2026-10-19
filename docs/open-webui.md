# Open WebUI with LiteLLM: connection, users and settings that matter

This guide explains how Open WebUI is wired to the LiteLLM Proxy in this repo and which Open WebUI settings decide whether the setup is safe for staff. You learn how the connection and the virtual key work, how spend is tracked per user, why document search runs through LiteLLM, which environment variables Open WebUI ignores after the first start, how sign-up and approval behave, what the privacy defaults do, how to delete old chats, what the licence says about branding, and how to upgrade without losing data.

Versions: Open WebUI v0.12.2 and LiteLLM v1.105.1. Statements marked "tested in this repo" are covered by `tests/test_gateway.py`. Open WebUI docs are quoted as of 2026-10-16; the main reference is the [environment variable reference](https://docs.openwebui.com/reference/env-configuration).

## Contents

- [How Open WebUI talks to LiteLLM](#how-open-webui-talks-to-litellm)
- [Per-user spend: the user info headers](#per-user-spend-the-user-info-headers)
- [Trust model for the key and the user header](#trust-model-for-the-key-and-the-user-header)
- [Embeddings and document search (RAG) via LiteLLM and pgvector](#embeddings-and-document-search-rag-via-litellm-and-pgvector)
- [OFFLINE_MODE and the Hugging Face download](#offline_mode-and-the-hugging-face-download)
- [The ENABLE_PERSISTENT_CONFIG trap](#the-enable_persistent_config-trap)
- [Sign-up, roles and approval](#sign-up-roles-and-approval)
- [Privacy defaults in compose.yaml](#privacy-defaults-in-composeyaml)
- [Chat retention](#chat-retention)
- [Speech-to-text](#speech-to-text)
- [Licence: branding above 50 users](#licence-branding-above-50-users)
- [Upgrading Open WebUI safely](#upgrading-open-webui-safely)
- [Common problems](#common-problems)
- [Related guides](#related-guides)

## How Open WebUI talks to LiteLLM

The relevant part of `compose.yaml`:

```yaml
      OPENAI_API_BASE_URL: http://litellm:4000/v1
      OPENAI_API_KEY: ${OPENWEBUI_LITELLM_KEY:?run ./scripts/init-env.sh first}
      ENABLE_OLLAMA_API: "false"
```

**`OPENAI_API_BASE_URL: http://litellm:4000/v1`.** Open WebUI treats LiteLLM as an OpenAI-compatible API. `litellm` is the service name on the internal Docker network, so this traffic never leaves the Docker host and does not go through the port published on `127.0.0.1:4000`. The Open WebUI default would be `https://api.openai.com/v1`.

**`OPENAI_API_KEY`: one virtual key for all of Open WebUI.** `init-env.sh` generates `OPENWEBUI_LITELLM_KEY`, and `scripts/bootstrap.py` registers it in LiteLLM with the alias `open-webui` and a budget for all Open WebUI traffic together (default 500 USD, reset monthly on the 1st). The script also restricts the key to the LLM API routes (`allowed_routes: ["llm_api_routes"]`), so it can list models, chat and embed, but `/key/generate` and the other management endpoints answer 403 (tested in this repo). Open WebUI never holds a provider key. If the Open WebUI server is compromised, the attacker gets a LiteLLM key with a spending cap, which you can block in the LiteLLM admin UI, not your Azure or Mistral credentials. The Open WebUI docs recommend the same: "For OpenAI-compatible backends and proxies (including LiteLLM), configure least-privilege keys for regular user traffic whenever possible."

**`ENABLE_OLLAMA_API: "false"`.** The default is `true`, which makes Open WebUI look for an Ollama server. All models come from LiteLLM here, so the Ollama connection is switched off. If you run Ollama, add it to LiteLLM (`examples/providers/self-hosted.yaml`) so it gets the same budgets and logging.

**The model list.** Open WebUI asks LiteLLM for `GET /v1/models` with its key. LiteLLM answers with every `model_name` the key may use. The `open-webui` key has no `models` restriction, so it sees everything in `litellm/models.yaml`. That includes `embedding` (tested in this repo: LiteLLM lists it with `"mode": "embedding"`). To keep users from picking the embedding model for chat, hide it in the Open WebUI admin panel under the models settings.

To restrict which models Open WebUI can use at all, give the key a model list in LiteLLM, for example in the admin UI under Virtual Keys. A request for a model outside the list returns HTTP 403 and never reaches the provider (tested in this repo).

**Model visibility for regular users.** The Open WebUI docs state that models, knowledge bases, tools and skills are "private by default" and access is granted per user, per group or as public ([authentication and access](https://docs.openwebui.com/features/authentication-access/), [workspace models](https://docs.openwebui.com/features/workspace/models)). If an approved user sees no models while the admin does, open the model in the admin panel and set its visibility to public or share it with a group. We did not test the default visibility of connection models in v0.12.2.

## Per-user spend: the user info headers

```yaml
      ENABLE_FORWARD_USER_INFO_HEADERS: "true"
```

With this setting (default `false`), Open WebUI adds the signed-in user's identity to its requests to LiteLLM. According to the Open WebUI docs, OpenAI-compatible connections receive:

| Header | Content |
|---|---|
| `X-OpenWebUI-User-Id` | Internal user id (stable) |
| `X-OpenWebUI-User-Name` | Display name |
| `X-OpenWebUI-User-Email` | E-mail address |
| `X-OpenWebUI-User-Role` | `admin`, `user` or `pending` |
| `X-OpenWebUI-Chat-Id` | Chat id |
| `X-OpenWebUI-Auth-Type` | `jwt` for a browser session, `api_key` for an Open WebUI API key |

On the LiteLLM side, `litellm/config.yaml` maps only the id:

```yaml
general_settings:
  user_header_mappings:
    - header_name: X-OpenWebUI-User-Id
      litellm_user_role: customer
```

Each Open WebUI user becomes a LiteLLM end user ("customer"). Spend is tracked per person, and the default per-user budget from `litellm_settings.max_end_user_budget_id` applies (tested in this repo, including a full chat through Open WebUI that shows up as spend on the user's id in LiteLLM). When a user exceeds the budget, LiteLLM answers HTTP 422 `budget_exceeded` (tested in this repo).

Why the id and not the e-mail: Open WebUI users can change their own name, and admins can change names and e-mails. With the e-mail as key, a changed address would create a new end user with a fresh budget. The LiteLLM docs give the same warning ([LiteLLM Open WebUI tutorial](https://docs.litellm.ai/docs/tutorials/openweb_ui), as of 2026-10-16).

To find a user's spend, look up their Open WebUI id (admin panel, user list) and search for it as a customer in the LiteLLM admin UI, or call:

```bash
export LITELLM_MASTER_KEY=$(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2)
curl -s "http://localhost:4000/customer/info?end_user_id=<open-webui-user-id>" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```

Two things to know:

- Name and e-mail are sent to LiteLLM too, even though only the id is mapped. Consider this in your records of processing.
- Do not set `FORWARD_USER_INFO_HEADER_JWT_SECRET` in this setup. According to the Open WebUI docs it replaces the four user headers with one signed JWT, so the `X-OpenWebUI-User-Id` header that LiteLLM maps would no longer arrive.

Per-user authentication against LiteLLM (each user with their own identity token instead of a shared key) exists, but the LiteLLM side needs JWT auth, which is a LiteLLM Enterprise feature ([LiteLLM enterprise page](https://docs.litellm.ai/docs/enterprise), as of 2026-10-16). The header mapping used here works in the open-source edition.

## Trust model for the key and the user header

LiteLLM does not check who sends `X-OpenWebUI-User-Id`. Any request with a valid key may carry any user id. So whoever holds `OPENWEBUI_LITELLM_KEY` can:

- bill another person's budget by sending their id,
- invent new ids and get a fresh default budget (`USER_BUDGET_USD`) for each one.

Only the budget on the key itself (`OPENWEBUI_BUDGET_USD`) still holds.

Who can get the key:

- the Open WebUI container environment,
- Open WebUI admins (Admin Panel > Settings > Connections),
- any Open WebUI Tool or Function: these are Python code that runs inside the Open WebUI container, with access to its environment and database connection,
- any process or user on the Docker host, because LiteLLM listens on `127.0.0.1:4000`.

What follows from that:

- Never reuse the Open WebUI key for other clients (scripts, n8n, coding agents). Give each application its own key with its own budget.
- Treat Open WebUI admins as trusted, keep the admin role small, and install Tools and Functions only from sources you trust.
- The key is restricted to `llm_api_routes`, so a leaked key cannot create new keys or read spend data. It can still spend up to its budget.

## Embeddings and document search (RAG) via LiteLLM and pgvector

```yaml
      DATABASE_URL: postgresql://llm:${POSTGRES_PASSWORD}@postgres:5432/openwebui
      VECTOR_DB: pgvector
      RAG_EMBEDDING_ENGINE: openai
      RAG_EMBEDDING_MODEL: ${RAG_EMBEDDING_MODEL:-embedding}
```

When a user uploads a document, Open WebUI splits it into chunks, computes an embedding vector for each chunk, and stores the vectors for search.

**Embeddings through LiteLLM.** `RAG_EMBEDDING_ENGINE=openai` makes Open WebUI call an OpenAI-compatible embedding API instead of running a local sentence-transformers model. The URL and key for embeddings (`RAG_OPENAI_API_BASE_URL`, `RAG_OPENAI_API_KEY`) default to `OPENAI_API_BASE_URL` and `OPENAI_API_KEY`, so embeddings go to LiteLLM with the same virtual key. `RAG_EMBEDDING_MODEL=embedding` selects the LiteLLM model called `embedding` in `models.yaml` (by default `mistral/mistral-embed` on the EU endpoint, with a price, so it counts against budgets).

Reasons for this choice:

- Document text goes to the same provider and region you chose for chat, and nowhere else.
- No model download from Hugging Face at start (see the next section).
- Embedding cost is priced and counted like chat cost.

If you switch provider, keep a model named `embedding` in `models.yaml`, or document upload fails. Changing the embedding model later means existing documents must be embedded again: vectors from different models are not comparable. The comment in the official Open WebUI Dockerfile says the same for its default model.

**Vectors in Postgres.** `VECTOR_DB=pgvector` stores the vectors in Postgres instead of the default Chroma. `PGVECTOR_DB_URL` defaults to `DATABASE_URL`, so the vectors live in the `openwebui` database. `postgres/init/10-openwebui.sql` creates that database and runs `CREATE EXTENSION IF NOT EXISTS vector` on the first start. Benefits: one database to back up, no extra container, and chats, users and vectors are restored together.

## OFFLINE_MODE and the Hugging Face download

```yaml
      OFFLINE_MODE: "true"
```

According to the Open WebUI docs, `OFFLINE_MODE` disables:

- version update checks and update notifications,
- downloads of embedding models from Hugging Face Hub,
- automatic updates of embedding, reranking and Whisper models,
- installation of Python packages listed in the requirements of functions and tools.

External LLM connections (LiteLLM here), OAuth login and RAG with external APIs keep working ([offline mode guide](https://docs.openwebui.com/tutorials/maintenance/offline-mode)).

Why it is on: without `RAG_EMBEDDING_ENGINE=openai` and `OFFLINE_MODE=true`, Open WebUI downloads a sentence-transformers model from Hugging Face on start, and the image health check reports unhealthy during that download (tested in this repo). With both set, the container starts without contacting Hugging Face or GitHub, which also helps on servers with restricted outbound traffic.

Side effects to know:

- Functions and tools from the community that declare Python requirements fail to load with `ModuleNotFoundError`. Pre-install the packages in a custom image if you need them.
- If you ever switch `RAG_EMBEDDING_ENGINE` back to the local default while offline, the Open WebUI docs warn that RAG may fail with `No embedding model is loaded`.
- Speech-to-text, see [below](#speech-to-text).

## The ENABLE_PERSISTENT_CONFIG trap

Open WebUI stores many settings in its database after the first start. `ENABLE_PERSISTENT_CONFIG` defaults to `true`, and the Open WebUI docs say: "Values saved in the database (via the Admin UI) take precedence. If a value is set in the UI, the environment variable is ignored for that setting." In practice: **for these settings, changing `compose.yaml` or `.env` after the first start has no effect** (tested in this repo).

From the variables in `compose.yaml`, these are persisted (marked `ConfigVar` in the Open WebUI env reference as of 2026-10-16):

| Persisted after first start | Read from the environment on every start |
|---|---|
| `OPENAI_API_BASE_URL`, `OPENAI_API_KEY` | `DATABASE_URL`, `VECTOR_DB`, `REDIS_URL` |
| `ENABLE_OLLAMA_API` | `OFFLINE_MODE` |
| `RAG_EMBEDDING_ENGINE`, `RAG_EMBEDDING_MODEL` | `ENABLE_FORWARD_USER_INFO_HEADERS` |
| `ENABLE_SIGNUP`, `DEFAULT_USER_ROLE` | `ENABLE_ADMIN_CHAT_ACCESS` |
| `ENABLE_COMMUNITY_SHARING` | `ENABLE_ADMIN_EXPORT` (needs a restart) |
| `WEBUI_URL` | `WEBUI_SECRET_KEY` |
| `ENABLE_API_KEYS` | |

The most likely way to hit this: you rotate `OPENWEBUI_LITELLM_KEY` in `.env`, recreate the container, and Open WebUI keeps using the old key from its database. Change the key in the Open WebUI admin panel under the connection settings instead, then register the new key with `python3 scripts/bootstrap.py`.

Two ways to deal with it:

1. **Change persisted settings in the admin panel** (recommended for running systems). Keep `compose.yaml` in sync so a fresh install gets the same values.
2. **Set `ENABLE_PERSISTENT_CONFIG=false`.** Then the environment always wins. The Open WebUI docs warn that changes made in the admin panel still seem to work, but "will be lost upon restart". Only choose this if all configuration is managed in files and every admin knows it.

## Sign-up, roles and approval

```yaml
      ENABLE_SIGNUP: "true"
      DEFAULT_USER_ROLE: pending
```

What happens on a fresh install (tested in this repo with Open WebUI v0.12.2):

1. **The first account becomes admin.** Create it right after the first start, before the page is reachable by others.
2. **Then sign-up closes.** Open WebUI v0.12.2 stores `ui.enable_signup=false` in its database after the first account, regardless of `ENABLE_SIGNUP=true`. Further sign-ups get HTTP 403.
3. **To let colleagues register**, an admin re-enables sign-up in **Admin Panel > Settings > General**.
4. **New accounts are `pending`.** `DEFAULT_USER_ROLE=pending` (also the Open WebUI default) means they can log in but cannot use the chat until an admin changes their role to `user` in the admin panel's user list.

The three roles:

| Role | Can do |
|---|---|
| `pending` | Log in and wait. No chat. |
| `user` | Chat with the models they can see, upload documents, manage their own chats. |
| `admin` | Everything, including settings, connections, users and model visibility. |

Why `pending` and not `user`: anyone who can reach the sign-up page could otherwise create an account and spend your budget. Approval is a cheap control. Keep the number of admins small. With the privacy defaults below, admins cannot read other users' chats in the UI, but they still manage users, connections and model access.

With single sign-on (`compose.entra.yaml`, Microsoft Entra ID), new colleagues get an account on their first login (`ENABLE_OAUTH_SIGNUP=true`), also with `DEFAULT_USER_ROLE`. Optional role mapping from Entra app roles (`ENTRA_ROLE_MANAGEMENT=true`) assigns `user` or `admin` automatically. Merging existing password accounts by e-mail (`OAUTH_MERGE_ACCOUNTS_BY_EMAIL`) is off by default, because the Open WebUI docs call it "considered unsafe as not all OAuth providers will verify email addresses". Set `ENTRA_MERGE_BY_EMAIL=true` only for a one-time migration of existing accounts, then switch it off again. Once SSO works, `ENABLE_LOGIN_FORM=false` hides the password form.

Watch the persistent config trap here. Of the SSO variables, only `ENABLE_LOGIN_FORM` (`ui.enable_login_form`) and `WEBUI_URL` are stored in the database. `MICROSOFT_*`, `ENABLE_OAUTH_SIGNUP`, `OAUTH_*` and `OPENID_PROVIDER_URL` are read from the environment on every start, because `ENABLE_OAUTH_PERSISTENT_CONFIG` defaults to `false` (checked in the v0.12.2 source). If you change `ENABLE_LOGIN_FORM` or `WEBUI_URL` on an installation that has already run, change them in the admin panel too. The Entra overlay has not been tested against a real tenant.

## Privacy defaults in compose.yaml

```yaml
      ENABLE_ADMIN_CHAT_ACCESS: "false"
      ENABLE_COMMUNITY_SHARING: "false"
      ENABLE_ADMIN_EXPORT: "false"
      ENABLE_API_KEYS: "false"
      SCARF_NO_ANALYTICS: "true"
      DO_NOT_TRACK: "true"
      ANONYMIZED_TELEMETRY: "false"
```

| Variable | Open WebUI default | Repo | Effect |
|---|---|---|---|
| `ENABLE_ADMIN_CHAT_ACCESS` | `true` | `false` | Admins cannot open other users' chats in the UI. |
| `ENABLE_ADMIN_EXPORT` | `true` | `false` | The export actions in the admin panel are off. Exports include user chats. |
| `ENABLE_COMMUNITY_SHARING` | `true` | `false` | No "share to Open WebUI Community" buttons and links. |
| `ENABLE_API_KEYS` | `false` | `false` | Users cannot create personal Open WebUI API keys. Set again to document the intent. Stored in the database (`auth.enable_api_keys`) after the first start, so later changes go through the admin panel. |
| `SCARF_NO_ANALYTICS`, `DO_NOT_TRACK`, `ANONYMIZED_TELEMETRY` | already set in the image | same values | Telemetry off. Set again in compose to document the intent. |

Limits, in the words of the Open WebUI docs: `ENABLE_ADMIN_CHAT_ACCESS` "covers the product surface only: an admin can still reach every chat through the database, the server itself or a Function or Tool." Anyone with shell access to the Docker host can read the `openwebui` database. Technical settings do not replace an access concept for the server. The docs also note an exception: chats Open WebUI creates on a user's behalf (sub-agent, timer and note-attached chats) stay retrievable by admins by id.

`ENABLE_COMMUNITY_SHARING` is persisted after the first start (see the [persistent config trap](#the-enable_persistent_config-trap)). Since it is `false` from the first start in this repo, that only matters if an admin switches it on later in the UI.

More GDPR context, including the LiteLLM side: [GDPR settings](gdpr.md).

## Chat retention

Open WebUI has no built-in chat retention. The env reference has no setting for automatic chat deletion, and the Open WebUI security page says that because you own the database, you control retention. This repo ships `scripts/purge-chats.sh` for that.

Dry run (counts how many chats would be deleted), then the real deletion:

```bash
scripts/purge-chats.sh
scripts/purge-chats.sh --apply
```

It deletes chats that nobody touched for `CHAT_RETENTION_DAYS` days (default 90), measured by the chat's last update. Values below 1 are refused, and a `CHAT_RETENTION_DAYS` line in `.env` that is not a whole number (quotes are allowed) stops the script with an error instead of falling back to 90. Run it from the repo folder, because it uses `docker compose exec` on the `postgres` service.

What goes with each chat (tested in this repo): messages, chat-file links, share links and tags (foreign key cascade plus an explicit tag delete). What stays: **uploaded files and their search index**. Remove those in **Admin Panel > Settings > Documents** or in the users' file lists. LiteLLM spend logs have their own retention (`maximum_spend_logs_retention_period: "90d"` in `config.yaml`) and contain no prompts in this setup.

The script takes `CHAT_RETENTION_DAYS` from the shell environment, otherwise from `.env`. To override it once, set it on the command line or in the cron entry:

```bash
CHAT_RETENTION_DAYS=30 scripts/purge-chats.sh
```

Daily cron job on the Docker host, at 03:30, from the comment in the script:

```bash
30 3 * * * cd /opt/llm-gateway && CHAT_RETENTION_DAYS=90 scripts/purge-chats.sh --apply >> /var/log/purge-chats.log 2>&1
```

Replace `/opt/llm-gateway` with the folder where you cloned the repo. Agree on the retention period with your data protection officer, tell users about it, and remember that backups keep deleted chats until the backups themselves expire.

## Speech-to-text

By default, Open WebUI transcribes voice input with a local Whisper model inside the container (`AUDIO_STT_ENGINE` empty). Local Whisper needs its model files. `OFFLINE_MODE` blocks model downloads and automatic Whisper model updates, so a Whisper model that is not already in the container cannot be fetched. The standard v0.12.2 image pre-downloads the Whisper `base` model at build time (visible in the official Dockerfile), but which model is used at runtime depends on `WHISPER_MODEL` and `WHISPER_MULTILINGUAL`. Voice input has not been tested in this repo.

Your options:

1. **Keep voice input off.** The simplest choice for a text chat, and nothing leaves the server.
2. **Route speech-to-text to an API.** Set `AUDIO_STT_ENGINE` to `openai` (or `azure`, `mistral`, `deepgram`) and configure the endpoint in the admin panel's audio settings. Audio then goes to that provider, so the same data protection questions apply as for chat. Note that `AUDIO_STT_ENGINE` is persisted after the first start.
3. **Bake the Whisper model you want into a custom image**, so it is present without a download.

The "Web API" option in a user's own settings uses the browser's built-in speech recognition and does not call the Open WebUI backend at all, according to the Open WebUI docs. Where the browser processes that audio depends on the browser, so check it before you allow it.

## Licence: branding above 50 users

Open WebUI is not under a plain BSD licence any more. The current licence (`LICENSE` at v0.12.2) is BSD-3 clauses 1 to 3 plus a branding clause. Clause 4, quoted from the [Open WebUI LICENSE at v0.12.2](https://github.com/open-webui/open-webui/blob/v0.12.2/LICENSE):

> "4. Notwithstanding any other provision of this License, and as a material condition of the rights granted herein, licensees are strictly prohibited from altering, removing, obscuring, or replacing any "Open WebUI" branding, including but not limited to the name, logo, or any visual, textual, or symbolic identifiers that distinguish the software and its interfaces, in any deployment or distribution, except in the following circumstances: (i) deployments or distributions where the total number of end users (defined as individual natural persons with direct access to the application) does not exceed fifty (50) within any rolling thirty (30) day period; (ii) the licensee has obtained specific prior written permission from the copyright holder; or (iii) where the licensee has obtained a duly executed enterprise license expressly permitting such modification. For all other cases, any removal or alteration of the "Open WebUI" branding shall constitute a material breach of license."

What that means in technical terms:

- Using, modifying and running Open WebUI internally is allowed at any size. The clause is about the branding.
- With more than 50 end users in any rolling 30-day window, do not remove or replace the "Open WebUI" name or logo, unless you have written permission or an enterprise licence that allows it.
- The Open WebUI docs describe the change as a "fair-use branding protection clause" added with v0.6.6 (April 2025), and state that code up to and including v0.6.5 remains under plain BSD-3 ([Open WebUI licence page](https://docs.openwebui.com/license), as of 2026-10-16).
- `WEBUI_NAME` changes the displayed name, but the env reference says it "Appends `(Open WebUI)` if overridden".
- Contributions to Open WebUI after v0.6.5 require a Contributor License Agreement.

This repo does not change the Open WebUI branding. If you plan to add your own logo or name, check the clause first, and count users per rolling 30 days, not per month.

## Upgrading Open WebUI safely

Open WebUI runs database migrations automatically on start (`ENABLE_DB_MIGRATIONS` defaults to `true`). The Open WebUI docs warn that migrations are one-way: rolling back the container does not undo them, and an older version may not work with the newer schema. To go back you need a backup taken **before** the update ([updating guide](https://docs.openwebui.com/getting-started/updating), [manual database migration](https://docs.openwebui.com/troubleshooting/manual-database-migration)). Open WebUI has published many security advisories in 2026, so do update, just in a controlled way.

**1. Read the release notes** of every version between yours and the target on [GitHub releases](https://github.com/open-webui/open-webui/releases). Look for migrations and breaking changes. Do not use `main`, `latest` or `dev` tags. Stay on v0.11.4 or newer, which fixed 19 advisories including session token theft from any website.

**2. Back up.** Database dumps for both applications, plus the Open WebUI volume with uploads (tested in this repo). The `backups/` folder is in `.gitignore`, so the dumps cannot end up in a commit; for regular backups use the script in [production](production.md#backups) instead:

```bash
mkdir -p backups
docker compose exec -T postgres pg_dump -U llm -d openwebui -Fc > backups/openwebui-$(date +%F).dump
docker compose exec -T postgres pg_dump -U llm -d litellm -Fc > backups/litellm-$(date +%F).dump
docker run --rm -v "${COMPOSE_PROJECT_NAME:-llm-gateway}_openwebui_data":/data:ro -v "$PWD/backups":/backup \
  alpine:3.20.9 tar czf /backup/openwebui-data-$(date +%F).tar.gz -C /data .
test -s backups/openwebui-$(date +%F).dump && test -s backups/litellm-$(date +%F).dump
```

The volume name comes from the project name (`llm-gateway` in `compose.yaml`, or `COMPOSE_PROJECT_NAME` if you set it); check it with `docker volume ls`. The last line fails if a dump is empty. The volume also holds a few hundred MB of model caches copied from the image. Keep a copy of `.env` with the backups: without the same `WEBUI_SECRET_KEY`, `LITELLM_SALT_KEY` and `POSTGRES_PASSWORD`, a restored database is of limited use. Store backups encrypted; they contain all chats.

**3. Change the version** in `.env`:

```bash
OPEN_WEBUI_VERSION=v0.12.2
```

Replace the value with the target version.

**4. Pull and recreate:**

```bash
docker compose pull open-webui
docker compose up -d --wait open-webui
docker compose logs --tail 100 open-webui
```

Watch the logs for migration errors. Then log in, open an old chat, upload a document and search it.

**5. If it fails,** stop Open WebUI, restore the `openwebui` database from the dump, set the old version and start again:

```bash
docker compose stop open-webui
docker compose exec -T postgres dropdb -U llm openwebui
docker compose exec -T postgres createdb -U llm -O llm openwebui
docker compose exec -T postgres pg_restore -U llm -d openwebui < backups/openwebui-YYYY-MM-DD.dump
```

Set `OPEN_WEBUI_VERSION` back to the old version in `.env`, then start again:

```bash
docker compose up -d --wait open-webui
```

The restore sequence was tested by hand on a separate test stack in this repo (the `vector` extension survived, the stack came back healthy). Practise it on a test machine before you need it.

This repo runs one Open WebUI container, so the multi-replica rules in the Open WebUI docs (only one instance migrates, no rolling updates across schema changes) do not apply until you scale out.

## Common problems

**No models in the picker.** Check in this order:

1. Does LiteLLM list models for the Open WebUI key?

   ```bash
   export OWUI_KEY=$(grep '^OPENWEBUI_LITELLM_KEY=' .env | cut -d= -f2)
   curl -s http://localhost:4000/v1/models -H "Authorization: Bearer $OWUI_KEY"
   ```

   If not, run `python3 scripts/bootstrap.py` and check the provider key in `.env`.
2. Is the key in Open WebUI still the one in `.env`? If you rotated it, change it in the admin panel's connection settings (persistent config).
3. Only regular users see nothing? Check model visibility in the admin panel.

**Colleagues get 403 on sign-up.** Expected after the first admin. Enable sign-up in **Admin Panel > Settings > General**.

**New users can log in but cannot chat.** They are `pending`. Change their role to `user` in the admin panel.

**Document upload fails.** There is no model named `embedding` in `models.yaml`, or `RAG_EMBEDDING_MODEL` points to a name LiteLLM does not know. Check `docker compose logs open-webui`.

**A changed environment variable has no effect.** It is a persisted setting. See [The ENABLE_PERSISTENT_CONFIG trap](#the-enable_persistent_config-trap).

**Chat shows a budget error.** The user or the whole Open WebUI key reached its budget (HTTP 422 `budget_exceeded`). Raise `USER_BUDGET_USD` or `OPENWEBUI_BUDGET_USD` in `.env` and run `python3 scripts/bootstrap.py`, or set an individual budget for that user in LiteLLM. See [Budgets](budgets.md).

**Open WebUI stays unhealthy on start.** Check that `OFFLINE_MODE=true` and `RAG_EMBEDDING_ENGINE=openai` are set; otherwise it may be downloading a model. Open WebUI also waits for a healthy LiteLLM.

## Related guides

- [Quick start](quickstart.md)
- [LiteLLM config.yaml explained](configuration.md)
- [Budgets and rate limits](budgets.md)
- [GDPR settings](gdpr.md)
- [PII masking with Presidio](pii-masking.md)

> **Note:** Technical information as of 16 October 2026, not legal advice; the authors are not lawyers or data protection officers. No guarantee of completeness or compliance. You remain the controller and must do your own assessment (DPIA, Art. 30 record, DPAs) with your data protection officer or a lawyer.

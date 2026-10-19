# LiteLLM GDPR checklist: internal LLM gateway with Open WebUI

This checklist maps the GDPR articles that matter for an internal ChatGPT alternative to concrete settings in this repository (file and key) and to the organisational tasks no config file can do for you. It covers retention periods, who can read which logs, how to delete one person's data in Open WebUI and LiteLLM, the works council question in Germany, and the AI Act dates that apply to deployers.

Read it together with your data protection officer. Statements marked "tested in this repo" are covered by `tests/test_gateway.py`. Everything else is quoted from the cited source as of 2026-10-16.

## Contents

- [What data the stack processes](#what-data-the-stack-processes)
- [Checklist by article](#checklist-by-article)
  - [Art. 5: data minimisation and storage limitation](#art-5-data-minimisation-and-storage-limitation)
  - [Art. 6, 9 and 13: legal basis and information](#art-6-9-and-13-legal-basis-and-information)
  - [Art. 28: processors](#art-28-processors)
  - [Art. 30: record of processing activities](#art-30-record-of-processing-activities)
  - [Art. 32: security of processing](#art-32-security-of-processing)
  - [Art. 35: data protection impact assessment](#art-35-data-protection-impact-assessment)
  - [Art. 44-49: transfers to third countries](#art-44-49-transfers-to-third-countries)
  - [Art. 88 and the works council (Germany)](#art-88-and-the-works-council-germany)
- [Retention periods](#retention-periods)
- [Who can read what](#who-can-read-what)
- [Requests from data subjects: access and deletion (Art. 15, 17; answer within one month, Art. 12(3))](#requests-from-data-subjects-access-and-deletion-art-15-17-answer-within-one-month-art-123)
- [AI Act: what applies to you as a deployer](#ai-act-what-applies-to-you-as-a-deployer)
- [What this repo does not do](#what-this-repo-does-not-do)
- [Common problems](#common-problems)
- [Related guides](#related-guides)

## What data the stack processes

Before you fill in any form, know where personal data ends up. With the default configuration:

| Where | What | Personal data |
|---|---|---|
| Open WebUI database (`openwebui`) | accounts, chats, uploaded files, memories, feedback | name, e-mail, everything users type or upload |
| Open WebUI vector index (pgvector, same database) | chunks of uploaded documents | whatever is in the documents |
| LiteLLM database (`litellm`), `LiteLLM_SpendLogs` | one row per request: time, model, tokens, cost, key hash, Open WebUI user id | user id, usage pattern |
| LiteLLM database, `LiteLLM_EndUserTable`, `LiteLLM_DailyEndUserSpend` | spend and budget per user, daily totals per user and model | user id, usage pattern |
| Redis | rate-limit counters, streaming responses while they are sent | short-lived; Redis runs without persistence (`--save ""`, `--appendonly no` in `compose.yaml`) |
| Docker logs | container output (`json-file`, 10 MB x 3 files per container) | LiteLLM logs at level `ERROR` only (`LITELLM_LOG: ERROR`) |
| The model provider | the prompt, chat history, document chunks and the answer | everything the user sends, unless [PII masking](pii-masking.md) removes it |

Prompts and answers are **not** stored in LiteLLM: with `store_prompts_in_spend_logs: false` the `messages` and `response` columns stay empty (tested in this repo).

## Checklist by article

### Art. 5: data minimisation and storage limitation

Art. 5(1)(c): personal data shall be "adequate, relevant and limited to what is necessary in relation to the purposes for which they are processed". Art. 5(1)(e): kept "for no longer than is necessary".

Settings in this repo:

- [ ] `litellm/config.yaml`, `general_settings.store_prompts_in_spend_logs: false`. Prompts and answers are not written to the spend log table (tested in this repo).
- [ ] `litellm/config.yaml`, `litellm_settings.turn_off_message_logging: true`. Keeps message content out of logging callbacks; metadata and spend are still logged.
- [ ] `litellm/config.yaml`, `litellm_settings.redact_user_api_key_info: true`. Key alias, user id and team id are not sent to logging callbacks.
- [ ] `litellm/config.yaml`, `general_settings.user_header_mappings` maps `X-OpenWebUI-User-Id` (not the e-mail) to a LiteLLM end user. Spend is tracked per pseudonymous id. Open WebUI also sends name, e-mail and role headers (`ENABLE_FORWARD_USER_INFO_HEADERS: "true"` in `compose.yaml`); LiteLLM only maps the id. In our test database no e-mail address appeared in the spend log `metadata` column.
- [ ] `litellm/config.yaml`, `general_settings.maximum_spend_logs_retention_period: "90d"`. Spend log rows are deleted after 90 days. Shorten it if 90 days is longer than you need.
- [ ] `scripts/purge-chats.sh` with `CHAT_RETENTION_DAYS` (default 90). Open WebUI has no built-in chat retention. Set up the cron job from the script header:

  Dry run (how many chats would go), then the deletion:

  ```bash
  scripts/purge-chats.sh
  scripts/purge-chats.sh --apply
  ```

  Cron entry, daily at 03:30:

  ```text
  30 3 * * * cd /opt/llm-gateway && scripts/purge-chats.sh --apply >> /var/log/purge-chats.log 2>&1
  ```

- [ ] `compose.yaml`, Open WebUI: `ENABLE_ADMIN_CHAT_ACCESS: "false"`, `ENABLE_COMMUNITY_SHARING: "false"`, `ENABLE_ADMIN_EXPORT: "false"`, telemetry off (`SCARF_NO_ANALYTICS`, `DO_NOT_TRACK`, `ANONYMIZED_TELEMETRY`).
- [ ] Optional: `compose.pii.yaml` masks names, places, e-mail addresses, IBANs and more before the prompt leaves your network. See [PII masking](pii-masking.md).

Organisational tasks:

- [ ] Write down the purpose of each data set (for example "budget control per user", "chat history for the user").
- [ ] Decide retention periods and set them in the files above. See [Retention periods](#retention-periods).
- [ ] Decide what happens to uploaded files and their search index, which `purge-chats.sh` does not delete.

### Art. 6, 9 and 13: legal basis and information

- [ ] Document the legal basis for each purpose (for employees often Art. 6(1)(b) or (f), or a works agreement under Art. 88). Note that the CJEU (C-34/21, 30 March 2023) limited § 26(1) BDSG.
- [ ] Tell users not to enter special categories of data (Art. 9) unless a basis exists.
- [ ] Update the staff privacy notice (Art. 13): purposes, recipients (providers), retention, transfers.
- [ ] Involve your data protection officer properly and in a timely manner (Art. 38(1)), before the rollout and not after it.

### Art. 28: processors

Art. 28(1): the controller "shall use only processors providing sufficient guarantees". Art. 28(3): processing "shall be governed by a contract or other legal act". Art. 28(2): a processor "shall not engage another processor without prior specific or general written authorisation of the controller".

- [ ] Sign the DPA of every model provider you configure in `litellm/models.yaml`. Links and status per provider are in [EU-hosted LLMs](eu-models.md). Several DPAs could not be reviewed by us (OpenAI, OVHcloud, STACKIT, Scaleway).
- [ ] Check the provider's sub-processors. Example: T-Systems forwards proprietary models to Azure or GCP, which "may use sub-processors worldwide".
- [ ] Sign a DPA with the company that hosts the server running this stack, if it is not your own hardware.
- [ ] If an external party operates the stack for you (for example an agency or IT service provider), that is a processor relationship too.

### Art. 30: record of processing activities

"Each controller ... shall maintain a record of processing activities under its responsibility." Points you can take from this repo:

- [ ] **Controller / DPO:** name and contact details of the controller and of the data protection officer.
- [ ] **Purpose:** AI chat assistant for staff; budget control per user.
- [ ] **Data subjects:** employees (users), plus any person mentioned in prompts or uploaded documents.
- [ ] **Data categories:** account data (name, e-mail, role), chat content, uploaded documents, usage data per user (time, model, tokens, cost).
- [ ] **Recipients:** the model providers in `litellm/models.yaml`; the hosting provider.
- [ ] **Transfers to third countries:** depends on provider and endpoint (see [Art. 44-49](#art-44-49-transfers-to-third-countries)).
- [ ] **Retention:** spend logs 90 days (`maximum_spend_logs_retention_period`), chats 90 days after last change (`CHAT_RETENTION_DAYS`), daily per-user totals and uploaded files without automatic deletion (see [Retention periods](#retention-periods)).
- [ ] **Technical and organisational measures:** see [Art. 32](#art-32-security-of-processing).

Keep the record in sync when you change `litellm/models.yaml`: a new provider is a new recipient.

### Art. 32: security of processing

Art. 32(1) asks for "appropriate technical and organisational measures", including "(a) the pseudonymisation and encryption of personal data; (b) the ability to ensure the ongoing confidentiality, integrity, availability and resilience of processing systems and services".

Settings in this repo:

- [ ] **Network.** In `compose.yaml` every published port binds to `127.0.0.1`. Postgres and Redis are not published at all.
- [ ] **TLS.** `compose.tls.yaml` puts Caddy in front of Open WebUI with an automatic certificate and HSTS (`caddy/Caddyfile`). Only Open WebUI is public; LiteLLM stays on `127.0.0.1:4000` and its admin UI is reached through an SSH tunnel (`ssh -L 4000:127.0.0.1:4000 your-server`).
- [ ] **Secrets.** `scripts/init-env.sh` creates `.env` with random secrets and file mode 600, stops if a secret comes out empty, and never overwrites an existing file. `.env` is in `.gitignore`. The Open WebUI key is restricted to the LLM API routes (`allowed_routes`), and its trust model is described in [Open WebUI with LiteLLM](open-webui.md#trust-model-for-the-key-and-the-user-header).
- [ ] **Single sign-on.** `compose.entra.yaml` configures Open WebUI's Microsoft Entra ID login. It has not been tested against a real tenant. Merging accounts by e-mail (`OAUTH_MERGE_ACCOUNTS_BY_EMAIL`) is off by default; the Open WebUI docs call it "considered unsafe as not all OAuth providers will verify email addresses and can lead to potential account takeovers". Turn it on (`ENTRA_MERGE_BY_EMAIL=true`) only for a one-time migration.
- [ ] **Account approval.** `DEFAULT_USER_ROLE: pending`: new accounts need admin approval (tested in this repo).
- [ ] **Least privilege between models.** A LiteLLM virtual key with a `models` list gets HTTP 403 for any other model, and the request never reaches the provider (tested in this repo).
- [ ] **Pinned images.** `ghcr.io/berriai/litellm:v1.105.1` and `ghcr.io/open-webui/open-webui:v0.12.2`. Never use LiteLLM 1.82.7 or 1.82.8 (the March 2026 PyPI malware releases). Raise the versions when upstream publishes security fixes.
- [ ] **Pseudonymisation.** Per-user tracking uses the Open WebUI user id. Optional PII masking with Presidio ([guide](pii-masking.md)).

Organisational tasks:

- [ ] **Backups and encryption at rest** of the Docker volumes `postgres_data` and `openwebui_data`. Not part of this repo.
- [ ] **Admin accounts.** Give the Open WebUI admin role and the LiteLLM master key to as few people as possible. The LiteLLM admin UI login is user `admin` with `LITELLM_MASTER_KEY` as password. LiteLLM's docs describe this as a bootstrap credential and recommend per-user admin accounts plus `general_settings.disable_env_credential_login: true` (not set in this repo).
- [ ] **Patch process.** Subscribe to the security advisories of LiteLLM and Open WebUI.

### Art. 35: data protection impact assessment

Art. 35(1): where processing "in particular using new technologies ... is likely to result in a high risk to the rights and freedoms of natural persons, the controller shall, prior to the processing, carry out an assessment of the impact". Art. 35(4) asks supervisory authorities to publish lists of processing operations that require an assessment.

Points that typically come up for this stack (facts, not a verdict):

- It uses a new technology (large language models).
- It records usage per employee (spend logs per user id), which is data about behaviour.
- Users can paste anything, including special categories of data (health, for example) and data about third parties.
- Depending on the provider, data may leave the EU.

- [ ] Check your supervisory authority's list under Art. 35(4).
- [ ] Decide with your data protection officer whether a DPIA is required, and document the decision either way.

### Art. 44-49: transfers to third countries

Art. 44: a transfer to a third country "shall take place only if ... the conditions laid down in this Chapter are complied with by the controller and processor, including for onward transfers". Art. 45 covers adequacy decisions, Art. 46 appropriate safeguards such as standard contractual clauses, Art. 49 derogations.

- [ ] Use EU endpoints and regions only. Every example in `examples/providers/` points to an EU option, but the details matter: the Azure SKU, the Bedrock source region, the Vertex location, the Mistral host. See [EU-hosted LLMs](eu-models.md).
- [ ] Check fallbacks in `router_settings.fallbacks` (`litellm/config.yaml`). A fallback to a global endpoint is a transfer path.
- [ ] Check what the provider's abuse monitoring stores and where.
- [ ] For US providers: the EU-US Data Privacy Framework (Decision (EU) 2023/1795) is in force as of 2026-10-16; an appeal (C-703/25 P) is pending. The US CLOUD Act (18 U.S.C. § 2713) applies to data in a US provider's "possession, custody, or control, regardless of whether such communication, record, or other information is located within or outside of the United States". Details and sources in [EU-hosted LLMs](eu-models.md#cloud-act-and-data-privacy-framework-the-facts).

### Art. 88 and the works council (Germany)

Art. 88 lets Member States provide more specific rules for processing employee data. In Germany, the works council has a co-determination right under BetrVG § 87(1) Nr. 6 on the "Einführung und Anwendung von technischen Einrichtungen, die dazu bestimmt sind, das Verhalten oder die Leistung der Arbeitnehmer zu überwachen" (introduction and use of technical devices designed to monitor the behaviour or performance of employees) ([gesetze-im-internet.de](https://www.gesetze-im-internet.de/betrvg/__87.html)). The Federal Labour Court reads "dazu bestimmt" as objectively suitable to monitor; the employer's intention does not matter.

What this stack records per employee:

- `LiteLLM_SpendLogs`: every request with time, model, token counts and cost, linked to the Open WebUI user id (for 90 days).
- `LiteLLM_DailyEndUserSpend`: daily totals per user and model (no automatic deletion).
- `LiteLLM_EndUserTable`: current spend against the budget.
- The LiteLLM admin UI and API (`/customer/info?end_user_id=...`) show this per user to anyone with the master key.
- Open WebUI: chats per user, readable by the user; admins cannot open them through the product with `ENABLE_ADMIN_CHAT_ACCESS: "false"`, but anyone with database access can.

Per-user spend shows when and how much each employee uses the tool, which is data about behaviour and performance. Involve the works council before rollout. Topics for a works agreement:

- [ ] Purpose: budget control only, no performance evaluation.
- [ ] Who may see per-user spend, and who holds the LiteLLM master key and database access.
- [ ] Retention periods (see below).
- [ ] Whether chats may ever be read by admins, and under which procedure.
- [ ] Alternative without per-user tracking: remove `user_header_mappings` from `litellm/config.yaml`. Then there are no per-user budgets either; only the shared Open WebUI key budget (`OPENWEBUI_BUDGET_USD`) applies.

## Retention periods

| Data | Default in this repo | Where to change |
|---|---|---|
| LiteLLM spend log rows | 90 days, cleanup daily | `general_settings.maximum_spend_logs_retention_period` and `maximum_spend_logs_retention_interval` in `litellm/config.yaml` |
| LiteLLM daily per-user totals (`LiteLLM_DailyEndUserSpend`) | no automatic deletion | manual SQL (see below) |
| LiteLLM end user rows (budget, spend) | no automatic deletion | `/customer/delete` (see below) |
| Open WebUI chats | 90 days after last change, if the cron job runs | `CHAT_RETENTION_DAYS`, `scripts/purge-chats.sh --apply` |
| Open WebUI uploaded files and search index | no automatic deletion | Admin Panel > Settings > Documents, or per user |
| Open WebUI accounts | until deleted | Admin Panel > Users |
| Docker container logs | 3 files x 10 MB per container | `x-logging` in `compose.yaml` |
| Provider abuse monitoring | provider-specific, often 30 days | provider contract (ZDR, modified abuse monitoring) |

Notes:

- The LiteLLM cleanup job deletes `LiteLLM_SpendLogs` and a few derived tables. Per LiteLLM's [spend log deletion docs](https://docs.litellm.ai/docs/proxy/spend_logs_deletion), it does not cover the daily per-user totals. The schedule lives in the process: the first run lands about one interval after startup, and a proxy that restarts more often than the interval never reaches its first run. In v1.105.1 the only option for that case is `maximum_spend_logs_cleanup_cron` (for example `"0 4 * * *"`), not set in this repo. Newer versions add `maximum_spend_logs_cleanup_run_on_startup`, which v1.105.1 silently ignores.
- `purge-chats.sh` deletes chats with their messages, chat-file links, share links and tags (tested in this repo). It does not delete uploaded files or their search index.
- LiteLLM also has an error table, `LiteLLM_ErrorLogs`, with a `request_kwargs` column. The cleanup job does not cover it. In our test database it stayed empty even after failed requests. `general_settings.disable_error_logs: true` turns error tracking in the database off explicitly (not set in this repo).
- Backups keep data beyond these periods. Align the backup retention.

## Who can read what

| Who | Can see |
|---|---|
| A user | their own chats, files and memories in Open WebUI |
| Open WebUI admin | users, settings, uploaded files. Not other users' chats in the product while `ENABLE_ADMIN_CHAT_ACCESS: "false"`; no admin export while `ENABLE_ADMIN_EXPORT: "false"` |
| Holder of `LITELLM_MASTER_KEY` | LiteLLM admin UI: all keys, budgets, spend per user and per key, spend logs (no prompts) |
| Anyone with database or server access | everything, including all chats |

The Open WebUI docs are explicit that `ENABLE_ADMIN_CHAT_ACCESS` "covers the product surface only: an admin can still reach every chat through the database, the server itself or a Function or Tool" ([env reference](https://docs.openwebui.com/reference/env-configuration)). Restrict server and database access accordingly.

Open WebUI's audit log is off by default (`AUDIT_LOG_LEVEL`, default `NONE`, not set in this repo). If you switch it on, note that `REQUEST` and `REQUEST_RESPONSE` include request and response bodies, which is chat content.

## Requests from data subjects: access and deletion (Art. 15, 17; answer within one month, Art. 12(3))

The person is identified across both systems by the Open WebUI user id, which LiteLLM stores as the end user id.

**1. Find the user id.**

```bash
docker compose exec -T postgres psql -U llm -d openwebui \
  -c "SELECT id, name, email, role FROM \"user\" WHERE email = 'jane.doe@example.com';"
```

**2. Access request: export what LiteLLM has.** Prompts are not stored, so this is usage data only.

```bash
docker compose exec -T postgres psql -U llm -d litellm \
  -c "SELECT \"startTime\", model_group, prompt_tokens, completion_tokens, spend FROM \"LiteLLM_SpendLogs\" WHERE end_user = '<user-id>' ORDER BY \"startTime\";"
```

Chats and files: the user sees them in Open WebUI. Admin export is switched off in this repo (`ENABLE_ADMIN_EXPORT: "false"`).

**3. Delete in Open WebUI.** Admin Panel > Users > delete the account (API: `DELETE /api/v1/users/{user_id}`, admins only). Open WebUI's docs describe user deletion via SCIM as removing "the user account with its chats and its sign-in record"; API keys and OAuth sessions cascade. The first admin account cannot be deleted through the UI. We have not verified whether uploaded files and memories are removed with the account. Check afterwards:

```bash
docker compose exec -T postgres psql -U llm -d openwebui \
  -c "SELECT (SELECT count(*) FROM chat WHERE user_id = '<user-id>') AS chats, (SELECT count(*) FROM file WHERE user_id = '<user-id>') AS files, (SELECT count(*) FROM memory WHERE user_id = '<user-id>') AS memories;"
```

With Entra ID SSO and `ENABLE_OAUTH_SIGNUP: "true"`, the account is created again at the next login. Remove the person from the Entra app first.

**4. Delete in LiteLLM.** Remove the end user (budget link and spend counter) through the API. It answers 404 if the id does not exist.

```bash
export $(grep '^LITELLM_MASTER_KEY=' .env)
curl -s -X POST http://localhost:4000/customer/delete \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_ids": ["<user-id>"]}'
```

`/customer/delete` does not touch the spend log rows or the daily totals. Delete them in the database:

```bash
docker compose exec -T postgres psql -U llm -d litellm -c "
  DELETE FROM \"LiteLLM_SpendLogs\" WHERE end_user = '<user-id>';
  DELETE FROM \"LiteLLM_DailyEndUserSpend\" WHERE end_user_id = '<user-id>';"
```

Alternatively, let the spend log rows expire with the 90-day retention, if that is acceptable for the request.

**5. Outside the stack.** Provider abuse-monitoring copies (see the provider's retention), backups, and any logging callbacks you added yourself.

## AI Act: what applies to you as a deployer

Regulation (EU) 2024/1689 (AI Act), amended by the Digital Omnibus on AI, Regulation (EU) 2026/1744 of 8 July 2026 ([EUR-Lex](https://eur-lex.europa.eu/eli/reg/2026/1744/oj/eng)), published on 24 July 2026 and in force since 27 July 2026. Facts only:

- **Art. 4 AI literacy.** Originally, providers and deployers "shall take measures to ensure, to their best extent, a sufficient level of AI literacy of their staff" (applicable since 2 February 2025). As amended by 2026/1744, they "shall take measures to support the development of AI literacy"; the obligation to ensure a "sufficient level" is removed.
- **Art. 5 prohibited practices** apply since 2 February 2025. New prohibitions in Art. 5(1) points (ba) and (bb), added by 2026/1744, apply from 2 December 2026.
- **Art. 50 transparency.** Art. 50(1) and 50(2) are duties of the provider of an AI system, not of the deployer. Providers must inform persons that they interact with an AI system unless it is obvious. Art. 50(2) requires machine-readable marking of synthetic audio, image, video or text output. For systems placed on the market before 2 August 2026 there is a transition period; recital 38 of 2026/1744 refers to four months. The exact end date (2 December 2026 according to a secondary source) is **not verified**.
- **High-risk obligations** (Chapter III Sections 1-3) are postponed by 2026/1744: from 2 December 2027 for Annex III systems, from 2 August 2028 for Annex I systems (product legislation). Art. 26 lists deployer obligations for high-risk systems (human oversight, use according to instructions). Art. 26(7) requires deployers who are employers to inform workers' representatives and affected workers before putting a high-risk system into use at the workplace. Annex III point 4 covers employment, for example selecting candidates or deciding on promotions. Whether a use is high-risk depends on the purpose listed in Annex III, so the same chat tool can be used for purposes inside or outside that list.
- **New Art. 4a** covers processing of special categories of personal data for bias detection and correction.
- **General-purpose AI models.** Chapter V applies since 2 August 2025 and addresses the providers of those models.

Tasks:

- [ ] Plan training on what the tool can and cannot do (Art. 4).
- [ ] Check whether you count as a provider of this AI system under the AI Act (for example, putting it into service under your own name). If so, Art. 50(1) and (2) apply; if not, informing users is still good practice.
- [ ] Check whether any team plans to use the chat for a purpose listed in Annex III.

## What this repo does not do

- **No legal compliance by default.** The settings reduce what is stored and where data goes. They do not replace a DPA, a record of processing, a DPIA decision or a works agreement.
- **No automatic deletion** of uploaded files, the search index, memories, daily per-user totals or end user rows.
- **No backups** and no encryption at rest for the Docker volumes.
- **No guarantee that personal data never reaches the provider.** PII masking is optional and catches only what Presidio detects ([limits](pii-masking.md#known-false-positives-and-limits)).
- **No protection against prompt injection.** Content users paste or upload goes to the model.
- **No audit log** of admin actions in Open WebUI (`AUDIT_LOG_LEVEL` is not set). LiteLLM's docs list audit logs as an enterprise feature.
- **No per-team logging control.** Disabling logging per team is a LiteLLM enterprise feature. This repo uses only open-source features.
- **No data subject request automation.** The steps above are manual.

## Common problems

**I changed a privacy variable in `compose.yaml` and nothing happened.** Open WebUI stores many settings in its database after the first start (`ENABLE_PERSISTENT_CONFIG`, default true), and later environment changes are ignored for those settings (tested in this repo). Change them in the admin panel, or set `ENABLE_PERSISTENT_CONFIG=false`.

**New colleagues cannot register.** After the first account (which becomes admin), Open WebUI v0.12.2 stores sign-up as disabled in its database, regardless of `ENABLE_SIGNUP=true`. Re-enable it in Admin Panel > Settings > General; new accounts are then pending and need approval (tested in this repo).

**Spend logs older than 90 days are still there.** The cleanup runs about one interval (1 day) after LiteLLM starts. If LiteLLM restarts daily, it may never run. See the notes under [Retention periods](#retention-periods).

**Spend per user is 0.** The model has no price in `litellm/models.yaml`, or `ENABLE_FORWARD_USER_INFO_HEADERS` is not active. See [EU-hosted LLMs](eu-models.md#prices).

## Related guides

- [EU-hosted LLMs with LiteLLM](eu-models.md)
- [PII masking with Presidio and LiteLLM](pii-masking.md)
- [Open WebUI with LiteLLM: users and settings](open-webui.md)
- [LiteLLM budgets and rate limits](budgets.md)
- [LiteLLM open source vs enterprise](open-source-vs-enterprise.md)
- [Security policy and defaults](../SECURITY.md)

> **Note:** Technical information as of 16 October 2026, not legal advice; the authors are not lawyers or data protection officers. No guarantee of completeness or compliance. You remain the controller and must do your own assessment (DPIA, Art. 30 record, DPAs) with your data protection officer or a lawyer.

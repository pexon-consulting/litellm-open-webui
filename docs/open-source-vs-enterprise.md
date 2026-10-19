# LiteLLM open source vs enterprise: what you get without a licence

This guide lists which LiteLLM features are open source and which need an enterprise licence, with a source link for every row. It also shows what this repo uses (only open-source features), the workarounds it applies for SSO and per-user spend, and the licence terms of Open WebUI that matter for a company rollout.

Everything here is as of 2026-10-16, LiteLLM `v1.105.1` and Open WebUI `v0.12.2`. Vendors move features between editions; check the linked pages before you decide.

## Contents

- [How LiteLLM is licensed](#how-litellm-is-licensed)
- [Feature matrix](#feature-matrix)
- [What this repo uses](#what-this-repo-uses)
- [Workarounds for enterprise features](#workarounds-for-enterprise-features)
- [When an enterprise licence is worth asking about](#when-an-enterprise-licence-is-worth-asking-about)
- [Open WebUI licence](#open-webui-licence)
- [Common problems](#common-problems)
- [Related guides](#related-guides)

## How LiteLLM is licensed

- The repository is MIT, except the `enterprise/` directory: "All content that resides under the "enterprise/" directory of this repository, if that directory exists, is licensed under the license defined in "enterprise/LICENSE". Content outside of the above mentioned directories or restrictions above is available under the MIT license" ([LICENSE](https://github.com/BerriAI/litellm/blob/main/LICENSE)). The PyPI package `litellm` declares `MIT` ([PyPI](https://pypi.org/pypi/litellm/json)).
- The Docker image is not purely MIT. The image also contains BerriAI's proprietary `enterprise/` code (`/app/enterprise/LICENSE.md`, "The BerriAI Enterprise license") and the `litellm_enterprise` package (`License-Expression: LicenseRef-Proprietary`), both seen in the `v1.105.1` image. Without `LITELLM_LICENSE` those features stay off.
- Enterprise is not a separate product: "Enterprise is a license key on the same Gateway image you may already run." The key goes into the environment variable `LITELLM_LICENSE` ([LiteLLM enterprise docs](https://docs.litellm.ai/docs/enterprise)).
- Pricing is not public: "Pricing depends on your deployment size. Get in touch". A 30-day trial key is offered ([enterprise docs](https://docs.litellm.ai/docs/enterprise), [litellm.ai/enterprise](https://www.litellm.ai/enterprise)). The licence error message in `v1.105.1` mentions a 7-day trial key instead (seen in this repo's stack), so the trial length is not consistent across sources.
- Target audience in the docs: "For teams running LiteLLM at scale (100+ users or 10+ production AI use cases)".

What "enterprise" means in practice: the code runs on the same image, and features check for the licence key at runtime. Without a key, gated endpoints answer with an error. Example from this repo's stack:

```bash
export LITELLM_MASTER_KEY=$(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2)
curl -s "http://localhost:4000/global/spend/report?start_date=2026-10-01&end_date=2026-10-16" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY"
```

```json
{"detail": {"error": "/spend/report endpoint You must be a LiteLLM Enterprise user to use this feature. If you have a license please set `LITELLM_LICENSE` in your env. ..."}}
```

That call returned HTTP 400.

## Feature matrix

"OSS" means usable without a licence. "Enterprise" means the LiteLLM docs list it as licence-gated. "Tested" means we called it against this repo's stack without a licence.

### Access and identity

| Feature | Edition | Source |
|---|---|---|
| Virtual keys (`/key/generate`), model allow-lists per key | OSS, tested | [users](https://docs.litellm.ai/docs/proxy/users) |
| Admin UI login with master key or `UI_USERNAME` / `UI_PASSWORD` | OSS | [config settings](https://docs.litellm.ai/docs/proxy/config_settings) |
| SSO for the Admin UI, up to 5 users | OSS | [admin UI SSO](https://docs.litellm.ai/docs/proxy/admin_ui_sso): "From v1.76.0, SSO is free for up to 5 users. Beyond that, an enterprise license is required." |
| SSO for the Admin UI, more than 5 users | Enterprise | same |
| JWT-based authentication (per-user tokens from your IdP) | Enterprise | [token auth](https://docs.litellm.ai/docs/proxy/token_auth) |
| Open WebUI "system_oauth" forwarding of the user's IdP token to LiteLLM | Enterprise (needs JWT auth) | [Open WebUI org rollout tutorial](https://docs.litellm.ai/docs/tutorials/openwebui_org_rollout) |
| Header mapping (`user_header_mappings`) to end users | OSS, tested | [Open WebUI tutorial](https://docs.litellm.ai/docs/tutorials/openweb_ui) |
| Role-based access control ("Organizations, teams, and user roles") | Enterprise per the list | [enterprise](https://docs.litellm.ai/docs/enterprise) |
| Teams with budgets (`/team/new`) | OSS, tested | [users](https://docs.litellm.ai/docs/proxy/users) |
| Public and private route controls, IP address ACLs | Enterprise | [enterprise](https://docs.litellm.ai/docs/enterprise) |
| Key rotations | Enterprise | same |
| Secret managers (AWS KMS, AWS Secrets Manager, Azure Key Vault, Google KMS, Google Secret Manager, HashiCorp Vault, CyberArk, custom) | Enterprise | same |
| Audit logs | Enterprise by default; `store_audit_logs` on other plans is ambiguous, not verified | [multiple admins](https://docs.litellm.ai/docs/proxy/multiple_admins) |

The matrix lists both "teams" (OSS, with budgets) and "RBAC: Organizations, teams, and user roles" (enterprise). The docs do not draw the line precisely. Team budgets worked without a licence in our test; organisations and fine-grained roles we did not test.

### Budgets and cost

| Feature | Edition | Source |
|---|---|---|
| Global, key, internal user, team, team member and customer `max_budget` / `budget_duration` | OSS, tested (key, team, customer) | [users](https://docs.litellm.ai/docs/proxy/users) |
| `rpm_limit`, `tpm_limit` on keys | OSS, `rpm_limit` tested | same |
| Default end-user budget (`max_end_user_budget_id`) | OSS, tested | this repo, [budgets.md](budgets.md) |
| `/budget/new` as an end-user or customer budget row | OSS, tested | this repo |
| Budget / rate limit tiers (a `/budget/new` row assigned to keys) | Enterprise | [rate limit tiers](https://docs.litellm.ai/docs/proxy/rate_limit_tiers) |
| Model-specific budgets per virtual key or internal user (`model_max_budget`) | Enterprise | [users](https://docs.litellm.ai/docs/proxy/users), [enterprise](https://docs.litellm.ai/docs/enterprise) |
| Tag-based budgets | Enterprise | [enterprise](https://docs.litellm.ai/docs/enterprise) |
| Temporary budget increases | Enterprise | same |
| Soft budget e-mail alerts | Enterprise | same |
| Spend per key, user, team, customer (`/key/info`, `/customer/info`, `/team/info`, `/spend/logs`, `/spend/keys`, `/spend/users`) | OSS, tested | [cost tracking](https://docs.litellm.ai/docs/proxy/cost_tracking) |
| Global spend report (`/global/spend/report`) | Enterprise, tested (HTTP 400 without licence) | [cost tracking](https://docs.litellm.ai/docs/proxy/cost_tracking) |
| Project management | Enterprise | [enterprise](https://docs.litellm.ai/docs/enterprise) |

Note: the marketing page [litellm.ai/enterprise](https://www.litellm.ai/enterprise) lists "Virtual keys, budgets, RPM/TPM limits" under "What Enterprise adds". The docs show the basic versions as open source, and they work without a licence in this repo. We rely on the docs list.

### Guardrails and data protection

| Feature | Edition | Source |
|---|---|---|
| Guardrail framework, custom guardrails, Presidio PII masking | OSS, Presidio tested | [enterprise](https://docs.litellm.ai/docs/enterprise): "The OSS guardrail framework includes custom guardrails and Presidio for PII masking." |
| Callbacks `llmguard_moderations`, `llamaguard_moderations`, `hide_secrets`, `openai_moderations`, `google_text_moderation`, `lakera_prompt_injection`, `aporia_prompt_injection` | Enterprise | same |
| Secret detection / redaction | Enterprise | [secret detection](https://docs.litellm.ai/docs/proxy/guardrails/secret_detection) |
| Guardrails per key or team, exposing guardrails to users, dynamic parameters, tag-based and model-level guardrail modes | Enterprise | [guardrails quick start](https://docs.litellm.ai/docs/proxy/guardrails/quick_start) |
| `store_prompts_in_spend_logs: false` (default) | OSS, tested | [config settings](https://docs.litellm.ai/docs/proxy/config_settings) |
| `turn_off_message_logging`, `redact_user_api_key_info`, `global_disable_no_log_param` | OSS | [logging](https://docs.litellm.ai/docs/proxy/logging) |
| Spend log retention (`maximum_spend_logs_retention_period`) | OSS | [spend logs deletion](https://docs.litellm.ai/docs/proxy/spend_logs_deletion): "Retention and cleanup are open source." |
| Enforced required params | Enterprise | [enterprise](https://docs.litellm.ai/docs/enterprise) |
| Max request / response size limits | Enterprise | same |

### Logging and operations

| Feature | Edition | Source |
|---|---|---|
| Logging callbacks (Langfuse, OpenTelemetry) for the whole proxy | OSS | [logging](https://docs.litellm.ai/docs/proxy/logging) |
| Team-based logging ("Route each team's logs to their own Langfuse project or callback") | Enterprise | [enterprise](https://docs.litellm.ai/docs/enterprise) |
| Disable logging per team ("GDPR-friendly opt-out at the team level") | Enterprise | same |
| Log export to GCS / Azure Blob | Enterprise | same |
| Prometheus metrics at `/metrics` | OSS per the docs; whether the code still checks a licence is not verified | [prometheus](https://docs.litellm.ai/docs/proxy/prometheus) |
| Health endpoints | OSS, tested (`/health/readiness`) | [health](https://docs.litellm.ai/docs/proxy/health) |
| Custom Swagger and e-mail branding, team-managed models, AI Hub, multi-tenant architecture | Enterprise | [enterprise](https://docs.litellm.ai/docs/enterprise) |
| Admin UI logo | No enterprise banner in the docs; licence check in code not verified | [UI logo](https://docs.litellm.ai/docs/proxy/ui/ui_edit_logo) |
| Support SLAs (Sev 0: 1 hour, Sev 1: 6 hours, Sev 2-3: 24 hours, vulnerabilities: 72 hours) | Enterprise | [litellm.ai/enterprise](https://www.litellm.ai/enterprise) |

On Prometheus: older LiteLLM versions gated it behind enterprise. The current page has no enterprise banner, the feature is not in the enterprise list, and the only enterprise note on the page covers one metric for managed batches. This repo does not enable Prometheus, so we have not tested it.

## What this repo uses

Only open-source features. There is no `LITELLM_LICENSE` anywhere in the repo, and `litellm/config.yaml` starts with "open-source features only, no enterprise license needed".

| Area | Setting in this repo | File |
|---|---|---|
| One virtual key for Open WebUI with a budget | `OPENWEBUI_LITELLM_KEY`, alias `open-webui` | `scripts/bootstrap.py` |
| Per-user spend and budget | `user_header_mappings` + `max_end_user_budget_id: per-user-default` | `litellm/config.yaml` |
| Prompts out of the database | `store_prompts_in_spend_logs: false` | `litellm/config.yaml` |
| Prompts out of logging callbacks | `turn_off_message_logging: true` | `litellm/config.yaml` |
| No user or key details in callbacks | `redact_user_api_key_info: true` | `litellm/config.yaml` |
| Clients cannot switch off logging | `global_disable_no_log_param: true` | `litellm/config.yaml` |
| Spend logs deleted after 90 days | `maximum_spend_logs_retention_period: "90d"` | `litellm/config.yaml` |
| PII masking before the provider | Presidio guardrail, German spaCy model | `compose.pii.yaml`, `litellm/guardrails.pii.yaml` |
| Fallback between models | `router_settings.fallbacks` | `litellm/config.yaml` |
| User login and SSO | Open WebUI, optionally Microsoft Entra ID | `compose.entra.yaml` |

`tests/test_gateway.py` runs against this setup without a licence, 15 tests.

## Workarounds for enterprise features

### SSO: let Open WebUI handle login

Staff never log in to LiteLLM. They log in to Open WebUI, which has its own OAuth and OIDC login in the open-source edition. `compose.entra.yaml` configures Microsoft Entra ID:

```bash
docker compose -f compose.yaml -f compose.tls.yaml -f compose.entra.yaml up -d
```

with `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET` and `MICROSOFT_CLIENT_TENANT_ID` in `.env`, and the redirect URI `https://<your-domain>/oauth/microsoft/callback` in the app registration. The file comment says it plainly: "This is Open WebUI's own OAuth login, free in the open-source edition. It is not LiteLLM SSO". This overlay was not tested against a real Entra tenant; the compose combination is only validated with `docker compose config` in CI.

The LiteLLM Admin UI stays for a few administrators. They log in with the master key (user `admin`), through an SSH tunnel when `compose.tls.yaml` is used:

```bash
ssh -L 4000:127.0.0.1:4000 your-server
```

Then open <http://localhost:4000/ui>.

If you have up to 5 LiteLLM admins and want SSO for the Admin UI too, the free SSO tier covers that. This repo does not configure it.

### Per-user spend: header mapping instead of JWT

The enterprise way to identify each person is JWT auth: Open WebUI forwards the user's IdP token (`OPENAI_API_CONFIGS` with `"auth_type":"system_oauth"`), and LiteLLM validates it. The LiteLLM tutorial for this says: "LiteLLM JWT auth is an enterprise feature and requires `LITELLM_LICENSE` to be set" ([org rollout tutorial](https://docs.litellm.ai/docs/tutorials/openwebui_org_rollout), as of 2026-10-16).

This repo uses the open-source path instead:

```yaml
# compose.yaml, service open-webui
ENABLE_FORWARD_USER_INFO_HEADERS: "true"
```

```yaml
# litellm/config.yaml
general_settings:
  user_header_mappings:
    - header_name: X-OpenWebUI-User-Id
      litellm_user_role: customer
litellm_settings:
  max_end_user_budget_id: per-user-default
```

Tested in this repo: a chat sent through Open WebUI lands as spend on the end user with that person's Open WebUI id, and an end user over budget gets HTTP 422.

Know the trade-off. With JWT, LiteLLM checks a signed token. With header mapping, LiteLLM trusts the header that comes with a valid key. Anyone who holds `OPENWEBUI_LITELLM_KEY` can send any `X-OpenWebUI-User-Id` and spend on someone else's budget. In this repo the key lives in `.env` and in the Open WebUI container, where Open WebUI admins and Open WebUI Tools and Functions can read it, and LiteLLM listens on `127.0.0.1` only. `scripts/bootstrap.py` limits the key to the LLM API routes. Do not hand the Open WebUI key to other clients, give them their own keys. Details: [trust model](open-webui.md#trust-model-for-the-key-and-the-user-header).

### Spend report: query the database

`/global/spend/report` is enterprise. Per-key, per-team and per-end-user numbers are open source (`/key/info`, `/team/info`, `/customer/info`, `/spend/keys`), and a monthly report per person is one SQL query against `LiteLLM_SpendLogs`. See [How to check spend](budgets.md#how-to-check-spend).

### Model-specific budgets: use separate keys or a model allow-list

Model-specific budgets per key are enterprise. Without them you can give a group a separate key that only allows the expensive model (`"models": ["mistral-medium"]`) with its own `max_budget`. For Open WebUI users this does not work, because all of them share one key. Per-user budgets then cover all models together.

### Secret managers: environment variables

Provider keys come from `.env` via `os.environ/...` in `litellm/models.yaml`. `tests/test_config_files.py::test_secrets_come_from_env` fails if a model file contains a literal key. Docker secrets or a secret manager that writes `.env` at deploy time are outside LiteLLM and need no licence. Native LiteLLM secret manager integrations do.

### Team logging: one logging target

Per-team logging and per-team logging opt-out are enterprise. This repo keeps message content out of all callbacks (`turn_off_message_logging: true`) and out of the database (`store_prompts_in_spend_logs: false`), so there is less to route per team.

## When an enterprise licence is worth asking about

Based on the matrix, a licence changes things if you need:

- Per-user authentication against LiteLLM with signed tokens (JWT), for example because clients other than Open WebUI must act on behalf of individual users.
- More than 5 people logging in to the LiteLLM Admin UI with SSO.
- Model-specific budgets, budget tiers on keys, tag-based budgets or soft budget e-mail alerts.
- Per-team logging targets or per-team logging opt-out.
- Secret manager integrations, IP ACLs, key rotation, audit logs by default.
- A support contract with SLAs.

If none of these apply, this repo's open-source setup covers chat for staff with per-person budgets.

## Open WebUI licence

Open WebUI is not under a plain open-source licence any more. GitHub reports the licence as `NOASSERTION` (custom) ([repo](https://github.com/open-webui/open-webui)). The text at `v0.12.2` is the "Open WebUI License": the three BSD-3 clauses plus a fourth clause about branding ([LICENSE @ v0.12.2](https://github.com/open-webui/open-webui/blob/v0.12.2/LICENSE)). Clause 4, quoted in full:

> "4. Notwithstanding any other provision of this License, and as a material condition of the rights granted herein, licensees are strictly prohibited from altering, removing, obscuring, or replacing any "Open WebUI" branding, including but not limited to the name, logo, or any visual, textual, or symbolic identifiers that distinguish the software and its interfaces, in any deployment or distribution, except in the following circumstances: (i) deployments or distributions where the total number of end users (defined as individual natural persons with direct access to the application) does not exceed fifty (50) within any rolling thirty (30) day period; (ii) the licensee has obtained specific prior written permission from the copyright holder; or (iii) where the licensee has obtained a duly executed enterprise license expressly permitting such modification. For all other cases, any removal or alteration of the "Open WebUI" branding shall constitute a material breach of license."

What the documents say:

- The clause is about branding. The Open WebUI docs describe it as "a fair-use branding protection clause" added with v0.6.6 (April 2025), and say "Branding requirements only apply to larger deployments (50+ users, aggregate)" ([Open WebUI licence docs](https://docs.openwebui.com/license), as of 2026-10-16).
- Above 50 end users in a rolling 30 days, the "Open WebUI" name and logo must stay as they are, unless you have written permission or an enterprise licence.
- Code up to and including v0.6.5 is plain BSD-3. The docs say "anyone can still fork from v0.6.5 with zero restrictions" ([licence docs](https://docs.openwebui.com/license), [LICENSE_HISTORY](https://github.com/open-webui/open-webui/blob/v0.12.2/LICENSE_HISTORY)). Note that v0.6.5 lacks many security fixes: the Open WebUI repo lists 165 [security advisories](https://github.com/open-webui/open-webui/security/advisories), 158 of them published in 2026 (queried 2026-10-16), so an old fork is a security decision, not only a licence decision.
- New contributions need a Contributor License Agreement.

What this repo does: it ships Open WebUI unchanged (`ghcr.io/open-webui/open-webui:v0.12.2`) and does not touch the branding. If you plan a company-branded chat for more than 50 people, clause 4 is the part to check.

## Common problems

**A LiteLLM feature returns "You must be a LiteLLM Enterprise user".** The feature is licence-gated in your version. Look it up in the matrix above and use the workaround, or ask for a trial key.

**The LiteLLM Open WebUI tutorial does not work without a licence.** The [org rollout tutorial](https://docs.litellm.ai/docs/tutorials/openwebui_org_rollout) depends on JWT auth, which is enterprise. Use the header mapping from the [simpler tutorial](https://docs.litellm.ai/docs/tutorials/openweb_ui) and this repo instead.

**Admin UI SSO stops working after the sixth admin.** The free SSO tier ends at 5 users. Keep the number of LiteLLM admins small; staff use Open WebUI.

**A feature was free in a blog post and is enterprise now (or the other way round).** Editions change between versions. Check the docs page for your pinned version and test against your stack.

## Related guides

- [LiteLLM budgets and rate limits](budgets.md)
- [LLM gateway comparison](llm-gateway-comparison.md)
- [GDPR settings](gdpr.md)
- [PII masking with Presidio](pii-masking.md)
- [Quick start](quickstart.md)
- [Configuration reference](configuration.md)
- [EU model providers](eu-models.md)
- [Open WebUI with LiteLLM](open-webui.md)

> **Note:** Technical information as of 16 October 2026, not legal advice; the authors are not lawyers or data protection officers. No guarantee of completeness or compliance. You remain the controller and must do your own assessment (DPIA, Art. 30 record, DPAs) with your data protection officer or a lawyer.

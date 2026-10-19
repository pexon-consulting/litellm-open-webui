# LLM gateway comparison: LiteLLM and the alternatives

This guide explains what an LLM gateway (also called an AI gateway) does, when you need one, and how LiteLLM compares with Portkey, Kong, Agent Router (formerly Envoy AI Gateway), Bifrost, OpenRouter, TensorZero and one-api. It sticks to what the projects say about themselves and what GitHub shows, as of 2026-10-16. It also covers when LiteLLM is the wrong choice, and what to check in a community Docker Compose repo for LiteLLM and Open WebUI.

We have not benchmarked or deployed the alternatives. The comparison is based on their repositories and docs, not on our own tests.

## Contents

- [What an LLM gateway does](#what-an-llm-gateway-does)
- [When you need one](#when-you-need-one)
- [Comparison table](#comparison-table)
- [Notes per product](#notes-per-product)
- [When LiteLLM is the wrong choice](#when-litellm-is-the-wrong-choice)
- [Community LiteLLM + Open WebUI compose repos](#community-litellm--open-webui-compose-repos)
- [How to evaluate a gateway yourself](#how-to-evaluate-a-gateway-yourself)
- [Related guides](#related-guides)

## What an LLM gateway does

An LLM gateway sits between your applications and the model providers. Clients send requests to one endpoint, usually in the OpenAI API format. The gateway decides which provider gets the request and adds controls on the way.

Typical jobs, using this repo's LiteLLM setup as the example:

| Job | In this repo |
|---|---|
| One API for many providers | Open WebUI calls `http://litellm:4000/v1`; models come from `litellm/models.yaml` (Mistral EU by default, other providers in `examples/providers/`) |
| Keys per application or team | Virtual keys via `/key/generate`; provider keys stay in `.env` |
| Cost tracking and budgets | Per key, per team, per end user; see [budgets.md](budgets.md) |
| Rate limits | `rpm_limit`, `tpm_limit` per key or budget row |
| Model access control | `models` allow-list per key (a request for another model gets HTTP 403, tested) |
| Retries and fallbacks | `num_retries: 2`, `fallbacks` from `mistral-medium` to `mistral-small` in `litellm/config.yaml` |
| Guardrails | Presidio PII masking before the request leaves your network (`compose.pii.yaml`) |
| Logging and retention | Spend logs without prompts, deleted after 90 days |

The gateway is also the one place where you enforce rules for data protection: which provider and region a request may go to, what is logged, and how long it is kept.

## When you need one

You likely need a gateway if:

- More than one application or team uses LLMs, and you want one place for provider keys instead of copies in every app.
- You need cost limits per person, team or application, not only one invoice at the end of the month.
- You want to switch providers (for example from a global endpoint to an EU endpoint) without changing every client.
- You must control which providers and regions are allowed, and prove it.
- You want fallbacks when a provider fails.

You may not need one if a single application talks to a single provider, the provider's own console gives you the cost and usage limits you need, and nobody else gets access.

A gateway is one more service to run, update and secure. LiteLLM alone had 42 entries in the GitHub advisory database for the pip package (GitHub global advisory database, queried with `gh api` on 2026-10-16; see also the [LiteLLM security advisories](https://github.com/BerriAI/litellm/security/advisories)), including a supply-chain incident in March 2026 where versions 1.82.7 and 1.82.8 on PyPI contained credential-harvesting malware ([GHSA-5mg7-485q-xm76](https://github.com/advisories/GHSA-5mg7-485q-xm76)). We did not compare advisory counts of the other projects.

## Comparison table

Stars, licences and release dates from `gh api repos/<repo>` on 2026-10-16. Descriptions are quotes from each project.

| Product | Licence | Self-hosted | Stars | Latest release (as of 2026-10-16) | Self-description |
|---|---|---|---|---|---|
| [LiteLLM](https://github.com/BerriAI/litellm) | MIT, except `enterprise/` | Yes | 61,332 | v1.105.1, 2026-10-14 | "The fastest, litest AI Gateway. Rust core with Python SDK…" |
| [Portkey AI Gateway](https://github.com/Portkey-AI/gateway) | MIT | Yes | 13,194 | v1.15.2, 2026-01-12 (last push 2026-05-25) | "A blazing fast AI Gateway with integrated guardrails. Route to 1,600+ LLMs, 50+ AI Guardrails with 1 fast & friendly API." |
| [Kong](https://github.com/Kong/kong) (AI Gateway) | Apache-2.0 for Kong OSS | Yes | 44,271 | not collected | "The API and AI Gateway" |
| [Agent Router](https://github.com/theagentrouter/agent-router) (formerly Envoy AI Gateway) | Apache-2.0 | Yes | 2,229 | v1.2.0, 2026-10-07 | "The open source control plane for AI and agent traffic, powered by Envoy. An Agentic AI Foundation project. Formerly Envoy AI Gateway." |
| [Bifrost](https://github.com/maximhq/bifrost) (Maxim) | Apache-2.0 | Yes | 8,836 | cli/v1.0.0, 2026-10-13 | "Open-source, high-performance AI gateway that works as your LLM gateway, MCP gateway and agent gateway. One OpenAI-compatible API for 10,000+ models, with failover, load balancing, semantic caching, virtual [keys]…" |
| [OpenRouter](https://openrouter.ai/docs/quickstart) | Hosted service | No | n/a | n/a | "OpenRouter gives you access to hundreds of AI models through a single API endpoint. It handles fallbacks automatically and picks the most cost-effective option for each request." |
| [TensorZero](https://github.com/tensorzero/tensorzero) | Apache-2.0 | Yes | 11,711 | 2026.6.0, 2026-06-04 (last push 2026-06-11) | "open-source LLMOps platform that unifies an LLM gateway, observability, evaluation, optimization, and experimentation." |
| [one-api](https://github.com/songquanpeng/one-api) | MIT | Yes | 37,168 | not collected | LLM API management and distribution system (Chinese-language project) |

Stars measure attention, not quality or fit. Release dates matter more for a component that sits in front of all your LLM traffic: check how quickly security fixes ship.

## Notes per product

**LiteLLM.** Open source under MIT, with an enterprise licence key that enables features on the same image ([enterprise docs](https://docs.litellm.ai/docs/enterprise)). Virtual keys, budgets per key, team and end user, rate limits, fallbacks and Presidio PII masking are open source. JWT auth, Admin UI SSO for more than 5 users, model-specific budgets, team-based logging and secret managers are enterprise. Full list in [open-source-vs-enterprise.md](open-source-vs-enterprise.md). LiteLLM supports "the four most recent stable minor lines" with patch releases; on 2026-10-16 those are 1.105, 1.104, 1.103 and 1.102 ([version support](https://docs.litellm.ai/docs/enterprise/version_support)). The weekly release cadence means you plan regular upgrades.

**Portkey AI Gateway.** MIT licensed, positions itself on guardrails and breadth of models ("1,600+ LLMs, 50+ AI Guardrails"). The latest GitHub release on 2026-10-16 is from January 2026, and the last push from May 2026. We did not check what Portkey's hosted product adds over the open-source gateway.

**Kong AI Gateway.** Kong is a general API gateway (Apache-2.0) with AI plugins. The `ai-proxy` plugin is in the open-source repo ([kong/plugins/ai-proxy](https://github.com/Kong/kong/tree/master/kong/plugins/ai-proxy)). Kong fits best if you already run it for your other APIs.

**Agent Router (formerly Envoy AI Gateway).** `envoyproxy/ai-gateway` now redirects to `theagentrouter/agent-router`. It describes itself as a control plane powered by Envoy and is an Agentic AI Foundation project. It is the option closest to Kubernetes-native traffic management. We did not check whether it ships per-user budgets.

**Bifrost.** Apache-2.0, by Maxim. Its description lists failover, load balancing, semantic caching and virtual keys, and covers LLM, MCP and agent traffic. A CLI v1.0.0 release shipped on 2026-10-13. We did not verify its budget or SSO features.

**OpenRouter.** A hosted service, not something you run yourself. Its old `openrouter-runner` repository is archived ("Deprecated inference engine") ([archive](https://github.com/OpenRouterArchived/openrouter-runner)). With a hosted router, all prompts pass through a third party in addition to the model provider. For European companies that means one more processor to assess. We did not check where OpenRouter processes data or what its contract terms are.

**TensorZero.** Apache-2.0. It is broader than a gateway: "an LLM gateway, observability, evaluation, optimization, and experimentation." Latest release on 2026-10-16 is from June 2026. It fits if evaluation and optimisation of LLM applications is the main goal, not only routing and budgets.

**one-api.** MIT, 37,168 stars, a Chinese-language LLM API management and distribution system. We did not evaluate its features or documentation language.

## When LiteLLM is the wrong choice

LiteLLM is a good fit for chat for staff with budgets, which is what this repo does. It is the wrong choice, or at least not the first choice, when:

- **You already run Kong or Envoy for all API traffic.** Adding AI plugins to the gateway you already operate can be less work than a second gateway with its own database, upgrades and advisories.
- **You need per-user authentication against the gateway without paying for a licence.** In LiteLLM, JWT auth is enterprise ([token auth](https://docs.litellm.ai/docs/proxy/token_auth)). The open-source workaround in this repo (Open WebUI sends a user id header) works for one trusted client, but it trusts the header. If many independent clients must act on behalf of individual users, check what the alternatives offer for free before you decide.
- **More than 5 people need SSO into the gateway's admin UI.** That needs a LiteLLM licence ([admin UI SSO](https://docs.litellm.ai/docs/proxy/admin_ui_sso)).
- **You cannot keep up with upgrades.** Only the four newest minor lines get patches, and releases are weekly. 2026 brought several critical LiteLLM advisories, for example an authentication bypass via Host header injection (fixed in 1.84.0) and a privilege escalation to `proxy_admin` with remote code execution (GHSA-7hp6-4w63-5g45, published 2026-09-30). If nobody owns updates, a hosted service may carry less risk than a self-hosted gateway that falls behind.
- **Your main need is evaluation and experimentation**, not budgets and access control. A platform built for that (TensorZero describes itself this way) may fit better.
- **You need exact, hard spend limits.** LiteLLM writes spend in batches and reserves worst-case costs; budgets can be overshot under load, and fallbacks can be skipped near the end of a budget (measured in this repo, see [budgets.md](budgets.md#overshoot-why-a-budget-can-be-exceeded)). Use the provider's spending limit as the hard stop in any case.

## Community LiteLLM + Open WebUI compose repos

Several community repos combine LiteLLM and Open WebUI for specific environments. When you evaluate one, check image pinning, secret handling, healthchecks and retention.

Why the image tag matters: LiteLLM's docs say "The rolling `main-latest` tag is deprecated and is no longer being updated" and "Avoid `latest` in production" ([image security](https://docs.litellm.ai/docs/proxy/docker_image_security), as of 2026-10-16). A compose file on `main-latest` keeps running an old image that does not get security fixes.

The official LiteLLM `docker-compose.yml` at v1.105.1 is a starting point, but it uses the deprecated `main-stable` tag, hard-codes the database password, publishes Postgres on a host port, has no Redis and starts LiteLLM without waiting for a healthy database ([docker-compose.yml @ v1.105.1](https://raw.githubusercontent.com/BerriAI/litellm/v1.105.1/docker-compose.yml)).

What this repo adds, for comparison: pinned images (`ghcr.io/berriai/litellm:v1.105.1`, `ghcr.io/open-webui/open-webui:v0.12.2`, checked by `tests/test_config_files.py::test_images_are_pinned`), one Postgres with pgvector for both apps, Redis, healthchecks, ports bound to `127.0.0.1`, per-user budgets without a licence, Presidio with a German model, an Entra ID overlay (not tested against a real tenant), a chat retention script, EU provider examples, and 15 end-to-end tests against a mock LLM in CI.

## How to evaluate a gateway yourself

Whatever you pick, test these points against your own setup before rollout. They are the ones that caused surprises with LiteLLM in this repo:

1. **Error codes.** What does a client get when a budget runs out, a rate limit hits, or a model is not allowed? LiteLLM `v1.105.1` returns 422 for budgets, while its docs say 429.
2. **Budget accuracy.** Send parallel requests against a tiny budget and measure the overshoot.
3. **Fallback behaviour near the budget limit.** Does a fallback still happen when the budget is nearly used up?
4. **Per-user identity.** How does the gateway know who the person is, and is that free or paid?
5. **What gets stored.** Send a unique marker string and search the gateway's database and logs for it (`tests/test_gateway.py::test_prompts_not_stored_in_spend_logs` does this).
6. **Upgrade path.** How often do releases ship, how long are old lines patched, and are images signed?

## Related guides

- [LiteLLM budgets and rate limits](budgets.md)
- [LiteLLM open source vs enterprise](open-source-vs-enterprise.md)
- [GDPR settings](gdpr.md)
- [PII masking with Presidio](pii-masking.md)
- [Quick start](quickstart.md)
- [Configuration reference](configuration.md)
- [EU model providers](eu-models.md)

> **Note:** Based on public repositories and documentation as of 16 October 2026, not on our own tests of the alternatives. Figures change. All product names are trademarks of their owners; no affiliation or endorsement.

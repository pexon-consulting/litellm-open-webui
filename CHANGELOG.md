# Changelog

## 0.1.1 - 2026-10-19

- Presidio services start with `GUNICORN_CMD_ARGS=--no-control-socket`. gunicorn 25.1.0 in the Presidio 2.2.362 images could deadlock at start, so the analyzer stayed unhealthy (seen in CI).

## 0.1.0 - 2026-10-19

First release.

- Docker Compose stack: LiteLLM v1.105.1, Open WebUI v0.12.2, PostgreSQL 16 with pgvector 0.8.1,
  Redis 7.4.11. All ports on 127.0.0.1.
- Default models: Mistral via the EU endpoint, with EU prices for cost tracking.
- Overlays: PII masking with Presidio 2.2.362 and a German spaCy model (`compose.pii.yaml`),
  HTTPS with Caddy (`compose.tls.yaml`), Microsoft Entra ID login for Open WebUI
  (`compose.entra.yaml`), mock LLM for tests (`compose.test.yaml`).
- Budgets: per Open WebUI user (header mapping plus a default end-user budget) and a cap for
  the Open WebUI key, set by `scripts/bootstrap.py`. The Open WebUI key may only call the LLM
  API routes (`allowed_routes`).
- Privacy defaults: no prompts in spend logs, 90-day spend log retention, chat retention script
  (`scripts/purge-chats.sh`).
- Provider examples for Azure OpenAI, AWS Bedrock, Google Vertex AI, OpenAI EU, Mistral,
  STACKIT, IONOS, OVHcloud, Scaleway, T-Systems and self-hosted models.
- 15 end-to-end tests and static config checks, run in CI on every push and weekly. GitHub
  Actions pinned to commit SHAs.

# Security

## Reporting a vulnerability

Please do not open public issues for security problems. Use
[GitHub private vulnerability reporting](https://github.com/pexon-consulting/litellm-open-webui/security/advisories/new).
We try to answer within five working days. There is no entitlement to an answer or a fix.

In scope: the files in this repository, for example a compose default that exposes a
service publicly, a script that leaks a secret, or a documented setting that does not do
what the docs say. Vulnerabilities in LiteLLM, Open WebUI, Presidio, PostgreSQL, Redis or
Caddy themselves belong to those projects:

- LiteLLM: https://github.com/BerriAI/litellm/security
- Open WebUI: https://github.com/open-webui/open-webui/security
- Presidio: https://github.com/microsoft/presidio/security

## What the defaults do

- Every port binds to 127.0.0.1. Only `compose.tls.yaml` opens 80 and 443, and only for
  Caddy in front of Open WebUI. The LiteLLM admin UI stays private (SSH tunnel).
- `scripts/init-env.sh` creates `.env` with random secrets and file mode 600, and never
  overwrites an existing file. It stops if `openssl` is missing or a value comes out empty.
  `.env` is in `.gitignore`. `.env.example` has empty secrets, and compose refuses to start
  without `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY` and the other secrets.
- Images are pinned to versions (Redis, Caddy and the test mock to patch versions).
  `main-latest` and other moving tags are not used; a test in
  `tests/test_config_files.py` enforces this. GitHub Actions are pinned to commit SHAs.
- The Open WebUI virtual key may only call the LLM API routes
  (`allowed_routes: ["llm_api_routes"]`, set by `scripts/bootstrap.py`). It cannot create
  keys or read spend data.
- With `compose.tls.yaml`, Caddy sends HSTS, `X-Content-Type-Options`, a
  `frame-ancestors 'self'` CSP and `X-Frame-Options SAMEORIGIN` against clickjacking.
- Prompts and responses are not written to LiteLLM's spend log table
  (`store_prompts_in_spend_logs: false`) and not passed to logging callbacks
  (`turn_off_message_logging: true`).

## Trust model of the Open WebUI key

LiteLLM trusts the `X-OpenWebUI-User-Id` header on any request with a valid key. Whoever
holds `OPENWEBUI_LITELLM_KEY` can send any user id: bill another person's budget, or invent
new ids and get a fresh default budget for each. Only the budget on the key itself holds.

The key is visible to the Open WebUI container, to Open WebUI admins (Admin Panel >
Settings > Connections), to Open WebUI Tools and Functions (Python code running in that
container) and to every process on the host, because LiteLLM listens on 127.0.0.1:4000.

- Never reuse this key for other clients. Give each application its own key.
- Treat Open WebUI admins as trusted.
- Every local user on the Docker host can reach LiteLLM on 127.0.0.1:4000. Limit shell
  access to the host.

Details: [docs/open-webui.md](docs/open-webui.md#trust-model-for-the-key-and-the-user-header).

## What they do not do

- No protection against prompt injection. Content users paste or upload goes to the model.
- PII masking (`compose.pii.yaml`) lowers the risk of personal data reaching a provider. It
  does not catch everything, and if the Presidio analyzer returns an error, the prompt goes
  to the provider unmasked; see [docs/pii-masking.md](docs/pii-masking.md).
- Open WebUI admins can see a lot (users, settings, uploaded files). Give the admin role to
  as few people as possible.

## Known limitations

These are deliberate trade-offs in the current version, not oversights:

- **One Postgres role for both applications.** LiteLLM and Open WebUI both connect as the
  superuser `llm`. A compromised Open WebUI (for example through an admin-installed
  Function) could read the LiteLLM database. A separate `openwebui` role would limit that.
- **`env_file: .env` gives LiteLLM every variable in `.env`**, including
  `WEBUI_SECRET_KEY` and `MICROSOFT_CLIENT_SECRET`, not only the provider keys it needs.
- **The Redis password is on the command line** (`--requirepass`), so it shows up in
  `docker inspect` and in the host's process list.

## Supported versions

Fixes go into the latest version on `main`. Pinned image versions are raised when upstream
publishes security fixes; the weekly CI run catches images that stop working.

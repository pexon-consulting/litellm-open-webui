# Contributing

Thanks for helping. The most useful contributions are:

- a documented behaviour that is wrong for a newer LiteLLM or Open WebUI version,
- a provider example (`examples/providers/`) with a source for its data residency claims,
- a test that proves a claim the docs make.

## Run the tests

Never run the tests against a production stack. The test overlay replaces your models, and
on a fresh stack the tests sign up the first Open WebUI admin with a random password. Use a
separate clone with its own `COMPOSE_PROJECT_NAME`, `OPEN_WEBUI_PORT`, `LITELLM_PORT` and
`MOCK_LLM_PORT` in `.env` (see [Run the tests](docs/quickstart.md#run-the-tests)).

```bash
./scripts/init-env.sh
docker compose -f compose.yaml -f compose.pii.yaml -f compose.test.yaml up -d --wait
python3 scripts/bootstrap.py
python3 -m venv .venv && .venv/bin/pip install pytest pyyaml
.venv/bin/pytest tests -v
```

The test overlay replaces all models with a local mock (`tests/mock-llm/server.py`), so the
tests cost nothing and need no provider key. The Open WebUI tests need a fresh stack
(`docker compose ... down -v` first, in the test clone only), because they sign up the first
admin. The tests delete the keys, end users and budget rows they create.

`tests/test_config_files.py` runs without Docker and checks the config files only.

## Rules

- Every claim in `docs/` is either covered by a test or links a primary source with an
  as-of date. Write "not verified" when neither is possible.
- Pin image versions. No `latest`, no `main-latest`.
- Secrets only via `.env` and `os.environ/`. Never commit keys, not even test keys that look real.
- Plain English, no em dashes or en dashes.

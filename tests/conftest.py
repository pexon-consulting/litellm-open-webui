"""Shared helpers for the end-to-end tests. Standard library plus pytest.

The tests expect the stack with the test overlay to be running:

    docker compose -f compose.yaml -f compose.test.yaml up -d --wait
    python3 scripts/bootstrap.py
    .venv/bin/pytest tests

Add -f compose.pii.yaml to the compose command to include the PII masking test.
Never run them against a production stack: use a separate clone with its own
COMPOSE_PROJECT_NAME and ports (LITELLM_PORT, OPEN_WEBUI_PORT, MOCK_LLM_PORT).
URLs: LITELLM_URL and MOCK_LLM_URL if set, else localhost with the ports from .env.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, _, value = line.partition("=")
                values[name.strip()] = value.strip()
    return {**values, **os.environ}


ENV = _read_env()
LITELLM = ENV.get("LITELLM_URL") or f"http://localhost:{ENV.get('LITELLM_PORT') or '4000'}"
WEBUI = f"http://localhost:{ENV.get('OPEN_WEBUI_PORT') or '3000'}"
MOCK = ENV.get("MOCK_LLM_URL") or f"http://localhost:{ENV.get('MOCK_LLM_PORT') or '8000'}"


def http(method: str, url: str, body: dict | None = None, token: str | None = None,
         headers: dict[str, str] | None = None, timeout: float = 60) -> tuple[int, dict]:
    all_headers = {"Content-Type": "application/json", **(headers or {})}
    if token:
        all_headers["Authorization"] = f"Bearer {token}"
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method, headers=all_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        raw = error.read()
        status = error.code
    try:
        return status, json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return status, {"raw": raw.decode(errors="replace")}


def wait_for(check, timeout: float = 30, interval: float = 1):
    """Call check() until it returns something truthy, or fail after timeout seconds."""
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() > deadline:
            pytest.fail(f"condition not met within {timeout} s")
        time.sleep(interval)


def psql(sql: str, database: str = "litellm") -> str:
    """Run SQL in the postgres container and return the raw output."""
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "llm", "-d", database, "-tAc", sql],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


@pytest.fixture(scope="session")
def master_key() -> str:
    key = ENV.get("LITELLM_MASTER_KEY", "")
    assert key.startswith("sk-"), "LITELLM_MASTER_KEY missing, run scripts/init-env.sh"
    return key


@pytest.fixture(scope="session")
def stack_is_up(master_key: str) -> None:
    status, _ = http("GET", f"{MOCK}/health", timeout=5)
    if status != 200:
        pytest.exit("Mock LLM not reachable. Start the stack with compose.test.yaml first.", returncode=2)
    wait_for(lambda: http("GET", f"{LITELLM}/health/readiness", timeout=5)[0] == 200, timeout=120)


@pytest.fixture()
def mock(stack_is_up) -> "Mock":
    m = Mock()
    m.reset()
    return m


class Mock:
    def reset(self) -> None:
        http("POST", f"{MOCK}/_reset")

    def requests(self) -> list[dict]:
        return http("GET", f"{MOCK}/_requests")[1]

    def models(self) -> list[str]:
        return [r["body"].get("model") for r in self.requests()]


@pytest.fixture()
def new_key(master_key: str):
    """Create a virtual key with the given settings. Keys are deleted after the test."""
    created: list[str] = []

    def make(**settings) -> str:
        status, answer = http("POST", f"{LITELLM}/key/generate",
                              {"key_alias": f"e2e-{uuid.uuid4().hex[:8]}", **settings}, token=master_key)
        assert status == 200, answer
        created.append(answer["key"])
        return answer["key"]

    yield make
    if created:
        http("POST", f"{LITELLM}/key/delete", {"keys": created}, token=master_key)


@pytest.fixture(scope="session")
def _end_users(master_key: str):
    """End users created by the tests. Deleted with their own budget rows at the end of the session."""
    created: list[str] = []
    yield created
    if not created:
        return
    # Spend is flushed in batches (proxy_batch_write_at 10 s plus up to 5 s jitter), and a late
    # flush recreates a deleted end user. Wait for the last flush before deleting.
    time.sleep(16)
    budgets = []
    for user in created:
        status, info = http("GET", f"{LITELLM}/customer/info?end_user_id={user}", token=master_key)
        if status == 200 and info.get("budget_id"):
            budgets.append(info["budget_id"])
    http("POST", f"{LITELLM}/customer/delete", {"user_ids": created}, token=master_key)
    for budget_id in budgets:
        if budget_id != "per-user-default":
            http("POST", f"{LITELLM}/budget/delete", {"id": budget_id}, token=master_key)


@pytest.fixture()
def end_user(_end_users: list[str]):
    """Return a fresh end user id, cleaned up at the end of the session."""

    def make() -> str:
        user = f"e2e-user-{uuid.uuid4().hex[:8]}"
        _end_users.append(user)
        return user

    return make


def chat(key: str, model: str = "mistral-small", text: str = "hello", **extra) -> tuple[int, dict]:
    headers = extra.pop("headers", None)
    body = {"model": model, "messages": [{"role": "user", "content": text}], **extra}
    return http("POST", f"{LITELLM}/v1/chat/completions", body, token=key, headers=headers)

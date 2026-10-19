#!/usr/bin/env python3
"""Register the Open WebUI key and the default per-user budget in LiteLLM.

Run once after the first `docker compose up -d`, and again whenever you change the
budget values in .env. Safe to repeat: existing objects are updated, not duplicated.

    python3 scripts/bootstrap.py

Reads .env from the repository root. For a variable that is in .env, the .env value wins over
the process environment (a warning goes to stderr if they differ); variables that are not in
.env, such as LITELLM_URL, can come from the environment. Python standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUDGET_ID = "per-user-default"
KEY_ALIAS = "open-webui"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        sys.exit(f"{path} not found. Run scripts/init-env.sh first.")
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


class LiteLLM:
    def __init__(self, base_url: str, master_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.master_key = master_key

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.master_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read() or b"{}")
            except json.JSONDecodeError:
                return error.code, {}
        except urllib.error.URLError as error:
            sys.exit(f"LiteLLM not reachable at {self.base_url}: {error.reason}. Is the stack running?")


def money(value: str, name: str) -> float:
    try:
        amount = float(value)
    except ValueError:
        sys.exit(f"{name} must be a number, got {value!r}")
    if amount <= 0:
        sys.exit(f"{name} must be greater than 0")
    return amount


def ensure_user_budget(api: LiteLLM, amount: float, period: str) -> None:
    budget = {"budget_id": BUDGET_ID, "max_budget": amount, "budget_duration": period}
    status, found = api.call("POST", "/budget/info", {"budgets": [BUDGET_ID]})
    exists = status == 200 and bool(found)
    status, answer = api.call("POST", "/budget/update" if exists else "/budget/new", budget)
    if status != 200:
        sys.exit(f"Budget {BUDGET_ID}: HTTP {status} {answer}")
    print(f"{'Updated' if exists else 'Created'} budget {BUDGET_ID}: {amount} USD per user, period {period}")


def ensure_openwebui_key(api: LiteLLM, key: str, amount: float, period: str) -> None:
    # The key may only call LLM routes (chat, embeddings, /v1/models), no management endpoints.
    settings = {
        "max_budget": amount,
        "budget_duration": period,
        "key_alias": KEY_ALIAS,
        "allowed_routes": ["llm_api_routes"],
    }
    status, _ = api.call("GET", f"/key/info?key={urllib.parse.quote(key, safe='')}")
    if status == 200:
        status, answer = api.call("POST", "/key/update", {"key": key, **settings})
        action = "Updated"
    else:
        status, answer = api.call("POST", "/key/generate", {"key": key, **settings})
        action = "Created"
    if status != 200:
        sys.exit(f"Key {KEY_ALIAS}: HTTP {status} {answer}")
    print(f"{action} key {KEY_ALIAS}: {amount} USD for all Open WebUI traffic, period {period}")


def merged_env() -> dict[str, str]:
    from_file = read_env(ROOT / ".env")
    for name, value in from_file.items():
        if name in os.environ and os.environ[name] != value:
            print(f"Warning: {name} in your shell differs from .env; using the .env value.", file=sys.stderr)
    return {**os.environ, **from_file}


def main() -> None:
    env = merged_env()
    master_key = env.get("LITELLM_MASTER_KEY", "")
    openwebui_key = env.get("OPENWEBUI_LITELLM_KEY", "")
    if not master_key.startswith("sk-") or not openwebui_key.startswith("sk-"):
        sys.exit("LITELLM_MASTER_KEY and OPENWEBUI_LITELLM_KEY must be set in .env and start with sk-")

    base_url = env.get("LITELLM_URL") or f"http://localhost:{env.get('LITELLM_PORT') or '4000'}"
    host = urllib.parse.urlsplit(base_url).hostname
    if base_url.startswith("http://") and host not in ("localhost", "127.0.0.1", "::1"):
        print(f"Warning: the master key goes over plain HTTP to {host}. Use an SSH tunnel.", file=sys.stderr)
    api = LiteLLM(base_url, master_key)
    ensure_user_budget(
        api,
        money(env.get("USER_BUDGET_USD", "20"), "USER_BUDGET_USD"),
        env.get("USER_BUDGET_PERIOD", "30d"),
    )
    ensure_openwebui_key(
        api,
        openwebui_key,
        money(env.get("OPENWEBUI_BUDGET_USD", "500"), "OPENWEBUI_BUDGET_USD"),
        env.get("OPENWEBUI_BUDGET_PERIOD", "30d"),
    )


if __name__ == "__main__":
    main()

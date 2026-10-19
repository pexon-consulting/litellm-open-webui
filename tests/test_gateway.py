"""End-to-end tests against the running stack: every claim the docs make about the gateway."""

from __future__ import annotations

import time
import uuid

import pytest

from conftest import ENV, LITELLM, WEBUI, chat, http, psql, wait_for

pytestmark = pytest.mark.usefixtures("stack_is_up")


def test_litellm_health(master_key):
    status, answer = http("GET", f"{LITELLM}/health/readiness")
    assert status == 200
    assert answer.get("db") == "connected"


def test_openwebui_health():
    assert http("GET", f"{WEBUI}/health")[0] == 200


def test_chat_through_gateway(new_key, mock):
    status, answer = chat(new_key(), text="ping")
    assert status == 200, answer
    assert answer["choices"][0]["message"]["content"] == "mock: ping"
    assert mock.models() == ["mock-small"]


def test_key_budget_returns_422(new_key, mock):
    # LiteLLM v1.105 answers 422 with type budget_exceeded. Its docs say 429.
    key = new_key(max_budget=0.0001)
    results = []
    for _ in range(6):
        status, answer = chat(key, text="spend money")
        results.append(status)
        if status != 200:
            break
        time.sleep(1)
    assert results[0] == 200, "the first request passes, the budget is checked before spend exists"
    assert status == 422, results
    assert answer["error"]["type"] == "budget_exceeded"


def test_rpm_limit_returns_429(new_key, mock):
    key = new_key(rpm_limit=2)
    statuses = [chat(key)[0] for _ in range(5)]
    assert statuses[:2] == [200, 200], statuses
    assert 429 in statuses, statuses


def test_model_not_allowed_returns_403(new_key, mock):
    key = new_key(models=["mistral-small"])
    status, answer = chat(key, model="mistral-medium")
    assert status == 403, answer
    assert mock.requests() == [], "the request must not reach the provider"


def test_fallback_to_second_model(new_key, mock):
    status, answer = chat(new_key(max_budget=100), model="mistral-medium", text="fallback")
    assert status == 200, answer
    assert mock.models() == ["fail-always", "fail-always", "fail-always", "mock-small"]


def test_header_user_gets_own_spend(new_key, end_user, master_key, mock):
    user = end_user()
    status, answer = chat(new_key(), headers={"X-OpenWebUI-User-Id": user})
    assert status == 200, answer

    def spend():
        code, info = http("GET", f"{LITELLM}/customer/info?end_user_id={user}", token=master_key)
        return code == 200 and (info.get("spend") or 0) > 0

    wait_for(spend, timeout=30)


def test_header_user_budget_returns_422(new_key, end_user, master_key, mock):
    user = end_user()
    status, answer = http("POST", f"{LITELLM}/customer/new", {"user_id": user, "max_budget": 0.0001},
                          token=master_key)
    assert status == 200, answer
    key = new_key()
    statuses = []
    for _ in range(20):
        status, answer = chat(key, headers={"X-OpenWebUI-User-Id": user})
        statuses.append(status)
        if status != 200:
            break
        time.sleep(1)
    assert status == 422, statuses
    assert answer["error"]["type"] == "budget_exceeded"


def test_openwebui_key_only_reaches_llm_routes(mock):
    # scripts/bootstrap.py sets allowed_routes: ["llm_api_routes"] on the Open WebUI key
    key = ENV["OPENWEBUI_LITELLM_KEY"]
    assert http("GET", f"{LITELLM}/v1/models", token=key)[0] == 200
    status, answer = chat(key, text="routes")
    assert status == 200, answer
    status, answer = http("POST", f"{LITELLM}/key/generate", {}, token=key)
    assert status == 403, answer


def test_prompts_not_stored_in_spend_logs(new_key, mock):
    marker = f"secret-{uuid.uuid4().hex}"
    status, answer = chat(new_key(), text=marker)
    assert status == 200, answer

    def row():
        return psql(
            'SELECT coalesce(messages::text, \'\') || \'|\' || coalesce(response::text, \'\') '
            f'FROM "LiteLLM_SpendLogs" WHERE request_id = \'{answer["id"]}\''
        )

    stored = wait_for(row, timeout=40)
    assert marker not in stored
    assert "mock:" not in stored


def test_pii_is_masked_before_the_provider(new_key, master_key, mock):
    status, guardrails = http("GET", f"{LITELLM}/guardrails/list", token=master_key)
    names = [g.get("guardrail_name") for g in guardrails.get("guardrails", [])] if status == 200 else []
    if "presidio-pii" not in names:
        pytest.skip("PII overlay not running (add -f compose.pii.yaml)")

    text = "Max Mustermann aus Berlin, IBAN DE79000000001234567890, an max.mustermann@example.com"
    status, answer = chat(new_key(), text=text)
    assert status == 200, answer
    sent = mock.requests()[-1]["body"]["messages"][-1]["content"]
    for original in ("Mustermann", "DE79000000001234567890", "max.mustermann@example.com"):
        assert original not in sent, sent
    assert "<EMAIL_ADDRESS>" in sent and "<IBAN_CODE>" in sent


@pytest.fixture(scope="module")
def webui_admin() -> str:
    """Token of an Open WebUI admin. Signs up the first user on a fresh stack."""
    credentials = {"email": "e2e-admin@example.com", "password": f"E2e-{uuid.uuid4().hex}"}
    status, answer = http("POST", f"{WEBUI}/api/v1/auths/signup", {"name": "E2E Admin", **credentials})
    if status != 200:
        pytest.skip("Open WebUI already has users; the Open WebUI tests need a fresh stack")
    assert answer.get("role") == "admin", answer
    return answer["token"]


def test_signup_closes_after_first_admin(webui_admin):
    # Open WebUI v0.12 stores ui.enable_signup=false after the first admin, despite ENABLE_SIGNUP=true
    status, answer = http("POST", f"{WEBUI}/api/v1/auths/signup", {
        "name": "New Colleague", "email": f"e2e-{uuid.uuid4().hex[:6]}@example.com",
        "password": f"E2e-{uuid.uuid4().hex}"})
    assert status == 403, answer


def test_reopened_signup_creates_pending_users(webui_admin):
    status, config = http("GET", f"{WEBUI}/api/v1/auths/admin/config", token=webui_admin)
    assert status == 200, config
    status, answer = http("POST", f"{WEBUI}/api/v1/auths/admin/config",
                          {**config, "ENABLE_SIGNUP": True}, token=webui_admin)
    assert status == 200, answer
    try:
        status, answer = http("POST", f"{WEBUI}/api/v1/auths/signup", {
            "name": "New Colleague", "email": f"e2e-{uuid.uuid4().hex[:6]}@example.com",
            "password": f"E2e-{uuid.uuid4().hex}"})
        assert status == 200, answer
        assert answer["role"] == "pending"
    finally:
        http("POST", f"{WEBUI}/api/v1/auths/admin/config", {**config, "ENABLE_SIGNUP": False}, token=webui_admin)


def test_openwebui_forwards_user_to_litellm(webui_admin, master_key, mock):
    status, me = http("GET", f"{WEBUI}/api/v1/auths/", token=webui_admin)
    assert status == 200, me
    wait_for(lambda: any(m.get("id") == "mistral-small"
                         for m in http("GET", f"{WEBUI}/api/models", token=webui_admin)[1].get("data", [])),
             timeout=60, interval=3)
    status, answer = http("POST", f"{WEBUI}/api/chat/completions", {
        "model": "mistral-small", "stream": False,
        "messages": [{"role": "user", "content": "via open webui"}]}, token=webui_admin)
    assert status == 200, answer
    assert "mock-small" in mock.models()

    def spend():
        code, info = http("GET", f"{LITELLM}/customer/info?end_user_id={me['id']}", token=master_key)
        return code == 200 and (info.get("spend") or 0) > 0

    wait_for(spend, timeout=30)

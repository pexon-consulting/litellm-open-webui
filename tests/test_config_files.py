"""Static checks on the config files. No running stack needed."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
PROVIDERS = sorted((ROOT / "examples" / "providers").glob("*.yaml"))
MODEL_FILES = [ROOT / "litellm" / "models.yaml", *PROVIDERS]
SECRET_PARAMS = {"api_key", "aws_access_key_id", "aws_secret_access_key", "vertex_credentials"}


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


@pytest.mark.parametrize("path", MODEL_FILES, ids=lambda p: p.name)
def test_secrets_come_from_env(path):
    for model in load(path)["model_list"]:
        for name, value in model["litellm_params"].items():
            if name in SECRET_PARAMS:
                assert str(value).startswith("os.environ/") or value == "not-needed", (path.name, model["model_name"])


@pytest.mark.parametrize("path", MODEL_FILES, ids=lambda p: p.name)
def test_no_global_endpoints(path):
    text = path.read_text()
    assert "https://api.mistral.ai" not in text, "use api.eu.mistral.ai"
    assert "https://api.openai.com" not in text, "use eu.api.openai.com"
    for model in load(path)["model_list"]:
        params = model["litellm_params"]
        assert params.get("vertex_location") != "global", model["model_name"]
        if params["model"].startswith("bedrock/anthropic"):
            pytest.fail(f"{model['model_name']}: use an eu. inference profile")


def test_main_models_have_eu_prices():
    for model in load(ROOT / "litellm" / "models.yaml")["model_list"]:
        assert model["litellm_params"].get("input_cost_per_token", 0) > 0, model["model_name"]


def test_fallbacks_point_to_existing_models():
    config = load(ROOT / "litellm" / "config.yaml")
    names = {m["model_name"] for m in load(ROOT / "litellm" / "models.yaml")["model_list"]}
    test_names = {m["model_name"] for m in load(ROOT / "tests" / "models.test.yaml")["model_list"]}
    assert names == test_names, "tests/models.test.yaml must use the same model names"
    for entry in config["router_settings"]["fallbacks"]:
        for primary, targets in entry.items():
            assert primary in names and set(targets) <= names, entry


def test_config_keeps_settings_out_of_includes():
    # "include" replaces non-list top-level keys, so settings in an included file would win
    for included in load(ROOT / "litellm" / "config.yaml")["include"]:
        data = load(ROOT / "litellm" / included) or {}
        assert not {"router_settings", "litellm_settings", "general_settings"} & set(data), included


def test_images_are_pinned():
    for path in ROOT.glob("compose*.yaml"):
        for image in re.findall(r"image:\s*(\S+)", path.read_text()):
            tag = image.rsplit(":", 1)[-1] if ":" in image else ""
            assert tag and tag != "latest" and not tag.startswith("main"), f"{path.name}: {image}"


def test_skill_mirrors_are_identical():
    canonical = (ROOT / "skills" / "litellm-gateway-admin" / "SKILL.md").read_text()
    for mirror in (".claude", ".agents"):
        path = ROOT / mirror / "skills" / "litellm-gateway-admin" / "SKILL.md"
        assert path.read_text() == canonical, f"{path} differs: cp skills/litellm-gateway-admin/SKILL.md {path}"


def test_embedding_model_for_open_webui():
    models = load(ROOT / "litellm" / "models.yaml")["model_list"]
    assert any(m["model_name"] == "embedding" and m.get("model_info", {}).get("mode") == "embedding" for m in models)


def test_entra_does_not_merge_accounts_by_default():
    text = (ROOT / "compose.entra.yaml").read_text()
    assert "OAUTH_MERGE_ACCOUNTS_BY_EMAIL: ${ENTRA_MERGE_BY_EMAIL:-false}" in text

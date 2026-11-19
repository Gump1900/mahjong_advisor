"""Local credential loading without network, output or global env mutation."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.players import config
from src.players.llm import LLMPlayer


@pytest.fixture
def local_config(tmp_path, monkeypatch):
    path = tmp_path / "local.toml"
    monkeypatch.setattr(config, "LOCAL_CONFIG", path)
    for name in ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "MAHJONG_BOT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return path


def test_missing_config_does_not_require_local_file(local_config):
    assert config.load_local_config() == {}
    assert LLMPlayer(provider="deepseek", client=object()).model == "deepseek-flash"


def test_file_credential_used_without_export_and_without_leaking(local_config, monkeypatch):
    import anthropic
    local_config.write_text('[deepseek]\napi_key = "test-local-secret"\nmodel = "test-model"\n')
    captured = []
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: captured.append(kw) or SimpleNamespace())
    bot = LLMPlayer(provider="deepseek")
    assert captured[0]["api_key"] == "test-local-secret" and bot.model == "test-model"
    assert "test-local-secret" not in repr(bot.__dict__)  # Only the SDK retains credentials.
    assert captured[0]["base_url"] == "https://api.deepseek.com/anthropic"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-env-secret")
    monkeypatch.setenv("MAHJONG_BOT_MODEL", "env-model")
    assert LLMPlayer(provider="deepseek").model == "env-model"
    assert captured[-1]["api_key"] == "test-local-secret"
    assert bot.key_source == "config/local.toml"
    assert LLMPlayer(provider="deepseek", model="explicit-model").model == "explicit-model"
    local_config.write_text('[deepseek]\napi_key = ""\n')
    assert LLMPlayer(provider="deepseek").key_source == "DEEPSEEK_API_KEY"
    assert captured[-1]["api_key"] == "test-env-secret"


@pytest.mark.parametrize("text", [
    '[deepseek]\napi_key = "test-secret',
    '[deepseek]\napi_key = 123',
    'deepseek = "test-secret"',
])
def test_invalid_configuration_never_echoes_credential(local_config, text):
    local_config.write_text(text)
    with pytest.raises(ValueError) as error:
        config.load_local_config()
    assert "test-secret" not in str(error.value)


def test_repository_private_file_ignored_but_template_not_ignored():
    root = Path(__file__).resolve().parents[1]
    ignored = subprocess.run(["git", "check-ignore", "config/local.toml"], cwd=root, capture_output=True, text=True)
    assert ignored.returncode == 0
    public = subprocess.run(["git", "check-ignore", "config/local.example.toml"], cwd=root, capture_output=True, text=True)
    assert public.returncode == 1

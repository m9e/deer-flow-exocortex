from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

import deerflow.config.app_config as app_config_module
from deerflow.config.agents_api_config import get_agents_api_config
from deerflow.config.app_config import get_app_config, reset_app_config
from deerflow.config.model_config import ModelConfig


def _write_config(path: Path, *, model_name: str, supports_thinking: bool) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {
                        "name": model_name,
                        "use": "langchain_openai:ChatOpenAI",
                        "model": "gpt-test",
                        "supports_thinking": supports_thinking,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_config_with_agents_api(
    path: Path,
    *,
    model_name: str,
    supports_thinking: bool,
    agents_api: dict | None = None,
) -> None:
    config = {
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "models": [
            {
                "name": model_name,
                "use": "langchain_openai:ChatOpenAI",
                "model": "gpt-test",
                "supports_thinking": supports_thinking,
            }
        ],
    }
    if agents_api is not None:
        config["agents_api"] = agents_api

    path.write_text(yaml.safe_dump(config), encoding="utf-8")


def _write_extensions_config(path: Path) -> None:
    path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")


def test_get_app_config_reloads_when_file_changes(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_path, model_name="first-model", supports_thinking=False)

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()

    try:
        initial = get_app_config()
        assert initial.models[0].supports_thinking is False

        _write_config(config_path, model_name="first-model", supports_thinking=True)
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        reloaded = get_app_config()
        assert reloaded.models[0].supports_thinking is True
        assert reloaded is not initial
    finally:
        reset_app_config()


def test_get_app_config_reloads_when_config_path_changes(tmp_path, monkeypatch):
    config_a = tmp_path / "config-a.yaml"
    config_b = tmp_path / "config-b.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config(config_a, model_name="model-a", supports_thinking=False)
    _write_config(config_b, model_name="model-b", supports_thinking=True)

    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_a))
    reset_app_config()

    try:
        first = get_app_config()
        assert first.models[0].name == "model-a"

        monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_b))
        second = get_app_config()
        assert second.models[0].name == "model-b"
        assert second is not first
    finally:
        reset_app_config()


def test_get_app_config_resets_agents_api_config_when_section_removed(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_config_with_agents_api(
        config_path,
        model_name="first-model",
        supports_thinking=False,
        agents_api={"enabled": True},
    )

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    reset_app_config()

    try:
        initial = get_app_config()
        assert initial.models[0].name == "first-model"
        assert get_agents_api_config().enabled is True

        _write_config_with_agents_api(
            config_path,
            model_name="first-model",
            supports_thinking=False,
        )
        next_mtime = config_path.stat().st_mtime + 5
        os.utime(config_path, (next_mtime, next_mtime))

        reloaded = get_app_config()
        assert reloaded is not initial
        assert get_agents_api_config().enabled is False
    finally:
        reset_app_config()


def test_get_app_config_merges_model_list_endpoint_models(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    config_path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {
                        "name": "manual",
                        "use": "langchain_openai:ChatOpenAI",
                        "model": "manual-model",
                    }
                ],
                "model_list_endpoint": {
                    "url": "http://example.test/v1/models",
                    "base_url": "http://example.test/v1",
                    "api_key": "n/a",
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setattr(
        app_config_module,
        "_build_model_list_endpoint_model_configs",
        lambda _cfg: [
            ModelConfig(name="dynamic", use="langchain_openai:ChatOpenAI", model="dynamic-model"),
            ModelConfig(name="manual-shadow", use="langchain_openai:ChatOpenAI", model="manual-model"),
        ],
    )
    reset_app_config()

    try:
        config = get_app_config()
        assert [model.name for model in config.models] == ["manual", "dynamic"]
        assert [model.model for model in config.models] == ["manual-model", "dynamic-model"]
    finally:
        reset_app_config()


def test_get_app_config_refreshes_model_list_endpoint_on_ttl(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    config_path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {
                        "name": "manual",
                        "use": "langchain_openai:ChatOpenAI",
                        "model": "manual-model",
                    }
                ],
                "model_list_endpoint": {
                    "url": "http://example.test/v1/models",
                    "base_url": "http://example.test/v1",
                    "cache_ttl_sec": 30,
                    "api_key": "n/a",
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    tick = {"value": 100.0}
    monkeypatch.setattr(app_config_module.time, "monotonic", lambda: tick["value"])

    discovered_names = iter(
        [
            ModelConfig(name="dynamic-one", use="langchain_openai:ChatOpenAI", model="dynamic-model-one"),
            ModelConfig(name="dynamic-two", use="langchain_openai:ChatOpenAI", model="dynamic-model-two"),
        ]
    )
    monkeypatch.setattr(
        app_config_module,
        "_build_model_list_endpoint_model_configs",
        lambda _cfg: [next(discovered_names)],
    )
    reset_app_config()

    try:
        initial = get_app_config()
        assert [model.name for model in initial.models] == ["manual", "dynamic-one"]

        still_cached = get_app_config()
        assert still_cached is initial

        tick["value"] += 31.0
        refreshed = get_app_config()
        assert refreshed is not initial
        assert [model.name for model in refreshed.models] == ["manual", "dynamic-two"]
    finally:
        reset_app_config()

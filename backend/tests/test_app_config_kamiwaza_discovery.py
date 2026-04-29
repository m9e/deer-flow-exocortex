from __future__ import annotations

import httpx
import yaml

from deerflow.config import app_config as app_config_module
from deerflow.config.app_config import get_app_config, reset_app_config
from deerflow.config.model_list_endpoint_config import ModelListEndpointConfig


def _write_extensions_config(path):
    path.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")


def _write_app_config(path, *, models):
    path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": models,
            }
        ),
        encoding="utf-8",
    )


def test_build_model_list_endpoint_model_configs_normalizes_kamiwaza_ids(monkeypatch):
    endpoint_config = ModelListEndpointConfig(
        url="http://example.test/v1/models",
        base_url="http://example.test/v1",
        use="langchain_openai:ChatOpenAI",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://example.test/v1/models"
        return httpx.Response(
            status_code=200,
            json={"data": [{"id": "kamiwaza/babynator3/Qwen3.5-27B-NVFP4"}]},
        )

    transport = httpx.MockTransport(handler)
    original_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(app_config_module.httpx, "Client", client_factory)

    discovered = app_config_module._build_model_list_endpoint_model_configs(endpoint_config)
    assert len(discovered) == 1
    assert discovered[0].model == "kamiwaza/babynator3/Qwen3.5-27B-NVFP4"
    assert discovered[0].name == "babynator3"
    assert discovered[0].display_name == "Qwen3.5-27B-NVFP4 (babynator3)"
    assert discovered[0].provider == "kamiwaza"


def test_get_app_config_normalizes_kamiwaza_model_ids(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    _write_extensions_config(extensions_path)
    _write_app_config(
        config_path,
        models=[
            {
                "name": "babynator3",
                "use": "langchain_openai:ChatOpenAI",
                "model": "kamiwaza/babynator3/Qwen3.5-27B-NVFP4",
                "base_url": "http://host.docker.internal:4000/v1",
                "api_key": "n/a",
            }
        ],
    )

    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(config_path))
    reset_app_config()

    try:
        config = get_app_config()
        assert config.models[0].model == "kamiwaza/babynator3/Qwen3.5-27B-NVFP4"
    finally:
        reset_app_config()


def test_endpoint_discovery_filters_stale_manual_kamiwaza_models(monkeypatch):
    endpoint_config = ModelListEndpointConfig(
        url="http://example.test/v1/models",
        base_url="http://example.test/v1",
        use="langchain_openai:ChatOpenAI",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"data": [{"id": "kamiwaza/relic/MiniMax-M2.7-AWQ-4bit"}]},
        )

    transport = httpx.MockTransport(handler)
    original_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(app_config_module.httpx, "Client", client_factory)

    stale = app_config_module.ModelConfig.model_validate(
        {
            "name": "babynator3",
            "use": "langchain_openai:ChatOpenAI",
            "model": "kamiwaza/babynator3/Qwen3.5-27B-NVFP4",
            "provider": "kamiwaza",
            "base_url": "http://example.test/v1",
            "api_key": "n/a",
        }
    )
    valid = app_config_module.ModelConfig.model_validate(
        {
            "name": "relic",
            "use": "langchain_openai:ChatOpenAI",
            "model": "kamiwaza/relic/MiniMax-M2.7-AWQ-4bit",
            "provider": "kamiwaza",
            "base_url": "http://example.test/v1",
            "api_key": "n/a",
        }
    )
    discovered = app_config_module._build_model_list_endpoint_model_configs(endpoint_config)

    merged = app_config_module._merge_model_configs([stale, valid], discovered, endpoint_config)

    assert [model.name for model in merged] == ["relic"]
    assert merged[0].model == "kamiwaza/relic/MiniMax-M2.7-AWQ-4bit"


def test_endpoint_discovery_filters_stale_manual_models_with_local_host_aliases(monkeypatch):
    endpoint_config = ModelListEndpointConfig(
        url="http://host.docker.internal:4000/v1/models",
        base_url="http://host.docker.internal:4000/v1",
        use="langchain_openai:ChatOpenAI",
        provider="kamiwaza",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={"data": [{"id": "kamiwaza/relic/MiniMax-M2.7-AWQ-4bit"}]},
        )

    transport = httpx.MockTransport(handler)
    original_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(app_config_module.httpx, "Client", client_factory)

    stale = app_config_module.ModelConfig.model_validate(
        {
            "name": "old-local-alias",
            "use": "langchain_openai:ChatOpenAI",
            "model": "Qwen3.5-27B-NVFP4",
            "base_url": "http://localhost:4000/v1",
            "api_key": "n/a",
        }
    )
    discovered = app_config_module._build_model_list_endpoint_model_configs(endpoint_config)

    merged = app_config_module._merge_model_configs([stale], discovered, endpoint_config)

    assert [model.model for model in merged] == ["kamiwaza/relic/MiniMax-M2.7-AWQ-4bit"]

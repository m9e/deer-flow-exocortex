from deerflow.config.kamiwaza_model_env import (
    apply_kamiwaza_env_defaults,
    infer_model_provider,
    normalize_kamiwaza_model_id,
)


def test_infer_model_provider_prefers_existing_value():
    provider = infer_model_provider(
        model="gpt-4",
        base_url="https://llm.example.com/v1",
        endpoint_path="/v1/chat/completions",
        provider="openai",
    )
    assert provider == "openai"


def test_infer_model_provider_from_kamiwaza_model_prefix():
    provider = infer_model_provider(
        model="kamiwaza/small-fast",
        base_url="https://llm.example.com/v1",
    )
    assert provider == "kamiwaza"


def test_infer_model_provider_from_runtime_endpoint():
    provider = infer_model_provider(
        model="tiny-fast",
        base_url="https://host.docker.internal/runtime/models/xyz/v1",
    )
    assert provider == "kamiwaza"


def test_apply_kamiwaza_env_defaults_fills_missing_model_and_paths(monkeypatch):
    monkeypatch.setenv("KAMIWAZA_MODEL_NAME", "Qwen3-Coder")
    monkeypatch.setenv("KAMIWAZA_MODEL_PATH", "/runtime/models/qwen3/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://host.docker.internal:7000")

    resolved = apply_kamiwaza_env_defaults(
        {
            "provider": "kamiwaza",
            "model": "",
            "endpoint_path": "{runtime_path}",
            "base_url": "{openai_base}",
        }
    )

    assert resolved["model"] == "Qwen3-Coder"
    assert resolved["endpoint_path"] == "/runtime/models/qwen3/v1"
    assert resolved["base_url"] == "https://host.docker.internal:7000"


def test_normalize_kamiwaza_model_id():
    assert normalize_kamiwaza_model_id(" kamiwaza/babynator3/Qwen3.5-27B-NVFP4 ") == "kamiwaza/babynator3/Qwen3.5-27B-NVFP4"
    assert normalize_kamiwaza_model_id("kamiwaza/big-smart") == "kamiwaza/big-smart"
    assert normalize_kamiwaza_model_id("google/gemini-2.5-pro-preview") == "google/gemini-2.5-pro-preview"


def test_apply_kamiwaza_env_defaults_preserves_deployment_qualified_model_id():
    resolved = apply_kamiwaza_env_defaults(
        {
            "provider": "kamiwaza",
            "model": "kamiwaza/babynator3/Qwen3.5-27B-NVFP4",
            "base_url": "http://host.docker.internal:4000/v1",
        }
    )
    assert resolved["model"] == "kamiwaza/babynator3/Qwen3.5-27B-NVFP4"

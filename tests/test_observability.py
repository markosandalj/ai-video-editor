from __future__ import annotations

import sys
import types
from pathlib import Path

from ai_video_editor.llm import LangChainModelConfig, build_chat_model
from ai_video_editor.observability import configure_observability, langsmith_status


LANGSMITH_ENV_KEYS = (
    "LANGSMITH_TRACING",
    "LANGSMITH_TRACING_V2",
    "LANGSMITH_ENDPOINT",
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGCHAIN_TRACING",
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_ENDPOINT",
    "LANGCHAIN_API_KEY",
    "LANGCHAIN_PROJECT",
)


def _clear_langsmith_env(monkeypatch) -> None:
    for key in LANGSMITH_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_configure_observability_loads_langsmith_dotenv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _clear_langsmith_env(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "LANGSMITH_TRACING=true",
                "LANGSMITH_ENDPOINT=https://api.smith.langchain.com",
                "LANGSMITH_API_KEY=test-key",
                "LANGSMITH_PROJECT=ai-video-editor",
            ]
        ),
        encoding="utf-8",
    )

    status = configure_observability(env_path)

    assert status.tracing_enabled is True
    assert status.endpoint == "https://api.smith.langchain.com"
    assert status.project == "ai-video-editor"
    assert status.has_api_key is True


def test_build_chat_model_loads_langsmith_env_from_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _clear_langsmith_env(monkeypatch)
    module_name = "tests.fake_observability_llm"
    module = types.ModuleType(module_name)

    class FakeChatModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    module.FakeChatModel = FakeChatModel
    monkeypatch.setitem(sys.modules, module_name, module)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "LANGSMITH_TRACING=true",
                "LANGSMITH_ENDPOINT=https://api.smith.langchain.com",
                "LANGSMITH_API_KEY=test-key",
                "LANGSMITH_PROJECT=ai-video-editor",
            ]
        ),
        encoding="utf-8",
    )

    model = build_chat_model(
        LangChainModelConfig(
            id="fake",
            class_path=f"{module_name}.FakeChatModel",
            model="fake-model",
            api_key_env=None,
        )
    )

    assert isinstance(model, FakeChatModel)
    assert langsmith_status().tracing_enabled is True
    assert langsmith_status().project == "ai-video-editor"

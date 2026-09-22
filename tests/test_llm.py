import sys
import types

from ai_video_editor.llm import LangChainModelConfig, build_chat_model


def test_langchain_model_config_dynamic_import_uses_fake_class(monkeypatch) -> None:
    module = types.ModuleType("tests.fake_llm")

    class FakeChatModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    module.FakeChatModel = FakeChatModel
    monkeypatch.setitem(sys.modules, module.__name__, module)
    config = LangChainModelConfig.model_validate(
        {
            "id": "fake",
            "class_path": f"{module.__name__}.FakeChatModel",
            "model": "fake-model",
            "temperature": 0.2,
            "api_key_env": None,
            "kwargs": {"custom": "value"},
        }
    )

    model = build_chat_model(config)

    assert isinstance(model, FakeChatModel)
    assert model.kwargs == {
        "model": "fake-model",
        "temperature": 0.2,
        "custom": "value",
    }

from __future__ import annotations

import importlib
import os
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from ai_video_editor.observability import configure_observability


class LangChainModelConfig(BaseModel):
    """Configuration for constructing a LangChain chat model dynamically."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(default="", description="Stable experiment/reporting id.")
    class_path: str = Field(
        default="langchain_google_genai.ChatGoogleGenerativeAI",
        description="Import path for the LangChain chat model class.",
    )
    model: str = Field(description="Provider model name passed to the chat class.")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    api_key_env: str | None = Field(
        default="GEMINI_API_KEY",
        description="Environment variable containing the provider API key. Null disables API key injection.",
    )
    provider_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("provider_kwargs", "kwargs"),
        serialization_alias="provider_kwargs",
        description="Extra constructor kwargs passed to the chat model class.",
    )

    def with_id(self, model_id: str) -> LangChainModelConfig:
        return self.model_copy(update={"id": self.id or model_id})

    def public_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


def default_cutting_model_config() -> LangChainModelConfig:
    return LangChainModelConfig(
        id="gemini-2.5-flash",
        model="gemini-2.5-flash",
        temperature=0.0,
        provider_kwargs={"timeout": 120, "max_retries": 4},
    )


def direct_gemini_model_config(
    *,
    model: str,
    temperature: float = 0.1,
) -> LangChainModelConfig:
    """Build a direct Gemini config for an explicitly named model."""
    return LangChainModelConfig(
        id=model,
        model=model,
        temperature=temperature,
        provider_kwargs={"timeout": 180, "max_retries": 4},
    )


def default_section_editor_model_config() -> LangChainModelConfig:
    """The section-editor model selected by the corpus evaluation."""
    return LangChainModelConfig(
        id="gpt-5.6-sol",
        class_path="langchain_openai.ChatOpenAI",
        model="openai/gpt-5.6-sol",
        temperature=1.0,
        api_key_env="OPENROUTER_API_KEY",
        provider_kwargs={
            "base_url": "https://openrouter.ai/api/v1",
            "timeout": 300,
            "max_retries": 3,
            "max_tokens": 16_000,
            "extra_body": {"reasoning": {"effort": "low", "exclude": True}},
        },
    )


def import_from_path(class_path: str) -> type[Any]:
    module_name, sep, class_name = class_path.rpartition(".")
    if not sep or not module_name or not class_name:
        raise ValueError(
            f"Invalid LangChain class path {class_path!r}; expected 'package.module.ClassName'."
        )
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            f"Could not import LangChain provider module {module_name!r}. "
            "Install the matching LangChain integration package or fix class_path."
        ) from exc
    try:
        cls = getattr(module, class_name)
    except AttributeError as exc:
        raise AttributeError(
            f"LangChain provider class {class_name!r} was not found in {module_name!r}."
        ) from exc
    if not isinstance(cls, type):
        raise TypeError(f"{class_path!r} resolved to {type(cls)!r}, not a class.")
    return cls


def build_chat_model(config: LangChainModelConfig) -> Any:
    """Construct a LangChain chat model from config.

    The function intentionally does not import provider packages directly. Gemini
    works through the existing dependency, and any other provider works once its
    LangChain integration package is installed.
    """
    configure_observability()

    kwargs: dict[str, Any] = {
        "model": config.model,
        "temperature": config.temperature,
        **config.provider_kwargs,
    }
    if config.api_key_env:
        api_key = os.environ.get(config.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{config.api_key_env} not found. Add it to your .env file or set api_key_env to null."
            )
        kwargs["api_key"] = api_key
    cls = import_from_path(config.class_path)
    return cls(**kwargs)

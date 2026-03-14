from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from .agents import AgentProfile, default_agent_name, get_agent_profile

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None


DEFAULT_MODEL = "gpt-5.4"
DEFAULT_PROVIDER = "openai"


@dataclass(frozen=True)
class AIResult:
    text: str
    provider: str
    agent: str
    model: str
    request_id: str | None


@dataclass(frozen=True)
class AIConfig:
    provider: str
    model: str
    agent: str


def available_providers() -> tuple[str, ...]:
    return ("openai",)


def default_provider_name() -> str:
    return os.environ.get("MNEME_AI_PROVIDER", DEFAULT_PROVIDER)


def default_model_name() -> str:
    return os.environ.get("MNEME_AI_MODEL", DEFAULT_MODEL)


def resolve_ai_config(
    *,
    provider: str | None = None,
    model: str | None = None,
    agent: str | None = None,
) -> AIConfig:
    provider_name = provider or default_provider_name()
    if provider_name not in available_providers():
        valid = ", ".join(available_providers())
        raise ValueError(f"Unknown provider '{provider_name}'. Valid providers: {valid}")

    agent_name = agent or os.environ.get("MNEME_AGENT", default_agent_name())
    get_agent_profile(agent_name)

    return AIConfig(
        provider=provider_name,
        model=model or default_model_name(),
        agent=agent_name,
    )


def openai_ready() -> tuple[bool, str | None]:
    if OpenAI is None:
        return False, "openai package is not installed"
    if not os.environ.get("OPENAI_API_KEY"):
        return False, "OPENAI_API_KEY is not set"
    return True, None


def provider_ready(provider: str) -> tuple[bool, str | None]:
    if provider == "openai":
        return openai_ready()
    return False, f"Provider '{provider}' is not implemented"


def answer_question(*, context_packet: dict[str, Any], config: AIConfig) -> AIResult:
    if config.provider != "openai":
        raise RuntimeError(f"Provider '{config.provider}' is not implemented")
    if OpenAI is None:
        raise RuntimeError("openai package is not installed")

    profile = get_agent_profile(config.agent)
    client = OpenAI()
    response = client.responses.create(
        model=config.model,
        instructions=profile.instructions,
        input=json.dumps(context_packet, indent=2, sort_keys=True),
    )
    text = (response.output_text or "").strip()
    if not text:
        raise RuntimeError("Model returned no text output")
    return AIResult(
        text=text,
        provider=config.provider,
        agent=config.agent,
        model=config.model,
        request_id=getattr(response, "_request_id", None),
    )

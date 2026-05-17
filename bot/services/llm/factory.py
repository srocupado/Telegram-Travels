from __future__ import annotations

import logging

from bot.config import Settings
from bot.services.llm.base import LLMClient

logger = logging.getLogger(__name__)


def make_llm(settings: Settings) -> LLMClient:
    provider = settings.ai_provider.lower()
    if provider == "anthropic":
        from bot.services.llm.anthropic_impl import AnthropicLLM

        llm = AnthropicLLM(settings)
    elif provider == "openai":
        from bot.services.llm.openai_impl import OpenAILLM

        llm = OpenAILLM(settings)
    elif provider == "gemini":
        from bot.services.llm.gemini_impl import GeminiLLM

        llm = GeminiLLM(settings)
    else:
        raise ValueError(
            f"AI_PROVIDER inválido: {settings.ai_provider!r}. Use anthropic, openai ou gemini."
        )
    logger.info(
        "LLM provider=%s fast=%s slow=%s",
        llm.provider,
        llm.fast_model,
        llm.slow_model,
    )
    return llm

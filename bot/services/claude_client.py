from anthropic import AsyncAnthropic

from bot.config import Settings


def make_claude(settings: Settings) -> AsyncAnthropic:
    return AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass
class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5.1")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    xai_api_key: str = os.getenv("XAI_API_KEY", "")
    xai_model: str = os.getenv("XAI_MODEL", "grok-3")
    xai_base_url: str = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
    request_timeout: float = float(os.getenv("LLM_TIMEOUT", "300"))
    stream_console_enabled: bool = os.getenv("STREAM_CONSOLE_ENABLED", "true").lower() not in {
        "0",
        "false",
        "no",
    }
    stream_buffer_chars: int = int(os.getenv("STREAM_BUFFER_CHARS", "120"))


@lru_cache()
def get_settings() -> Settings:
    return Settings()

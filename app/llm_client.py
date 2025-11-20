from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Union

import httpx
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .config import Settings
from .prompts import build_system_prompt, build_user_prompt

logger = logging.getLogger(__name__)

class LLMProvider(str, Enum):
    OPENAI = "openai"
    GROK = "grok"

    @classmethod
    def from_label(cls, label: str) -> "LLMProvider":
        normalized = (label or "").strip().lower()
        if normalized in {"grok", "gork", "xai"}:
            return cls.GROK
        return cls.OPENAI


@dataclass
class ProviderConfig:
    api_key: str
    model: str
    base_url: str


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def generate_card(
        self,
        provider: LLMProvider,
        user_payload: str,
        on_stream: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, Dict[str, Union[int, float]]]:
        config = self._config_for(provider)
        if not config.api_key:
            raise ValueError(f"{provider.value} API key 尚未設定")

        lc_messages, http_messages = self._build_messages(user_payload)
        logger.info("LLM 呼叫開始 provider=%s model=%s", provider.value, config.model)

        if provider is LLMProvider.OPENAI:
            result_text, usage = await self._call_openai(lc_messages, config, on_stream)
        else:
            result_text, usage = await self._call_grok(http_messages, config, on_stream)

        logger.info(
            "LLM 呼叫結束 provider=%s total_tokens=%s prompt_tokens=%s completion_tokens=%s",
            provider.value,
            usage.get("total_tokens"),
            usage.get("input_tokens") or usage.get("prompt_tokens"),
            usage.get("output_tokens") or usage.get("completion_tokens"),
        )
        return result_text.strip(), usage

    def _config_for(self, provider: LLMProvider) -> ProviderConfig:
        if provider is LLMProvider.OPENAI:
            return ProviderConfig(
                api_key=self.settings.openai_api_key,
                model=self.settings.openai_model,
                base_url=self.settings.openai_base_url,
            )
        return ProviderConfig(
            api_key=self.settings.xai_api_key,
            model=self.settings.xai_model,
            base_url=self.settings.xai_base_url,
        )

    async def _call_openai(
        self,
        messages: List[SystemMessage | HumanMessage],
        config: ProviderConfig,
        on_stream: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, Dict[str, Union[int, float]]]:
        model = self._build_openai_model(config)
        chunks: List[str] = []
        usage: Dict[str, Union[int, float]] = {}
        buffer = ""
        try:
            async for event in model.astream_events(messages, version="v1"):
                if event["event"] == "on_chat_model_stream":
                    chunk: AIMessageChunk = event["data"]["chunk"]
                    text = self._chunk_to_text(chunk)
                    if text:
                        chunks.append(text)
                        if on_stream:
                            on_stream(text)
                        buffer = self._stream_to_console(buffer, text)
                elif event["event"] == "on_chat_model_end":
                    output = event["data"]["output"]
                    if output.usage_metadata:
                        usage = {
                            key: value
                            for key, value in output.usage_metadata.items()
                            if value is not None
                        }
        except Exception as exc:  # noqa: BLE001
            logger.exception("OpenAI 呼叫失敗")
            raise ValueError(f"OpenAI 呼叫失敗: {exc}") from exc
        finally:
            self._flush_stream_buffer(buffer)
        return "".join(chunks), usage

    async def _call_grok(
        self,
        messages: List[Dict[str, str]],
        config: ProviderConfig,
        on_stream: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, Dict[str, Union[int, float]]]:
        url = f"{config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": config.model,
            "messages": messages,
            "temperature": 0.3,
            "stream": True,
        }
        chunks: List[str] = []
        usage: Dict[str, Union[int, float]] = {}
        buffer = ""

        async with httpx.AsyncClient(timeout=self.settings.request_timeout) as client:
            try:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        detail = await response.aread()
                        raise ValueError(
                            f"Grok API 錯誤 {response.status_code}: {detail.decode(errors='ignore')}"
                        )
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line.split("data:", 1)[1].strip()
                        if not data_str:
                            continue
                        if data_str == "[DONE]":
                            break
                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        delta = ""
                        choices = event.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta", {}).get("content") or ""
                        if delta:
                            chunks.append(delta)
                            if on_stream:
                                on_stream(delta)
                            buffer = self._stream_to_console(buffer, delta)
                        if "usage" in event and event["usage"]:
                            usage = {
                                key: value
                                for key, value in event["usage"].items()
                                if value is not None
                            }
            except Exception as exc:  # noqa: BLE001
                logger.exception("Grok API 呼叫失敗")
                raise ValueError(f"Grok API 呼叫失敗: {exc}") from exc
            finally:
                self._flush_stream_buffer(buffer)

        return "".join(chunks), usage

    def _build_openai_model(self, config: ProviderConfig) -> ChatOpenAI:
        return ChatOpenAI(
            api_key=config.api_key,
            model=config.model,
            base_url=config.base_url,
            temperature=0.3,
            timeout=self.settings.request_timeout,
            max_retries=2,
            streaming=True,
            model_kwargs={"response_format": {"type": "json_object"}},
        )

    def _build_messages(
        self, payload: str
    ) -> Tuple[List[SystemMessage | HumanMessage], List[Dict[str, str]]]:
        system_content = build_system_prompt()
        user_content = build_user_prompt(payload)
        lc_messages: List[SystemMessage | HumanMessage] = [
            SystemMessage(content=system_content),
            HumanMessage(content=user_content),
        ]
        http_messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ]
        return lc_messages, http_messages

    def _chunk_to_text(self, chunk: AIMessageChunk) -> str:
        content: Union[str, List[Dict[str, str]]] = chunk.content
        if isinstance(content, str):
            return content
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )

    def _stream_to_console(self, buffer: str, text: str) -> str:
        if not self.settings.stream_console_enabled:
            return ""
        buffer += text
        threshold = max(20, self.settings.stream_buffer_chars)
        if "\n" in buffer or len(buffer) >= threshold:
            print(buffer, end="", flush=True)
            return ""
        return buffer

    def _flush_stream_buffer(self, buffer: str) -> None:
        if self.settings.stream_console_enabled and buffer:
            print(buffer, flush=True)

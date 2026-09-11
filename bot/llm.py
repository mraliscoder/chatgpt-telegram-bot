"""OpenAI chat completions with streaming."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from .config import Settings
from .db import HistoryItem

log = logging.getLogger(__name__)


class LLM:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            timeout=settings.request_timeout,
        )

    def build_messages(
        self,
        history: list[HistoryItem],
        *,
        chat_title: str | None = None,
    ) -> list[dict[str, str]]:
        system = self.settings.system_prompt
        if chat_title:
            system += f"\nНазвание чата: {chat_title}."

        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        for item in history:
            if item.role == "assistant":
                messages.append({"role": "assistant", "content": item.text})
            else:
                # Prefix with the author so the model can tell participants apart.
                prefix = f"{item.name}: " if item.name else ""
                messages.append({"role": "user", "content": f"{prefix}{item.text}"})
        return messages

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str]:
        """Yield response text deltas as they arrive."""
        stream = await self.client.chat.completions.create(
            model=self.settings.model,
            messages=messages,
            temperature=self.settings.temperature,
            max_tokens=self.settings.max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    async def close(self) -> None:
        await self.client.close()

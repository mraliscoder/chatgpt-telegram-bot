"""Streams text into a Telegram message, editing it as the text grows."""

from __future__ import annotations

import asyncio
import logging

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import Message

log = logging.getLogger(__name__)

# Telegram's hard limit is 4096 characters; leave room for the cursor.
PART_LIMIT = 3800


class Typewriter:
    """Renders a growing string into one (or more) Telegram messages.

    Deltas are pushed in with :meth:`feed`; a background task edits the
    message at most once per ``interval`` seconds, which keeps us well
    inside Telegram's edit rate limits while still looking like typing.
    """

    def __init__(
        self,
        origin: Message,
        *,
        interval: float = 1.1,
        min_delta: int = 24,
        cursor: str = "▍",
        placeholder: str = "…",
    ) -> None:
        self._origin = origin
        self._interval = interval
        self._min_delta = min_delta
        self._cursor = cursor
        self._placeholder = placeholder

        self._buffer = ""
        self._offset = 0           # where the current message's slice starts
        self._last_tail = ""       # text last pushed to the current message
        self._rendered = ""        # exact string currently shown (cursor included)
        self._message: Message | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()

        self.message_ids: list[int] = []

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        self._message = await self._origin.reply(self._placeholder)
        self._rendered = self._placeholder
        self.message_ids.append(self._message.message_id)
        self._task = asyncio.create_task(self._ticker(), name="typewriter")

    def feed(self, delta: str) -> None:
        self._buffer += delta

    @property
    def text(self) -> str:
        return self._buffer

    async def finish(self, fallback: str = "") -> None:
        """Stop ticking and render the final state exactly once."""
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        if not self._buffer.strip():
            self._buffer = fallback or "🤷 Модель вернула пустой ответ."
        async with self._lock:
            await self._flush(final=True)

    async def fail(self, text: str) -> None:
        """Abort the stream and show an error instead."""
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        async with self._lock:
            if self._buffer.strip():
                self._buffer = f"{self._buffer.rstrip()}\n\n⚠️ {text}"
            else:
                self._buffer = f"⚠️ {text}"
            await self._flush(final=True)

    # ------------------------------------------------------------------ internals

    async def _ticker(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                return  # stop requested
            except asyncio.TimeoutError:
                pass
            try:
                async with self._lock:
                    await self._flush(final=False)
            except asyncio.CancelledError:
                raise
            except Exception:  # never let the ticker kill the response
                log.exception("typewriter flush failed")

    async def _flush(self, *, final: bool) -> None:
        if self._message is None:
            return

        text = self._buffer

        # Overflow: seal the current message and continue in a new one.
        while len(text) - self._offset > PART_LIMIT:
            cut = self._cut_point(text, self._offset)
            await self._edit(text[self._offset : cut].rstrip())
            self._offset = cut
            self._last_tail = ""
            self._rendered = ""
            self._message = await self._origin.answer(self._placeholder)
            self._rendered = self._placeholder
            self.message_ids.append(self._message.message_id)

        tail = text[self._offset :]
        if not final:
            if not tail.strip():
                return
            if len(tail) - len(self._last_tail) < self._min_delta:
                return
            body = tail + self._cursor
        else:
            body = tail.strip()
            if not body:
                return

        self._last_tail = tail
        await self._edit(body)

    @staticmethod
    def _cut_point(text: str, offset: int) -> int:
        """Pick a readable split point inside ``text[offset:offset + PART_LIMIT]``."""
        window = text[offset : offset + PART_LIMIT]
        floor = PART_LIMIT // 2
        for separator in ("\n\n", "\n", ". ", " "):
            position = window.rfind(separator)
            if position >= floor:
                return offset + position + len(separator)
        return offset + PART_LIMIT

    async def _edit(self, body: str) -> None:
        if self._message is None or body == self._rendered:
            return
        for attempt in range(3):
            try:
                await self._message.edit_text(body)
                self._rendered = body
                return
            except TelegramRetryAfter as exc:
                # Back off and permanently slow down: the chat is rate limited.
                self._interval = max(self._interval, float(exc.retry_after) + 0.5)
                log.warning(
                    "rate limited, sleeping %ss (interval -> %.1fs)",
                    exc.retry_after,
                    self._interval,
                )
                await asyncio.sleep(exc.retry_after + 0.2)
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc).lower():
                    self._rendered = body
                    return
                log.warning("edit failed (attempt %s): %s", attempt + 1, exc)
                return

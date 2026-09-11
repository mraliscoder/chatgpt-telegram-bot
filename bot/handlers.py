"""Telegram update handlers."""

from __future__ import annotations

import asyncio
import logging
import re
from collections import defaultdict

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from .config import Settings
from .db import Database
from .llm import LLM
from .typewriter import Typewriter

log = logging.getLogger(__name__)

router = Router(name="chat")

# One in-flight answer per chat, so concurrent questions do not interleave.
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


def build_trigger(prefixes: tuple[str, ...]) -> re.Pattern[str]:
    """Match '<prefix> <question>' at the very start of a message."""
    alternatives = "|".join(re.escape(p) for p in prefixes)
    return re.compile(
        rf"^\s*(?:{alternatives})(?:[\s,.:;!?—–-]+(?P<query>.*))?$",
        re.IGNORECASE | re.DOTALL,
    )


def author_name(message: Message) -> str:
    user = message.from_user
    if user is None:
        return message.chat.title or "Аноним"
    return user.full_name or user.username or str(user.id)


def message_text(message: Message) -> str:
    return message.text or message.caption or ""


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings) -> None:
    prefix = settings.trigger_prefixes[0]
    await message.reply(
        "Привет! Я отвечаю на сообщения, которые начинаются с "
        f"«{prefix} ».\n\n"
        f"Например: {prefix} что приготовить из гречки?\n\n"
        "Я читаю последние сообщения чата, чтобы понимать контекст.\n\n"
        "Команды:\n"
        "/clear_history — забыть историю этого чата\n"
        "/help — эта справка"
    )


@router.message(Command("clear_history"))
async def cmd_clear_history(message: Message, db: Database, settings: Settings) -> None:
    if settings.clear_requires_admin and message.chat.type in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        member = await message.bot.get_chat_member(
            message.chat.id, message.from_user.id
        )
        if member.status not in ("creator", "administrator"):
            await message.reply("Очистить историю может только администратор чата.")
            return

    removed = await db.clear_history(message.chat.id)
    await message.reply(f"🧹 История очищена, удалено сообщений: {removed}.")


@router.message(F.text | F.caption)
async def on_message(message: Message, db: Database, llm: LLM, settings: Settings) -> None:
    text = message_text(message)
    if not text.strip():
        return

    trigger = build_trigger(settings.trigger_prefixes)
    match = trigger.match(text)

    # Remember everything we are allowed to see, so the bot has context later.
    if settings.log_all_messages or match:
        await db.add_message(
            chat_id=message.chat.id,
            role="user",
            text=text,
            message_id=message.message_id,
            user_id=message.from_user.id if message.from_user else None,
            name=author_name(message),
        )

    if not match:
        return

    query = (match.group("query") or "").strip()
    quoted = message.reply_to_message
    if not query and not quoted:
        await message.reply(
            f"Напиши вопрос после «{settings.trigger_prefixes[0]} » "
            "или ответь этой командой на чьё-нибудь сообщение."
        )
        return

    async with _locks[message.chat.id]:
        await answer(message, db, llm, settings)


async def answer(message: Message, db: Database, llm: LLM, settings: Settings) -> None:
    history = await db.get_history(
        message.chat.id, settings.history_limit, settings.history_max_chars
    )
    messages = llm.build_messages(history, chat_title=message.chat.title)

    quoted = message.reply_to_message
    if quoted is not None:
        quoted_text = message_text(quoted).strip()
        if quoted_text:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Последняя реплика — ответ на сообщение "
                        f"{author_name(quoted)}: «{quoted_text[:2000]}»"
                    ),
                }
            )

    writer = Typewriter(
        message,
        interval=settings.edit_interval,
        min_delta=settings.min_delta_chars,
        cursor=settings.cursor,
    )
    await writer.start()

    try:
        async for delta in llm.stream(messages):
            writer.feed(delta)
        await writer.finish()
    except Exception as exc:  # noqa: BLE001 — surface any API failure to the chat
        log.exception("generation failed in chat %s", message.chat.id)
        await writer.fail(f"Не получилось ответить: {type(exc).__name__}")
        return

    reply_text = writer.text.strip()
    if reply_text:
        await db.add_message(
            chat_id=message.chat.id,
            role="assistant",
            text=reply_text,
            message_id=writer.message_ids[0] if writer.message_ids else None,
        )

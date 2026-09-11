"""Entry point: wires config, storage, OpenAI and the Telegram polling loop."""

from __future__ import annotations

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from .config import Settings
from .db import Database
from .handlers import router
from .llm import LLM

log = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def run() -> None:
    settings = Settings.from_env()

    db = Database(settings.db_path)
    await db.connect()

    llm = LLM(settings)
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=None),
    )

    dispatcher = Dispatcher()
    dispatcher["db"] = db
    dispatcher["llm"] = llm
    dispatcher["settings"] = settings
    dispatcher.include_router(router)

    me = await bot.get_me()
    log.info(
        "starting @%s | model=%s | triggers=%s",
        me.username,
        settings.model,
        ", ".join(settings.trigger_prefixes),
    )

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(
            bot, allowed_updates=dispatcher.resolve_used_update_types()
        )
    finally:
        await llm.close()
        await db.close()
        await bot.session.close()


def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # dotenv is optional in production
        pass
    setup_logging()
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        log.info("stopped")


if __name__ == "__main__":
    main()

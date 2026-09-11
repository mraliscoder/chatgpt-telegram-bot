"""Drives real Updates through the real Dispatcher with a fake Telegram transport."""
import asyncio, os, sys, tempfile
from datetime import datetime, timezone

os.environ["TELEGRAM_BOT_TOKEN"] = "123:abc"
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["TYPEWRITER_INTERVAL"] = "0.05"
os.environ["TYPEWRITER_MIN_CHARS"] = "2"
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "it.db")

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.types import Chat, Message, Update, User

from bot.config import Settings
from bot.db import Database
from bot.handlers import router
from bot.llm import LLM

failures = []
def check(label, cond):
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond: failures.append(label)

sent, edited = [], []
BOT_USER = User(id=42, is_bot=True, first_name="AI", username="ai_bot")
CHAT = Chat(id=-1001, type="supergroup", title="Тестовый чат")
USER = User(id=7, is_bot=False, first_name="Эдуард")
NOW = datetime.now(timezone.utc)

class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self._next_id = 1000
    async def make_request(self, bot, method, timeout=None):
        name = type(method).__name__
        if name == "GetMe":
            return BOT_USER
        if name == "SendMessage":
            self._next_id += 1
            sent.append((self._next_id, method.text))
            return Message(message_id=self._next_id, date=NOW, chat=CHAT,
                           from_user=BOT_USER, text=method.text).as_(bot)
        if name == "EditMessageText":
            edited.append((method.message_id, method.text))
            return Message(message_id=method.message_id, date=NOW, chat=CHAT,
                           from_user=BOT_USER, text=method.text).as_(bot)
        raise AssertionError(f"unexpected API call: {name}")
    async def stream_content(self, *a, **kw):
        yield b""
    async def close(self):
        pass

CHUNKS = ["Конечно", ", ", "вот ", "ответ ", "на ", "твой ", "вопрос", "."]
async def fake_stream(self, messages):
    fake_stream.last = messages
    for chunk in CHUNKS:
        await asyncio.sleep(0.03)
        yield chunk
LLM.stream = fake_stream

def update(uid, text, from_user=USER):
    return Update(update_id=uid, message=Message(
        message_id=uid, date=NOW, chat=CHAT, from_user=from_user, text=text))

async def main():
    settings = Settings.from_env()
    db = Database(settings.db_path)
    await db.connect()
    bot = Bot(token=settings.bot_token, session=FakeSession(),
              default=DefaultBotProperties(parse_mode=None))
    dp = Dispatcher()
    dp["db"], dp["llm"], dp["settings"] = db, LLM(settings), settings
    dp.include_router(router)

    check("resolve_used_update_types works", "message" in dp.resolve_used_update_types())

    print("plain message (context only):")
    await dp.feed_update(bot, update(1, "ребята, го в кино"))
    check("no reply sent", not sent)
    check("logged to history", await db.count(CHAT.id) == 1)

    print("triggered message:")
    await dp.feed_update(bot, update(2, "ии посоветуй фильм"))
    check("placeholder + no extra messages", len(sent) == 1)
    check("streamed with several edits", len(edited) >= 3)
    check("final text complete", edited[-1][1] == "".join(CHUNKS))
    check("cursor gone at the end", not edited[-1][1].endswith(settings.cursor))
    check("edits target the placeholder", all(e[0] == sent[0][0] for e in edited))

    prompt = fake_stream.last
    check("system prompt present", prompt[0]["role"] == "system")
    check("context includes earlier chat message",
          any("Эдуард: ребята, го в кино" == m["content"] for m in prompt))
    check("question is the last turn",
          prompt[-1]["content"] == "Эдуард: ии посоветуй фильм")
    check("answer stored as assistant", await db.count(CHAT.id) == 3)

    print("second question sees the answer:")
    edited.clear(); sent.clear()
    await dp.feed_update(bot, update(3, "ии а ещё?"))
    prompt = fake_stream.last
    check("assistant turn replayed",
          {"role": "assistant", "content": "".join(CHUNKS)} in prompt)

    print("/clear_history:")
    sent.clear()
    await dp.feed_update(bot, update(4, "/clear_history"))
    check("history wiped", await db.count(CHAT.id) == 0)
    check("confirmation sent", sent and "История очищена" in sent[0][1])

    print("/help:")
    sent.clear()
    await dp.feed_update(bot, update(5, "/help"))
    check("help sent", sent and "ии " in sent[0][1])
    check("help not logged", await db.count(CHAT.id) == 0)

    print("bare trigger without reply:")
    sent.clear()
    await dp.feed_update(bot, update(6, "ии"))
    check("asks for a question", sent and "Напиши вопрос" in sent[0][1])

    print("API failure:")
    async def boom(self, messages):
        raise RuntimeError("boom")
        yield
    LLM.stream = boom
    sent.clear(); edited.clear()
    await dp.feed_update(bot, update(7, "ии сломайся"))
    check("error shown in chat", edited and "Не получилось ответить" in edited[-1][1])
    check("failed answer not stored",
          all("RuntimeError" not in h.text for h in await db.get_history(CHAT.id, 50, 99999)))

    await db.close()

asyncio.run(main())
print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILURES: {failures}"))
sys.exit(1 if failures else 0)

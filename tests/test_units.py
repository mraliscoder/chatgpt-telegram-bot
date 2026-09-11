"""Offline smoke test: trigger matching, history store, typewriter rendering."""
import asyncio, os, sys, tempfile

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "x")
os.environ.setdefault("OPENAI_API_KEY", "x")

from bot.config import Settings
from bot.db import Database
from bot.handlers import build_trigger
from bot.llm import LLM
from bot.typewriter import Typewriter, PART_LIMIT

failures = []
def check(label, cond):
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond: failures.append(label)

# ---------------------------------------------------------------- trigger
t = build_trigger(("ии", "ai"))
cases = [
    ("ии привет", "привет"),
    ("ИИ, как дела?", "как дела?"),
    ("ии: расскажи\nанекдот", "расскажи\nанекдот"),
    ("  ии — что это", "что это"),
    ("ai hello there", "hello there"),
    ("ии", ""),
]
print("trigger matches:")
for text, expected in cases:
    m = t.match(text)
    got = (m.group("query") or "").strip() if m else None
    check(f"{text!r} -> {got!r}", got == expected)
print("trigger non-matches:")
for text in ["иии привет", "привет ии", "иипривет", "мои идеи", "/clear_history"]:
    check(f"{text!r} ignored", t.match(text) is None)

# ---------------------------------------------------------------- database
async def test_db():
    print("database:")
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    db = Database(path)
    await db.connect()
    for i in range(5):
        await db.add_message(chat_id=1, role="user", text=f"msg{i}", name=f"user{i}")
    await db.add_message(chat_id=1, role="assistant", text="ответ")
    await db.add_message(chat_id=2, role="user", text="другой чат", name="z")

    hist = await db.get_history(1, limit=10, max_chars=10_000)
    check("ordered oldest-first", [h.text for h in hist] == ["msg0","msg1","msg2","msg3","msg4","ответ"])
    check("chats isolated", len(await db.get_history(2, 10, 10_000)) == 1)

    limited = await db.get_history(1, limit=2, max_chars=10_000)
    check("respects limit", [h.text for h in limited] == ["msg4", "ответ"])

    trimmed = await db.get_history(1, limit=10, max_chars=12)
    check("respects char budget", 0 < len(trimmed) < 6)

    # prompt assembly
    s = Settings.from_env()
    llm = LLM(s)
    msgs = llm.build_messages(hist, chat_title="Чат")
    check("system first", msgs[0]["role"] == "system" and "Чат" in msgs[0]["content"])
    check("named user turns", msgs[1] == {"role": "user", "content": "user0: msg0"})
    check("assistant turn unnamed", msgs[-1] == {"role": "assistant", "content": "ответ"})
    await llm.close()

    removed = await db.clear_history(1)
    check("clear removes own chat", removed == 6 and await db.count(1) == 0)
    check("clear keeps other chat", await db.count(2) == 1)
    await db.close()

# ---------------------------------------------------------------- typewriter
class FakeMsg:
    def __init__(self, log, mid):
        self.log, self.message_id = log, mid
        self.text = None
    async def edit_text(self, text):
        self.text = text
        self.log.append(("edit", self.message_id, text))
    async def reply(self, text):
        return self._new(text, "reply")
    async def answer(self, text):
        return self._new(text, "answer")
    def _new(self, text, kind):
        self.log.append((kind, text))
        m = FakeMsg(self.log, len(self.log) + 100)
        m.text = text
        return m

async def test_typewriter():
    print("typewriter:")
    log = []
    origin = FakeMsg(log, 1)
    w = Typewriter(origin, interval=0.05, min_delta=3, cursor="|")
    await w.start()
    for word in ["Привет", ", ", "как ", "дела", "?"]:
        w.feed(word)
        await asyncio.sleep(0.06)
    await w.finish()
    edits = [e[2] for e in log if e[0] == "edit"]
    check("placeholder sent first", log[0][0] == "reply")
    check("intermediate edits happened", len(edits) >= 2)
    check("cursor shown while typing", all(e.endswith("|") for e in edits[:-1]))
    check("final text clean", edits[-1] == "Привет, как дела?")
    check("one message used", w.message_ids == [101])

    print("typewriter (overflow + empty + error):")
    log2 = []
    w2 = Typewriter(FakeMsg(log2, 1), interval=5, min_delta=1, cursor="|")
    await w2.start()
    w2.feed(("слово " * 1200))   # ~7200 chars -> two messages
    await w2.finish()
    parts = {}
    for entry in log2:
        if entry[0] == "edit":
            parts[entry[1]] = entry[2]
    check("split into two messages", len(w2.message_ids) == 2)
    check("each part within limit", all(len(p) <= PART_LIMIT for p in parts.values()))
    check("no text lost", "".join(parts[m] for m in w2.message_ids).replace(" ", "")
          == w2.text.replace(" ", ""))

    log3 = []
    w3 = Typewriter(FakeMsg(log3, 1), interval=5)
    await w3.start()
    await w3.finish()
    check("empty answer gets fallback", "пустой" in [e[2] for e in log3 if e[0]=="edit"][-1])

    log4 = []
    w4 = Typewriter(FakeMsg(log4, 1), interval=5)
    await w4.start()
    w4.feed("частичный ответ")
    await w4.fail("APIError")
    last = [e[2] for e in log4 if e[0] == "edit"][-1]
    check("error keeps partial text", last.startswith("частичный ответ") and "APIError" in last)

async def main():
    await test_db()
    await test_typewriter()

asyncio.run(main())
print("\n" + ("ALL PASS" if not failures else f"{len(failures)} FAILURES: {failures}"))
sys.exit(1 if failures else 0)

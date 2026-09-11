# Telegram AI bot

A group-chat bot that answers messages starting with **`ии `** using the OpenAI API.

* **Wake word** — any message beginning with `ии ` (configurable) gets an answer.
  Replying to someone with a bare `ии` uses that message as the subject.
* **Memory** — every message the bot can see is logged to SQLite and the last
  `HISTORY_LIMIT` of them are sent to the model as context, in `Name: text` form.
* **`/clear_history`** — wipes the stored history for the current chat.
* **Typewriter effect** — the reply is streamed from OpenAI and the Telegram
  message is edited about once a second, with a `▍` cursor at the end.
  Answers longer than 4096 characters continue in a follow-up message.
* **Dockerized** — `docker compose up -d`, history persisted in `./data`.

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. **Turn Privacy Mode off**: BotFather → `/mybots` → your bot → *Bot Settings* →
   *Group Privacy* → **Turn off**. Without this Telegram only delivers commands
   and replies to the bot, so the bot cannot see (or remember) normal chat
   messages. Re-add the bot to the group after changing this.
3. Add the bot to the group.

```bash
cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN and OPENAI_API_KEY
```

## Run with Docker

```bash
docker compose up -d --build
docker compose logs -f
```

The SQLite database lives in `./data/bot.db` on the host, so history survives
restarts and rebuilds.

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m bot.main
```

## Configuration

All settings are environment variables; see `.env.example` for the full list
with defaults. The ones worth knowing:

| Variable | Default | Meaning |
| --- | --- | --- |
| `TRIGGER_PREFIXES` | `ии` | Comma-separated wake words, e.g. `ии,ai,бот` |
| `OPENAI_MODEL` | `gpt-4o-mini` | Any chat-completions model |
| `OPENAI_BASE_URL` | — | Point at a proxy or OpenAI-compatible API |
| `SYSTEM_PROMPT` | see `bot/config.py` | The bot's persona |
| `HISTORY_LIMIT` | `40` | Messages of context per request |
| `LOG_ALL_MESSAGES` | `true` | Log non-triggering messages too |
| `CLEAR_REQUIRES_ADMIN` | `false` | Restrict `/clear_history` to admins |
| `TYPEWRITER_INTERVAL` | `1.1` | Seconds between edits — don't go below 1.0 |

## Tests

No pytest, no network, no Telegram token needed — see `tests/README.md`:

```bash
docker run --rm -v "$PWD/tests:/app/tests" telegram-ai-bot python tests/test_units.py
docker run --rm -v "$PWD/tests:/app/tests" telegram-ai-bot python tests/test_integration.py
```

## Layout

```
bot/
  config.py      environment-driven settings
  db.py          SQLite history (aiosqlite)
  llm.py         OpenAI streaming client, prompt assembly
  typewriter.py  incremental message editing, rate limits, 4096-char splitting
  handlers.py    trigger matching, logging, /clear_history
  main.py        entry point
tests/           unit + dispatcher-level integration scripts
```

## Notes

* Replies are sent as plain text — models like to emit Markdown, which Telegram
  would show literally or reject; the default system prompt asks the model not
  to use it.
* Telegram rate-limits edits per chat. On a `retry_after` the bot backs off and
  permanently slows its edit interval for the rest of that answer.
* One answer at a time per chat: concurrent questions queue behind a per-chat
  lock so their edits don't interleave.

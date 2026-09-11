Dependency-free test scripts (no pytest, no network, no Telegram token).

```bash
docker build -t telegram-ai-bot .
docker run --rm -v "$PWD/tests:/app/tests" telegram-ai-bot python tests/test_units.py
docker run --rm -v "$PWD/tests:/app/tests" telegram-ai-bot python tests/test_integration.py
```

`test_units.py` covers trigger matching, the SQLite history store, prompt
assembly and the typewriter (edits, cursor, 4096-char splitting, empty answer,
mid-stream failure).

`test_integration.py` feeds real `Update` objects through the real aiogram
`Dispatcher` with a stubbed Telegram transport and a stubbed OpenAI stream.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/bot.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

RUN useradd --create-home --uid 10001 botuser \
    && mkdir -p /data \
    && chown -R botuser:botuser /data /app
USER botuser

VOLUME ["/data"]

CMD ["python", "-m", "bot.main"]

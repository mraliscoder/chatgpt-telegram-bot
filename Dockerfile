FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/bot.db

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN useradd --create-home --uid 10001 botuser \
    && mkdir -p /data \
    && chown -R botuser:botuser /data /app \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

VOLUME ["/data"]

# Starts as root only to chown the data volume, then runs as botuser.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "bot.main"]

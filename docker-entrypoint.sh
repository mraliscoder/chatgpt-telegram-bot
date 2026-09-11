#!/bin/sh
# Bind-mounted volumes keep the host's ownership, which is usually root, while
# the bot runs as an unprivileged user. Fix the data dir, then drop privileges.
set -e

DB_DIR=$(dirname "${DB_PATH:-/data/bot.db}")
mkdir -p "$DB_DIR"

if [ "$(id -u)" = "0" ]; then
    chown -R botuser:botuser "$DB_DIR" 2>/dev/null || true
    exec setpriv --reuid=botuser --regid=botuser --init-groups "$@"
fi

exec "$@"

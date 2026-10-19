#!/usr/bin/env sh
# Deletes Open WebUI chats that nobody touched for CHAT_RETENTION_DAYS days (default 90).
# CHAT_RETENTION_DAYS comes from the shell environment, else from .env. It must be 1 or more.
# Open WebUI has no built-in chat retention. Without --apply it only counts.
#
#   scripts/purge-chats.sh            # how many chats would go
#   scripts/purge-chats.sh --apply    # delete them
#
# Cron on the Docker host, daily at 03:30:
#   30 3 * * * cd /opt/llm-gateway && scripts/purge-chats.sh --apply >> /var/log/purge-chats.log 2>&1
#
# Deleted with each chat: messages, chat-file links, share links, tags.
# Not deleted: uploaded files and their search index (Admin Panel > Settings > Documents,
# or the file list per user). LiteLLM spend logs have their own retention in config.yaml.
set -eu
cd "$(dirname "$0")/.."

if [ -z "${CHAT_RETENTION_DAYS:-}" ] && [ -f .env ] && grep -q '^CHAT_RETENTION_DAYS=' .env; then
  # Accepts 30, "30", '30' and a trailing comment. Anything else is an error, not the default.
  CHAT_RETENTION_DAYS=$(grep '^CHAT_RETENTION_DAYS=' .env | tail -n 1 |
    sed -n "s/^CHAT_RETENTION_DAYS=[\"']\{0,1\}\([0-9][0-9]*\)[\"']\{0,1\}[[:space:]]*\(#.*\)\{0,1\}$/\1/p")
  if [ -z "$CHAT_RETENTION_DAYS" ]; then
    echo "CHAT_RETENTION_DAYS in .env is not a whole number" >&2
    exit 1
  fi
fi
DAYS="${CHAT_RETENTION_DAYS:-90}"
case "$DAYS" in ''|*[!0-9]*) echo "CHAT_RETENTION_DAYS must be a whole number" >&2; exit 1 ;; esac
DAYS=$(expr "$DAYS" + 0 || true)
if [ "$DAYS" -lt 1 ]; then
  echo "CHAT_RETENTION_DAYS must be 1 or more (0 would delete every chat)" >&2
  exit 1
fi

psql_owui() {
  docker compose exec -T postgres psql -U llm -d openwebui -v ON_ERROR_STOP=1 -qtA "$@"
}

CUTOFF="extract(epoch from now() - interval '$DAYS days')::bigint"
COUNT=$(psql_owui -c "SELECT count(*) FROM chat WHERE updated_at < $CUTOFF;")

if [ "${1:-}" != "--apply" ]; then
  echo "$COUNT chats older than $DAYS days. Run with --apply to delete them."
  exit 0
fi

psql_owui <<SQL
BEGIN;
DELETE FROM chatidtag WHERE chat_id IN (SELECT id FROM chat WHERE updated_at < $CUTOFF);
DELETE FROM chat WHERE updated_at < $CUTOFF;
COMMIT;
SQL
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) deleted $COUNT chats older than $DAYS days"

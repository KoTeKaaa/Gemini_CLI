#!/usr/bin/env bash
# Disposable local PostgreSQL; no host port, provider requests or production DDL.
set -euo pipefail
cd "$(dirname "$0")/../.."
container_name="codex-history-test-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:10])')"
export POSTGRES_PASSWORD
POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
cleanup() { podman rm -f --volumes "$container_name" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM
podman run --detach --name "$container_name" --env POSTGRES_PASSWORD \
    docker.io/library/postgres:17 >/dev/null
for attempt in {1..60}; do
    # The init-only server accepts Unix sockets before restarting. TCP is final.
    if podman exec "$container_name" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; then break; fi
    if (( attempt == 60 )); then echo 'PostgreSQL readiness timed out' >&2; exit 1; fi
    sleep 1
done
sql() { podman exec -i "$container_name" psql -X -U postgres -v ON_ERROR_STOP=1 "$@"; }
sql < supabase/tests/history_baseline.sql >/dev/null
# Deliberately reverse insertion order for equal-time legacy messages.
sql >/dev/null <<'SQL'
insert into auth.users values ('00000000-0000-0000-0000-000000000091');
insert into public.chats(id,user_id,title) values
    ('00000000-0000-0000-0000-000000000091','00000000-0000-0000-0000-000000000091','legacy');
insert into public.messages(id,chat_id,role,content,created_at) values
    ('00000000-0000-0000-0000-000000000092','00000000-0000-0000-0000-000000000091','user','same','2000-01-01T00:00:00Z'),
    ('00000000-0000-0000-0000-000000000091','00000000-0000-0000-0000-000000000091','user','same','2000-01-01T00:00:00Z');
SQL
sql < deploy/history_events.sql >/dev/null
sql >/dev/null <<'SQL'
do $$ begin
    if (select array_agg(id order by sequence) from public.messages) <>
       array['00000000-0000-0000-0000-000000000091'::uuid,'00000000-0000-0000-0000-000000000092'::uuid]
       or exists (select 1 from public.messages where status <> 'legacy') then
        raise exception 'deterministic legacy backfill failed';
    end if;
end $$;
SQL
sql < supabase/tests/history_events.sql >/dev/null
# Also exercise empty-table migration and identity initialization independently.
sql -c 'create database empty_history' >/dev/null
sql -d empty_history < supabase/tests/history_baseline.sql >/dev/null
sql -d empty_history < deploy/history_events.sql >/dev/null
sql -d empty_history < supabase/tests/history_events.sql >/dev/null
echo 'PASS: PostgreSQL 17 populated/empty migration, legacy ordering, identity, RLS and provenance'

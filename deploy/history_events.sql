-- Planned S4.1 migration. Generate its canonical filename with Supabase CLI.
begin;

-- ALTER holds an exclusive lock until commit; legacy inserts cannot race backfill.
alter table public.messages
    add column turn_id uuid,
    add column request_id uuid,
    add column event_index integer check (event_index >= 0),
    add column status text not null default 'legacy'
        check (status in ('legacy', 'running', 'completed', 'cancelled', 'failed')),
    add column call_id text,
    add column thought_signature text,
    add column sequence bigint;

create sequence public.message_event_sequence;
alter sequence public.message_event_sequence owned by public.messages.sequence;
with ordered as (
    select id, row_number() over (order by created_at, id) as position
    from public.messages
)
update public.messages m set sequence = ordered.position from ordered where m.id = ordered.id;
select setval('public.message_event_sequence', coalesce(max(sequence), 1), count(*) > 0)
    from public.messages;
alter table public.messages
    alter column sequence set default nextval('public.message_event_sequence'),
    alter column sequence set not null;
create unique index messages_sequence_idx on public.messages(sequence);
create unique index messages_request_event_idx
    on public.messages(chat_id, request_id, event_index);
create index messages_chat_sequence_idx on public.messages(chat_id, sequence);
alter table public.messages add constraint messages_chat_event_unique unique (chat_id, id);

alter table public.chats
    add column summary text,
    add column summary_boundary uuid,
    add column fork_parent_id uuid,
    add column fork_boundary uuid,
    add constraint chats_owner_identity unique (id, user_id),
    add constraint chats_summary_pair check ((summary is null) = (summary_boundary is null)),
    add constraint chats_summary_boundary foreign key (id, summary_boundary)
        references public.messages(chat_id, id) deferrable initially deferred;
alter table public.chats
    add constraint chats_fork_owner foreign key (fork_parent_id, user_id)
        references public.chats(id, user_id) on delete set null (fork_parent_id),
    add constraint chats_fork_boundary foreign key (fork_parent_id, fork_boundary)
        references public.messages(chat_id, id) on delete set null (fork_boundary)
        deferrable initially deferred;
create index chats_fork_parent_idx on public.chats(fork_parent_id);

-- Existing authenticated ownership policies remain in force. Anonymous messages
-- access was a permissive exception; signed-in legacy clients do not require it.
drop policy if exists "Allow anon insert to messages" on public.messages;
drop policy if exists "Allow anon select from messages" on public.messages;
revoke all on public.messages from public, anon;
revoke all on sequence public.message_event_sequence from public, anon;
grant usage, select on sequence public.message_event_sequence to authenticated, service_role;

commit;

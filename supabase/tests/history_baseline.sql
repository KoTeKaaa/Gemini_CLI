-- Synthetic pre-S4 schema for disposable PostgreSQL only; never production.
do $$ begin
    if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
    if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
    if not exists (select 1 from pg_roles where rolname = 'service_role') then create role service_role nologin bypassrls; end if;
end $$;
create schema auth;
create table auth.users (id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$
    select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;
grant usage on schema public, auth to anon, authenticated, service_role;
grant execute on function auth.uid() to anon, authenticated, service_role;
create table public.chats (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    title text not null, created_at timestamptz not null default now()
);
create table public.messages (
    id uuid primary key default gen_random_uuid(),
    chat_id uuid not null references public.chats(id) on delete cascade,
    role text not null check (role in ('user', 'model', 'tool')),
    content text not null, created_at timestamptz not null default now(),
    name text, args jsonb
);
alter table public.chats enable row level security;
alter table public.messages enable row level security;
grant all on public.chats, public.messages to anon, authenticated, service_role;
create policy "Users can manage their own chats" on public.chats for all to authenticated
    using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "Users can manage messages in their chats" on public.messages for all to authenticated
    using (exists (select 1 from public.chats where chats.id = messages.chat_id and chats.user_id = auth.uid()))
    with check (exists (select 1 from public.chats where chats.id = messages.chat_id and chats.user_id = auth.uid()));
create policy "Allow anon insert to messages" on public.messages for insert to anon with check (true);
create policy "Allow anon select from messages" on public.messages for select to anon using (true);
